"""One-click update window: a little helicopter flies while the new version downloads."""
from __future__ import annotations

import asyncio
import math
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QDialog, QHBoxLayout, QProgressBar, QVBoxLayout, QWidget

from .. import config
from ..core import updates
from . import theme
from .components.widgets import button, label


class Helicopter(QWidget):
    """Hand-drawn helicopter: spinning rotor, tail rotor, gentle bobbing. Speeds up while downloading."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(240, 150)
        self.angle = 0.0
        self.t = 0.0
        self.speed = 0.35
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._step)
        self.timer.start()

    def set_speed(self, s: float) -> None:
        self.speed = s

    def _step(self) -> None:
        self.angle = (self.angle + self.speed) % (2 * math.pi)
        self.t += 0.016
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = theme.palette()
        blue, cyan = QColor("#1E6BFF"), QColor("#00C2FF")
        cx = self.width() / 2
        cy = 78 + math.sin(self.t * 2.2) * 5  # bob up and down
        # wind lines
        p.setPen(QPen(QColor(pal.faint), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for i in range(3):
            x = (self.t * 140 + i * 80) % (self.width() + 60) - 30
            y = 40 + i * 30
            p.drawLine(QPointF(self.width() - x, y), QPointF(self.width() - x + 22, y))
        # body
        g = QLinearGradient(cx - 50, cy - 20, cx + 40, cy + 25)
        g.setColorAt(0, blue)
        g.setColorAt(1, cyan)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRoundedRect(QRectF(cx - 46, cy - 20, 78, 42), 21, 21)
        # tail boom + fin
        p.drawRoundedRect(QRectF(cx + 24, cy - 6, 62, 10), 5, 5)
        fin = QPainterPath()
        fin.moveTo(cx + 80, cy - 2)
        fin.lineTo(cx + 92, cy - 22)
        fin.lineTo(cx + 96, cy - 22)
        fin.lineTo(cx + 90, cy + 2)
        fin.closeSubpath()
        p.drawPath(fin)
        # window with a Bluetooth rune
        p.setBrush(QColor(255, 255, 255, 215))
        p.drawRoundedRect(QRectF(cx - 38, cy - 13, 30, 20), 9, 9)
        p.setPen(QPen(blue, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        bx, by = cx - 23, cy - 3
        p.drawPolyline([QPointF(bx - 4, by - 4), QPointF(bx + 4, by + 4), QPointF(bx, by + 8), QPointF(bx, by - 8),
                        QPointF(bx + 4, by - 4), QPointF(bx - 4, by + 4)])
        # skids
        p.setPen(QPen(QColor(pal.muted), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx - 30, cy + 22), QPointF(cx - 30, cy + 30))
        p.drawLine(QPointF(cx + 14, cy + 22), QPointF(cx + 14, cy + 30))
        p.drawLine(QPointF(cx - 46, cy + 30), QPointF(cx + 28, cy + 30))
        # mast + main rotor (two blades seen edge-on: their length pulses as they spin)
        p.setPen(QPen(QColor(pal.text), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx - 8, cy - 20), QPointF(cx - 8, cy - 30))
        rot = QPen(QColor(pal.text), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        for k in (0, math.pi / 2):
            span = 78 * abs(math.cos(self.angle + k))
            c = QColor(pal.text)
            c.setAlpha(110 + int(140 * abs(math.cos(self.angle + k))))
            rot.setColor(c)
            p.setPen(rot)
            p.drawLine(QPointF(cx - 8 - span, cy - 31), QPointF(cx - 8 + span, cy - 31))
        # tail rotor
        p.setPen(QPen(QColor(pal.text), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        tr = 11
        tx, ty = cx + 92, cy - 4
        a = self.angle * 3
        p.drawLine(QPointF(tx - tr * math.cos(a), ty - tr * math.sin(a)),
                   QPointF(tx + tr * math.cos(a), ty + tr * math.sin(a)))


class UpdateDialog(QDialog):
    progressed = Signal(int, int)

    def __init__(self, win, auto_check: bool = True) -> None:
        super().__init__(win)
        self.win = win
        self.latest: str | None = None
        self._cancel = False
        self.setWindowTitle("Update Blue Cench Chat")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 22, 28, 22)
        lay.setSpacing(10)
        self.heli = Helicopter()
        lay.addWidget(self.heli, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title = label("Checking for updates...", "h2")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.title)
        self.text = label(f"You have version {config.APP_VERSION}.", "muted", wrap=True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.text)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.hide()
        lay.addWidget(self.bar)
        row = QHBoxLayout()
        row.addStretch(1)
        self.b_close = button("Close", variant="ghost")
        self.b_go = button("Update now", "download", "primary")
        self.b_go.hide()
        row.addWidget(self.b_close)
        row.addWidget(self.b_go)
        row.addStretch(1)
        lay.addLayout(row)
        self.b_close.clicked.connect(self._close)
        self.b_go.clicked.connect(self._start)
        self.progressed.connect(self._on_progress)
        if auto_check:
            QTimer.singleShot(50, self._check)

    # ------------------------------------------------------------------ steps
    def _check(self) -> None:
        async def go():
            return await asyncio.to_thread(updates.latest_version)

        def done(v):
            self.latest = v
            if v is None:
                self.title.setText("Couldn't check for updates")
                self.text.setText("Connect to the internet and try again.")
                self.heli.set_speed(0.12)
            elif updates.is_newer(v):
                self.title.setText(f"Version {v} is ready")
                self.text.setText(f"You have {config.APP_VERSION}. The update downloads, is checked for damage, "
                                  "installs by itself and reopens the app - your chats and account stay.")
                self.b_go.show()
                self.b_go.setFocus()
            else:
                self.title.setText("You're up to date")
                self.text.setText(f"Blue Cench Chat {config.APP_VERSION} is the newest version.")
                self.heli.set_speed(0.15)
        self.win.bridge.run(go(), done)

    def _start(self) -> None:
        if os.name != "nt":
            self.win.toast("Automatic install works on Windows", "warning")
            return
        self.b_go.setEnabled(False)
        self.bar.show()
        self.heli.set_speed(0.9)
        self.title.setText("Flying in the update...")
        self.text.setText("Downloading")
        dest = Path(tempfile.gettempdir()) / "BlueCenchChat-update" / "BlueCenchChat-Setup.exe"

        async def go():
            return await asyncio.to_thread(updates.download_installer, dest,
                                           lambda d, t: self.progressed.emit(d, t), lambda: self._cancel)

        def done(_digest):
            self.bar.setValue(1000)
            self.title.setText("Landing - installing now")
            self.text.setText("The app will close for a few seconds and open again by itself.")
            self.heli.set_speed(1.3)
            try:
                updates.install_silently(dest)
            except Exception as exc:  # noqa: BLE001
                self._fail(str(exc))
                return
            QTimer.singleShot(1200, self.win.quit_app)

        self.win.bridge.run(go(), done, self._fail)

    def _fail(self, msg) -> None:
        self.heli.set_speed(0.12)
        self.title.setText("Update didn't finish")
        self.text.setText(str(msg))
        self.bar.hide()
        self.b_go.setEnabled(True)
        self.b_go.setText("Try again")

    def _on_progress(self, done: int, total: int) -> None:
        mb = done / 1_048_576
        if total:
            self.bar.setValue(int(1000 * done / total))
            self.text.setText(f"Downloading  {mb:.1f} of {total / 1_048_576:.1f} MB")
        else:
            self.text.setText(f"Downloading  {mb:.1f} MB")

    def _close(self) -> None:
        self._cancel = True
        self.reject()
