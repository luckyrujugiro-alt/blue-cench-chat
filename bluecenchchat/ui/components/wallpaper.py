"""Blue Cench chat wallpaper: a hand-drawn doodle tile (our own), tinted per theme."""
from __future__ import annotations

import math
import random
from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPalette, QPen, QPixmap

TILE = 360


def _bluetooth(p: QPainter, c: QPointF, s: float) -> None:
    pts = [QPointF(c.x() - s * .45, c.y() - s * .45), QPointF(c.x() + s * .45, c.y() + s * .45),
           QPointF(c.x(), c.y() + s * .9), QPointF(c.x(), c.y() - s * .9),
           QPointF(c.x() + s * .45, c.y() - s * .45), QPointF(c.x() - s * .45, c.y() + s * .45)]
    p.drawPolyline(pts)


def _bubble(p: QPainter, c: QPointF, s: float) -> None:
    path = QPainterPath()
    path.addRoundedRect(QRectF(c.x() - s, c.y() - s * .7, 2 * s, s * 1.3), s * .5, s * .5)
    p.drawPath(path)
    p.drawLine(QPointF(c.x() - s * .5, c.y() + s * .6), QPointF(c.x() - s * .8, c.y() + s))
    for i in (-1, 0, 1):
        p.drawPoint(QPointF(c.x() + i * s * .45, c.y()))


def _star(p: QPainter, c: QPointF, s: float) -> None:
    path = QPainterPath()
    for i in range(11):
        a = -math.pi / 2 + i * math.pi / 5
        r = s if i % 2 == 0 else s * .45
        pt = QPointF(c.x() + r * math.cos(a), c.y() + r * math.sin(a))
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    p.drawPath(path)


def _heart(p: QPainter, c: QPointF, s: float) -> None:
    path = QPainterPath()
    path.moveTo(c.x(), c.y() + s * .8)
    path.cubicTo(c.x() - s * 1.3, c.y() - s * .1, c.x() - s * .6, c.y() - s * 1.1, c.x(), c.y() - s * .35)
    path.cubicTo(c.x() + s * .6, c.y() - s * 1.1, c.x() + s * 1.3, c.y() - s * .1, c.x(), c.y() + s * .8)
    p.drawPath(path)


def _note(p: QPainter, c: QPointF, s: float) -> None:
    p.drawEllipse(QRectF(c.x() - s * .7, c.y() + s * .3, s * .7, s * .55))
    p.drawLine(QPointF(c.x(), c.y() + s * .55), QPointF(c.x(), c.y() - s * .9))
    p.drawLine(QPointF(c.x(), c.y() - s * .9), QPointF(c.x() + s * .6, c.y() - s * .55))


def _plane(p: QPainter, c: QPointF, s: float) -> None:
    p.drawPolygon([QPointF(c.x() - s, c.y()), QPointF(c.x() + s, c.y() - s * .7), QPointF(c.x() + s * .2, c.y() + s * .8)])
    p.drawLine(QPointF(c.x() + s, c.y() - s * .7), QPointF(c.x() - s * .15, c.y() + s * .15))


def _smile(p: QPainter, c: QPointF, s: float) -> None:
    p.drawEllipse(c, s, s)
    p.drawPoint(QPointF(c.x() - s * .35, c.y() - s * .2))
    p.drawPoint(QPointF(c.x() + s * .35, c.y() - s * .2))
    p.drawArc(QRectF(c.x() - s * .5, c.y() - s * .3, s, s * .8), -20 * 16, -140 * 16)


def _waves(p: QPainter, c: QPointF, s: float) -> None:
    for i in range(1, 4):
        r = s * .35 * i
        p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), -45 * 16, 90 * 16)
    p.drawEllipse(c, s * .12, s * .12)


SHAPES = [_bluetooth, _bubble, _star, _heart, _note, _plane, _smile, _waves]


@lru_cache(maxsize=8)
def doodle_tile(ink: str, alpha: int, bg: str) -> QPixmap:
    pm = QPixmap(TILE, TILE)
    pm.fill(QColor(bg))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    col = QColor(ink)
    col.setAlpha(alpha)
    pen = QPen(col, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    rnd = random.Random(7)  # same pattern every time
    cell = TILE / 6
    for gy in range(6):
        for gx in range(6):
            cx = gx * cell + cell / 2 + rnd.uniform(-cell * .2, cell * .2)
            cy = gy * cell + cell / 2 + rnd.uniform(-cell * .2, cell * .2)
            size = rnd.uniform(9, 14)
            p.save()
            p.translate(cx, cy)
            p.rotate(rnd.uniform(-25, 25))
            SHAPES[(gx + gy * 3 + rnd.randint(0, 7)) % len(SHAPES)](p, QPointF(0, 0), size)
            p.restore()
    p.end()
    return pm


def apply_wallpaper(widget, palette) -> None:
    """Paint the doodle tile behind a scroll area's viewport."""
    dark = palette.name in ("dark", "midnight")
    ink = "#4DB2FF" if palette.name == "midnight" else ("#FFFFFF" if dark else "#1E6BFF")
    alpha = 34 if dark else 30
    tile = doodle_tile(ink, alpha, palette.bg if dark else "#F4F7FC")
    pal = widget.palette()
    pal.setBrush(QPalette.ColorRole.Window, QBrush(tile))
    pal.setBrush(QPalette.ColorRole.Base, QBrush(tile))
    widget.setPalette(pal)
    widget.setAutoFillBackground(True)


from PySide6.QtWidgets import QWidget  # noqa: E402


class WallpaperHost(QWidget):
    """Content widget of the chat scroll area that paints the doodle tile itself
    (immune to stylesheet backgrounds)."""

    def __init__(self, palette_fn) -> None:
        super().__init__()
        self._palette_fn = palette_fn

    def paintEvent(self, e) -> None:
        pal = self._palette_fn()
        dark = pal.name in ("dark", "midnight")
        ink = "#4DB2FF" if pal.name == "midnight" else ("#FFFFFF" if dark else "#1E6BFF")
        tile = doodle_tile(ink, 30 if dark else 26, pal.bg if dark else "#F4F7FC")
        p = QPainter(self)
        p.drawTiledPixmap(e.rect(), tile, e.rect().topLeft())
