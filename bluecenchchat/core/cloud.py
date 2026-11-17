"""Online mode: find everyone, follow and text from anywhere (Firebase).

Design
------
* Firebase Authentication (email + password, the same as the app account) gives each
  person an online ID ("fuid").
* Firebase Realtime Database holds only:
    /users/{fuid}      public profile: name, username, Blue Cench Chat ID, public keys, tick, last seen
    /mailbox/{fuid}/*  sealed envelopes waiting for that person (deleted as soon as they arrive)
* Every envelope is END-TO-END ENCRYPTED: X25519 (ephemeral -> recipient's mailbox key)
  + HKDF + ChaCha20-Poly1305, and SIGNED with the sender's Ed25519 identity. Firebase
  (and anyone who reads the database) sees only who sent something to whom and when.
* The envelope carries the same small JSON messages the Bluetooth/LAN sessions use
  ("msg", "ack", "read", "s_follow", "s_hello", ...), so chats, follows, notes and
  counts work the same online and offline.

The public client config (API key, database URL) lives in bluecenchchat/cloud.json.
That key only identifies the project; access is controlled by the database rules in
firebase/database.rules.json.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .. import config
from . import crypto

log = logging.getLogger("bluecenchchat.cloud")

MAX_ENVELOPE = 1_600_000        # bytes per message (a post photo is <= 900 KB); RTDB allows 10 MB
PROFILE_REFRESH = 120           # seconds between "last seen" heartbeats
DIRECTORY_TTL = 20              # seconds to cache the people directory
PASS_THROUGH = {"msg", "ack", "read", "typing", "msg_del", "react"}


def b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def b64d(s: str) -> bytes:
    return base64.b64decode(s.encode() if isinstance(s, str) else s)


def load_config() -> dict:
    env = os.environ.get("BLUECENCHCHAT_CLOUD")
    if env:
        try:
            return json.loads(env)
        except ValueError:
            return {}
    try:
        return json.loads(config.resource_path("bluecenchchat", "cloud.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class CloudError(Exception):
    pass


def _friendly(code: str) -> str:
    return {
        "EMAIL_EXISTS": "An online account with this email already exists with a different password.",
        "INVALID_PASSWORD": "Wrong password for your online account.",
        "INVALID_LOGIN_CREDENTIALS": "Wrong email or password for your online account.",
        "EMAIL_NOT_FOUND": "No online account with this email.",
        "WEAK_PASSWORD": "Password is too weak for the online account (at least 6 characters).",
        "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts - try again in a few minutes.",
        "OPERATION_NOT_ALLOWED": "Online accounts are not switched on for this project yet.",
        "USER_DISABLED": "This online account was disabled.",
    }.get(code.split(" ")[0].split(":")[0], code)


class CloudService:
    def __init__(self, node) -> None:
        self.node = node
        self.cfg = load_config()
        self.status = "off"          # off | connecting | online | needs_password | error | unavailable
        self.error = ""
        self.fuid = ""
        self._id_token = ""
        self._expires = 0.0
        self._tasks: list[asyncio.Task] = []
        self._client: httpx.AsyncClient | None = None
        self._profiles: dict[str, tuple[float, dict]] = {}
        self._directory: tuple[float, list[dict]] = (0.0, [])
        self._seen_keys: set[str] = set()
        self._lock = asyncio.Lock()
        self._pub_pending = False
        node.bus.on("social", self._schedule_publish)

    def _schedule_publish(self, *_a) -> None:
        """Counts, note or tick changed: refresh the public profile soon (debounced)."""
        if not self.online or self._pub_pending:
            return
        self._pub_pending = True

        async def later():
            await asyncio.sleep(3)
            self._pub_pending = False
            if self.online:
                try:
                    await self.publish_profile()
                    self._directory = (0.0, self._directory[1])
                except Exception as exc:  # noqa: BLE001
                    log.info("profile refresh failed: %s", exc)
        asyncio.ensure_future(later())

    # ------------------------------------------------------------------ config / state
    @property
    def configured(self) -> bool:
        return bool(self.cfg.get("apiKey") and self.cfg.get("databaseURL"))

    @property
    def online(self) -> bool:
        return self.status == "online"

    def _set(self, status: str, error: str = "") -> None:
        self.status, self.error = status, error
        self.node.bus.emit("cloud")
        self.node.bus.emit("status")

    @property
    def _db(self) -> str:
        return self.cfg["databaseURL"].rstrip("/")

    def _auth_url(self, op: str) -> str:
        base = self.cfg.get("authURL", "https://identitytoolkit.googleapis.com/v1")
        return f"{base}/accounts:{op}?key={self.cfg['apiKey']}"

    def _token_url(self) -> str:
        base = self.cfg.get("tokenURL", "https://securetoken.googleapis.com/v1")
        return f"{base}/token?key={self.cfg['apiKey']}"

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(20, read=60), verify=self.cfg.get("verify", True))
        return self._client

    # mailbox key (X25519), separate from the Ed25519 identity, stored with the account settings
    def _xkey(self) -> X25519PrivateKey:
        raw = self.node.settings.get("cloud_xkey")
        if raw:
            try:
                return X25519PrivateKey.from_private_bytes(b64d(raw))
            except Exception:
                pass
        k = X25519PrivateKey.generate()
        self.node.update_settings(cloud_xkey=b64e(k.private_bytes(serialization.Encoding.Raw,
                                                                    serialization.PrivateFormat.Raw,
                                                                    serialization.NoEncryption())))
        return k

    def _xpub(self) -> bytes:
        return self._xkey().public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

    # ------------------------------------------------------------------ lifecycle
    async def start(self, password: str | None = None) -> None:
        """Go online. Uses the saved session, or the account password (first time)."""
        acc = self.node.repo.account()
        if not self.configured:
            self._set("unavailable", "Online mode isn't set up in this build yet.")
            return
        if acc.is_guest or not self.node.settings.get("online_enabled", True):
            self._set("off")
            return
        self._set("connecting")
        try:
            if self.node.settings.get("cloud_refresh") and not password:
                await self._refresh()
            elif password:
                await self._password_login(acc.email, password)
            else:
                self._set("needs_password", "Enter your password once to go online.")
                return
        except CloudError as exc:
            if password is None and self.node.settings.get("cloud_refresh"):
                self.node.update_settings(cloud_refresh="")
                self._set("needs_password", "Your online session expired - enter your password to go online again.")
            else:
                self._set("error", str(exc))
            return
        except httpx.HTTPError as exc:
            self._set("error", f"Can't reach the internet: {exc.__class__.__name__}")
            self._tasks.append(asyncio.create_task(self._retry_later()))
            return
        try:
            await self.publish_profile()
        except Exception as exc:  # noqa: BLE001
            self._set("error", f"Could not publish your profile: {exc}")
            return
        self._set("online")
        self._tasks.append(asyncio.create_task(self._listen_loop()))
        self._tasks.append(asyncio.create_task(self._heartbeat_loop()))
        asyncio.ensure_future(self.flush_all())

    async def _retry_later(self) -> None:
        await asyncio.sleep(60)
        if self.status == "error":
            await self.start()

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        if self.online:
            try:
                await self._req("PATCH", f"users/{self.fuid}", {"seen": {".sv": "timestamp"}, "on": False})
            except Exception:
                pass
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        if self.status not in ("unavailable",):
            self.status = "off"

    async def go_offline(self) -> None:
        self.node.update_settings(online_enabled=False)
        await self.stop()
        self._set("off")

    async def go_online(self, password: str | None = None) -> None:
        self.node.update_settings(online_enabled=True)
        await self.stop()
        await self.start(password)

    # ------------------------------------------------------------------ auth
    async def _password_login(self, email: str, password: str) -> None:
        if not email:
            raise CloudError("Your account has no email address - add one in My Profile to go online.")
        body = {"email": email, "password": password, "returnSecureToken": True}
        r = await self._http().post(self._auth_url("signInWithPassword"), json=body)
        if r.status_code != 200:
            code = _err_code(r)
            if code.startswith(("EMAIL_NOT_FOUND", "INVALID_LOGIN_CREDENTIALS")):
                r2 = await self._http().post(self._auth_url("signUp"), json=body)
                if r2.status_code != 200:
                    code2 = _err_code(r2)
                    raise CloudError(_friendly(code if code2.startswith("EMAIL_EXISTS") else code2))
                r = r2
            else:
                raise CloudError(_friendly(code))
        d = r.json()
        self._take_tokens(d["localId"], d["idToken"], d["refreshToken"], d.get("expiresIn", "3600"))

    async def _refresh(self) -> None:
        r = await self._http().post(self._token_url(), data={"grant_type": "refresh_token",
                                                             "refresh_token": self.node.settings["cloud_refresh"]})
        if r.status_code != 200:
            raise CloudError(_friendly(_err_code(r)))
        d = r.json()
        self._take_tokens(d["user_id"], d["id_token"], d["refresh_token"], d.get("expires_in", "3600"))

    def _take_tokens(self, fuid: str, id_token: str, refresh: str, expires_in) -> None:
        self.fuid, self._id_token = fuid, id_token
        self._expires = time.time() + int(expires_in) - 120
        self.node.update_settings(cloud_refresh=refresh, cloud_uid=fuid)

    async def _token(self) -> str:
        async with self._lock:
            if time.time() > self._expires:
                await self._refresh()
        return self._id_token

    # ------------------------------------------------------------------ database
    async def _req(self, method: str, path: str, body=None, params: dict | None = None):
        q = {"auth": await self._token(), **(params or {})}
        r = await self._http().request(method, f"{self._db}/{path}.json", params=q,
                                       content=None if body is None else json.dumps(body))
        if r.status_code == 401:
            self._expires = 0
            q["auth"] = await self._token()
            r = await self._http().request(method, f"{self._db}/{path}.json", params=q,
                                           content=None if body is None else json.dumps(body))
        if r.status_code >= 400:
            raise CloudError(f"Online database said {r.status_code}: {r.text[:200]}")
        return r.json() if r.content else None

    # ------------------------------------------------------------------ profile + directory
    async def publish_profile(self) -> None:
        acc = self.node.repo.account()
        st = self.node.social.stats()
        avatar = ""
        if acc.avatar:
            try:
                avatar = b64e(_thumb(acc.avatar))
            except Exception:
                avatar = ""
        await self._req("PUT", f"users/{self.fuid}", {
            "name": acc.display_name[:80], "username": acc.username[:40], "about": (acc.about or "")[:280],
            "uid": acc.user_id, "pub": b64e(self.node.identity.public_bytes), "xpub": b64e(self._xpub()),
            "tick": self.node.social.my_tick(), "followers": st["followers"], "following": st["following"],
            "posts": st["posts"], "note": self.node.social.note().get("text", "")[:60],
            "avatar": avatar, "seen": {".sv": "timestamp"}, "on": True, "v": config.APP_VERSION,
        })

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(PROFILE_REFRESH)
            try:
                await self.publish_profile()
            except Exception as exc:  # noqa: BLE001
                log.info("heartbeat failed: %s", exc)

    async def directory(self, force: bool = False) -> list[dict]:
        """Everyone with an online Blue Cench Chat account (newest activity first)."""
        if not self.online:
            return []
        ts, cached = self._directory
        if not force and time.time() - ts < DIRECTORY_TTL:
            return cached
        data = await self._req("GET", "users") or {}
        people = []
        for fuid, p in data.items():
            if not isinstance(p, dict) or fuid == self.fuid or not _valid_profile(p):
                continue
            p = {**p, "fuid": fuid}
            self._profiles[fuid] = (time.time(), p)
            people.append(p)
        people.sort(key=lambda p: -(p.get("seen") or 0))
        self._directory = (time.time(), people)
        return people

    async def profile(self, fuid: str, max_age: float = 300) -> dict | None:
        hit = self._profiles.get(fuid)
        if hit and time.time() - hit[0] < max_age:
            return hit[1]
        p = await self._req("GET", f"users/{fuid}")
        if not isinstance(p, dict) or not _valid_profile(p):
            return None
        p = {**p, "fuid": fuid}
        self._profiles[fuid] = (time.time(), p)
        return p

    def is_recent(self, p: dict) -> bool:
        return bool(p.get("on")) and time.time() * 1000 - (p.get("seen") or 0) < PROFILE_REFRESH * 2500

    def contact_for(self, p: dict):
        """Create / update the local contact for an online person, so chats, follows and ticks just work."""
        pub = b64d(p["pub"])
        c = self.node.repo.contact_by_peer(p["uid"])
        fields = {"username": p.get("username", "")[:40], "display_name": p.get("name", "")[:80],
                  "about": (p.get("about") or "")[:280],
                  "address": {"fuid": p["fuid"], "xpub": p["xpub"]}}
        if c is None:
            c = self.node.repo.upsert_contact(p["uid"], pub, status="accepted", **fields)
            self.node.repo.log("social", f"Added {c.name} from online")
        else:
            if c.identity_pub != pub:
                raise CloudError("This person's keys changed - not trusted")
            self.node.repo.upsert_contact(p["uid"], pub, **fields)
            if c.status in ("pending_out", "pending_in", "rejected", "removed"):
                self.node.repo.set_contact(c.id, status="accepted")
        avatar = p.get("avatar")
        if avatar:
            try:
                self.node.repo.set_contact(c.id, avatar=b64d(avatar))
            except Exception:
                pass
        self.node.bus.emit("contacts")
        return self.node.repo.contact(c.id)

    async def open_person(self, fuid: str) -> int:
        p = await self.profile(fuid, max_age=0)
        if not p:
            raise CloudError("That person couldn't be found online")
        return self.contact_for(p).id

    # ------------------------------------------------------------------ sending
    def can_reach(self, contact) -> bool:
        a = contact.address if contact else {}
        return self.online and bool(a.get("fuid") and a.get("xpub"))

    async def send(self, contact, obj: dict) -> bool:
        if not self.can_reach(contact) or contact.status == "blocked":
            return False
        a = contact.address
        acc = self.node.repo.account()
        payload = json.dumps({"uid": acc.user_id, "to": contact.peer_user_id, "ts": time.time(), "m": obj},
                             separators=(",", ":")).encode()
        signed = json.dumps({"p": b64e(payload), "s": b64e(self.node.identity.sign(payload))}).encode()
        eph = X25519PrivateKey.generate()
        eph_pub = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        peer_x = b64d(a["xpub"])
        key = _kdf(eph.exchange(X25519PublicKey.from_public_bytes(peer_x)), eph_pub, peer_x)
        nonce = os.urandom(12)
        aad = f"{self.fuid}>{a['fuid']}".encode()
        ct = ChaCha20Poly1305(key).encrypt(nonce, signed, aad)
        if len(ct) > MAX_ENVELOPE:
            log.info("online message too large (%d bytes) - skipped", len(ct))
            return False
        try:
            await self._req("POST", f"mailbox/{a['fuid']}", {"f": self.fuid, "e": b64e(eph_pub), "n": b64e(nonce),
                                                            "c": b64e(ct), "t": {".sv": "timestamp"}})
            return True
        except (CloudError, httpx.HTTPError) as exc:
            log.info("online send failed: %s", exc)
            return False

    async def flush_all(self) -> None:
        for c in self.node.repo.contacts(("accepted",)):
            if self.can_reach(c) and not self.node.connections.session_for_contact(c.id):
                await self.node.messaging.flush_queue(c.id)

    # ------------------------------------------------------------------ receiving
    async def _listen_loop(self) -> None:
        backoff = 2
        while True:
            try:
                await self._stream()
                backoff = 2
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.info("mailbox stream ended: %s", exc)
                try:
                    await self._poll_once()
                except Exception:
                    pass
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _stream(self) -> None:
        token = await self._token()
        url = f"{self._db}/mailbox/{self.fuid}.json"
        deadline = self._expires
        async with self._http().stream("GET", url, params={"auth": token},
                                       headers={"Accept": "text/event-stream"},
                                       timeout=httpx.Timeout(20, read=90)) as r:
            if r.status_code != 200:
                raise CloudError(f"stream {r.status_code}")
            event = ""
            async for line in r.aiter_lines():
                if time.time() > deadline:
                    return  # reconnect with a fresh token
                if line.startswith("event:"):
                    event = line[6:].strip()
                elif line.startswith("data:"):
                    data = line[5:].strip()
                    if event in ("put", "patch") and data and data != "null":
                        try:
                            await self._on_event(json.loads(data))
                        except Exception as exc:  # noqa: BLE001
                            log.info("bad mailbox event: %s", exc)
                    elif event in ("auth_revoked", "cancel"):
                        self._expires = 0
                        return

    async def _poll_once(self) -> None:
        data = await self._req("GET", f"mailbox/{self.fuid}") or {}
        for key, item in sorted(data.items(), key=lambda kv: (kv[1] or {}).get("t", 0) if isinstance(kv[1], dict) else 0):
            await self._handle(key, item)

    async def _on_event(self, ev: dict) -> None:
        path, data = ev.get("path", "/"), ev.get("data")
        if data is None:
            return
        if path == "/":
            items = sorted(data.items(), key=lambda kv: (kv[1] or {}).get("t", 0) if isinstance(kv[1], dict) else 0)
            for key, item in items:
                await self._handle(key, item)
        else:
            key = path.strip("/").split("/")[0]
            if "/" not in path.strip("/"):
                await self._handle(key, data)

    async def _handle(self, key: str, item) -> None:
        if key in self._seen_keys:
            return
        self._seen_keys.add(key)
        try:
            if isinstance(item, dict):
                await self._open(item)
        except Exception as exc:  # noqa: BLE001
            log.info("dropped online message: %s", exc)
        finally:
            try:
                await self._req("DELETE", f"mailbox/{self.fuid}/{key}")
            except Exception:
                pass

    async def _open(self, item: dict) -> None:
        sender = str(item.get("f", ""))
        eph_pub, nonce, ct = b64d(item["e"]), b64d(item["n"]), b64d(item["c"])
        my_x = self._xpub()
        key = _kdf(self._xkey().exchange(X25519PublicKey.from_public_bytes(eph_pub)), eph_pub, my_x)
        signed = json.loads(ChaCha20Poly1305(key).decrypt(nonce, ct, f"{sender}>{self.fuid}".encode()))
        payload = b64d(signed["p"])
        body = json.loads(payload)
        if body.get("to") != self.node.repo.account().user_id:
            raise CloudError("not addressed to me")
        uid = str(body.get("uid", ""))
        contact = self.node.repo.contact_by_peer(uid)
        if contact is not None and contact.status == "blocked":
            return
        if contact is not None and contact.address.get("fuid") == sender:
            pub = contact.identity_pub
        else:
            p = await self.profile(sender, max_age=0)
            if not p or p["uid"] != uid:
                raise CloudError("sender profile mismatch")
            pub = b64d(p["pub"])
            if contact is None or contact.identity_pub == pub:
                contact = self.contact_for(p)
        crypto.verify_signature(pub, b64d(signed["s"]), payload)
        if crypto.user_id_from_pub(pub) != uid:
            raise CloudError("forged sender")
        if contact is None:
            raise CloudError("unknown sender")
        msg = body.get("m")
        if not isinstance(msg, dict) or not isinstance(msg.get("t"), str):
            return
        await self.dispatch(contact, msg)

    async def dispatch(self, contact, msg: dict) -> None:
        t = msg["t"]
        self.node.repo.set_contact(contact.id, last_seen=time.time())
        if t in PASS_THROUGH:
            await self.node.messaging.on_message(contact, msg)
        elif t.startswith("s_"):
            await self.node.social.on_message(contact, msg)


def _kdf(shared: bytes, eph_pub: bytes, recipient_pub: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"bluecenchchat-mailbox-v1" + eph_pub + recipient_pub).derive(shared)


def _err_code(r: httpx.Response) -> str:
    try:
        return r.json()["error"]["message"]
    except Exception:
        return f"HTTP {r.status_code}"


def _valid_profile(p: dict) -> bool:
    try:
        pub = b64d(p["pub"])
        return len(pub) == 32 and len(b64d(p["xpub"])) == 32 and crypto.user_id_from_pub(pub) == p["uid"]
    except Exception:
        return False


def _thumb(img: bytes) -> bytes:
    import io

    from PIL import Image

    im = Image.open(io.BytesIO(img)).convert("RGB")
    im.thumbnail((96, 96))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=80)
    return out.getvalue()
