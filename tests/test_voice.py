"""Voice messages: codec, sending over a nearby (LAN) session, offline queue, and online."""
import math
import struct

import pytest

from bluecenchchat.core import voice

from .conftest import connect_and_accept, wait_for


def tone(seconds=1.5, rate=8000, freq=440):
    n = int(seconds * rate)
    return b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))


def test_mulaw_roundtrip_and_helpers():
    pcm = tone(0.5)
    enc = voice.encode(pcm)
    assert len(enc) == len(pcm) // 2
    dec = voice.decode(enc)
    a = struct.unpack(f"<{len(pcm) // 2}h", pcm)
    b = struct.unpack(f"<{len(dec) // 2}h", dec)
    assert max(abs(x - y) for x, y in zip(a, b)) < 700  # mu-law error is small at this level
    assert voice.duration(enc) == pytest.approx(0.5)
    assert len(voice.resample_to_8k(tone(1.0, 48000), 48000)) == pytest.approx(16000, abs=4)
    assert len(voice.peaks(enc, 20)) == 20
    w = voice.wav(dec)
    assert w[:4] == b"RIFF" and w[8:12] == b"WAVE"
    assert voice.fmt(75) == "1:15"


async def test_voice_message_nearby_and_queued(pair, tmp_path, monkeypatch):
    monkeypatch.setattr(voice.config, "data_dir", lambda: tmp_path)
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    mid = await a.messaging.send_voice(ab, tone(1.5))
    await wait_for(lambda: b.repo.message(mid) is not None)
    m = b.repo.message(mid)
    assert m.kind == "voice" and float(m.body) == pytest.approx(1.5, abs=0.05)
    assert m.preview.startswith("Voice message 0:0")
    assert voice.load(mid) == voice.load(mid) and len(voice.load(mid)) == 12000
    await wait_for(lambda: a.repo.message(mid).status in ("delivered", "read"))
    with pytest.raises(ValueError):
        await a.messaging.send_voice(ab, tone(0.2))
    # offline: queued, then delivered on reconnect
    await a.connections.disconnect(ab)
    await wait_for(lambda: not a.connections.is_online(ab))
    mid2 = await a.messaging.send_voice(ab, tone(1.0))
    assert a.repo.message(mid2).status == "queued"
    await a.connections.connect(lan=("127.0.0.1", b.lan.port))  # already friends: just reconnect
    await wait_for(lambda: b.repo.message(mid2) is not None)
    await wait_for(lambda: a.repo.message(mid2).status in ("delivered", "read"))


async def test_bad_voice_payload_is_dropped(pair, tmp_path, monkeypatch):
    monkeypatch.setattr(voice.config, "data_dir", lambda: tmp_path)
    a, b = pair
    ab, ba = await connect_and_accept(a, b)
    s = a.connections.session_for_contact(ab)
    await s.session.send_json({"t": "msg", "id": "22222222-2222-4222-8222-222222222222", "text": "x",
                               "kind": "voice", "audio": "!!!not base64!!!"})
    await s.session.send_json({"t": "msg", "id": "33333333-3333-4333-8333-333333333333", "text": "ok"})
    await wait_for(lambda: b.repo.message("33333333-3333-4333-8333-333333333333") is not None)
    assert b.repo.message("22222222-2222-4222-8222-222222222222") is None
