"""Extended range: messages hop through other Blue Cench Chat devices (store, carry, forward).

When a friend is out of Bluetooth / Wi-Fi range and you're not online, the message is
sealed for that friend only and handed to the friends you ARE connected to. They carry
it and pass it on when they meet the recipient (or another friend, up to MAX_HOPS).

Privacy: relays see only the recipient's Blue Cench Chat ID. The sender, the content and
the message type are inside the sealed envelope (X25519 + ChaCha20-Poly1305 to the
recipient's mailbox key, signed with the sender's Ed25519 identity). Relays only accept
envelopes from people they have accepted as connections, keep at most MAX_STORE envelopes,
and drop them after MAX_AGE.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import crypto

log = logging.getLogger("bluecenchchat.mesh")

MAX_HOPS = 3
MAX_STORE = 300
MAX_AGE = 3 * 24 * 3600
MAX_ENVELOPE = 1_600_000
CARRY = {"msg", "ack", "read", "msg_del", "react"}


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode()


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode() if isinstance(s, str) else s, validate=True)


def _kdf(shared: bytes, eph_pub: bytes, recipient_pub: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=b"bluecenchchat-mesh-v1" + eph_pub + recipient_pub).derive(shared)


class Mesh:
    def __init__(self, node) -> None:
        self.node = node
        self.seen: dict[str, float] = {}   # envelope id -> first seen (loop / duplicate guard)
        self.store: dict[str, dict] = {}   # envelopes we carry for others

    # ------------------------------------------------------------------ keys
    def xpub(self) -> bytes:
        return self.node.cloud._xpub()

    def _xkey(self) -> X25519PrivateKey:
        return self.node.cloud._xkey()

    def remember_key(self, contact, xpub_b64) -> None:
        """Peers tell us their mailbox key in the hello; keep it so we can seal for them later."""
        if not isinstance(xpub_b64, str):
            return
        try:
            if len(_b64d(xpub_b64)) != 32:
                return
        except Exception:
            return
        addr = dict(contact.address or {})
        if addr.get("xpub") != xpub_b64:
            addr["xpub"] = xpub_b64
            self.node.repo.set_contact(contact.id, address=addr)

    # ------------------------------------------------------------------ sending
    def can_seal(self, contact) -> bool:
        return bool(contact and (contact.address or {}).get("xpub"))

    def _relays(self, exclude_uid: str = "") -> list:
        out = []
        for uid, active in list(self.node.connections.sessions.items()):
            if uid == exclude_uid or active.session.closed:
                continue
            c = self.node.repo.contact(active.contact_id)
            if c and c.status == "accepted" and self.node.settings.get("mesh_enabled", True):
                out.append(active)
        return out

    async def send(self, contact, obj: dict) -> bool:
        """Seal `obj` for `contact` and hand it to every connected friend. True if anyone took it."""
        if not self.node.settings.get("mesh_enabled", True) or not self.can_seal(contact):
            return False
        if contact.status != "accepted":
            return False
        relays = self._relays(exclude_uid=contact.peer_user_id)
        if not relays:
            return False
        env = self.seal(contact, obj)
        if env is None:
            return False
        self.seen[env["id"]] = time.time()
        ok = False
        for active in relays:
            try:
                await active.session.send_json(env)
                ok = True
            except Exception as exc:  # noqa: BLE001
                log.debug("relay hand-off failed: %s", exc)
        return ok

    def seal(self, contact, obj: dict) -> dict | None:
        acc = self.node.repo.account()
        payload = json.dumps({"uid": acc.user_id, "pub": _b64e(self.node.identity.public_bytes),
                              "to": contact.peer_user_id, "ts": time.time(), "m": obj},
                             separators=(",", ":")).encode()
        signed = json.dumps({"p": _b64e(payload), "s": _b64e(self.node.identity.sign(payload))}).encode()
        peer_x = _b64d(contact.address["xpub"])
        eph = X25519PrivateKey.generate()
        eph_pub = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        key = _kdf(eph.exchange(X25519PublicKey.from_public_bytes(peer_x)), eph_pub, peer_x)
        nonce = os.urandom(12)
        env_id = str(uuid.uuid4())
        ct = ChaCha20Poly1305(key).encrypt(nonce, signed, f"{env_id}>{contact.peer_user_id}".encode())
        if len(ct) > MAX_ENVELOPE:
            return None
        return {"t": "relay", "id": env_id, "to": contact.peer_user_id, "hops": MAX_HOPS,
                "e": _b64e(eph_pub), "n": _b64e(nonce), "c": _b64e(ct), "ts": time.time()}

    # ------------------------------------------------------------------ receiving / carrying
    async def on_relay(self, from_contact, env: dict) -> None:
        """An envelope arrived from a connected friend: open it if it's for me, else carry it."""
        if from_contact.status != "accepted":
            return
        env_id, to = env.get("id"), env.get("to")
        if not isinstance(env_id, str) or len(env_id) > 64 or not isinstance(to, str) or len(to) > 64:
            return
        if not all(isinstance(env.get(k), str) for k in ("e", "n", "c")) or len(env["c"]) > MAX_ENVELOPE * 2:
            return
        self._expire()
        if env_id in self.seen:
            return
        if to == self.node.identity.user_id:
            try:
                await self._open(env)
                self.seen[env_id] = time.time()   # only a genuine envelope burns its ID
            except Exception as exc:  # noqa: BLE001
                log.info("dropped relayed message: %s", exc)
            return
        self.seen[env_id] = time.time()
        hops = env.get("hops")
        if not isinstance(hops, int) or hops <= 1 or not self.node.settings.get("mesh_enabled", True):
            return
        carried = {**env, "hops": hops - 1, "got": time.time()}
        if len(self.store) >= MAX_STORE:
            oldest = min(self.store, key=lambda k: self.store[k].get("got", 0))
            self.store.pop(oldest, None)
        self.store[env_id] = carried
        await self._forward_now(carried, exclude=from_contact.peer_user_id)

    async def _forward_now(self, env: dict, exclude: str = "") -> None:
        target = self.node.connections.sessions.get(env["to"])
        out = {k: v for k, v in env.items() if k != "got"}
        if target is not None and not target.session.closed:
            try:
                await target.session.send_json(out)
                self.store.pop(env["id"], None)
                return
            except Exception:
                pass
        for active in self._relays(exclude_uid=exclude):
            c = self.node.repo.contact(active.contact_id)
            if c is None or c.peer_user_id == env["to"]:
                continue
            try:
                await active.session.send_json(out)
            except Exception:
                pass

    async def on_session(self, contact) -> None:
        """A friend just connected: hand over anything we carry for them (or that may reach them)."""
        self._expire()
        for env in list(self.store.values()):
            if env["to"] == contact.peer_user_id:
                await self._forward_now(env)
        for env in list(self.store.values()):
            if env["to"] != contact.peer_user_id and env.get("hops", 0) > 1:
                active = self.node.connections.sessions.get(contact.peer_user_id)
                if active is not None and not active.session.closed:
                    try:
                        await active.session.send_json({k: v for k, v in env.items() if k != "got"})
                    except Exception:
                        pass

    def _expire(self) -> None:
        now = time.time()
        for k in [k for k, ts in self.seen.items() if now - ts > MAX_AGE]:
            self.seen.pop(k, None)
        for k in [k for k, e in self.store.items() if now - e.get("ts", now) > MAX_AGE]:
            self.store.pop(k, None)

    async def _open(self, env: dict) -> None:
        eph_pub, nonce, ct = _b64d(env["e"]), _b64d(env["n"]), _b64d(env["c"])
        my_x = self.xpub()
        key = _kdf(self._xkey().exchange(X25519PublicKey.from_public_bytes(eph_pub)), eph_pub, my_x)
        signed = json.loads(ChaCha20Poly1305(key).decrypt(nonce, ct, f"{env['id']}>{env['to']}".encode()))
        payload = _b64d(signed["p"])
        body = json.loads(payload)
        if body.get("to") != self.node.identity.user_id:
            raise ValueError("not for me")
        pub = _b64d(body["pub"])
        uid = str(body.get("uid", ""))
        crypto.verify_signature(pub, _b64d(signed["s"]), payload)
        if crypto.user_id_from_pub(pub) != uid:
            raise ValueError("forged sender")
        contact = self.node.repo.contact_by_peer(uid)
        if contact is None or contact.status != "accepted" or contact.identity_pub != pub:
            raise ValueError("relayed messages are only accepted from your connections")
        msg = body.get("m")
        if not isinstance(msg, dict) or msg.get("t") not in CARRY:
            return
        self.node.repo.set_contact(contact.id, last_seen=time.time())
        await self.node.messaging.on_message(contact, msg)
