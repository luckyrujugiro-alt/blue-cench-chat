"""Lucide SVG icons (ISC licence, see assets/icons/LICENSE-lucide.txt) rendered
in any colour at any size.  No emoji are used anywhere in the interface."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .. import config
from . import theme


@lru_cache(maxsize=512)
def _svg(name: str) -> str:
    path = config.resource_path("assets", "icons", f"{name}.svg")
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return config.resource_path("assets", "icons", "circle-help.svg").read_text(encoding="utf-8")


@lru_cache(maxsize=2048)
def pixmap(name: str, size: int = 18, color: str | None = None, stroke: float = 2.0, dpr: float = 2.0) -> QPixmap:
    color = color or theme.palette().text
    data = _svg(name).replace("currentColor", color).replace('stroke-width="2"', f'stroke-width="{stroke}"')
    renderer = QSvgRenderer(QByteArray(data.encode()))
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(p, QRectF(0, 0, size * dpr, size * dpr))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, size: int = 18, color: str | None = None, active_color: str | None = None) -> QIcon:
    ic = QIcon()
    ic.addPixmap(pixmap(name, size, color or theme.palette().muted), QIcon.Mode.Normal, QIcon.State.Off)
    ic.addPixmap(pixmap(name, size, active_color or theme.palette().text), QIcon.Mode.Normal, QIcon.State.On)
    ic.addPixmap(pixmap(name, size, active_color or theme.palette().text), QIcon.Mode.Active, QIcon.State.Off)
    ic.addPixmap(pixmap(name, size, theme.palette().faint), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic


def plain(name: str, size: int = 18, color: str | None = None) -> QIcon:
    return QIcon(pixmap(name, size, color))


def qsize(n: int) -> QSize:
    return QSize(n, n)


def clear_cache() -> None:
    pixmap.cache_clear()
