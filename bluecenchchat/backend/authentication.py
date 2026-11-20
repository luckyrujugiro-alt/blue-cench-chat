"""Local account authentication.

How accounts work offline
-------------------------
* Accounts live in the local SQLite database; nothing requires internet.
* The password is hashed with Argon2id (``argon2-cffi`` PasswordHasher).
* The account's Ed25519 identity key is stored *encrypted* twice: once under
  an Argon2id-derived key from the password and once under the one-time
  recovery key.  Signing in therefore both authenticates the user and
  unlocks the identity used for peer authentication.  Stealing the database
  file does not reveal the identity key.
* "Forgot password" works offline: the recovery key (shown once at sign-up)
  unlocks the identity, the user picks a new password and a fresh recovery
  key is issued.  Without the recovery key a password cannot be reset - that
  is deliberate; there is no server that could vouch for you.
* Repeated failures lock the account for ``LOCKOUT_SECONDS``.

Internet-assisted mode (future) would add an optional sync server; the local
identity key would stay the root of trust.
"""
from __future__ import annotations

import re
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from pydantic import BaseModel, field_validator, model_validator
from sqlalchemy import func, or_, select

from .. import config
from ..core import crypto
from .database import Database
from .models import Account

_ph = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)

USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,24}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9 ()-]{6,20}$")


class AuthError(Exception):
    pass


def password_problems(pw: str) -> list[str]:
    issues = []
    if len(pw) < 8:
        issues.append("at least 8 characters")
    if not re.search(r"[A-Za-z]", pw):
        issues.append("a letter")
    if not re.search(r"\d", pw):
        issues.append("a number")
    if len(pw) > 128:
        issues.append("at most 128 characters")
    return issues


def password_strength(pw: str) -> int:
    """0-4 score for the UI meter."""
    score = 0
    if len(pw) >= 8:
        score += 1
    if len(pw) >= 12:
        score += 1
    if re.search(r"[A-Z]", pw) and re.search(r"[a-z]", pw):
        score += 1
    if re.search(r"\d", pw) and re.search(r"[^A-Za-z0-9]", pw):
        score += 1
    return score


class RegistrationData(BaseModel):
    full_name: str
    username: str
    email: str
    password: str
    confirm_password: str
    phone: str = ""
    avatar: bytes | None = None

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 2 <= len(v) <= 80:
            raise ValueError("Full name must be 2-80 characters")
        return v

    @field_validator("username")
    @classmethod
    def _username(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("Username: 3-24 characters, letters, numbers, _ or .")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v.lower()

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        if v and not PHONE_RE.match(v):
            raise ValueError("Enter a valid phone number")
        return v

    @model_validator(mode="after")
    def _passwords(self):
        if problems := password_problems(self.password):
            raise ValueError("Password needs " + ", ".join(problems))
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


DEFAULT_SETTINGS = {
    "theme": "light",
    "font_scale": 100,
    "visible": True,
    "lan_enabled": True,
    "ble_enabled": True,
    "rfcomm_enabled": True,
    "download_dir": "",
    "notify_messages": True,
    "notify_files": True,
    "notify_requests": True,
    "notify_security": True,
    "auto_reconnect": True,
    "skip_duplicates": True,
    "auto_accept_verified": False,
    "minimize_to_tray": True,
    "start_with_windows": False,
    "battery_saver": True,
    "onboarded": False,
    "reduce_motion": False,
    "web_enabled": False,
    "web_port": 8765,
    "note_text": "",
    "note_music": "",
    "note_ts": 0,
    "tick_request": "",
    "tick_request_sent": False,
}


def shrink_avatar(raw: bytes | None, size: int = 160) -> bytes | None:
    """Normalise a profile picture to a small square PNG (Qt is used for decoding)."""
    if not raw:
        return None
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
        from PySide6.QtGui import QImage

        img = QImage.fromData(QByteArray(raw))
        if img.isNull():
            raise AuthError("Unsupported image file")
        side = min(img.width(), img.height())
        img = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
        img = img.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "PNG")
        return bytes(buf.data())
    except ImportError:  # pragma: no cover - Qt always present in app
        return raw[:200_000]


class AuthService:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------
    def register(self, data: RegistrationData, guest: bool = False) -> tuple[Account, str, crypto.Identity]:
        with self.db.session() as s:
            clash = s.scalar(
                select(Account).where(
                    or_(Account.username == data.username, func.lower(Account.email) == data.email)
                )
            )
            if clash:
                field = "username" if clash.username == data.username else "email"
                raise AuthError(f"That {field} is already registered on this computer")

            identity = crypto.Identity.generate()
            recovery = crypto.generate_recovery_key()
            salt_pw, enc_pw = crypto.wrap_secret(data.password, identity.private_bytes())
            salt_rk, enc_rk = crypto.wrap_secret(recovery, identity.private_bytes())
            settings = dict(DEFAULT_SETTINGS)
            settings["download_dir"] = str(config.default_download_dir())
            import json

            acc = Account(
                user_id=identity.user_id,
                username=data.username,
                full_name=data.full_name,
                email=data.email,
                phone=data.phone,
                avatar=shrink_avatar(data.avatar),
                password_hash=_ph.hash(data.password),
                recovery_hash=_ph.hash(recovery),
                identity_pub=identity.public_bytes,
                identity_enc_pw=enc_pw,
                identity_salt_pw=salt_pw,
                identity_enc_rk=enc_rk,
                identity_salt_rk=salt_rk,
                is_guest=guest,
                settings_json=json.dumps(settings),
                last_login=time.time(),
            )
            s.add(acc)
            s.commit()
            return acc, recovery, identity

    def create_guest(self) -> tuple[Account, crypto.Identity]:
        """Guest = a throw-away local identity that is erased at sign-out."""
        import secrets

        suffix = secrets.token_hex(3)
        pw = secrets.token_urlsafe(24) + "a1"
        data = RegistrationData(
            full_name=f"Guest {suffix.upper()}",
            username=f"guest_{suffix}",
            email=f"guest_{suffix}@guest.local",
            password=pw,
            confirm_password=pw,
        )
        acc, _, ident = self.register(data, guest=True)
        return acc, ident

    def delete_account(self, account_id: int) -> None:
        with self.db.session() as s:
            acc = s.get(Account, account_id)
            if acc:
                s.delete(acc)
                s.commit()

    # ------------------------------------------------------------------
    def login(self, login: str, password: str) -> tuple[Account, crypto.Identity]:
        login = login.strip().lower()
        with self.db.session() as s:
            acc = s.scalar(
                select(Account).where(
                    or_(Account.username == login, func.lower(Account.email) == login),
                    Account.is_guest.is_(False),
                )
            )
            if acc is None:
                _ph.hash("timing-equaliser")  # do similar work for unknown users
                raise AuthError("Incorrect username or password")
            now = time.time()
            if acc.locked_until > now:
                mins = int((acc.locked_until - now) // 60) + 1
                raise AuthError(f"Too many failed attempts. Try again in {mins} min.")
            try:
                _ph.verify(acc.password_hash, password)
            except (VerifyMismatchError, InvalidHashError):
                acc.failed_attempts += 1
                if acc.failed_attempts >= config.MAX_FAILED_LOGINS:
                    acc.locked_until = now + config.LOCKOUT_SECONDS
                    acc.failed_attempts = 0
                    s.commit()
                    raise AuthError("Account locked for 5 minutes after repeated failures")
                left = config.MAX_FAILED_LOGINS - acc.failed_attempts
                s.commit()
                raise AuthError(f"Incorrect username or password ({left} attempts left)")
            identity = crypto.Identity.from_bytes(
                crypto.unwrap_secret(password, acc.identity_salt_pw, acc.identity_enc_pw)
            )
            if _ph.check_needs_rehash(acc.password_hash):
                acc.password_hash = _ph.hash(password)
            acc.failed_attempts = 0
            acc.last_login = now
            s.commit()
            return acc, identity

    def recover(self, login: str, recovery_key: str, new_password: str) -> str:
        """Reset the password with the recovery key. Returns a NEW recovery key."""
        if problems := password_problems(new_password):
            raise AuthError("Password needs " + ", ".join(problems))
        rk = crypto.normalize_recovery_key(recovery_key)
        login = login.strip().lower()
        with self.db.session() as s:
            acc = s.scalar(
                select(Account).where(or_(Account.username == login, func.lower(Account.email) == login))
            )
            if acc is None or acc.is_guest:
                raise AuthError("Account not found on this computer")
            if acc.locked_until > time.time():
                raise AuthError("Account temporarily locked. Try again later.")
            try:
                _ph.verify(acc.recovery_hash, rk)
                raw = crypto.unwrap_secret(rk, acc.identity_salt_rk, acc.identity_enc_rk)
            except (VerifyMismatchError, InvalidHashError, crypto.CryptoError):
                acc.failed_attempts += 1
                if acc.failed_attempts >= config.MAX_FAILED_LOGINS:
                    acc.locked_until = time.time() + config.LOCKOUT_SECONDS
                    acc.failed_attempts = 0
                s.commit()
                raise AuthError("Recovery key is not valid")
            new_rk = crypto.generate_recovery_key()
            acc.password_hash = _ph.hash(new_password)
            acc.identity_salt_pw, acc.identity_enc_pw = crypto.wrap_secret(new_password, raw)
            acc.recovery_hash = _ph.hash(new_rk)
            acc.identity_salt_rk, acc.identity_enc_rk = crypto.wrap_secret(new_rk, raw)
            acc.failed_attempts = 0
            s.commit()
            return new_rk

    def change_password(self, account_id: int, old: str, new: str) -> None:
        if problems := password_problems(new):
            raise AuthError("Password needs " + ", ".join(problems))
        with self.db.session() as s:
            acc = s.get(Account, account_id)
            try:
                _ph.verify(acc.password_hash, old)
            except (VerifyMismatchError, InvalidHashError):
                raise AuthError("Current password is incorrect")
            raw = crypto.unwrap_secret(old, acc.identity_salt_pw, acc.identity_enc_pw)
            acc.password_hash = _ph.hash(new)
            acc.identity_salt_pw, acc.identity_enc_pw = crypto.wrap_secret(new, raw)
            s.commit()

    def regenerate_recovery_key(self, account_id: int, password: str) -> str:
        with self.db.session() as s:
            acc = s.get(Account, account_id)
            try:
                _ph.verify(acc.password_hash, password)
            except (VerifyMismatchError, InvalidHashError):
                raise AuthError("Password is incorrect")
            raw = crypto.unwrap_secret(password, acc.identity_salt_pw, acc.identity_enc_pw)
            rk = crypto.generate_recovery_key()
            acc.recovery_hash = _ph.hash(rk)
            acc.identity_salt_rk, acc.identity_enc_rk = crypto.wrap_secret(rk, raw)
            s.commit()
            return rk

    def list_accounts(self) -> list[Account]:
        with self.db.session() as s:
            return list(s.scalars(select(Account).where(Account.is_guest.is_(False)).order_by(Account.last_login.desc())))

    def purge_guests(self) -> None:
        with self.db.session() as s:
            for acc in s.scalars(select(Account).where(Account.is_guest.is_(True))):
                s.delete(acc)
            s.commit()
