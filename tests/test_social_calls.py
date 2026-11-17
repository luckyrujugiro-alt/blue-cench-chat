"""Social layer, blue-tick verification and calls - two real nodes over TCP."""
import asyncio
import io

import pytest
from PIL import Image

from bluecenchchat.core import crypto
from bluecenchchat.core import verification as vf

from .conftest import connect_and_accept, wait_for


def jpeg_bytes(color=(40, 120, 255)):
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1500), color).save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture
def alice_is_verifier(pair, monkeypatch):
    a, b = pair
    monkeypatch.setattr(vf, "verifier_keys", lambda: frozenset({a.identity.public_bytes}))
    return a, b


async def test_follow_posts_likes_comments(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    await b.social.follow(ba)                       # Bob follows Alice
    await wait_for(lambda: a.repo.contact(ab).follows_me)
    assert a.social.stats()["followers"] == 1 and b.social.stats()["following"] == 1
    pid = await a.social.create_post("Sunset in Kigali", jpeg_bytes(), music="Track - Artist")
    await wait_for(lambda: b.social.post(pid) is not None)
    p = b.social.post(pid)
    assert p.caption == "Sunset in Kigali" and p.music == "Track - Artist"
    assert p.image[:3] == b"\xff\xd8\xff"                          # re-encoded JPEG
    assert Image.open(io.BytesIO(p.image)).size[0] <= 1080         # resized like Instagram
    assert [x.id for x in b.social.feed()] == [pid]
    await b.social.toggle_like(pid)
    await wait_for(lambda: a.social.post(pid).likes == 1)
    await b.social.add_comment(pid, "Beautiful!")
    await wait_for(lambda: a.social.post(pid).comments == 1)
    assert a.social.comments(pid)[0].author_name == "Bob Tester"
    await b.social.refresh_comments(pid)
    await wait_for(lambda: len(b.social.comments(pid)) == 1 and b.social.post(pid).comments == 1)
    assert any(n.kind == "like" for n in a.repo.notifications())
    await a.social.delete_post(pid)
    await wait_for(lambda: b.social.post(pid) is None)


async def test_feed_catch_up_after_reconnect_and_notes(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    await b.social.follow(ba)
    await wait_for(lambda: a.repo.contact(ab).follows_me)
    await a.connections.disconnect(ab)
    await wait_for(lambda: not b.connections.is_online(ba))
    pid = await a.social.create_post("Posted while you were away", None)
    await a.social.set_note("At the library", "Afrobeats mix")
    await a.connections.connect(lan=("127.0.0.1", b.lan.port), expect_user_id=b.identity.user_id)
    await wait_for(lambda: b.social.post(pid) is not None)
    await wait_for(lambda: b.repo.contact(ba).note_text == "At the library")
    assert b.repo.contact(ba).note_music == "Afrobeats mix"
    assert b.repo.contact(ba).posts_count == 1


async def test_unfollowed_peer_cannot_push_posts(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    s = a.connections.session_for_contact(ab)
    await s.session.send_json({"t": "s_post", "id": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed", "caption": "spam", "ts": 1})
    await asyncio.sleep(0.3)
    assert b.social.feed() == []


async def test_blue_tick_request_grant_revoke(alice_is_verifier, monkeypatch):
    a, b = alice_is_verifier
    ab, ba = await connect_and_accept(a, b)
    assert a.social.is_admin() and a.social.is_verified_me()           # official account is verified
    await wait_for(lambda: b.social.is_verified(b.repo.contact(ba)))   # Bob sees Alice's tick
    with pytest.raises(ValueError, match="40 followers"):
        await b.social.request_tick()
    monkeypatch.setattr(b.social, "stats", lambda: {"followers": 40, "following": 0, "posts": 0})
    msg = await b.social.request_tick("Musician in Kigali")
    assert "sent" in msg
    await wait_for(lambda: len(a.social.tick_requests("pending")) == 1)
    req = a.social.tick_requests("pending")[0]
    assert req.followers == 40 and req.peer_uid == b.identity.user_id
    await a.social.grant_tick(b.identity.user_id)
    await wait_for(lambda: b.social.is_verified_me())
    assert a.social.is_verified(a.repo.contact(ab))
    await a.social.revoke_tick(b.identity.user_id)
    await wait_for(lambda: not b.social.is_verified_me())
    assert not a.social.is_verified(a.repo.contact(ab))


async def test_forged_tick_is_rejected(alice_is_verifier):
    a, b = alice_is_verifier
    mallory = crypto.Identity.generate()
    forged = vf.issue_tick(mallory, b.identity.user_id, b.identity.public_bytes, "Bob")
    assert not vf.check_tick(forged, b.identity.user_id, b.identity.public_bytes)
    genuine = vf.issue_tick(a.identity, b.identity.user_id, b.identity.public_bytes, "Bob")
    assert vf.check_tick(genuine, b.identity.user_id, b.identity.public_bytes)
    # a genuine tick for Bob is useless to anyone else
    assert not vf.check_tick(genuine, mallory.user_id, mallory.public_bytes)


async def test_non_admin_cannot_grant(pair):
    a, b = pair
    await connect_and_accept(a, b)
    with pytest.raises(PermissionError):
        await b.social.grant_tick(a.identity.user_id)


async def test_voice_and_video_call(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    got_audio, got_video = [], []
    b.calls.on_audio = got_audio.append
    b.calls.on_video = got_video.append
    call = await a.calls.start(ab, video=True)
    await wait_for(lambda: b.calls.current is not None and b.calls.current.state == "ringing")
    assert b.calls.current.video and b.calls.current.rate == 16000
    await b.calls.accept()
    await wait_for(lambda: a.calls.current.state == "active")
    await a.calls.send_audio(b"\x01\x02" * 640)
    await a.calls.send_video(b"\xff\xd8\xff" + b"x" * 5000)
    await wait_for(lambda: got_audio and got_video)
    assert got_audio[0] == b"\x01\x02" * 640
    await a.calls.hangup()
    await wait_for(lambda: b.calls.current.state == "ended")
    await wait_for(lambda: any(m.kind == "call" and m.body.startswith("Video call") for m in b.repo.messages(ba)))


async def test_video_refused_on_bluetooth_and_missed_call(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    a.connections.session_for_contact(ab).transport = "rfcomm"   # pretend the link is Bluetooth
    with pytest.raises(ValueError, match="Video calls need Wi-Fi"):
        await a.calls.start(ab, video=True)
    call = await a.calls.start(ab, video=False)
    assert call.rate == 8000                                       # Bluetooth audio rate
    await wait_for(lambda: b.calls.current is not None)
    await a.calls.hangup()                                         # caller gives up before answer
    await wait_for(lambda: any(m.body == "Missed voice call" for m in b.repo.messages(ba)))
    assert any(n.kind == "call_missed" for n in b.repo.notifications())


async def test_busy_when_already_in_call(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    await b.calls.start(ba, video=False)
    await wait_for(lambda: a.calls.current is not None)
    with pytest.raises(ValueError, match="already in a call"):
        await a.calls.start(ab, video=False)
