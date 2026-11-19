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
    """Blue Cench's own typing indicator.

    A message bubble "being written" on the incoming side: a glowing avatar ring with the
    person's initial, a bubble whose three dots ride a wave while a blue-to-cyan gradient
    sweeps through them, a shimmer passing over the bubble, and "Alice is typing" beside it.
    It fades in, and stops animating the moment the person stops typing.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name = ""
        self.phase = 0.0
        self.fade = 0.0
        self.setFixedHeight(42)
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self._step)
        self.hide()

    def show_for(self, name: str) -> None:
        if not self.isVisible():
            self.fade = 0.0
        self.name = name
        self.show()
        self.timer.start()

    def stop(self) -> None:
        self.timer.stop()
        self.hide()

    def _step(self) -> None:
        self.phase = (self.phase + 0.03) % 1.0
        self.fade = min(1.0, self.fade + 0.12)
        self.update()

    def paintEvent(self, _e) -> None:
        import math

        from PySide6.QtGui import QLinearGradient, QRadialGradient

        pal = theme.palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.fade)
        h = self.height()
        wave = self.phase * 2 * math.pi
        blue, cyan, violet = QColor("#1D9BF0"), QColor("#22D3EE"), QColor("#8B5CF6")
        # --- avatar ring with initial, breathing glow
        ar = 13.0
        ax, ay = 24.0, h / 2
        glow = QRadialGradient(ax, ay, ar + 7)
        g = QColor(blue)
        g.setAlpha(int(70 + 50 * (0.5 + 0.5 * math.sin(wave))))
        glow.setColorAt(0.6, g)
        glow.setColorAt(1.0, QColor(29, 155, 240, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(ax - ar - 7, ay - ar - 7, 2 * (ar + 7), 2 * (ar + 7)))
        ring = QLinearGradient(ax - ar, ay - ar, ax + ar, ay + ar)
        ring.setColorAt(0, blue)
        ring.setColorAt(1, cyan)
        p.setBrush(ring)
        p.drawEllipse(QRectF(ax - ar, ay - ar, 2 * ar, 2 * ar))
        p.setBrush(QColor(pal.surface))
        p.drawEllipse(QRectF(ax - ar + 2, ay - ar + 2, 2 * ar - 4, 2 * ar - 4))
        initial = (self.name or "?").strip()[:1].upper() or "?"
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(9.5)
        p.setFont(f)
        p.setPen(QColor(pal.primary))
        p.drawText(QRectF(ax - ar, ay - ar, 2 * ar, 2 * ar), Qt.AlignmentFlag.AlignCenter, initial)
        # --- the bubble being written (incoming side, tail bottom-left)
        bx, bw, bh = ax + ar + 9, 66.0, 30.0
        by = (h - bh) / 2
        rect = QRectF(bx, by, bw, bh)
        path = QPainterPath()
        path.addRoundedRect(rect, bh / 2, bh / 2)
        tail = QPainterPath()
        tail.moveTo(bx + 4, by + bh - 9)
        tail.lineTo(bx - 4, by + bh + 1)
        tail.lineTo(bx + 14, by + bh - 2)
        path = path.united(tail)
        p.setPen(QPen(QColor(29, 155, 240, 110), 1.2))
        p.setBrush(QColor(pal.surface2))
        p.drawPath(path)
        # shimmer sweeping across the bubble
        sx = bx - 30 + (bw + 60) * self.phase
        sh = QLinearGradient(sx - 22, 0, sx + 22, 0)
        sh.setColorAt(0, QColor(255, 255, 255, 0))
        sh.setColorAt(0.5, QColor(255, 255, 255, 34))
        sh.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(sh)
        p.save()
        p.setClipPath(path)
        p.drawRect(rect)
        p.restore()
        # three dots riding a wave, colour sweeping blue -> cyan -> violet
        for i in range(3):
            t = wave - i * 0.9
            lift = max(0.0, math.sin(t)) * 5.0
            size = 3.6 + max(0.0, math.sin(t)) * 1.2
            mix = 0.5 + 0.5 * math.sin(t + 1.2)
            c1, c2 = (blue, cyan) if i < 2 else (cyan, violet)
            col = QColor(int(c1.red() + (c2.red() - c1.red()) * mix), int(c1.green() + (c2.green() - c1.green()) * mix),
                         int(c1.blue() + (c2.blue() - c1.blue()) * mix))
            cx = bx + 17 + i * 16
            cy = by + bh / 2 - lift + 1.5
            p.setBrush(col)
            p.drawEllipse(QRectF(cx - size, cy - size, size * 2, size * 2))
        # --- label
        name = (self.name or "").split()[0][:18] if self.name else ""
        f.setBold(False)
        f.setItalic(True)
        f.setPointSizeF(9)
        p.setFont(f)
        p.setPen(QColor(pal.muted))
        p.drawText(QRectF(bx + bw + 12, 0, 260, h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   f"{name} is typing" if name else "typing")
        p.end()


