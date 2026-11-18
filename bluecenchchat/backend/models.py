"""SQLAlchemy ORM models.

Every row that belongs to a signed-in user carries ``account_id`` so several
local accounts can share one database file without seeing each other's data.
"""
from __future__ import annotations

import json
import time
import uuid

from sqlalchemy import (
    Boolean,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(254), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    about: Mapped[str] = mapped_column(String(280), default="")
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    password_hash: Mapped[str] = mapped_column(String(200))
    recovery_hash: Mapped[str] = mapped_column(String(200))
    identity_pub: Mapped[bytes] = mapped_column(LargeBinary)
    identity_enc_pw: Mapped[bytes] = mapped_column(LargeBinary)
    identity_salt_pw: Mapped[bytes] = mapped_column(LargeBinary)
    identity_enc_rk: Mapped[bytes] = mapped_column(LargeBinary)
    identity_salt_rk: Mapped[bytes] = mapped_column(LargeBinary)

    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[float] = mapped_column(Float, default=0.0)
    is_guest: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_login: Mapped[float] = mapped_column(Float, default=0.0)
    tick_cert: Mapped[str] = mapped_column(Text, default="")
    settings_json: Mapped[str] = mapped_column(Text, default="{}")

    @property
    def settings(self) -> dict:
        try:
            return json.loads(self.settings_json or "{}")
        except ValueError:
            return {}

    @property
    def display_name(self) -> str:
        return self.full_name or self.username


class Contact(Base):
    """A remote Blue Cench Chat identity known to this account."""

    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("account_id", "peer_user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    peer_user_id: Mapped[str] = mapped_column(String(20), index=True)
    username: Mapped[str] = mapped_column(String(40), default="")
    display_name: Mapped[str] = mapped_column(String(80), default="")
    about: Mapped[str] = mapped_column(String(280), default="")
    avatar: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    identity_pub: Mapped[bytes] = mapped_column(LargeBinary)
    # pending_out | pending_in | accepted | rejected | blocked
    status: Mapped[str] = mapped_column(String(16), default="pending_out")
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen: Mapped[float] = mapped_column(Float, default=0.0)
    last_transport: Mapped[str] = mapped_column(String(16), default="")
    address_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    # --- social (Instagram-style) -------------------------------------------
    i_follow: Mapped[bool] = mapped_column(Boolean, default=False)
    follows_me: Mapped[bool] = mapped_column(Boolean, default=False)
    followers_count: Mapped[int] = mapped_column(Integer, default=0)   # as reported by them
    following_count: Mapped[int] = mapped_column(Integer, default=0)
    posts_count: Mapped[int] = mapped_column(Integer, default=0)
    note_text: Mapped[str] = mapped_column(String(80), default="")
    note_music: Mapped[str] = mapped_column(String(80), default="")
    note_ts: Mapped[float] = mapped_column(Float, default=0.0)
    tick_cert: Mapped[str] = mapped_column(Text, default="")            # verified blue-tick certificate

    @property
    def address(self) -> dict:
        try:
            return json.loads(self.address_json or "{}")
        except ValueError:
            return {}

    @address.setter
    def address(self, value: dict) -> None:
        self.address_json = json.dumps(value or {})

    @property
    def name(self) -> str:
        return self.display_name or self.username or self.peer_user_id


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(3))  # out | in
    kind: Mapped[str] = mapped_column(String(8), default="text")  # text | file | system
    body: Mapped[str] = mapped_column(Text, default="")
    reply_to: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # queued | sent | delivered | read | failed  (out)  /  received | read (in)
    status: Mapped[str] = mapped_column(String(10), default="queued")
    reaction: Mapped[str] = mapped_column(String(16), default="")
    transfer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    ts: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def preview(self) -> str:
        """Short text for chat lists and notifications."""
        if self.kind == "voice":
            try:
                s = int(round(float(self.body)))
            except ValueError:
                s = 0
            return f"Voice message {s // 60}:{s % 60:02d}"
        if self.kind == "file":
            return f"File: {self.body}"
        return self.body


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), index=True)
    direction: Mapped[str] = mapped_column(String(3))
    # offered | waiting | active | paused | completed | failed | cancelled | rejected | interrupted
    status: Mapped[str] = mapped_column(String(12), default="waiting")
    transport: Mapped[str] = mapped_column(String(16), default="")
    total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    done_bytes: Mapped[int] = mapped_column(Integer, default=0)
    files_json: Mapped[str] = mapped_column(Text, default="[]")
    label: Mapped[str] = mapped_column(String(260), default="")
    error: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    finished_at: Mapped[float] = mapped_column(Float, default=0.0)

    @property
    def files(self) -> list[dict]:
        try:
            return json.loads(self.files_json or "[]")
        except ValueError:
            return []

    @files.setter
    def files(self, value: list[dict]) -> None:
        self.files_json = json.dumps(value)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(400), default="")
    ref: Mapped[str] = mapped_column(String(64), default="")
    ts: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)


class Activity(Base):
    __tablename__ = "activity"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))  # connection | message | transfer | security | system
    text: Mapped[str] = mapped_column(String(300))
    ts: Mapped[float] = mapped_column(Float, default=time.time, index=True)


class SuspiciousReport(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    peer_user_id: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(500))
    ts: Mapped[float] = mapped_column(Float, default=time.time)


class WebDevice(Base):
    """A phone / tablet / watch browser paired with this account over Wi-Fi."""

    __tablename__ = "web_devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(60))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_agent: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    last_seen: Mapped[float] = mapped_column(Float, default=time.time)
    last_ip: Mapped[str] = mapped_column(String(64), default="")


class Post(Base):
    """A photo/text post - our own (author_uid == our id) or one synced from someone we follow."""

    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    author_uid: Mapped[str] = mapped_column(String(20), index=True)
    caption: Mapped[str] = mapped_column(String(2200), default="")
    music: Mapped[str] = mapped_column(String(80), default="")
    image: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    liked: Mapped[bool] = mapped_column(Boolean, default=False)       # liked by me
    saved: Mapped[bool] = mapped_column(Boolean, default=False)
    received_at: Mapped[float] = mapped_column(Float, default=time.time)


class PostLike(Base):
    """Who liked one of OUR posts."""

    __tablename__ = "post_likes"
    __table_args__ = (UniqueConstraint("post_id", "liker_uid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[str] = mapped_column(String(36), index=True)
    liker_uid: Mapped[str] = mapped_column(String(20))
    ts: Mapped[float] = mapped_column(Float, default=time.time)


class PostComment(Base):
    __tablename__ = "post_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[str] = mapped_column(String(36), index=True)
    author_uid: Mapped[str] = mapped_column(String(20))
    author_name: Mapped[str] = mapped_column(String(80), default="")
    text: Mapped[str] = mapped_column(String(500))
    ts: Mapped[float] = mapped_column(Float, default=time.time)


class TickRequest(Base):
    """Blue-tick requests received by the official verifier account."""

    __tablename__ = "tick_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    peer_uid: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(80), default="")
    followers: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | granted | declined | revoked
    cert: Mapped[str] = mapped_column(Text, default="")
    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    ts: Mapped[float] = mapped_column(Float, default=time.time)


class Revocation(Base):
    """Signed blue-tick revocations seen on the network (gossiped between peers)."""

    __tablename__ = "revocations"
    __table_args__ = (UniqueConstraint("account_id", "uid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    uid: Mapped[str] = mapped_column(String(20))
    blob: Mapped[str] = mapped_column(Text)
    ts: Mapped[float] = mapped_column(Float, default=time.time)
