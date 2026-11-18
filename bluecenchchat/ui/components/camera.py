"""Take a photo with the PC's camera (for stories, posts and your profile picture)."""
from __future__ import annotations

import os

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from .widgets import button, label


def capture_photo(parent) -> bytes | None:
    """Opens a live camera preview; returns JPEG bytes of the snapshot, or None."""
    if os.environ.get("BLUECENCHCHAT_NO_MEDIA"):
        return None
    try:
        from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
    except Exception:
        parent.window().toast("The camera isn't available on this PC", "warning")
        return None
    dev = QMediaDevices.defaultVideoInput()
    if dev.isNull():
        parent.window().toast("No camera found", "warning")
        return None

    d = QDialog(parent)
    d.setWindowTitle("Camera")
    d.setMinimumSize(560, 520)
    lay = QVBoxLayout(d)
    lay.setContentsMargins(18, 16, 18, 16)
    view = QLabel("Starting camera...")
    view.setAlignment(Qt.AlignmentFlag.AlignCenter)
    view.setMinimumHeight(380)
    view.setStyleSheet("background:#000; color:#9DB2D9; border-radius:14px;")
    lay.addWidget(view, 1)
    lay.addWidget(label("If the picture stays black, allow camera access in Windows Settings > Privacy > Camera.",
                        "faint", wrap=True))
    row = QHBoxLayout()
    row.addStretch(1)
    cancel = button("Cancel", variant="ghost")
    snap = button("Take photo", "camera", "primary")
    row.addWidget(cancel)
    row.addWidget(snap)
    row.addStretch(1)
    lay.addLayout(row)

    state = {"img": None, "jpeg": None}
    cam = QCamera(dev, d)
    session = QMediaCaptureSession(d)
    session.setCamera(cam)
    sink = QVideoSink(d)
    session.setVideoOutput(sink)

    def frame(f) -> None:
        img = f.toImage()
        if img.isNull():
            return
        state["img"] = img
        view.setPixmap(QPixmap.fromImage(img).scaled(view.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.FastTransformation))

    def take() -> None:
        img = state["img"]
        if img is None:
            return
        buf = QBuffer()
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        img.mirrored(True, False).save(buf, "JPG", 90)
        state["jpeg"] = bytes(buf.data())
        d.accept()

    sink.videoFrameChanged.connect(frame)
    snap.clicked.connect(take)
    cancel.clicked.connect(d.reject)
    cam.start()
    d.exec()
    cam.stop()
    return state["jpeg"]
