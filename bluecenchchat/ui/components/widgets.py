"""Reusable Blue Cench Chat interface components."""
from __future__ import annotations

import time

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .. import icons, theme


# --------------------------------------------------------------------------- helpers
def label(text: str = "", role: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    if selectable:
        lb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lb


def button(text: str, icon_name: str | None = None, variant: str | None = None, tooltip: str = "") -> QPushButton:
    b = QPushButton(text)
    if variant:
        b.setProperty("variant", variant)
    if icon_name:
        p = theme.palette()
        color = p.on_primary if variant == "primary" else (p.danger if variant == "danger" else
                                                           (p.primary if variant == "link" else p.text))
        b.setIcon(icons.plain(icon_name, 16, color))
        b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if tooltip:
        b.setToolTip(tooltip)
    return b


def tool_button(icon_name: str, tooltip: str, size: int = 18, color: str | None = None) -> QToolButton:
    b = QToolButton()
    b.setIcon(icons.plain(icon_name, size, color or theme.palette().muted))
    b.setIconSize(QSize(size, size))
    b.setToolTip(tooltip)
    b.setAccessibleName(tooltip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


def icon_label(icon_name: str, size: int = 18, color: str | None = None) -> QLabel:
    lb = QLabel()
    lb.setPixmap(icons.pixmap(icon_name, size, color))
    lb.setFixedSize(size, size)
    return lb


def divider() -> QFrame:
    f = QFrame()
    f.setObjectName("Divider")
    return f


def hbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0), stretch_at: int | None = None) -> QHBoxLayout:
    lay = QHBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for i, w in enumerate(widgets):
        if stretch_at is not None and i == stretch_at:
            lay.addStretch(1)
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


def vbox(*widgets, spacing: int = 8, margins=(0, 0, 0, 0)) -> QVBoxLayout:
    lay = QVBoxLayout()
    lay.setSpacing(spacing)
    lay.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            lay.addStretch(1)
        elif isinstance(w, QWidget):
            lay.addWidget(w)
        else:
            lay.addLayout(w)
    return lay


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_time(ts: float) -> str:
    if not ts:
        return "never"
    d = time.time() - ts
    if d < 45:
        return "just now"
    if d < 3600:
        return f"{int(d // 60)} min ago"
    lt, now = time.localtime(ts), time.localtime()
    if lt.tm_yday == now.tm_yday and lt.tm_year == now.tm_year:
        return time.strftime("%H:%M", lt)
    if d < 7 * 86400:
        return time.strftime("%a %H:%M", lt)
    return time.strftime("%d %b %Y", lt)


def human_duration(sec: float | None) -> str:
    if sec is None:
        return "--"
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    if sec < 3600:
        return f"{sec // 60}m {sec % 60:02d}s"
    return f"{sec // 3600}h {(sec % 3600) // 60:02d}m"


def shadow(widget: QWidget, blur: int = 28, alpha: int = 90, dy: int = 8) -> None:
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(0, 0, 0, alpha if theme.palette().name == "dark" else alpha // 3))
    widget.setGraphicsEffect(eff)


# --------------------------------------------------------------------------- containers
class Card(QFrame):
    def __init__(self, title: str | None = None, icon_name: str | None = None, padding: int = 18,
                 spacing: int = 12, object_name: str = "Card") -> None:
        super().__init__()
        self.setObjectName(object_name)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(spacing)
        self.header_layout = None
        if title:
            self.header_layout = QHBoxLayout()
            self.header_layout.setSpacing(8)
            if icon_name:
                self.header_layout.addWidget(icon_label(icon_name, 17, theme.palette().cyan))
            self.title_label = label(title, "h3")
            self.header_layout.addWidget(self.title_label)
            self.header_layout.addStretch(1)
            self.body.addLayout(self.header_layout)

    def add(self, w) -> None:
        if isinstance(w, QWidget):
            self.body.addWidget(w)
        else:
            self.body.addLayout(w)

    def add_header_widget(self, w: QWidget) -> None:
        if self.header_layout is not None:
            self.header_layout.addWidget(w)


class Pill(QLabel):
    def __init__(self, text: str, tone: str = "neutral") -> None:
        super().__init__(text)
        self.setObjectName("Pill")
        self.set_tone(tone)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)

    def set_tone(self, tone: str) -> None:
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)


class Page(QWidget):
    """Scrollable page with a title header."""

    def __init__(self, title: str, subtitle: str = "", scroll: bool = True) -> None:
        super().__init__()
        self.setObjectName("Page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        inner = QWidget()
        inner.setObjectName("PageInner")
        self.content = QVBoxLayout(inner)
        self.content.setContentsMargins(32, 26, 32, 28)
        self.content.setSpacing(18)
        head = QHBoxLayout()
        head.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(3)
        self.title_label = label(title, "h1")
        titles.addWidget(self.title_label)
        if subtitle:
            self.subtitle_label = label(subtitle, "muted", wrap=True)
            titles.addWidget(self.subtitle_label)
        head.addLayout(titles, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        head.addLayout(self.actions)
        self.content.addLayout(head)
        if scroll:
            sa = QScrollArea()
            sa.setWidgetResizable(True)
            sa.setFrameShape(QFrame.Shape.NoFrame)
            sa.setWidget(inner)
            outer.addWidget(sa)
        else:
            outer.addWidget(inner)

    def on_show(self) -> None:
        """Called by the main window whenever the page becomes visible."""

    def set_compact(self, compact: bool) -> None:
        m = 16 if compact else 32
        self.content.setContentsMargins(m, 18 if compact else 26, m, 20 if compact else 28)


class EmptyState(QWidget):
    def __init__(self, icon_name: str, title: str, text: str, action: QPushButton | None = None) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 36, 20, 36)
        lay.setSpacing(10)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bubble = QLabel()
        bubble.setFixedSize(64, 64)
        bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bubble.setStyleSheet(f"background:{theme.palette().primary_soft}; border-radius:32px;")
        bubble.setPixmap(icons.pixmap(icon_name, 28, theme.palette().primary_hover))
        lay.addWidget(bubble, 0, Qt.AlignmentFlag.AlignHCenter)
        t = label(title, "h3")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        d = label(text, "muted", wrap=True)
        d.setAlignment(Qt.AlignmentFlag.AlignCenter)
        d.setMaximumWidth(420)
        lay.addWidget(d, 0, Qt.AlignmentFlag.AlignHCenter)
        if action:
            lay.addSpacing(6)
            lay.addWidget(action, 0, Qt.AlignmentFlag.AlignHCenter)


# --------------------------------------------------------------------------- avatar
_AVATAR_COLORS = ["#2F7BFF", "#22D3EE", "#8B5CF6", "#F59E0B", "#10B981", "#EF4444", "#EC4899", "#14B8A6"]


class Avatar(QLabel):
    def __init__(self, size: int = 40) -> None:
        super().__init__()
        self._size = size
        self.setFixedSize(size, size)
        self._online: bool | None = None
        self._pm: QPixmap | None = None

    def set(self, name: str, image: bytes | None = None, online: bool | None = None, seed: str = "") -> "Avatar":
        self._online = online
        s, dpr = self._size, 2.0
        pm = QPixmap(int(s * dpr), int(s * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addEllipse(QRectF(0, 0, s, s))
        p.setClipPath(path)
        src = QPixmap()
        if image and src.loadFromData(image):
            p.drawPixmap(QRectF(0, 0, s, s), src, QRectF(src.rect()))
        else:
            color = QColor(_AVATAR_COLORS[sum(map(ord, seed or name or "x")) % len(_AVATAR_COLORS)])
            p.fillRect(QRectF(0, 0, s, s), color)
            initials = "".join(w[0] for w in (name or "?").split()[:2]).upper() or "?"
            f = QFont()
            f.setPixelSize(int(s * 0.38))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("white"))
            p.drawText(QRectF(0, 0, s, s), Qt.AlignmentFlag.AlignCenter, initials)
        p.setClipping(False)
        if online is not None:
            r = max(8, s * 0.26)
            ring = QColor(theme.palette().surface)
            p.setBrush(ring)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(s - r - 0.5, s - r - 0.5, r + 1, r + 1))
            p.setBrush(QColor(theme.palette().success if online else theme.palette().faint))
            p.drawEllipse(QRectF(s - r + 1.5, s - r + 1.5, r - 3, r - 3))
        p.end()
        self.setPixmap(pm)
        return self


# --------------------------------------------------------------------------- stats & charts
class StatCard(Card):
    def __init__(self, icon_name: str, caption: str, tone: str = "primary") -> None:
        super().__init__(padding=16, spacing=6)
        p = theme.palette()
        color = {"primary": p.primary_hover, "cyan": p.cyan, "success": p.success, "warning": p.warning}.get(tone, p.text)
        top = QHBoxLayout()
        chip = QLabel()
        chip.setFixedSize(34, 34)
        chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        chip.setStyleSheet(f"background:{p.surface3}; border-radius:10px;")
        chip.setPixmap(icons.pixmap(icon_name, 18, color))
        top.addWidget(chip)
        top.addStretch(1)
        self.body.addLayout(top)
        self.value = label("-", "stat")
        self.caption = label(caption, "muted")
        self.detail = label("", "faint")
        self.add(self.value)
        self.add(self.caption)
        self.add(self.detail)

    def set(self, value: str, detail: str = "") -> None:
        self.value.setText(value)
        self.detail.setText(detail)


class BarChart(QWidget):
    """Grouped bar chart drawn with QPainter (two series)."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(190)
        self.labels: list[str] = []
        self.a: list[float] = []
        self.b: list[float] = []
        self.names = ("Received", "Sent")

    def set_data(self, labels, a, b) -> None:
        self.labels, self.a, self.b = list(labels), list(a), list(b)
        self.update()

    def paintEvent(self, _e) -> None:
        p = theme.palette()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        left, bottom, top = 54, 26, 24
        plot_h = h - bottom - top
        mx = max([1.0, *self.a, *self.b])
        f = QFont()
        f.setPixelSize(theme.px(11))
        qp.setFont(f)
        for i in range(4):
            y = top + plot_h * i / 3
            qp.setPen(QPen(QColor(p.border), 1, Qt.PenStyle.DashLine))
            qp.drawLine(left, int(y), w - 8, int(y))
            qp.setPen(QColor(p.faint))
            qp.drawText(QRectF(0, y - 8, left - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                        human_size(mx * (3 - i) / 3).replace(".0 ", " "))
        n = max(1, len(self.labels))
        slot = (w - left - 8) / n
        bw = max(4.0, min(18.0, slot * 0.28))
        for i, lab in enumerate(self.labels):
            cx = left + slot * i + slot / 2
            for j, (vals, color) in enumerate(((self.a, p.cyan), (self.b, p.primary))):
                v = vals[i] if i < len(vals) else 0
                bh = plot_h * v / mx
                x = cx - bw - 2 if j == 0 else cx + 2
                path = QPainterPath()
                path.addRoundedRect(QRectF(x, top + plot_h - bh, bw, max(bh, 2)), 3, 3)
                qp.fillPath(path, QColor(color))
            qp.setPen(QColor(p.faint))
            qp.drawText(QRectF(cx - slot / 2, h - bottom + 6, slot, 16), Qt.AlignmentFlag.AlignCenter, lab)
        # legend
        lx = w - 170
        for j, (name, color) in enumerate(zip(self.names, (p.cyan, p.primary))):
            qp.setBrush(QColor(color))
            qp.setPen(Qt.PenStyle.NoPen)
            qp.drawRoundedRect(QRectF(lx + j * 85, 4, 10, 10), 2, 2)
            qp.setPen(QColor(p.muted))
            qp.drawText(QRectF(lx + j * 85 + 14, 0, 70, 18), Qt.AlignmentFlag.AlignVCenter, name)
        qp.end()


class RingGauge(QWidget):
    def __init__(self, size: int = 120) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.fraction = 0.0
        self.text = ""
        self.sub = ""

    def set(self, fraction: float, text: str, sub: str = "") -> None:
        self.fraction, self.text, self.sub = max(0.0, min(1.0, fraction)), text, sub
        self.update()

    def paintEvent(self, _e) -> None:
        p = theme.palette()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(8, 8, self.width() - 16, self.height() - 16)
        qp.setPen(QPen(QColor(p.surface3), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        qp.drawArc(r, 0, 360 * 16)
        color = p.danger if self.fraction > 0.9 else (p.warning if self.fraction > 0.75 else p.primary)
        qp.setPen(QPen(QColor(color), 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        qp.drawArc(r, 90 * 16, int(-self.fraction * 360 * 16))
        f = QFont()
        f.setPixelSize(theme.px(18))
        f.setBold(True)
        qp.setFont(f)
        qp.setPen(QColor(p.text))
        qp.drawText(QRectF(0, -8, self.width(), self.height()), Qt.AlignmentFlag.AlignCenter, self.text)
        f.setPixelSize(theme.px(11))
        f.setBold(False)
        qp.setFont(f)
        qp.setPen(QColor(p.muted))
        qp.drawText(QRectF(0, 18, self.width(), self.height()), Qt.AlignmentFlag.AlignCenter, self.sub)
        qp.end()


class SignalBars(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedSize(22, 16)
        self.bars = 0

    def set(self, bars: int) -> None:
        self.bars = bars
        self.setToolTip("Signal strength unavailable" if bars == 0 else f"Signal {bars}/4")
        self.update()

    def paintEvent(self, _e) -> None:
        p = theme.palette()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i in range(4):
            hgt = 4 + i * 4
            color = p.cyan if i < self.bars else p.surface3
            qp.setBrush(QColor(color))
            qp.setPen(Qt.PenStyle.NoPen)
            qp.drawRoundedRect(QRectF(i * 5.5, 16 - hgt, 4, hgt), 1.5, 1.5)
        qp.end()


class Radar(QWidget):
    """Animated scanning indicator for the discovery page."""

    def __init__(self, size: int = 84) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.phase = 0.0
        self.active = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def set_active(self, on: bool) -> None:
        self.active = on
        self._timer.start(33) if on and not theme.REDUCE_MOTION else self._timer.stop()
        self.update()

    def _tick(self) -> None:
        self.phase = (self.phase + 0.012) % 1.0
        self.update()

    def paintEvent(self, _e) -> None:
        p = theme.palette()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = self.width() / 2
        base = QColor(p.primary)
        for k in range(3):
            ph = (self.phase + k / 3) % 1.0 if self.active else 0.33 * (k + 1)
            rad = 10 + ph * (c - 12)
            col = QColor(base)
            col.setAlphaF(max(0.0, 0.55 * (1 - ph)) if self.active else 0.18)
            qp.setPen(QPen(col, 2))
            qp.setBrush(Qt.BrushStyle.NoBrush)
            qp.drawEllipse(QRectF(c - rad, c - rad, rad * 2, rad * 2))
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(QColor(p.primary if self.active else p.surface3))
        qp.drawEllipse(QRectF(c - 15, c - 15, 30, 30))
        qp.drawPixmap(int(c - 9), int(c - 9), icons.pixmap("bluetooth-searching" if self.active else "bluetooth", 18,
                                                           "#FFFFFF" if self.active else p.muted))
        qp.end()


# --------------------------------------------------------------------------- inputs
class Toggle(QWidget):
    toggled = Signal(bool)

    def __init__(self, checked: bool = False) -> None:
        super().__init__()
        self.setFixedSize(42, 24)
        self._checked = checked
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, v: bool, emit: bool = False) -> None:
        if v != self._checked:
            self._checked = v
            self.update()
            if emit:
                self.toggled.emit(v)

    def mouseReleaseEvent(self, _e) -> None:
        self.setChecked(not self._checked, emit=True)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.setChecked(not self._checked, emit=True)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e) -> None:
        p = theme.palette()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        qp.setPen(QPen(QColor(p.primary), 2) if self.hasFocus() else Qt.PenStyle.NoPen)
        qp.setBrush(QColor(p.primary if self._checked else p.surface3))
        qp.drawRoundedRect(QRectF(1, 1, 40, 22), 11, 11)
        qp.setPen(Qt.PenStyle.NoPen)
        qp.setBrush(QColor("white"))
        x = 21 if self._checked else 4
        qp.drawEllipse(QRectF(x, 4, 16, 16))
        qp.end()


class SettingRow(QWidget):
    """Title + description on the left, a control on the right."""

    def __init__(self, title: str, description: str, control: QWidget, icon_name: str | None = None) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 6)
        lay.setSpacing(12)
        if icon_name:
            lay.addWidget(icon_label(icon_name, 18, theme.palette().muted), 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        texts.addWidget(label(title, "h3"))
        if description:
            texts.addWidget(label(description, "muted", wrap=True))
        lay.addLayout(texts, 1)
        lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)


class SearchBox(QLineEdit):
    def __init__(self, placeholder: str = "Search") -> None:
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.addAction(icons.plain("search", 16, theme.palette().faint), QLineEdit.ActionPosition.LeadingPosition)
        self.setClearButtonEnabled(True)


class PasswordField(QLineEdit):
    def __init__(self, placeholder: str = "Password") -> None:
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setEchoMode(QLineEdit.EchoMode.Password)
        self._act = self.addAction(icons.plain("eye", 16, theme.palette().faint), QLineEdit.ActionPosition.TrailingPosition)
        self._act.setToolTip("Show password")
        self._act.triggered.connect(self._flip)

    def _flip(self) -> None:
        hidden = self.echoMode() == QLineEdit.EchoMode.Password
        self.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
        self._act.setIcon(icons.plain("eye-off" if hidden else "eye", 16, theme.palette().faint))


class StrengthMeter(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(18)
        self.score = 0

    def set_score(self, s: int) -> None:
        self.score = s
        self.update()

    def paintEvent(self, _e) -> None:
        p = theme.palette()
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        colors = [p.danger, p.danger, p.warning, p.cyan, p.success]
        seg = (self.width() - 120) / 4
        for i in range(4):
            qp.setBrush(QColor(colors[self.score] if i < self.score else p.surface3))
            qp.setPen(Qt.PenStyle.NoPen)
            qp.drawRoundedRect(QRectF(i * seg, 6, seg - 5, 5), 2, 2)
        qp.setPen(QColor(p.muted))
        f = QFont()
        f.setPixelSize(theme.px(11))
        qp.setFont(f)
        txt = ["Too weak", "Weak", "Fair", "Good", "Strong"][self.score]
        qp.drawText(QRectF(self.width() - 110, 0, 110, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    txt)
        qp.end()


# --------------------------------------------------------------------------- toast
class Toast(QFrame):
    """Short in-app confirmation that fades out (bottom-right of the window)."""

    def __init__(self, parent: QWidget, text: str, tone: str = "info") -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        p = theme.palette()
        icon_name, color = {"success": ("circle-check", p.success), "error": ("circle-alert", p.danger),
                            "warning": ("triangle-alert", p.warning)}.get(tone, ("info", p.cyan))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 10, 16, 10)
        lay.setSpacing(10)
        lay.addWidget(icon_label(icon_name, 18, color))
        t = label(text, wrap=True)
        t.setMaximumWidth(360)
        lay.addWidget(t)
        self.adjustSize()
        shadow(self, 30, 120, 6)
        par = parent.rect()
        self.move(par.width() - self.width() - 24, par.height() - self.height() - 24)
        self.show()
        self.raise_()
        self._fx = QGraphicsOpacityEffect(self)
        QTimer.singleShot(3200, self._fade)

    def _fade(self) -> None:
        self.setGraphicsEffect(self._fx)
        anim = QPropertyAnimation(self._fx, b"opacity", self)
        anim.setDuration(350)
        anim.setStartValue(1.0)
        anim.setEndValue(0.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self.deleteLater)
        anim.start()


def fade_in(widget: QWidget, ms: int = 180) -> None:
    if theme.REDUCE_MOTION:
        return
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    anim = QPropertyAnimation(eff, b"opacity", widget)
    anim.setDuration(ms)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.Type.OutCubic)
    anim.finished.connect(lambda: widget.setGraphicsEffect(None))
    anim.start()
