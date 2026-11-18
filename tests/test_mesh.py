"""Extended range: Alice -> (Bob relays) -> Carol, when Alice and Carol are out of range of each other."""
import asyncio
import json
import random

import pytest

from bluecenchchat.backend.database import Database
from bluecenchchat.core.node import BlueCenchChatNode

from .conftest import connect_and_accept, make_account, wait_for


@pytest.fixture
async def trio(tmp_path):
    port = random.randint(48000, 60000)
    nodes = []
    for name in ("alice", "bob", "carol"):
        db = Database(tmp_path / f"{name}.db")
        acc, _, ident = make_account(db, name)
        node = BlueCenchChatNode(db, acc.id, ident, beacon_port=port)
        node.update_settings(download_dir=str(tmp_path), auto_reconnect=False)
        await node.start()
        nodes.append(node)
    yield nodes
    for n in nodes:
        await n.stop()


async def test_message_hops_through_a_friend(trio):
    a, b, c = trio
    # Alice and Carol met once (so they know each other's keys), then went out of range.
    ac, ca = await connect_and_accept(a, c)
    await wait_for(lambda: a.repo.contact(ac).address.get("xpub") and c.repo.contact(ca).address.get("xpub"))
    await a.connections.disconnect(ac)
    await wait_for(lambda: not a.connections.is_online(ac) and not c.connections.is_online(ca))
    # Bob is friends with both and is near each of them.
    ab, ba = await connect_and_accept(a, b)
    bc, cb = await connect_and_accept(b, c)
    mid = await a.messaging.send_text(ac, "Carried by Bob, sealed for Carol")
    await wait_for(lambda: c.repo.message(mid) is not None)
    assert c.repo.message(mid).body == "Carried by Bob, sealed for Carol"
    # Bob never sees the text
    assert b.repo.message(mid) is None
    assert all("Carried by Bob" not in json.dumps(e) for e in b.mesh.store.values())
    # Carol's delivery receipt hops back the same way
    await wait_for(lambda: a.repo.message(mid).status in ("delivered", "read"))


async def test_relay_carries_until_recipient_appears(trio):
    a, b, c = trio
    ac, ca = await connect_and_accept(a, c)
    await wait_for(lambda: a.repo.contact(ac).address.get("xpub"))
    await a.connections.disconnect(ac)
    await wait_for(lambda: not a.connections.is_online(ac))
    ab, ba = await connect_and_accept(a, b)
    bc, cb = await connect_and_accept(b, c)
    await b.connections.disconnect(bc)            # Bob walks away from Carol...
    await wait_for(lambda: not b.connections.is_online(bc))
    mid = await a.messaging.send_text(ac, "store and forward")
    assert a.repo.message(mid).status == "relayed"
    await wait_for(lambda: len(b.mesh.store) == 1)
    assert c.repo.message(mid) is None
    await b.connections.connect(lan=("127.0.0.1", c.lan.port))   # ...and later meets her
    await wait_for(lambda: c.repo.message(mid) is not None)
    await wait_for(lambda: not b.mesh.store)


async def test_relay_rejects_strangers_and_tampering(trio):
    a, b, c = trio
    ac, ca = await connect_and_accept(a, c)
    await wait_for(lambda: a.repo.contact(ac).address.get("xpub"))
    env = a.mesh.seal(a.repo.contact(ac), {"t": "msg", "id": "44444444-4444-4444-8444-444444444444", "text": "hi"})
    # tampered ciphertext is dropped
    bad = {**env, "c": env["c"][:-8] + "AAAAAAA="}
    await c.mesh.on_relay(c.repo.contact(ca), bad)
    assert c.repo.message("44444444-4444-4444-8444-444444444444") is None
    # a relay that is not an accepted connection is ignored
    stranger = c.repo.contact(ca)
    c.repo.set_contact(ca, status="blocked")
    await c.mesh.on_relay(c.repo.contact(ca), env)
    assert c.repo.message("44444444-4444-4444-8444-444444444444") is None
    c.repo.set_contact(ca, status=stranger.status)
    await c.mesh.on_relay(c.repo.contact(ca), env)
    assert c.repo.message("44444444-4444-4444-8444-444444444444").body == "hi"
    # duplicates are ignored
    await c.mesh.on_relay(c.repo.contact(ca), env)
    assert len([m for m in c.repo.messages(ca) if m.body == "hi"]) == 1
