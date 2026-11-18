"""Voice messages on the PC: recorder button, playable waveform bubble, and the
Blue Cench "signal" typing indicator."""
from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ...core import voice
from .. import icons, theme
from .widgets import tool_button

log = logging.getLogger("bluecenchchat.ui.voice")

try:
    from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QAudioSource, QMediaDevices

    MULTIMEDIA = True
except Exception:  # pragma: no cover
    MULTIMEDIA = False


def _no_media() -> bool:
    return bool(os.environ.get("BLUECENCHCHAT_NO_MEDIA")) or not MULTIMEDIA


def _fmt() -> "QAudioFormat":
    f = QAudioFormat()
    f.setSampleRate(voice.RATE)
    f.setChannelCount(1)
    f.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return f


# --------------------------------------------------------------------------- player
_PLAYING: "VoiceBubble | None" = None


class Waveform(QWidget):
    seek = Signal(float)

    def __init__(self, bars: list[float], color: str, dim: str) -> None:
        super().__init__()
        self.bars, self.color, self.dim, self.progress = bars, QColor(color), QColor(dim), 0.0
        self.setFixedHeight(30)
        self.setMinimumWidth(150)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self.bars)
        gap = 2.0
        w = max(2.0, (self.width() - gap * (n - 1)) / n)
        for i, v in enumerate(self.bars):
            h = max(3.0, v * (self.height() - 2))
            x = i * (w + gap)
            r = QRectF(x, (self.height() - h) / 2, w, h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(self.color if (i + 0.5) / n <= self.progress else self.dim)
            p.drawRoundedRect(r, w / 2, w / 2)

    def mousePressEvent(self, e) -> None:
        self.seek.emit(max(0.0, min(1.0, e.position().x() / max(1, self.width()))))


class VoiceBubble(QWidget):
    """Play / pause, waveform with progress, duration."""

    def __init__(self, msg_id: str, seconds: float, outgoing: bool) -> None:
        super().__init__()
        self.msg_id, self.seconds = msg_id, seconds
        self.sink = self.io = None
        self.pcm = b""
        self.pos = 0
        p = theme.palette()
        fg = "#FFFFFF" if outgoing else p.primary
        dim = "rgba(255,255,255,0.45)" if outgoing else p.border_strong
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(10)
        self.btn = tool_button("play", "Play voice message", 20, "#FFFFFF" if outgoing else "#FFFFFF")
        self.btn.setFixedSize(38, 38)
        bg = "rgba(255,255,255,0.22)" if outgoing else p.primary
        self.btn.setStyleSheet(f"QToolButton {{ background:{bg}; border-radius:19px; }}")
        self.btn.clicked.connect(self.toggle)
        lay.addWidget(self.btn)
        audio = voice.load(msg_id) or b""
        self.wave = Waveform(voice.peaks(audio, 32), fg, dim)
        self.wave.seek.connect(self._seek)
        lay.addWidget(self.wave, 1)
        self.time = QLabel(voice.fmt(seconds))
        self.time.setStyleSheet(f"color:{'rgba(255,255,255,0.9)' if outgoing else p.muted};"
                                f"font-size:{theme.px(12)}px;")
        lay.addWidget(self.time)
        self.available = bool(audio)
        if not audio:
            self.btn.setEnabled(False)
            self.btn.setToolTip("Voice file missing")
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self._pump)

    def toggle(self) -> None:
        global _PLAYING
        if self.sink is not None:
            self.stop()
            return
        if _no_media():
            return
        if _PLAYING is not None and _PLAYING is not self:
            _PLAYING.stop()
        out = QMediaDevices.defaultAudioOutput()
        if out.isNull():
            self.window().toast("No speaker found", "warning") if hasattr(self.window(), "toast") else None
            return
        if not self.pcm:
            self.pcm = voice.decode(voice.load(self.msg_id) or b"")
        self.sink = QAudioSink(out, _fmt(), self)
        self.sink.setBufferSize(voice.RATE)  # 0.5 s
        self.io = self.sink.start()
        if self.pos >= len(self.pcm):
            self.pos = 0
        self.btn.setIcon(icons.plain("pause", 20, "#FFFFFF"))
        _PLAYING = self
        self.timer.start()

    def _pump(self) -> None:
        if self.sink is None:
            return
        free = self.sink.bytesFree()
        if free > 0 and self.pos < len(self.pcm):
            chunk = self.pcm[self.pos:self.pos + free - free % 2]
            self.io.write(chunk)
            self.pos += len(chunk)
        played = self.pos - (self.sink.bufferSize() - self.sink.bytesFree())
        frac = max(0.0, min(1.0, played / max(1, len(self.pcm))))
        self.wave.progress = frac
        self.wave.update()
        self.time.setText(voice.fmt(self.seconds * frac) if frac > 0 else voice.fmt(self.seconds))
        if self.pos >= len(self.pcm) and self.sink.bytesFree() >= self.sink.bufferSize() - 64:
            self.stop(finished=True)

    def _seek(self, frac: float) -> None:
        if not self.pcm:
            self.pcm = voice.decode(voice.load(self.msg_id) or b"")
        self.pos = int(len(self.pcm) * frac) // 2 * 2
        self.wave.progress = frac
        self.wave.update()
        if self.sink is None:
            self.toggle()

    def stop(self, finished: bool = False) -> None:
        global _PLAYING
        self.timer.stop()
        if self.sink is not None:
            try:
                self.sink.stop()
            except Exception:
                pass
        self.sink = self.io = None
        if finished:
            self.pos = 0
            self.wave.progress = 0.0
            self.wave.update()
            self.time.setText(voice.fmt(self.seconds))
        self.btn.setIcon(icons.plain("play", 20, "#FFFFFF"))
        if _PLAYING is self:
            _PLAYING = None


# --------------------------------------------------------------------------- recorder
class Recorder(QWidget):
    """Mic button: click to record, click again (or Enter) to send, Esc / bin to cancel."""

    finished = Signal(bytes)  # 16-bit PCM at 8 kHz

    def __init__(self) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        p = theme.palette()
        self.cancel_btn = tool_button("trash-2", "Cancel recording", 18, p.danger)
        self.cancel_btn.clicked.connect(self.cancel)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.dot.setStyleSheet(f"background:{p.danger}; border-radius:5px;")
        self.clock = QLabel("0:00")
        self.clock.setStyleSheet(f"color:{p.danger}; font-weight:600;")
        self.mic = tool_button("mic", "Record a voice message (Ctrl+R)", 20)
        self.mic.clicked.connect(self.toggle)
        for w in (self.cancel_btn, self.dot, self.clock):
            w.hide()
            lay.addWidget(w)
        lay.addWidget(self.mic)
        self.src = self.io = None
        self.buf = bytearray()
        self.t0 = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self._tick)

    @property
    def recording(self) -> bool:
        return self.src is not None

    def toggle(self) -> None:
        if self.recording:
            self.stop(send=True)
        else:
            self.start()

    def start(self) -> None:
        if _no_media():
            self._toast("Voice recording isn't available on this PC", "warning")
            return
        dev = QMediaDevices.defaultAudioInput()
        if dev.isNull():
            self._toast("No microphone found - plug one in or check Windows sound settings", "warning")
            return
        fmt = _fmt()
        if not dev.isFormatSupported(fmt):
            fmt = dev.preferredFormat()
        self.rate = fmt.sampleRate()
        self.channels = fmt.channelCount()
        self.sfmt = fmt.sampleFormat()
        self.src = QAudioSource(dev, fmt, self)
        self.io = self.src.start()
        self.io.readyRead.connect(self._read)
        self.buf = bytearray()
        self.t0 = time.monotonic()
        for w in (self.cancel_btn, self.dot, self.clock):
            w.show()
        p = theme.palette()
        self.mic.setIcon(icons.plain("send", 20, "#FFFFFF"))
        self.mic.setToolTip("Send voice message (Enter)")
        self.mic.setStyleSheet(f"QToolButton {{ background:{p.danger}; border-radius:8px; }}")
        self.timer.start()

    def _read(self) -> None:
        if self.io is not None:
            self.buf += bytes(self.io.readAll())

    def _tick(self) -> None:
        s = time.monotonic() - self.t0
        self.clock.setText(voice.fmt(s))
        self.dot.setVisible(int(s * 2) % 2 == 0)
        if s >= voice.MAX_SECONDS:
            self.stop(send=True)

    def cancel(self) -> None:
        self.stop(send=False)

    def stop(self, send: bool) -> None:
        if not self.recording:
            return
        self._read()
        try:
            self.src.stop()
        except Exception:
            pass
        self.src = self.io = None
        self.timer.stop()
        for w in (self.cancel_btn, self.dot, self.clock):
            w.hide()
        self.mic.setIcon(icons.plain("mic", 20, theme.palette().muted))
        self.mic.setToolTip("Record a voice message (Ctrl+R)")
        self.mic.setStyleSheet("")
        if send:
            pcm = self._to_mono16(bytes(self.buf))
            self.finished.emit(voice.resample_to_8k(pcm, self.rate))
        self.buf = bytearray()

    def _to_mono16(self, raw: bytes) -> bytes:
        import array

        SF = QAudioFormat.SampleFormat
        if self.sfmt == SF.Float:
            a = array.array("f")
            a.frombytes(raw[: len(raw) // 4 * 4])
            samples = [max(-32768, min(32767, int(x * 32767))) for x in a]
        elif self.sfmt == SF.Int32:
            a = array.array("i")
            a.frombytes(raw[: len(raw) // 4 * 4])
            samples = [x >> 16 for x in a]
        elif self.sfmt == SF.UInt8:
            samples = [(b - 128) << 8 for b in raw]
        else:
            a = array.array("h")
            a.frombytes(raw[: len(raw) // 2 * 2])
            samples = list(a)
        if self.channels > 1:
            ch = self.channels
            samples = [sum(samples[i:i + ch]) // ch for i in range(0, len(samples) - ch + 1, ch)]
        return array.array("h", samples).tobytes()

    def _toast(self, text: str, kind: str) -> None:
        w = self.window()
        if hasattr(w, "toast"):
            w.toast(text, kind)


# --------------------------------------------------------------------------- typing signal
class SignalIndicator(QWidget):
    """Blue Cench's own "is writing" signal: beams pulsing out like a Bluetooth broadcast."""

    def __init__(self) -> None:
        super().__init__()
        self.name = ""
        self.phase = 0.0
        self.setFixedHeight(26)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self._step)
        self.hide()

    def show_for(self, name: str) -> None:
        self.name = name
        self.show()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        self.hide()

    def _step(self) -> None:
        self.phase = (self.phase + 0.05) % 1.0
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = theme.palette()
        c = QColor(pal.primary)
        x0, cy = 30.0, self.height() / 2
        # source dot
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawEllipse(QRectF(x0 - 3, cy - 3, 6, 6))
        for i in range(3):
            t = (self.phase - i * 0.18) % 1.0
            alpha = int(255 * (0.18 + 0.82 * max(0.0, 1 - abs(t - 0.35) * 2.4)))
            col = QColor(c)
            col.setAlpha(alpha)
            pen = QPen(col, 2.2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            r = 5 + i * 4.5
            path = QPainterPath()
            path.arcMoveTo(QRectF(x0 - r, cy - r, 2 * r, 2 * r), -50)
            path.arcTo(QRectF(x0 - r, cy - r, 2 * r, 2 * r), -50, 100)
            p.drawPath(path)
        p.setPen(QColor(pal.primary))
        f = p.font()
        f.setPointSizeF(f.pointSizeF() * 0.95)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(52, 0, self.width() - 52, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, f"{self.name} is writing")
