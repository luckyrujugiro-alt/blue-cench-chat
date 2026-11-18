"""Online mode against a local fake Firebase: directory, follow, encrypted texting from anywhere."""
import asyncio
import json
import random
import socket

import pytest
import uvicorn

from bluecenchchat.backend.database import Database
from bluecenchchat.core import cloud as cloud_mod
from bluecenchchat.core.node import BlueCenchChatNode

from .conftest import make_account, wait_for
from .fake_firebase import make_app


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
async def firebase(monkeypatch):
    app = make_app()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    task = asyncio.create_task(server.serve())
    for _ in range(200):
        if server.started:
            break
        await asyncio.sleep(0.02)
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("BLUECENCHCHAT_CLOUD", json.dumps({
        "apiKey": "test", "databaseURL": f"{base}/db", "authURL": f"{base}/auth", "tokenURL": f"{base}/token"}))
    yield app.state.fb
    server.should_exit = True
    await task


@pytest.fixture
async def far_apart(tmp_path, firebase):
    """Two people who are NOT nearby: no LAN, no Bluetooth - only the internet."""
    nodes = []
    for name in ("alice", "bob"):
        db = Database(tmp_path / f"{name}.db")
        acc, _, ident = make_account(db, name)
        node = BlueCenchChatNode(db, acc.id, ident, beacon_port=random.randint(48000, 60000))
        node.update_settings(lan_enabled=False, rfcomm_enabled=False, download_dir=str(tmp_path))
        await node.start()
        nodes.append(node)
    yield nodes
    for n in nodes:
        await n.stop()


async def test_everyone_follow_and_text_over_internet(far_apart, firebase):
    a, b = far_apart
    await a.cloud.start("Passw0rd!x")       # first sign-in creates the online account
    await b.cloud.start("Passw0rd!x")
    assert a.cloud.online and b.cloud.online, (a.cloud.error, b.cloud.error)
    # the database only ever sees public profiles and sealed envelopes
    profiles = firebase["db"]["users"]
    assert {p["username"] for p in profiles.values()} == {"alice", "bob"}
    # Alice sees Bob in the directory and opens him as a contact
    people = await a.cloud.directory(force=True)
    assert [p["username"] for p in people] == ["bob"]
    cid = await a.cloud.open_person(people[0]["fuid"])
    # follow + text - no Bluetooth or LAN between them
    await a.social.follow(cid, True)
    mid = await a.messaging.send_text(cid, "Hi Bob, from far away!")
    await wait_for(lambda: (c := b.repo.contact_by_peer(a.identity.user_id)) is not None
                   and any(m.body == "Hi Bob, from far away!" for m in b.repo.messages(c.id)))
    ba = b.repo.contact_by_peer(a.identity.user_id)
    assert ba.status == "accepted"
    await wait_for(lambda: b.repo.contact(ba.id).follows_me)
    # delivery receipt comes back online too
    await wait_for(lambda: a.repo.message(mid).status in ("delivered", "read"))
    # Bob replies, and his read receipt arrives
    await b.messaging.send_text(ba.id, "Hey Alice!")
    await wait_for(lambda: any(m.body == "Hey Alice!" for m in a.repo.messages(cid)))
    await b.messaging.mark_read(ba.id)
    await wait_for(lambda: a.repo.message(mid).status == "read")
    # follower counts arrive with the hello
    await wait_for(lambda: a.repo.contact(cid).followers_count == 1)
    # mailbox is emptied after delivery and holds no readable text
    await wait_for(lambda: not any(firebase["db"].get("mailbox", {}).values()))
    raw = json.dumps(firebase["db"])
    assert "far away" not in raw and "Hey Alice" not in raw


async def test_queued_messages_go_out_when_online_and_blocking_works(far_apart, firebase):
    a, b = far_apart
    await b.cloud.start("Passw0rd!x")
    await a.cloud.start("Passw0rd!x")
    bob = (await a.cloud.directory(force=True))[0]
    cid = await a.cloud.open_person(bob["fuid"])
    await a.cloud.stop()
    mid = await a.messaging.send_text(cid, "written while offline")
    assert a.repo.message(mid).status == "queued"
    await a.cloud.start()                    # saved session, no password needed
    assert a.cloud.online
    await wait_for(lambda: a.repo.message(mid).status in ("sent", "delivered", "read"))
    await wait_for(lambda: b.repo.contact_by_peer(a.identity.user_id) is not None)
    ba = b.repo.contact_by_peer(a.identity.user_id)
    await b.connections.block(ba.id)
    await a.messaging.send_text(cid, "can you hear me?")
    await asyncio.sleep(1.0)
    assert not any(m.body == "can you hear me?" for m in b.repo.messages(ba.id))


async def test_wrong_password_and_forged_sender(far_apart, firebase):
    a, b = far_apart
    await a.cloud.start("Passw0rd!x")
    await a.cloud.stop()
    a.update_settings(cloud_refresh="")
    await a.cloud.start("totally-wrong")
    assert a.cloud.status == "error" and "password" in a.cloud.error.lower()
    await a.cloud.start("Passw0rd!x")
    await b.cloud.start("Passw0rd!x")
    # Bob pretends to be Alice: the envelope is signed with Bob's key, so Alice's Bob-contact
    # would get it - but an envelope claiming Alice's ID must be rejected.
    bob_on_a = await a.cloud.open_person((await a.cloud.directory(force=True))[0]["fuid"])
    alice = (await b.cloud.directory(force=True))[0]
    c = b.cloud.contact_for(alice)
    real = b.repo.account().user_id
    with b.db.session() as s:  # tamper: claim to be Alice
        from bluecenchchat.backend.models import Account
        s.get(Account, b.repo.account_id).user_id = a.identity.user_id
        s.commit()
    await b.cloud.send(c, {"t": "msg", "id": "11111111-1111-4111-8111-111111111111", "text": "I am Alice"})
    await asyncio.sleep(1.0)
    with b.db.session() as s:
        from bluecenchchat.backend.models import Account
        s.get(Account, b.repo.account_id).user_id = real
        s.commit()
    assert all(m.body != "I am Alice" for m in a.repo.messages(bob_on_a))


def test_config_missing_means_unavailable(monkeypatch):
    monkeypatch.setenv("BLUECENCHCHAT_CLOUD", "{}")
    assert cloud_mod.load_config() == {}


async def test_voice_message_over_internet(far_apart, firebase, tmp_path, monkeypatch):
    import math
    import struct

    from bluecenchchat.core import voice
    monkeypatch.setattr(voice.config, "data_dir", lambda: tmp_path)
    a, b = far_apart
    await a.cloud.start("Passw0rd!x")
    await b.cloud.start("Passw0rd!x")
    cid = await a.cloud.open_person((await a.cloud.directory(force=True))[0]["fuid"])
    pcm = b"".join(struct.pack("<h", int(9000 * math.sin(i / 3))) for i in range(8000 * 3))
    mid = await a.messaging.send_voice(cid, pcm)
    await wait_for(lambda: b.repo.message(mid) is not None)
    assert b.repo.message(mid).kind == "voice"
    assert "audio" not in json.dumps(firebase["db"])
