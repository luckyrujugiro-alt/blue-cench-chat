"""Call audio conversion between the call format and real Windows device formats."""
import numpy as np

from bluecenchchat.core import audio_dsp as dsp


def tone(rate, secs=0.5, hz=440, channels=1, fmt="Float"):
    t = np.arange(int(rate * secs)) / rate
    a = 0.5 * np.sin(2 * np.pi * hz * t).astype(np.float32)
    if channels > 1:
        a = np.repeat(a[:, None], channels, axis=1).reshape(-1)
    return dsp._from_float(a, fmt)


def dominant_hz(pcm16: bytes, rate: int) -> float:
    a = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32)
    spec = np.abs(np.fft.rfft(a))
    return np.fft.rfftfreq(a.size, 1 / rate)[spec.argmax()]


def test_typical_windows_mic_to_call():
    # 48 kHz stereo float (the usual Windows mix format) -> 16 kHz mono 16-bit
    pcm = dsp.device_to_call(tone(48000, channels=2), 48000, 2, "Float", 16000)
    assert len(pcm) == 16000 * 2 // 2           # half a second of 16-bit mono
    assert abs(dominant_hz(pcm, 16000) - 440) < 5


def test_call_to_typical_speaker_and_back():
    call = dsp.device_to_call(tone(16000, fmt="Int16"), 16000, 1, "Int16", 16000)
    out = dsp.call_to_device(call, 16000, 44100, 2, "Int32")
    assert len(out) == int(round(8000 * 44100 / 16000)) * 2 * 4
    back = dsp.device_to_call(out, 44100, 2, "Int32", 8000)    # also covers the Bluetooth rate
    assert abs(dominant_hz(back, 8000) - 440) < 5


def test_partial_frames_and_clipping():
    assert dsp.device_to_call(b"\x01\x02\x03", 48000, 2, "Float", 16000) == b""
    loud = dsp._from_float(np.array([5.0, -5.0], dtype=np.float32), "Float")
    assert dsp.device_to_call(loud, 16000, 1, "Float", 16000) == np.array([32767, -32767], np.int16).tobytes()


def test_jitter_buffer_waits_then_plays_and_catches_up():
    jb = dsp.JitterBuffer(bytes_per_ms=32, target_ms=120, max_ms=300)
    jb.push(b"a" * 32 * 40)
    assert jb.pull(100) == b""                  # still buffering
    jb.push(b"b" * 32 * 100)
    assert len(jb.pull(640)) == 640              # now playing
    for _ in range(20):
        jb.push(b"c" * 3200)                     # flood: latency is capped
    assert jb.size <= 32 * 300
