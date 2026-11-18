"""Stories (24 h) and notes with a real song from the device."""
import time

import pytest

from bluecenchchat.core import social as social_mod

from .conftest import connect_and_accept, wait_for

MP3 = b"ID3\x03\x00\x00\x00\x00\x00\x00" + bytes([0xFF, 0xFB, 0x90, 0x64]) + b"\x00" * 4000


async def test_story_reaches_followers_and_expires(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    await b.social.follow(ba, True)                    # Bob follows Alice
    await wait_for(lambda: a.repo.contact(ab).follows_me)
    sid = await a.social.create_post("At the lake", None, story=True)
    await wait_for(lambda: b.social.post(sid) is not None)
    assert b.social.post(sid).story
    assert sid not in [p.id for p in b.social.feed()]            # stories aren't feed posts
    groups = dict(b.social.stories())
    assert [p.id for p in groups[a.identity.user_id]] == [sid]
    # Bob watches it: Alice sees who viewed
    await b.social.mark_story_seen(sid)
    await wait_for(lambda: b.identity.user_id in (a.social.post(sid).viewer_ids or ""))
    # after 24 h it disappears
    with b.db.session() as s:
        from bluecenchchat.backend.models import Post
        s.get(Post, sid).created_at = time.time() - 25 * 3600
        s.commit()
    assert a.identity.user_id not in dict(b.social.stories())


async def test_note_with_song_from_device(pair):
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    await a.social.set_note("Vibes", "My song", clip=MP3)
    await wait_for(lambda: b.repo.contact(ba).note_clip == MP3)
    assert b.repo.contact(ba).note_music == "My song"
    # removing the note removes the song
    await a.social.set_note("", "")
    await wait_for(lambda: b.repo.contact(ba).note_text == "")
    assert a.social.note_clip() is None


def test_clip_checks():
    assert social_mod.looks_like_audio(MP3)
    assert not social_mod.looks_like_audio(b"MZ\x90\x00 not audio at all")
    big = MP3 + b"\x00" * 900_000
    assert len(social_mod.trim_clip(big)) == social_mod.MAX_CLIP
    with pytest.raises(ValueError):
        social_mod.trim_clip(b"RIFF" + b"\x00" * 900_000)
