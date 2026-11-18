"""Blue Cench characters: 12 original cartoon avatars, drawn in code (no image files, no copyrights).

Everyone without a photo gets one picked from their ID, and anyone can choose one in My Profile.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient

BACKGROUNDS = [("#1E6BFF", "#00C2FF"), ("#7C4DFF", "#1E8BFF"), ("#00BA7C", "#22D3EE"), ("#F59E0B", "#F4212E"),
               ("#0F2147", "#1E8BFF"), ("#EC4899", "#8B5CF6"), ("#14B8A6", "#3B82F6"), ("#64748B", "#0EA5E9")]
SKINS = ["#FFC94A", "#F5B041", "#E8A33D", "#C68642", "#8D5524", "#FFD39B"]

NAMES = ["Cap", "Shades", "Gentleman", "Beanie", "Headphones", "Glasses", "King", "Cool kid", "Wink",
         "Starry", "Hoodie", "Pilot"]


def _face(p: QPainter, c: QPointF, r: float, skin: str) -> None:
    g = QRadialGradient(QPointF(c.x() - r * .35, c.y() - r * .4), r * 1.4)
    base = QColor(skin)
    g.setColorAt(0, base.lighter(130))
    g.setColorAt(1, base.darker(112))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawEllipse(c, r, r)


def _eyes(p: QPainter, c: QPointF, r: float, style: str = "dot") -> None:
    p.setBrush(QColor("#2B1B12"))
    p.setPen(Qt.PenStyle.NoPen)
    for dx in (-1, 1):
        e = QPointF(c.x() + dx * r * .36, c.y() - r * .12)
        if style == "happy":
            pen = QPen(QColor("#2B1B12"), r * .09, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(QRectF(e.x() - r * .13, e.y() - r * .08, r * .26, r * .2), 0, 180 * 16)
            p.setPen(Qt.PenStyle.NoPen)
        elif style == "wink" and dx == 1:
            pen = QPen(QColor("#2B1B12"), r * .09, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(e.x() - r * .12, e.y()), QPointF(e.x() + r * .12, e.y()))
            p.setPen(Qt.PenStyle.NoPen)
        else:
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(e, r * .14, r * .16)
            p.setBrush(QColor("#2B1B12"))
            p.drawEllipse(QPointF(e.x(), e.y() + r * .02), r * .08, r * .09)


def _smile(p: QPainter, c: QPointF, r: float, open_mouth: bool = False) -> None:
    if open_mouth:
        path = QPainterPath()
        path.moveTo(c.x() - r * .38, c.y() + r * .22)
        path.quadTo(c.x(), c.y() + r * .78, c.x() + r * .38, c.y() + r * .22)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#7A1F1F"))
        p.drawPath(path)
        p.setBrush(QColor("#F4212E"))
        p.drawEllipse(QPointF(c.x(), c.y() + r * .5), r * .16, r * .09)
    else:
        pen = QPen(QColor("#2B1B12"), r * .09, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(c.x() - r * .38, c.y() - r * .05, r * .76, r * .62), -20 * 16, -140 * 16)


def _cap(p, c, r, color="#1E6BFF"):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    path = QPainterPath()
    path.moveTo(c.x() - r * 1.0, c.y() - r * .25)
    path.cubicTo(c.x() - r, c.y() - r * 1.35, c.x() + r, c.y() - r * 1.35, c.x() + r * 1.0, c.y() - r * .25)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(QColor(color).darker(130))
    p.drawRoundedRect(QRectF(c.x() - r * .1, c.y() - r * .42, r * 1.45, r * .2), r * .1, r * .1)
    p.setBrush(QColor("#FFFFFF"))
    p.drawEllipse(QPointF(c.x(), c.y() - r * 1.02), r * .08, r * .08)


def _beanie(p, c, r, color="#2F5233"):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    path = QPainterPath()
    path.moveTo(c.x() - r * .98, c.y() - r * .3)
    path.cubicTo(c.x() - r * .9, c.y() - r * 1.45, c.x() + r * .9, c.y() - r * 1.45, c.x() + r * .98, c.y() - r * .3)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(QColor(color).darker(125))
    p.drawRoundedRect(QRectF(c.x() - r * 1.02, c.y() - r * .5, r * 2.04, r * .32), r * .12, r * .12)
    p.setPen(QPen(QColor(color).lighter(120), r * .05))
    for i in range(-4, 5):
        x = c.x() + i * r * .22
        p.drawLine(QPointF(x, c.y() - r * .48), QPointF(x, c.y() - r * .2))


def _fedora(p, c, r):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#7B4A2A"))
    p.drawEllipse(QRectF(c.x() - r * 1.35, c.y() - r * .78, r * 2.7, r * .5))
    p.drawRoundedRect(QRectF(c.x() - r * .72, c.y() - r * 1.45, r * 1.44, r * .85), r * .35, r * .35)
    p.setBrush(QColor("#2B2F3A"))
    p.drawRect(QRectF(c.x() - r * .72, c.y() - r * .82, r * 1.44, r * .18))


def _mustache(p, c, r):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#2B2F3A"))
    for dx in (-1, 1):
        path = QPainterPath()
        path.moveTo(c.x(), c.y() + r * .2)
        path.cubicTo(c.x() + dx * r * .2, c.y() + r * .02, c.x() + dx * r * .6, c.y() + r * .05,
                     c.x() + dx * r * .62, c.y() + r * .32)
        path.cubicTo(c.x() + dx * r * .45, c.y() + r * .2, c.x() + dx * r * .2, c.y() + r * .32, c.x(), c.y() + r * .28)
        p.drawPath(path)


def _shades(p, c, r):
    p.setPen(QPen(QColor("#111"), r * .07))
    p.setBrush(QColor("#111"))
    for dx in (-1, 1):
        p.drawRoundedRect(QRectF(c.x() + dx * r * .38 - r * .3, c.y() - r * .3, r * .6, r * .36), r * .14, r * .14)
    p.drawLine(QPointF(c.x() - r * .1, c.y() - r * .2), QPointF(c.x() + r * .1, c.y() - r * .2))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 90))
    p.drawEllipse(QPointF(c.x() - r * .5, c.y() - r * .2), r * .07, r * .05)


def _glasses(p, c, r):
    p.setPen(QPen(QColor("#1F2937"), r * .07))
    p.setBrush(QColor(255, 255, 255, 40))
    for dx in (-1, 1):
        p.drawEllipse(QPointF(c.x() + dx * r * .38, c.y() - r * .12), r * .25, r * .23)
    p.drawLine(QPointF(c.x() - r * .13, c.y() - r * .14), QPointF(c.x() + r * .13, c.y() - r * .14))


def _headphones(p, c, r):
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor("#111827"), r * .16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(c.x() - r * 1.05, c.y() - r * 1.15, r * 2.1, r * 1.9), 10 * 16, 160 * 16)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1E6BFF"))
    for dx in (-1, 1):
        p.drawRoundedRect(QRectF(c.x() + dx * r * .95 - r * .2, c.y() - r * .35, r * .4, r * .7), r * .15, r * .15)


def _crown(p, c, r):
    p.setPen(Qt.PenStyle.NoPen)
    g = QLinearGradient(0, c.y() - r * 1.6, 0, c.y() - r * .7)
    g.setColorAt(0, QColor("#FFE58A"))
    g.setColorAt(1, QColor("#F59E0B"))
    p.setBrush(g)
    path = QPainterPath()
    base = c.y() - r * .78
    path.moveTo(c.x() - r * .75, base)
    for i, (dx, up) in enumerate(((-0.75, .75), (-0.38, .35), (0, .85), (0.38, .35), (0.75, .75))):
        path.lineTo(c.x() + dx * r, base - up * r)
        if i < 4:
            path.lineTo(c.x() + (dx + .19) * r, base - .3 * r)
    path.lineTo(c.x() + r * .75, base)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(QColor("#1D9BF0"))
    p.drawEllipse(QPointF(c.x(), base - r * .22), r * .09, r * .09)


def _hood(p, c, r, color="#1E293B"):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(color))
    path = QPainterPath()
    path.addEllipse(QRectF(c.x() - r * 1.3, c.y() - r * 1.3, r * 2.6, r * 2.8))
    inner = QPainterPath()
    inner.addEllipse(QRectF(c.x() - r * 1.02, c.y() - r * 1.02, r * 2.04, r * 2.1))
    p.drawPath(path.subtracted(inner))


def _helmet(p, c, r):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#E5E7EB"))
    path = QPainterPath()
    path.moveTo(c.x() - r * 1.05, c.y() - r * .15)
    path.cubicTo(c.x() - r * 1.05, c.y() - r * 1.45, c.x() + r * 1.05, c.y() - r * 1.45, c.x() + r * 1.05, c.y() - r * .15)
    path.closeSubpath()
    p.drawPath(path)
    p.setBrush(QColor(0, 194, 255, 170))
    p.drawRoundedRect(QRectF(c.x() - r * .75, c.y() - r * .52, r * 1.5, r * .42), r * .2, r * .2)


def _stars(p, c, r):
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#FFFFFF"))
    for (dx, dy, s) in ((-1.15, -1.0, .16), (1.1, -1.1, .12), (1.25, .2, .1), (-1.3, .3, .09)):
        cx, cy = c.x() + dx * r, c.y() + dy * r
        path = QPainterPath()
        for i in range(9):
            a = -math.pi / 2 + i * math.pi / 4
            rr = s * r * (1 if i % 2 == 0 else .4)
            pt = QPointF(cx + rr * math.cos(a), cy + rr * math.sin(a))
            path.moveTo(pt) if i == 0 else path.lineTo(pt)
        p.drawPath(path)


def draw_character(index: int, size: int = 256) -> QPixmap:
    index %= len(NAMES)
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    a, b = BACKGROUNDS[index % len(BACKGROUNDS)]
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor(a))
    g.setColorAt(1, QColor(b))
    clip = QPainterPath()
    clip.addEllipse(QRectF(0, 0, size, size))
    p.setClipPath(clip)
    p.fillRect(QRectF(0, 0, size, size), g)
    # shoulders
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255, 60))
    p.drawEllipse(QRectF(size * .14, size * .78, size * .72, size * .5))
    c = QPointF(size / 2, size * .5)
    r = size * .3
    skin = SKINS[index % len(SKINS)]
    if index == 10:
        _hood(p, c, r)
    _face(p, c, r, skin)
    eyes = {2: "happy", 8: "wink", 3: "happy"}.get(index, "dot")
    _eyes(p, c, r, eyes)
    _smile(p, c, r, open_mouth=index in (2, 6, 9))
    {0: lambda: _cap(p, c, r), 1: lambda: _shades(p, c, r),
     2: lambda: (_fedora(p, c, r), _mustache(p, c, r)), 3: lambda: _beanie(p, c, r),
     4: lambda: _headphones(p, c, r), 5: lambda: _glasses(p, c, r), 6: lambda: _crown(p, c, r),
     7: lambda: (_cap(p, c, r, "#F4212E"), _shades(p, c, r)), 8: lambda: None, 9: lambda: _stars(p, c, r),
     10: lambda: None, 11: lambda: _helmet(p, c, r)}[index]()
    p.end()
    return pm


def character_png(index: int, size: int = 256) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    draw_character(index, size).save(buf, "PNG")
    return bytes(buf.data())


def index_for(seed: str) -> int:
    return sum((i + 1) * ord(ch) for i, ch in enumerate(seed or "x")) % len(NAMES)
