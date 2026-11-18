"""Voice messages: 8 kHz G.711 mu-law (8 KB per second - small enough for Bluetooth)."""
from __future__ import annotations

import array
import math
import sys
from pathlib import Path

from .. import config

RATE = 8000
MAX_SECONDS = 90
MAX_BYTES = RATE * MAX_SECONDS


def _build_tables():
    BIAS, CLIP = 0x84, 32635
    enc = bytearray(65536)
    for i in range(65536):
        s = i - 65536 if i >= 32768 else i
        sign = 0x80 if s < 0 else 0
        s = min(abs(s), CLIP) + BIAS
        exp = 7
        mask = 0x4000
        while exp > 0 and not (s & mask):
            exp -= 1
            mask >>= 1
        mant = (s >> (exp + 3)) & 0x0F
        enc[i] = ~(sign | (exp << 4) | mant) & 0xFF
    dec = array.array("h", [0] * 256)
    for u in range(256):
        v = ~u & 0xFF
        sign, exp, mant = v & 0x80, (v >> 4) & 7, v & 0x0F
        mag = ((mant << 3) + BIAS) << exp
        dec[u] = -(mag - BIAS) if sign else (mag - BIAS)
    return bytes(enc), dec


_ENC, _DEC = _build_tables()


def encode(pcm16: bytes) -> bytes:
    """16-bit little-endian mono PCM at 8 kHz -> mu-law bytes."""
    a = array.array("h")
    a.frombytes(pcm16[: len(pcm16) // 2 * 2])
    if sys.byteorder == "big":
        a.byteswap()
    enc = _ENC
    return bytes(enc[s & 0xFFFF] for s in a)


def decode(ulaw: bytes) -> bytes:
    dec = _DEC
    out = array.array("h", (dec[b] for b in ulaw))
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def resample_to_8k(pcm16: bytes, rate: int) -> bytes:
    """Simple averaging downsampler (16/24/32/48 kHz mic input -> 8 kHz)."""
    if rate == RATE:
        return pcm16
    a = array.array("h")
    a.frombytes(pcm16[: len(pcm16) // 2 * 2])
    step = rate / RATE
    out = array.array("h")
    n = int(len(a) / step)
    for i in range(n):
        lo, hi = int(i * step), max(int(i * step) + 1, int((i + 1) * step))
        chunk = a[lo:hi]
        out.append(int(sum(chunk) / len(chunk)) if chunk else 0)
    return out.tobytes()


def duration(ulaw: bytes) -> float:
    return len(ulaw) / RATE


def peaks(ulaw: bytes, bars: int = 36) -> list[float]:
    """Loudness per bar (0..1) for the waveform drawing."""
    if not ulaw:
        return [0.0] * bars
    step = max(1, len(ulaw) // bars)
    dec = _DEC
    out = []
    for i in range(bars):
        seg = ulaw[i * step:(i + 1) * step:4]
        if not seg:
            out.append(0.0)
            continue
        rms = math.sqrt(sum(dec[b] * dec[b] for b in seg) / len(seg))
        out.append(min(1.0, rms / 9000))
    top = max(out) or 1.0
    return [max(0.08, v / top) for v in out]


def voice_dir() -> Path:
    d = config.data_dir() / "voice"
    d.mkdir(parents=True, exist_ok=True)
    return d


def path_for(msg_id: str) -> Path:
    return voice_dir() / f"{msg_id}.ulaw"


def save(msg_id: str, ulaw: bytes) -> Path:
    p = path_for(msg_id)
    p.write_bytes(ulaw)
    return p


def load(msg_id: str) -> bytes | None:
    try:
        return path_for(msg_id).read_bytes()
    except OSError:
        return None


def fmt(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


def wav(pcm16: bytes, rate: int = RATE) -> bytes:
    """Wrap 16-bit mono PCM in a WAV header (for phones and saving)."""
    import struct

    n = len(pcm16)
    return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", n) + pcm16)
