"""Hand-drawn badges: the verified seal (blue), the founder seal (gold) and avatar rings."""
from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QConicalGradient, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel

VERIFIED = ("#1D9BF0", "#0A7BD8")          # blue seal (gradient top -> bottom)
FOUNDER = ("#FFD54A", "#F59E0B")           # gold seal for the official account


def _seal_path(c: QPointF, r: float, bumps: int = 8) -> QPainterPath:
    """A rosette: circle with rounded scallops (like a wax seal)."""
    path = QPainterPath()
    steps = bumps * 24
    for i in range(steps + 1):
        a = 2 * math.pi * i / steps - math.pi / 2
        rr = r * (0.88 + 0.12 * math.cos(bumps * a))
        p = QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a))
        if i == 0:
            path.moveTo(p)
        else:
            path.lineTo(p)
    path.closeSubpath()
    return path


@lru_cache(maxsize=64)
def seal_pixmap(size: int, kind: str = "verified", dpr: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    top, bottom = FOUNDER if kind == "founder" else VERIFIED
    g = QLinearGradient(0, 0, 0, size)
    g.setColorAt(0, QColor(top))
    g.setColorAt(1, QColor(bottom))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    c = QPointF(size / 2, size / 2)
    p.drawPath(_seal_path(c, size / 2 - 0.5))
    # check mark
    pen = QPen(QColor("#FFFFFF"), max(1.6, size * 0.12), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    s = size
    p.drawPolyline([QPointF(s * 0.30, s * 0.52), QPointF(s * 0.44, s * 0.66), QPointF(s * 0.71, s * 0.37)])
    p.end()
    return pm


def seal_label(size: int = 16, kind: str = "verified") -> QLabel:
    lb = QLabel()
    lb.setPixmap(seal_pixmap(size, kind))
    lb.setFixedSize(size, size)
    lb.setObjectName("Tick")
    lb.setToolTip("Founder of Blue Cench Chat" if kind == "founder" else "Verified by Blue Cench Chat")
    return lb


def ring_pixmap(size: int, kind: str = "story", width: float = 3.0, dpr: float = 2.0) -> QPixmap:
    """Gradient ring drawn around avatars: brand blue for stories, gold for the founder, grey when seen."""
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(width / 2, width / 2, size - width, size - width)
    if kind == "seen":
        pen = QPen(QColor(150, 160, 175, 160), width)
    else:
        g = QConicalGradient(rect.center(), 90)
        stops = (["#FFE58A", "#F59E0B", "#FFD54A", "#FFF3C4", "#FFE58A"] if kind == "founder"
                 else ["#00C2FF", "#1E6BFF", "#7C4DFF", "#00C2FF"])
        for i, col in enumerate(stops):
            g.setColorAt(i / (len(stops) - 1), QColor(col))
        pen = QPen(g, width)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(rect)
    p.end()
    return pm
