"""Call window: incoming/outgoing ringing, voice (mic + speaker) and video (camera)."""
from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QBuffer, QIODevice, Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from ..core import audio_dsp as dsp
from ..core.calls import fmt_duration
from . import icons
from .components.widgets import Avatar, label, tool_button

log = logging.getLogger("bluecenchchat.ui.calls")

try:  # QtMultimedia ships with PySide6 Essentials, but guard anyway
    from PySide6.QtMultimedia import (
        QAudioFormat,
        QAudioSink,
        QAudioSource,
        QCamera,
        QMediaCaptureSession,
        QMediaDevices,
        QVideoSink,
    )

    MULTIMEDIA = True
except Exception:  # pragma: no cover
    MULTIMEDIA = False


def _device_format(dev):
    """The device's own preferred format, made mono/16-bit if the device supports it (less work)."""
    fmt = dev.preferredFormat()
    nicer = QAudioFormat(fmt)
    nicer.setChannelCount(1)
    nicer.setSampleFormat(QAudioFormat.SampleFormat.Int16)
    return nicer if dev.isFormatSupported(nicer) else fmt


def _fmt_name(fmt) -> str:
    sf = fmt.sampleFormat()
    for name in ("UInt8", "Int16", "Int32", "Float"):
        if sf == getattr(QAudioFormat.SampleFormat, name):
            return name
    return "Int16"


def _round_button(icon_name: str, tip: str, color: str) -> QLabel:
    b = tool_button(icon_name, tip, 26, "#FFFFFF")
    b.setFixedSize(60, 60)
    b.setStyleSheet(f"QToolButton {{ background:{color}; border-radius:30px; }}"
                    f"QToolButton:hover {{ background:{color}; border:2px solid rgba(255,255,255,0.5); }}")
    return b


class CallWindow(QDialog):
    def __init__(self, win, call) -> None:
        super().__init__(win)
        self.win, self.node, self.call = win, win.node, call
        c = self.node.repo.contact(call.contact_id)
        self.name = c.name if c else "Unknown"
        self.setWindowTitle(f"{'Video' if call.video else 'Voice'} call - {self.name}")
        self.setMinimumSize(420, 560 if call.video else 480)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setStyleSheet("QDialog { background: #0C1014; } QLabel { color: #F5F5F5; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 24, 20, 24)
        lay.setSpacing(12)

        self.remote = QLabel()
        self.remote.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.remote.setMinimumHeight(300 if call.video else 0)
        self.remote.setStyleSheet("background:#000; border-radius:16px;")
        self.remote.setVisible(call.video)
        lay.addWidget(self.remote, 1)
        self.local = QLabel(self.remote)
        self.local.setFixedSize(132, 99)
        self.local.setStyleSheet("background:#222; border-radius:10px; border:2px solid #FFFFFF;")
        self.local.setVisible(call.video)

        self.avatar = Avatar(110).set(self.name, c.avatar if c else None, seed=c.peer_user_id if c else "")
        lay.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignHCenter)
        self.avatar.setVisible(not call.video)
        nm = label(self.name, "h2")
        nm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(nm)
        self.status = label("", "muted")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setStyleSheet("color:#A8A8A8;")
        lay.addWidget(self.status)
        self.info = label("", "faint")
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info.setStyleSheet("color:#737373;")
        lay.addWidget(self.info)
        if not call.video:
            lay.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(18)
        row.addStretch(1)
        self.b_mute = _round_button("mic", "Mute (M)", "#363636")
        self.b_cam = _round_button("video", "Camera on/off (V)", "#363636")
        self.b_accept = _round_button("phone", "Answer", "#22C55E")
        self.b_end = _round_button("phone-off", "Hang up (Esc)", "#ED4956")
        for b in (self.b_mute, self.b_cam, self.b_accept, self.b_end):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.b_cam.setVisible(call.video)
        self.b_mute.clicked.connect(self._toggle_mute)
        self.b_cam.clicked.connect(self._toggle_cam)
        self.b_accept.clicked.connect(lambda: self.win.bridge.run(self.node.calls.accept()))
        self.b_end.clicked.connect(self._end)

        self._media_started = False
        self.jitter = None
        self.play_timer = None
        self.muted = False
        self.cam_on = True
        self._mic_buf = b""
        self._last_frame = 0.0
        self.src = self.sink = self.src_io = self.sink_io = None
        self.camera = self.capture = self.vsink = None
        self.node.calls.on_audio = self._play
        self.node.calls.on_video = self._show_remote
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(500)
        self.update_state(call)

    # ---------------------------------------------------------------- state
    def _ring(self, on: bool) -> None:
        """Loop a chime while ringing (incoming) / a softer tone while calling out."""
        if os.environ.get("BLUECENCHCHAT_NO_MEDIA") or not MULTIMEDIA:
            return
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtMultimedia import QSoundEffect

            if on and getattr(self, "ringer", None) is None:
                import tempfile
                from pathlib import Path
                f = Path(tempfile.gettempdir()) / "bluecenchchat-ring.wav"
                if not f.exists():
                    f.write_bytes(dsp.ringtone_wav())
                self.ringer = QSoundEffect(self)
                self.ringer.setSource(QUrl.fromLocalFile(str(f)))
                self.ringer.setLoopCount(-2)  # QSoundEffect.Infinite
                self.ringer.setVolume(0.8 if not self.call.outgoing else 0.35)
                self.ringer.play()
            elif not on and getattr(self, "ringer", None) is not None:
                self.ringer.stop()
                self.ringer = None
        except Exception as exc:  # pragma: no cover
            log.info("ringtone unavailable: %s", exc)

    def update_state(self, call) -> None:
        self.call = call
        self._ring(call.state == "ringing")
        transport = {"lan": "Wi-Fi / LAN", "online": "Internet"}.get(call.transport, "Bluetooth")
        self.info.setText(f"{'Video' if call.video else 'Voice'} · {transport} · end-to-end encrypted")
        ringing_in = call.state == "ringing" and not call.outgoing
        self.b_accept.setVisible(ringing_in)
        self.b_mute.setVisible(call.state == "active")
        self.b_cam.setVisible(call.state == "active" and call.video)
        if call.state == "ringing":
            self.status.setText("Incoming call…" if not call.outgoing else "Calling…")
        elif call.state == "active":
            self._start_media()
        elif call.state == "ended":
            self.status.setText(call.ended_reason)
            self._stop_media()
            QTimer.singleShot(1400, self.accept)

    def _tick(self) -> None:
        if self.call.state == "active":
            self.status.setText(fmt_duration(self.call.duration) + ("  ·  muted" if self.muted else ""))
        self.local.move(self.remote.width() - 144, self.remote.height() - 111)

    # ---------------------------------------------------------------- media
    def _start_media(self) -> None:
        if os.environ.get("BLUECENCHCHAT_NO_MEDIA"):  # headless tests / CI without sound hardware
            return
        if self._media_started or not MULTIMEDIA:
            if not MULTIMEDIA:
                self.win.toast("Audio is not available on this PC (Qt Multimedia missing)", "warning")
            return
        self._media_started = True
        self.chunk = self.call.rate * 2 // 25  # 40 ms of 16-bit mono at the call rate
        try:
            out_dev = QMediaDevices.defaultAudioOutput()
            if out_dev.isNull():  # no speakers / headphones: creating a sink would crash Qt
                self.win.toast("No speaker found - you won't hear the other person", "warning")
            else:
                ofmt = _device_format(out_dev)
                self.out_fmt = (ofmt.sampleRate(), ofmt.channelCount(), _fmt_name(ofmt))
                self.sink = QAudioSink(out_dev, ofmt, self)
                bpms = ofmt.sampleRate() * ofmt.channelCount() * ofmt.bytesPerSample() / 1000
                self.sink.setBufferSize(int(bpms * 200))
                self.sink_io = self.sink.start()
                online = self.call.transport == "online"
                self.jitter = dsp.JitterBuffer(self.call.rate * 2 / 1000, target_ms=420 if online else 120,
                                               max_ms=1600 if online else 600)
                self.play_timer = QTimer(self)
                self.play_timer.setInterval(20)
                self.play_timer.timeout.connect(self._feed_speaker)
                self.play_timer.start()
            in_dev = QMediaDevices.defaultAudioInput()
            if in_dev.isNull():
                self.win.toast("No microphone found - they can't hear you", "warning")
            else:
                ifmt = _device_format(in_dev)
                self.in_fmt = (ifmt.sampleRate(), ifmt.channelCount(), _fmt_name(ifmt))
                self.src = QAudioSource(in_dev, ifmt, self)
                self.src_io = self.src.start()
                if self.src_io is None:
                    self.win.toast("Microphone blocked - allow it in Windows Settings > Privacy > Microphone "
                                   "(\"Let desktop apps access your microphone\")", "warning")
                else:
                    self.src_io.readyRead.connect(self._mic)
        except Exception as exc:  # pragma: no cover - device specific
            log.warning("audio start failed: %s", exc)
            self.win.toast(f"Audio problem: {exc}", "error")
        if self.call.video:
            try:
                cam_dev = QMediaDevices.defaultVideoInput()
                if cam_dev.isNull():
                    self.win.toast("No camera found - continuing with voice", "warning")
                    return
                self.camera = QCamera(cam_dev, self)
                self.capture = QMediaCaptureSession(self)
                self.capture.setCamera(self.camera)
                self.vsink = QVideoSink(self)
                self.capture.setVideoOutput(self.vsink)
                self.vsink.videoFrameChanged.connect(self._frame)
                self.camera.start()
            except Exception as exc:  # pragma: no cover
                log.warning("camera start failed: %s", exc)

    def _mic(self) -> None:
        if self.src_io is None:
            return
        rate, ch, name = self.in_fmt
        self._mic_buf += dsp.device_to_call(bytes(self.src_io.readAll()), rate, ch, name, self.call.rate)
        while len(self._mic_buf) >= self.chunk:
            pkt, self._mic_buf = self._mic_buf[: self.chunk], self._mic_buf[self.chunk :]
            if not self.muted:
                self.win.bridge.run(self.node.calls.send_audio(pkt))

    def _play(self, data: bytes) -> None:
        if self.jitter is not None:
            self.jitter.push(data)

    def _feed_speaker(self) -> None:
        """Every 20 ms: move smoothed call audio into the speaker in its own format."""
        if self.sink is None or self.sink_io is None or self.jitter is None:
            return
        rate, ch, name = self.out_fmt
        per_call_byte = rate * ch * dsp.FORMATS[name][1] / (self.call.rate * 2)
        free = self.sink.bytesFree()
        want = int(free / per_call_byte) & ~1
        if want <= 0:
            return
        pcm = self.jitter.pull(min(want, self.call.rate * 2 // 10))
        if pcm:
            self.sink_io.write(dsp.call_to_device(pcm, self.call.rate, rate, ch, name))

    def _frame(self, frame) -> None:
        now = time.monotonic()
        if now - self._last_frame < 0.08 or not self.cam_on:
            return
        self._last_frame = now
        img = frame.toImage()
        if img.isNull():
            return
        img = img.scaled(480, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
        self.local.setPixmap(QPixmap.fromImage(img).scaled(self.local.size(), Qt.AspectRatioMode.KeepAspectRatio))
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.save(buf, "JPG", 55)
        self.win.bridge.run(self.node.calls.send_video(bytes(buf.data())))

    def _show_remote(self, data: bytes) -> None:
        img = QImage.fromData(data, "JPG")
        if not img.isNull():
            self.remote.setPixmap(QPixmap.fromImage(img).scaled(self.remote.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                                Qt.TransformationMode.SmoothTransformation))

    def _stop_media(self) -> None:
        self._ring(False)
        for obj in (self.src, self.sink, self.camera):
            try:
                if obj is not None:
                    obj.stop()
            except Exception:
                pass
        if getattr(self, "play_timer", None) is not None:
            self.play_timer.stop()
        self.src = self.sink = self.camera = None
        self.src_io = self.sink_io = None
        self.jitter = None
        self.node.calls.on_audio = None
        self.node.calls.on_video = None

    # ---------------------------------------------------------------- controls
    def _toggle_mute(self) -> None:
        self.muted = not self.muted
        self.b_mute.setIcon(icons.plain("mic-off" if self.muted else "mic", 26, "#FFFFFF"))

    def _toggle_cam(self) -> None:
        self.cam_on = not self.cam_on
        self.b_cam.setIcon(icons.plain("video" if self.cam_on else "video-off", 26, "#FFFFFF"))
        if not self.cam_on:
            self.local.clear()
        self.win.bridge.run(self.node.calls.set_camera(self.cam_on))

    def _end(self) -> None:
        st = self.call.state
        self.win.bridge.run(self.node.calls.decline() if st == "ringing" else self.node.calls.hangup())

    def keyPressEvent(self, e) -> None:
        k = e.key()
        if k == Qt.Key.Key_Escape:
            self._end()
        elif k == Qt.Key.Key_M and self.call.state == "active":
            self._toggle_mute()
        elif k == Qt.Key.Key_V and self.call.state == "active" and self.call.video:
            self._toggle_cam()
        elif k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.call.state == "ringing" and not self.call.outgoing:
            self.win.bridge.run(self.node.calls.accept())
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e) -> None:
        if self.call.state != "ended":
            self._end()
        self._stop_media()
        super().closeEvent(e)
