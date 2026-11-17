"""End-to-end tests: two real BlueCenchChatNode instances over localhost TCP.

These exercise exactly the production code paths (handshake, encryption,
requests, messaging, file transfer) - only the physical link differs from a
two-PC test.
"""
import asyncio
import hashlib
import os

import pytest

from bluecenchchat.core.transports.base import TransportError

from .conftest import connect_and_accept, wait_for


async def test_connection_request_flow(pair):
    a, b = pair
    cid = await a.connections.connect(lan=("127.0.0.1", b.lan.port))
    assert a.repo.contact(cid).status == "stranger"
    seen = []
    b.bus.on("request", lambda c: seen.append(c))
    await a.connections.send_request(cid, "hello from alice")
    await wait_for(lambda: seen)
    cb = b.repo.contact(seen[0])
    assert cb.status == "pending_in" and cb.peer_user_id == a.identity.user_id
    assert any(n.kind == "request" for n in b.repo.notifications())
    await b.connections.accept(cb.id)
    await wait_for(lambda: a.repo.contact(cid).status == "accepted")
    # profile card exchanged
    await wait_for(lambda: a.repo.contact(cid).display_name == "Bob Tester")


async def test_stranger_cannot_message(pair):
    a, b = pair
    cid = await a.connections.connect(lan=("127.0.0.1", b.lan.port))
    s = a.connections.session_for_contact(cid)
    await s.session.send_json({"t": "msg", "id": "8f0f5c8e-8b8d-4d55-9a7b-3b8f6b8a1c11", "text": "spam"})
    await asyncio.sleep(0.3)
    cb = b.repo.contact_by_peer(a.identity.user_id)
    assert b.repo.messages(cb.id) == []
    with pytest.raises(ValueError):
        await a.messaging.send_text(cid, "not allowed yet")


async def test_reject(pair):
    a, b = pair
    cid = await a.connections.connect(lan=("127.0.0.1", b.lan.port))
    await a.connections.send_request(cid)
    await wait_for(lambda: (c := b.repo.contact_by_peer(a.identity.user_id)) and c.status == "pending_in")
    await b.connections.reject(b.repo.contact_by_peer(a.identity.user_id).id)
    await wait_for(lambda: a.repo.contact(cid).status == "rejected")


async def test_messaging_receipts_reply_delete_react(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    b.messaging.active_contact = None
    mid = await a.messaging.send_text(ab, "Hello Bob")
    await wait_for(lambda: a.repo.message(mid).status == "delivered")
    assert b.repo.message(mid).body == "Hello Bob"
    await b.messaging.mark_read(ba)
    await wait_for(lambda: a.repo.message(mid).status == "read")
    rid = await b.messaging.send_text(ba, "Hi Alice", reply_to=mid)
    await wait_for(lambda: a.repo.message(rid) is not None)
    assert a.repo.message(rid).reply_to == mid
    await b.messaging.react(mid, "heart")
    await wait_for(lambda: a.repo.message(mid).reaction == "heart")
    await a.messaging.delete(mid, for_everyone=True)
    await wait_for(lambda: b.repo.message(mid).deleted)
    typing = []
    b.bus.on("typing", lambda c, on: typing.append(on))
    await a.messaging.set_typing(ab, True)
    await wait_for(lambda: typing == [True])
    assert [m.body for m in b.repo.messages(ba, search="alice")] == ["Hi Alice"]


async def test_offline_queue_and_reconnect(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    await a.connections.disconnect(ab)
    await wait_for(lambda: not b.connections.is_online(ba))
    mid = await a.messaging.send_text(ab, "queued while offline")
    assert a.repo.message(mid).status == "queued"
    await a.connections.connect(lan=("127.0.0.1", b.lan.port), expect_user_id=b.identity.user_id)
    await wait_for(lambda: a.repo.message(mid).status == "delivered")


def _make_file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def test_file_and_folder_transfer(pair, tmp_path):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    src = tmp_path / "src"
    h1 = _make_file(src / "big.bin", 3 * 1024 * 1024 + 17)
    h2 = _make_file(src / "Folder" / "deep" / "x.txt", 1000)
    (src / "Folder" / "empty.dat").write_bytes(b"")
    offers = []
    b.bus.on("transfer_offer", offers.append)
    tid = await a.transfers.send_paths(ab, [str(src / "big.bin"), str(src / "Folder")])
    await wait_for(lambda: offers)
    assert b.repo.transfer(tid).status == "offered"
    await b.transfers.accept(tid)
    await wait_for(lambda: a.repo.transfer(tid).status == "completed", timeout=30)
    await wait_for(lambda: b.repo.transfer(tid).status == "completed")
    dl = tmp_path / "bob_downloads"
    assert hashlib.sha256((dl / "big.bin").read_bytes()).hexdigest() == h1
    assert hashlib.sha256((dl / "Folder" / "deep" / "x.txt").read_bytes()).hexdigest() == h2
    assert (dl / "Folder" / "empty.dat").exists()
    assert not (dl / ".bluecenchchat-partial").exists()
    assert a.repo.transfer(tid).transport == "lan"
    stats = b.repo.transfer_stats()
    assert stats["files_in"] == 3
    # chat shows a file card on both sides
    assert any(m.kind == "file" and m.transfer_id == tid for m in b.repo.messages(ba))


async def test_decline(pair, tmp_path):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    _make_file(tmp_path / "f.bin", 100)
    offers = []
    b.bus.on("transfer_offer", offers.append)
    tid = await a.transfers.send_paths(ab, [str(tmp_path / "f.bin")])
    await wait_for(lambda: offers)
    await b.transfers.decline(tid)
    await wait_for(lambda: a.repo.transfer(tid).status == "rejected")


async def test_interrupted_transfer_resumes(pair, tmp_path):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    h = _make_file(tmp_path / "movie.bin", 12 * 1024 * 1024)
    offers = []
    b.bus.on("transfer_offer", offers.append)
    tid = await a.transfers.send_paths(ab, [str(tmp_path / "movie.bin")])
    await wait_for(lambda: offers)
    await b.transfers.accept(tid)
    await wait_for(lambda: b.transfers.stats_for(tid)["done"] > 2 * 1024 * 1024)
    await a.connections.disconnect(ab)  # simulate link loss mid-transfer
    await wait_for(lambda: b.repo.transfer(tid).status == "interrupted")
    await wait_for(lambda: a.repo.transfer(tid).status == "interrupted")
    part = tmp_path / "bob_downloads" / ".bluecenchchat-partial" / tid / "0.part"
    kept = part.stat().st_size
    assert 0 < kept < 12 * 1024 * 1024
    # reconnect -> sender automatically re-offers -> receiver resumes from offset
    await a.connections.connect(lan=("127.0.0.1", b.lan.port), expect_user_id=b.identity.user_id)
    await wait_for(lambda: b.repo.transfer(tid).status == "completed", timeout=30)
    got = tmp_path / "bob_downloads" / "movie.bin"
    assert hashlib.sha256(got.read_bytes()).hexdigest() == h


async def test_pause_resume_cancel(pair, tmp_path):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    _make_file(tmp_path / "p.bin", 20 * 1024 * 1024)
    offers = []
    b.bus.on("transfer_offer", offers.append)
    tid = await a.transfers.send_paths(ab, [str(tmp_path / "p.bin")])
    await wait_for(lambda: offers)
    await b.transfers.accept(tid)
    await wait_for(lambda: a.repo.transfer(tid).status == "active")
    await a.transfers.pause(tid)
    await wait_for(lambda: b.repo.transfer(tid).status == "paused")
    await asyncio.sleep(0.3)
    frozen = b.transfers.stats_for(tid)["done"]
    await asyncio.sleep(0.3)
    assert b.transfers.stats_for(tid)["done"] == frozen
    await b.transfers.resume(tid)  # receiver can resume too
    await wait_for(lambda: a.repo.transfer(tid).status == "active")
    await b.transfers.cancel(tid)
    await wait_for(lambda: a.repo.transfer(tid).status == "cancelled")
    assert not (tmp_path / "bob_downloads" / ".bluecenchchat-partial" / tid).exists()


async def test_integrity_failure_detected(pair, tmp_path):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    f = tmp_path / "doc.bin"
    _make_file(f, 600 * 1024)
    offers = []
    b.bus.on("transfer_offer", offers.append)
    tid = await a.transfers.send_paths(ab, [str(f)])
    await wait_for(lambda: offers)
    f.write_bytes(os.urandom(600 * 1024))  # file changes after hashing -> must not be accepted
    await b.transfers.accept(tid)
    await wait_for(lambda: b.repo.transfer(tid).status == "failed", timeout=20)
    await wait_for(lambda: a.repo.transfer(tid).status == "failed")
    assert not (tmp_path / "bob_downloads" / "doc.bin").exists()
    assert any("Integrity" in x.text for x in b.repo.activity(kind="security"))


async def test_duplicate_detection(pair, tmp_path):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    _make_file(tmp_path / "same.bin", 500 * 1024)
    offers = []
    b.bus.on("transfer_offer", offers.append)
    t1 = await a.transfers.send_paths(ab, [str(tmp_path / "same.bin")])
    await wait_for(lambda: len(offers) == 1)
    await b.transfers.accept(t1)
    await wait_for(lambda: b.repo.transfer(t1).status == "completed")
    t2 = await a.transfers.send_paths(ab, [str(tmp_path / "same.bin")])
    await wait_for(lambda: len(offers) == 2)
    await b.transfers.accept(t2)
    await wait_for(lambda: a.repo.transfer(t2).status == "completed")
    assert b.repo.transfer(t2).files[0]["status"] == "duplicate"
    assert not (tmp_path / "bob_downloads" / "same (1).bin").exists()


async def test_malicious_offer_path_is_contained(pair, tmp_path):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    s = a.connections.session_for_contact(ab)
    import uuid as _u
    tid = str(_u.uuid4())
    data = b"owned"
    await s.session.send_json({"t": "x_offer", "id": tid, "label": "x", "total": len(data), "files": [
        {"i": 0, "path": "../../../../evil.txt", "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}]})
    await wait_for(lambda: b.repo.transfer(tid) is not None)
    await b.transfers.accept(tid)
    # drive the raw sender side manually
    await s.session.send_chunk(_u.UUID(tid).bytes, 0, 0, data)
    await wait_for(lambda: b.repo.transfer(tid).status == "completed")
    assert (tmp_path / "bob_downloads" / "evil.txt").read_bytes() == b"owned"
    assert not (tmp_path / "evil.txt").exists()


async def test_block_disconnects_and_refuses(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    await b.connections.block(ba)
    await wait_for(lambda: not a.connections.is_online(ab))
    # Alice can still complete a handshake, but Bob drops the session at once.
    try:
        await a.connections.connect(lan=("127.0.0.1", b.lan.port))
    except TransportError:
        pass
    await asyncio.sleep(0.5)
    assert not b.connections.is_online(ba)
    await wait_for(lambda: not a.connections.is_online(ab))
    assert any("Blocked" in x.text for x in b.repo.activity(kind="security"))


async def test_identity_code_pins_and_verifies(pair):
    a, b = pair
    code = b.identity_code()
    data = a.parse_identity_code(code)
    assert data["uid"] == b.identity.user_id
    # tampered code fails integrity check
    with pytest.raises(ValueError):
        a.parse_identity_code(code[:-4] + "AAAA")
    # connect by pinned key (use loopback since container IP may differ)
    cid = await a.connections.connect(lan=("127.0.0.1", b.lan.port), pinned_pub=data["pub_bytes"],
                                      expect_user_id=data["uid"])
    assert a.repo.contact(cid).verified
    await wait_for(lambda: b.repo.contact_by_peer(a.identity.user_id) is not None)
    assert a.safety_number(cid) == b.safety_number(b.repo.contact_by_peer(a.identity.user_id).id)


async def test_lan_beacon_discovery(pair):
    a, b = pair
    # beacons are broadcast on a shared UDP port; this works on hosts that allow broadcast
    try:
        await wait_for(lambda: any(p.user_id == b.identity.user_id for p in a.discovery.list()), timeout=6)
    except AssertionError:
        pytest.skip("UDP broadcast not available in this environment")
    peer = next(p for p in a.discovery.list() if p.user_id == b.identity.user_id)
    assert peer.lan_port == b.lan.port and "lan" in peer.transports
