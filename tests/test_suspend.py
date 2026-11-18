"""Official account suspends someone: signed, spreads, enforced, can be lifted."""
import pytest

from bluecenchchat.core import verification as vf

from .conftest import connect_and_accept, wait_for


async def test_suspend_spreads_blocks_and_lifts(pair, monkeypatch):
    a, b = pair   # a = official account (key published for the test)
    monkeypatch.setattr(vf, "verifier_keys", lambda: frozenset({a.identity.public_bytes}))
    monkeypatch.setattr(vf, "can_verify", lambda username, pub: pub == a.identity.public_bytes)
    ab, ba = await connect_and_accept(a, b)
    await a.social.suspend(b.identity.user_id, 4, "spam")
    # Bob's own app learns it and stops him posting / messaging
    await wait_for(lambda: b.social.my_suspension() is not None)
    assert b.social.my_suspension()["reason"] == "spam"
    with pytest.raises(PermissionError, match="suspended until"):
        await b.messaging.send_text(ba, "hello?")
    with pytest.raises(PermissionError):
        await b.social.create_post("nope", None)
    # even a modified client: Alice's app drops his messages
    await b.connections.session_for_contact(ba).session.send_json(
        {"t": "msg", "id": "55555555-5555-4555-8555-555555555555", "text": "sneaky"})
    import asyncio
    await asyncio.sleep(0.3)
    assert a.repo.message("55555555-5555-4555-8555-555555555555") is None
    # lift it
    await a.social.suspend(b.identity.user_id, 0)
    await wait_for(lambda: b.social.my_suspension() is None)
    await b.messaging.send_text(ba, "I'm back")
    await wait_for(lambda: any(m.body == "I'm back" for m in a.repo.messages(ab)))


async def test_fake_suspension_rejected(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    fake = vf.issue_suspension(a.identity, b.identity.user_id, vf.FOREVER, "fake")  # a is NOT official here
    assert not b.social.store_suspension(fake)
    with pytest.raises(PermissionError):
        await a.social.suspend(b.identity.user_id, None)
    assert b.social.my_suspension() is None
