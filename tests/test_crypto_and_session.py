import asyncio

import pytest

from bluecenchchat.core import crypto
from bluecenchchat.core.session import PeerSession, ProtocolError
from bluecenchchat.core.transports.base import AsyncioStream


def test_user_id_bound_to_key():
    a, b = crypto.Identity.generate(), crypto.Identity.generate()
    assert a.user_id != b.user_id
    assert crypto.user_id_from_pub(a.public_bytes) == a.user_id


def test_safety_number_symmetric():
    a, b = crypto.Identity.generate(), crypto.Identity.generate()
    assert crypto.safety_number(a.public_bytes, b.public_bytes) == crypto.safety_number(b.public_bytes, a.public_bytes)
    assert len(crypto.safety_number(a.public_bytes, b.public_bytes).replace(" ", "")) == 12


def test_secure_channel_detects_tamper_and_replay():
    k1, k2 = b"1" * 32, b"2" * 32
    a, b = crypto.SecureChannel(k1, k2), crypto.SecureChannel(k2, k1)
    ct = a.encrypt(b"hello")
    assert b.decrypt(ct) == b"hello"
    with pytest.raises(crypto.CryptoError):
        b.decrypt(ct)  # replay -> counter mismatch
    ct2 = bytearray(a.encrypt(b"world"))
    ct2[0] ^= 1
    with pytest.raises(crypto.CryptoError):
        b.decrypt(bytes(ct2))


def test_wrap_unwrap():
    salt, blob = crypto.wrap_secret("pw", b"secret")
    assert crypto.unwrap_secret("pw", salt, blob) == b"secret"
    with pytest.raises(crypto.CryptoError):
        crypto.unwrap_secret("other", salt, blob)


async def _pipe():
    """Two connected AsyncioStreams over a real localhost TCP socket."""
    fut = asyncio.get_running_loop().create_future()

    async def on_conn(r, w):
        fut.set_result(AsyncioStream(r, w))

    server = await asyncio.start_server(on_conn, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    r, w = await asyncio.open_connection("127.0.0.1", port)
    client = AsyncioStream(r, w)
    srv = await fut
    return client, srv, server


async def test_handshake_and_encrypted_exchange():
    a_id, b_id = crypto.Identity.generate(), crypto.Identity.generate()
    c, s, server = await _pipe()
    sa = PeerSession(c, a_id, {"username": "alice", "display_name": "Alice"}, initiator=True)
    sb = PeerSession(s, b_id, {"username": "bob", "display_name": "Bob"}, initiator=False)
    pa, pb = await asyncio.gather(sa.handshake(), sb.handshake())
    assert pa.user_id == b_id.user_id and pb.user_id == a_id.user_id
    assert pa.display_name == "Bob"
    await sa.send_json({"t": "msg", "text": "hi"})
    ftype, msg = await sb.recv()
    assert msg == {"t": "msg", "text": "hi"}
    await sa.send_chunk(b"\x01" * 16, 3, 1024, b"data")
    _, (tid, i, off, data) = await sb.recv()
    assert (i, off, data) == (3, 1024, b"data")
    await sa.close()
    server.close()


class EvilSession(PeerSession):
    """Claims a victim's identity key but cannot sign with it."""

    def __init__(self, *a, victim_pub, **kw):
        super().__init__(*a, **kw)
        self.victim_pub = victim_pub

    async def _handshake(self):
        import json, os
        eph = crypto.EphemeralKey()
        hello = {"t": "hello", "v": 1, "app": "Blue Cench Chat", "user_id": crypto.user_id_from_pub(self.victim_pub),
                 "identity_pub": crypto.b64e(self.victim_pub), "eph": crypto.b64e(eph.public_bytes),
                 "nonce": crypto.b64e(os.urandom(16))}
        mine = json.dumps(hello).encode()
        await self._write_frame(mine)
        peer = await self._read_frame()
        import hashlib
        tr = hashlib.sha256(mine + peer).digest()
        shared = eph.exchange(crypto.b64d(json.loads(peer)["eph"]))
        k1, k2 = crypto.derive_session_keys(shared, tr)
        self.channel = crypto.SecureChannel(k1, k2)
        # signs with its OWN key - cannot produce the victim's signature
        await self.send_json({"t": "auth", "sig": crypto.b64e(self.identity.sign(crypto.auth_payload("initiator", tr)))})
        await asyncio.sleep(1)


async def test_impersonation_rejected():
    victim, attacker, target = (crypto.Identity.generate() for _ in range(3))
    c, s, server = await _pipe()
    evil = EvilSession(c, attacker, {}, initiator=True, victim_pub=victim.public_bytes)
    honest = PeerSession(s, target, {}, initiator=False)
    task = asyncio.create_task(evil.handshake())
    with pytest.raises(crypto.CryptoError):
        await honest.handshake()
    task.cancel()
    server.close()


async def test_spoofed_user_id_rejected():
    a, b = crypto.Identity.generate(), crypto.Identity.generate()
    c, s, server = await _pipe()
    import json
    bad = {"t": "hello", "v": 1, "app": "Blue Cench Chat", "user_id": "NX-AAAAA-AAAAA",
           "identity_pub": crypto.b64e(a.public_bytes), "eph": crypto.b64e(b"\x09" * 32), "nonce": "AA=="}
    raw = json.dumps(bad).encode()
    await c.write(len(raw).to_bytes(4, "big") + raw)
    with pytest.raises(ProtocolError, match="does not match"):
        await PeerSession(s, b, {}, initiator=False).handshake()
    server.close()


async def test_oversized_frame_rejected():
    b = crypto.Identity.generate()
    c, s, server = await _pipe()
    await c.write((50 * 1024 * 1024).to_bytes(4, "big"))
    with pytest.raises(ProtocolError, match="illegal frame"):
        await PeerSession(s, b, {}, initiator=False).handshake()
    server.close()
