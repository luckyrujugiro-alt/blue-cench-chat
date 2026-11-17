"""Authenticated, encrypted peer session over any transport stream.

Wire format: every frame is ``[u32 big-endian length][payload]``.

Handshake
---------
1. Both sides send a plaintext HELLO (JSON) with their identity public key,
   derived Blue Cench Chat ID and a fresh X25519 ephemeral key.
2. transcript = SHA-256(initiator_hello_bytes || responder_hello_bytes)
3. Traffic keys = HKDF(X25519(eph_a, eph_b), salt=transcript)
4. Each side sends, *encrypted*, an Ed25519 signature over
   ``Blue Cench Chat-AUTH|<role>|transcript``.  Verifying it proves the peer owns the
   identity key it advertised and binds that identity to these session keys
   (prevents man-in-the-middle and key-substitution attacks).

After the handshake every frame is ChaCha20-Poly1305 encrypted.  The first
plaintext byte is the frame type: 0x01 = JSON control message,
0x02 = binary file chunk.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import struct
import time
from dataclasses import dataclass, field

from .. import config
from . import crypto
from .transports.base import Stream, TransportError

log = logging.getLogger("bluecenchchat.session")

FT_JSON = 0x01
FT_CHUNK = 0x02
CHUNK_HDR = struct.Struct(">16sIQ")  # transfer uuid, file index, offset


class ProtocolError(Exception):
    pass


@dataclass
class PeerInfo:
    user_id: str
    username: str
    display_name: str
    identity_pub: bytes
    lan_port: int | None = None
    bt_addr: int | None = None
    extra: dict = field(default_factory=dict)


class TokenBucket:
    def __init__(self, rate: float, burst: int) -> None:
        self.rate, self.capacity = rate, burst
        self.tokens = float(burst)
        self.stamp = time.monotonic()

    def allow(self) -> bool:
        now = time.monotonic()
        self.tokens = min(self.capacity, self.tokens + (now - self.stamp) * self.rate)
        self.stamp = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class PeerSession:
    def __init__(self, stream: Stream, identity: crypto.Identity, local_profile: dict, initiator: bool):
        self.stream = stream
        self.identity = identity
        self.local_profile = local_profile
        self.initiator = initiator
        self.peer: PeerInfo | None = None
        self.channel: crypto.SecureChannel | None = None
        self.closed = False
        self.established_at = 0.0
        self.bytes_sent = 0
        self.bytes_recv = 0
        self._send_lock = asyncio.Lock()
        self._limiter = TokenBucket(rate=60, burst=300)

    # -- raw framing -------------------------------------------------------
    async def _write_frame(self, payload: bytes) -> None:
        if len(payload) > config.MAX_FRAME:
            raise ProtocolError("frame too large")
        await self.stream.write(struct.pack(">I", len(payload)) + payload)
        self.bytes_sent += len(payload) + 4

    async def _read_frame(self) -> bytes:
        (length,) = struct.unpack(">I", await self.stream.read_exactly(4))
        if length == 0 or length > config.MAX_FRAME + 64:
            raise ProtocolError(f"illegal frame length {length}")
        data = await self.stream.read_exactly(length)
        self.bytes_recv += length + 4
        return data

    # -- handshake ---------------------------------------------------------
    async def handshake(self, timeout: float = 20.0) -> PeerInfo:
        try:
            return await asyncio.wait_for(self._handshake(), timeout)
        except asyncio.TimeoutError as exc:
            raise ProtocolError("handshake timed out") from exc

    async def _handshake(self) -> PeerInfo:
        eph = crypto.EphemeralKey()
        hello = {
            "t": "hello",
            "v": config.PROTOCOL_VERSION,
            "app": config.APP_NAME,
            "user_id": self.identity.user_id,
            "identity_pub": crypto.b64e(self.identity.public_bytes),
            "eph": crypto.b64e(eph.public_bytes),
            "nonce": crypto.b64e(os.urandom(16)),
            **{k: v for k, v in self.local_profile.items() if k in ("username", "display_name", "lan_port", "bt_addr")},
        }
        my_bytes = json.dumps(hello, separators=(",", ":")).encode()
        if self.initiator:
            await self._write_frame(my_bytes)
            peer_bytes = await self._read_frame()
        else:
            peer_bytes = await self._read_frame()
            await self._write_frame(my_bytes)

        peer_hello = self._parse_hello(peer_bytes)
        transcript = hashlib.sha256(
            (my_bytes + peer_bytes) if self.initiator else (peer_bytes + my_bytes)
        ).digest()
        shared = eph.exchange(crypto.b64d(peer_hello["eph"]))
        k_i2r, k_r2i = crypto.derive_session_keys(shared, transcript)
        self.channel = (
            crypto.SecureChannel(k_i2r, k_r2i) if self.initiator else crypto.SecureChannel(k_r2i, k_i2r)
        )
        my_role, peer_role = ("initiator", "responder") if self.initiator else ("responder", "initiator")
        sig = self.identity.sign(crypto.auth_payload(my_role, transcript))
        await self.send_json({"t": "auth", "sig": crypto.b64e(sig)})
        ftype, msg = await self.recv()
        if ftype != FT_JSON or msg.get("t") != "auth":
            raise ProtocolError("expected auth")
        peer_pub = crypto.b64d(peer_hello["identity_pub"])
        crypto.verify_signature(peer_pub, crypto.b64d(msg["sig"]), crypto.auth_payload(peer_role, transcript))

        self.peer = PeerInfo(
            user_id=peer_hello["user_id"],
            username=str(peer_hello.get("username", ""))[:40],
            display_name=str(peer_hello.get("display_name", ""))[:80],
            identity_pub=peer_pub,
            lan_port=peer_hello.get("lan_port") if isinstance(peer_hello.get("lan_port"), int) else None,
            bt_addr=peer_hello.get("bt_addr") if isinstance(peer_hello.get("bt_addr"), int) else None,
        )
        self.established_at = time.time()
        log.info("session established with %s over %s", self.peer.user_id, self.stream.kind)
        return self.peer

    @staticmethod
    def _parse_hello(raw: bytes) -> dict:
        try:
            h = json.loads(raw)
        except ValueError as exc:
            raise ProtocolError("malformed hello") from exc
        if not isinstance(h, dict) or h.get("t") != "hello" or h.get("app") != config.APP_NAME:
            raise ProtocolError("not a Blue Cench Chat peer")
        if h.get("v") != config.PROTOCOL_VERSION:
            raise ProtocolError(f"unsupported protocol version {h.get('v')}")
        try:
            pub = crypto.b64d(h["identity_pub"])
            eph = crypto.b64d(h["eph"])
        except Exception as exc:
            raise ProtocolError("bad key encoding") from exc
        if len(pub) != 32 or len(eph) != 32:
            raise ProtocolError("bad key length")
        if h.get("user_id") != crypto.user_id_from_pub(pub):
            raise ProtocolError("user id does not match identity key")
        return h

    # -- encrypted messaging -----------------------------------------------
    async def _send_plain(self, plaintext: bytes) -> None:
        if self.closed:
            raise TransportError("session closed")
        async with self._send_lock:
            assert self.channel is not None
            await self._write_frame(self.channel.encrypt(plaintext))

    async def send_json(self, obj: dict) -> None:
        await self._send_plain(bytes([FT_JSON]) + json.dumps(obj, separators=(",", ":")).encode())

    async def send_chunk(self, transfer_id: bytes, index: int, offset: int, data: bytes) -> None:
        await self._send_plain(bytes([FT_CHUNK]) + CHUNK_HDR.pack(transfer_id, index, offset) + data)

    async def recv(self):
        """Return (FT_JSON, dict) or (FT_CHUNK, (transfer_id, index, offset, data))."""
        assert self.channel is not None
        pt = self.channel.decrypt(await self._read_frame())
        ftype = pt[0]
        if ftype == FT_JSON:
            if not self._limiter.allow():
                raise ProtocolError("peer exceeded message rate limit")
            try:
                obj = json.loads(pt[1:])
            except ValueError as exc:
                raise ProtocolError("malformed message") from exc
            if not isinstance(obj, dict) or not isinstance(obj.get("t"), str):
                raise ProtocolError("malformed message")
            return FT_JSON, obj
        if ftype == FT_CHUNK:
            if len(pt) < 1 + CHUNK_HDR.size:
                raise ProtocolError("short chunk")
            tid, idx, off = CHUNK_HDR.unpack_from(pt, 1)
            return FT_CHUNK, (tid, idx, off, pt[1 + CHUNK_HDR.size :])
        raise ProtocolError(f"unknown frame type {ftype}")

    async def close(self) -> None:
        if self.closed:
            return
        try:
            if self.channel:
                await asyncio.wait_for(self.send_json({"t": "bye"}), 1)
        except Exception:
            pass
        self.closed = True
        await self.stream.close()
