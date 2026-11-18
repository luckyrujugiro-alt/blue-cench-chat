"""Live transfer card used on the Transfers page, the dashboard and in chats."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from .. import icons, system, theme
from .widgets import Pill, button, human_duration, human_size, label, tool_button

STATUS_TEXT = {
    "preparing": ("Preparing (hashing)", "neutral"),
    "queued": ("Queued - contact offline", "neutral"),
    "waiting": ("Waiting for receiver", "primary"),
    "offered": ("Incoming - needs your approval", "warning"),
    "active": ("Transferring", "cyan"),
    "paused": ("Paused", "warning"),
    "completed": ("Completed - SHA-256 verified", "success"),
    "failed": ("Failed", "danger"),
    "cancelled": ("Cancelled", "neutral"),
    "rejected": ("Declined", "neutral"),
    "interrupted": ("Interrupted - resumes on reconnect", "warning"),
}


TYPE_COLORS = {  # file-type tile gradients
    "video": ("#7C4DFF", "#00C2FF"), "image": ("#00BA7C", "#1D9BF0"), "audio": ("#F59E0B", "#F4212E"),
    "archive": ("#64748B", "#334155"), "doc": ("#1E6BFF", "#00C2FF"), "app": ("#0F2147", "#1E8BFF"),
    "other": ("#475569", "#1E293B"),
}
KINDS = {
    "video": {".mp4", ".mkv", ".mov", ".avi", ".webm"}, "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"},
    "audio": {".mp3", ".m4a", ".wav", ".ogg", ".flac", ".aac"}, "archive": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "doc": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".md"},
    "app": {".exe", ".msi", ".apk", ".iso"},
}


def type_tile(label_text: str, size: int = 44) -> QPixmap:
    """Rounded gradient tile with the file extension (MP4, ZIP, PDF...)."""
    ext = Path(label_text).suffix.lower()
    kind = next((k for k, exts in KINDS.items() if ext in exts), "other")
    if label_text.endswith(")") or not ext:  # folders / multi-file bundles
        kind, ext = "app", ".dir"
    a, b = TYPE_COLORS[kind]
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor(a))
    g.setColorAt(1, QColor(b))
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), 12, 12)
    p.fillPath(path, g)
    f = QFont()
    f.setBold(True)
    f.setPixelSize(int(size * (0.30 if len(ext) <= 4 else 0.24)))
    p.setFont(f)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter,
               "FILES" if ext == ".dir" else (ext[1:5].upper() or "FILE"))
    p.end()
    return pm


def rounded(pm: QPixmap, radius: int = 14) -> QPixmap:
    out = QPixmap(pm.size())
    out.setDevicePixelRatio(pm.devicePixelRatio())
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    w, h = pm.width() / pm.devicePixelRatio(), pm.height() / pm.devicePixelRatio()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


class TransferRow(QFrame):
    def __init__(self, bridge, transfer_id: str, compact: bool = False) -> None:
        super().__init__()
        self.bridge = bridge
        self.node = bridge.node
        self.tid = transfer_id
        self.compact = compact
        self.setObjectName("SoftCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(40, 40)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setStyleSheet(f"background:{theme.palette().surface3}; border-radius:10px;")
        top.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = label("", "h3")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.sub = label("", "muted")
        col.addWidget(self.title)
        col.addWidget(self.sub)
        top.addLayout(col, 1)
        self.transport = Pill("", "neutral")
        self.status = Pill("", "neutral")
        top.addWidget(self.transport)
        top.addWidget(self.status)
        lay.addLayout(top)
        self.preview = QLabel()
        self.preview.hide()
        lay.addWidget(self.preview)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        if compact:
            self.bar.setTextVisible(False)
            self.bar.setFixedHeight(6)
            self.bar.setStyleSheet(
                f"QProgressBar {{ background:{theme.palette().surface3}; border:none; border-radius:3px; }}"
                "QProgressBar::chunk { border-radius:3px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,"
                " stop:0 #1E6BFF, stop:1 #00C2FF); }")
        lay.addWidget(self.bar)
        bottom = QHBoxLayout()
        self.stats = label("", "faint")
        bottom.addWidget(self.stats, 1)
        self.b_accept = button("Accept", "download", "primary")
        self.b_decline = button("Decline", "x")
        self.b_pause = tool_button("pause", "Pause")
        self.b_resume = tool_button("play", "Resume")
        self.b_retry = tool_button("rotate-cw", "Retry")
        self.b_cancel = tool_button("x", "Cancel transfer")
        self.b_open = tool_button("folder-open", "Show in folder")
        for b in (self.b_accept, self.b_decline, self.b_pause, self.b_resume, self.b_retry, self.b_open, self.b_cancel):
            bottom.addWidget(b)
        lay.addLayout(bottom)
        eng = self.node.transfers
        self.b_accept.clicked.connect(lambda: self._accept())
        self.b_decline.clicked.connect(lambda: bridge.run(eng.decline(self.tid)))
        self.b_pause.clicked.connect(lambda: bridge.run(eng.pause(self.tid)))
        self.b_resume.clicked.connect(lambda: bridge.run(eng.resume(self.tid)))
        self.b_retry.clicked.connect(lambda: bridge.run(eng.retry(self.tid)))
        self.b_cancel.clicked.connect(lambda: bridge.run(eng.cancel(self.tid)))
        self.b_open.clicked.connect(self._open)
        self._preview_done = False
        self.refresh()

    def _accept(self) -> None:
        t = self.node.repo.transfer(self.tid)
        if t and t.transport == "rfcomm" and t.total_bytes > 200 * 1024 * 1024:
            self.bridge.toast("Large transfer over Bluetooth RFCOMM - this may take a long time. "
                              "Connect over the local network for faster speeds.", "warning")
        if self.node.low_battery():
            self.bridge.toast("Battery is below 20%. Consider plugging in before a long transfer.", "warning")
        self.bridge.run(self.node.transfers.accept(self.tid))

    def _open(self) -> None:
        t = self.node.repo.transfer(self.tid)
        if not t:
            return
        if t.direction == "in":
            paths = [f.get("dest_path") for f in t.files if f.get("dest_path")]
            if paths:
                system.reveal_file(paths[0])
            else:
                system.open_path(self.node.settings.get("download_dir"))
        else:
            system.reveal_file(t.files[0]["src_path"])

    def refresh(self) -> None:
        t = self.node.repo.transfer(self.tid)
        if t is None:
            self.hide()
            return
        p = theme.palette()
        c = self.node.repo.contact(t.contact_id)
        name = c.name if c else "Unknown"
        if self.compact:
            self.icon.setPixmap(type_tile(t.label, 40))
            self.icon.setStyleSheet("background: transparent;")
        else:
            self.icon.setPixmap(icons.pixmap(system.file_icon_name(t.label), 20,
                                             p.cyan if t.direction == "in" else p.primary_hover))
        self.title.setText(t.label)
        arrow = "from" if t.direction == "in" else "to"
        nfiles = f"{len(t.files)} file{'s' if len(t.files) != 1 else ''}"
        if self.compact:  # in a chat the person is obvious - keep it short
            self.sub.setText(f"{human_size(t.total_bytes)}  ·  {nfiles}")
        else:
            self.sub.setText(f"{'Receiving' if t.direction == 'in' else 'Sending'} {arrow} {name}  |  "
                             f"{nfiles}  |  {human_size(t.total_bytes)}")
        if t.transport and self.compact:
            self.transport.hide()
        elif t.transport:
            self.transport.setText(self.node.transport_label(t.transport))
            self.transport.set_tone("cyan" if t.transport == "lan" else "primary")
            self.transport.show()
        else:
            self.transport.hide()
        text, tone = STATUS_TEXT.get(t.status, (t.status, "neutral"))
        self.status.setText(text if not self.compact else text.split(" - ")[0])
        self.status.set_tone(tone)
        st = self.node.transfers.stats_for(self.tid)
        frac = (st["done"] / st["total"]) if st["total"] else (1.0 if t.status == "completed" else 0.0)
        if t.status == "completed":
            frac = 1.0
        self.bar.setValue(int(frac * 1000))
        state = {"completed": "done", "failed": "error", "paused": "paused", "interrupted": "paused"}.get(t.status, "")
        if self.bar.property("state") != state:
            self.bar.setProperty("state", state)
            self.bar.style().unpolish(self.bar)
            self.bar.style().polish(self.bar)
        parts = [f"{human_size(st['done'])} of {human_size(st['total'])}", f"{frac * 100:.0f}%"]
        if t.status == "active":
            parts.append(f"{human_size(st['speed'])}/s")
            parts.append(f"{human_duration(st['eta'])} left")
        if self.compact and t.transport:
            parts.append("via " + self.node.transport_label(t.transport))
        if t.error and t.status not in ("completed", "active"):
            parts.append(t.error)
        dups = sum(1 for f in t.files if f.get("status") == "duplicate")
        if dups:
            parts.append(f"{dups} duplicate(s) skipped")
        self.stats.setText("  |  ".join(parts))
        s = t.status
        self.b_accept.setVisible(t.direction == "in" and s == "offered")
        self.b_decline.setVisible(t.direction == "in" and s == "offered")
        self.b_pause.setVisible(s == "active")
        self.b_resume.setVisible(s == "paused")
        self.b_retry.setVisible(s in ("interrupted", "failed") or (s == "queued" and t.direction == "out"))
        self.b_cancel.setVisible(s in ("active", "paused", "waiting", "queued", "interrupted", "preparing"))
        self.b_open.setVisible(s == "completed" or t.direction == "out")
        self._maybe_preview(t)

    def _maybe_preview(self, t) -> None:
        """Photos show straight away when sending (we have the file) and as soon as they arrive."""
        if self._preview_done or len(t.files) != 1:
            return
        if t.direction == "in" and t.status != "completed":
            return
        f = t.files[0]
        path = f.get("dest_path") if t.direction == "in" else f.get("src_path")
        if not path or Path(path).suffix.lower() not in system.IMAGE_EXT or f["size"] > 25 * 1024 * 1024:
            return
        pm = QPixmap(path)
        if pm.isNull():
            return
        self._preview_done = True
        box = 300 if self.compact else 240
        pm = pm.scaled(box, int(box * 0.75), Qt.AspectRatioMode.KeepAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(rounded(pm, 14))
        self.preview.setCursor(Qt.CursorShape.PointingHandCursor)
        self.preview.setToolTip("Open photo")
        self.preview.mousePressEvent = lambda _e, path=path: system.open_path(path)
        self.preview.show()
