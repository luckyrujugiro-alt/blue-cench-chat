"""Sound conversion for calls.

Windows sound devices usually only accept their own "mix format" (often 48 kHz, stereo,
32-bit float). Calls travel as 16-bit mono PCM at 16 kHz (Wi-Fi) or 8 kHz (Bluetooth), so we
convert in both directions. numpy keeps this fast enough for real time.
"""
from __future__ import annotations

from collections import deque

import numpy as np

# sample format names (match Qt's QAudioFormat.SampleFormat names)
FORMATS = {
    "UInt8": (np.uint8, 1),
    "Int16": (np.int16, 2),
    "Int32": (np.int32, 4),
    "Float": (np.float32, 4),
}


def _to_float(data: bytes, sample_format: str) -> np.ndarray:
    dtype, _ = FORMATS[sample_format]
    a = np.frombuffer(data, dtype=dtype)
    if sample_format == "UInt8":
        return (a.astype(np.float32) - 128.0) / 128.0
    if sample_format == "Int16":
        return a.astype(np.float32) / 32768.0
    if sample_format == "Int32":
        return a.astype(np.float32) / 2147483648.0
    return a.astype(np.float32)


def _from_float(a: np.ndarray, sample_format: str) -> bytes:
    a = np.clip(a, -1.0, 1.0)
    if sample_format == "UInt8":
        return (a * 127.0 + 128.0).astype(np.uint8).tobytes()
    if sample_format == "Int16":
        return (a * 32767.0).astype(np.int16).tobytes()
    if sample_format == "Int32":
        return (a * 2147483647.0).astype(np.int32).tobytes()
    return a.astype(np.float32).tobytes()


def _resample(x: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or x.size == 0:
        return x
    n_out = max(1, int(round(x.size * dst_rate / src_rate)))
    t_out = np.linspace(0, x.size - 1, n_out, dtype=np.float64)
    return np.interp(t_out, np.arange(x.size), x).astype(np.float32)


def frame_bytes(sample_format: str, channels: int) -> int:
    return FORMATS[sample_format][1] * channels


def device_to_call(data: bytes, rate: int, channels: int, sample_format: str, call_rate: int) -> bytes:
    """Microphone bytes (device format) -> 16-bit mono at the call rate."""
    fb = frame_bytes(sample_format, channels)
    usable = len(data) - len(data) % fb
    if usable <= 0:
        return b""
    a = _to_float(data[:usable], sample_format)
    if channels > 1:
        a = a.reshape(-1, channels).mean(axis=1)
    return _from_float(_resample(a, rate, call_rate), "Int16")


def call_to_device(data: bytes, call_rate: int, rate: int, channels: int, sample_format: str) -> bytes:
    """16-bit mono at the call rate -> speaker bytes (device format)."""
    data = data[: len(data) - len(data) % 2]
    if not data:
        return b""
    a = _resample(_to_float(data, "Int16"), call_rate, rate)
    if channels > 1:
        a = np.repeat(a[:, None], channels, axis=1).reshape(-1)
    return _from_float(a, sample_format)


class JitterBuffer:
    """Smooths network hiccups: holds ~120 ms before playing, drops the oldest audio if it falls behind."""

    def __init__(self, bytes_per_ms: float, target_ms: int = 120, max_ms: int = 600) -> None:
        self.q: deque[bytes] = deque()
        self.size = 0
        self.target = int(bytes_per_ms * target_ms)
        self.max = int(bytes_per_ms * max_ms)
        self.started = False

    def push(self, chunk: bytes) -> None:
        self.q.append(chunk)
        self.size += len(chunk)
        while self.size > self.max and self.q:  # too much latency: catch up
            self.size -= len(self.q.popleft())

    def pull(self, n: int) -> bytes:
        if not self.started:
            if self.size < self.target:
                return b""
            self.started = True
        out = bytearray()
        while self.q and len(out) < n:
            c = self.q.popleft()
            take = n - len(out)
            out += c[:take]
            if len(c) > take:
                self.q.appendleft(c[take:])
            self.size -= min(len(c), take)
        if not self.q:
            self.started = False  # underrun: re-buffer
        return bytes(out)


def ringtone_wav(rate: int = 44100) -> bytes:
    """A soft two-note chime (our own), as WAV bytes - played while a call rings."""
    import io
    import wave

    def note(hz, secs):
        t = np.arange(int(rate * secs)) / rate
        env = np.exp(-3.2 * t) * np.minimum(1.0, t * 40)
        return (0.35 * env * (np.sin(2 * np.pi * hz * t) + 0.3 * np.sin(2 * np.pi * 2 * hz * t))).astype(np.float32)

    pattern = np.concatenate([note(880, 0.35), note(1174.7, 0.55), np.zeros(int(rate * 1.1), np.float32)])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(_from_float(pattern, "Int16"))
    return buf.getvalue()
