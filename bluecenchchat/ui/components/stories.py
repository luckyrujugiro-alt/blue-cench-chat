"""Stories: a column of people with 24-hour stories, a full-screen viewer, and the "add story" dialog."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from .badges import ring_pixmap
from .widgets import Avatar, Card, button, clear_layout, human_time, label

STORY_SECONDS = 6
GRADIENTS = [("#1E6BFF", "#00C2FF"), ("#7C4DFF", "#00C2FF"), ("#0F2147", "#1E8BFF"), ("#00BA7C", "#1D9BF0"),
             ("#F59E0B", "#F4212E")]


class RingAvatar(QWidget):
    """Avatar with a gradient story ring (blue = new, grey = seen, gold = founder)."""

    def __init__(self, name: str, image: bytes | None, seed: str, size: int = 48, ring: str = "story") -> None:
        super().__init__()
        self.setFixedSize(size + 8, size + 8)
        self.ring = QLabel(self)
        self.ring.setPixmap(ring_pixmap(size + 8, ring) if ring else QPixmap())
        self.ring.setGeometry(0, 0, size + 8, size + 8)
        av = Avatar(size).set(name, image, seed=seed)
        av.setParent(self)
        av.move(4, 4)


class StoriesCard(Card):
    """Vertical stories list for the right-hand column of Home."""

    def __init__(self, win) -> None:
        super().__init__("Stories", "circle-plus", padding=14, spacing=6)
        self.win, self.node = win, win.node
        self.rows = QVBoxLayout()
        self.rows.setSpacing(4)
        self.add(self.rows)
        self.refresh()

    def _row(self, name: str, image, seed: str, sub: str, ring: str, on_click) -> QWidget:
        w = QWidget()
        w.setCursor(Qt.CursorShape.PointingHandCursor)
        r = QHBoxLayout(w)
        r.setContentsMargins(2, 2, 2, 2)
        r.setSpacing(10)
        r.addWidget(RingAvatar(name, image, seed, 40, ring))
        col = QVBoxLayout()
        col.setSpacing(0)
        nm = label(name, "h3")
        nm.setTextFormat(Qt.TextFormat.PlainText)
        col.addWidget(nm)
        col.addWidget(label(sub, "faint"))
        r.addLayout(col, 1)
        w.mousePressEvent = lambda _e: on_click()
        return w

    def refresh(self) -> None:
        clear_layout(self.rows)
        node = self.node
        acc = node.repo.account()
        groups = node.social.stories()
        mine = next((g for uid, g in groups if uid == node.identity.user_id), None)
        if mine:
            self.rows.addWidget(self._row("Your story", acc.avatar, acc.user_id,
                                          f"{len(mine)} · {human_time(mine[-1].created_at)}",
                                          "founder" if node.social.badge() == "founder" else "story",
                                          lambda: StoryViewer(self.win, groups, 0).exec()))
        else:
            self.rows.addWidget(self._row("Add to your story", acc.avatar, acc.user_id, "Share a moment for 24 h",
                                          "", lambda: new_story_dialog(self.win)))
        for i, (uid, posts) in enumerate(groups):
            if uid == node.identity.user_id:
                continue
            c = node.repo.contact_by_peer(uid)
            if not c:
                continue
            seen = all(p.seen for p in posts)
            ring = "seen" if seen else ("founder" if node.social.badge(c) == "founder" else "story")
            self.rows.addWidget(self._row(c.name, c.avatar, uid, human_time(posts[-1].created_at), ring,
                                          lambda i=i: StoryViewer(self.win, groups, i).exec()))
        if len(groups) <= (1 if mine else 0):
            self.rows.addWidget(label("Stories from people you follow appear here.", "faint", wrap=True))


class StoryViewer(QDialog):
    """Full-screen-ish viewer: segmented progress bars, tap right/left (or arrows) to move, auto-advances."""

    def __init__(self, win, groups, start: int = 0) -> None:
        super().__init__(win)
        self.win, self.node = win, win.node
        self.groups = [g for g in groups if g[1]]
        self.gi = min(start, len(self.groups) - 1)
        self.pi = next((i for i, p in enumerate(self.groups[self.gi][1]) if not p.seen), 0) if self.groups else 0
        self.setWindowTitle("Stories")
        self.setMinimumSize(420, 720)
        self.setStyleSheet("QDialog { background: #000; } QLabel { color: #FFFFFF; }")
        self.t0 = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(50)
        self._show()

    # -------------------------------------------------------------- navigation
    def _cur(self):
        return self.groups[self.gi][1][self.pi]

    def _show(self) -> None:
        if not self.groups:
            self.reject()
            return
        self.t0 = time.monotonic()
        p = self._cur()
        self.win.bridge.run(self.node.social.mark_story_seen(p.id))
        self.update()

    def _next(self) -> None:
        if self.pi + 1 < len(self.groups[self.gi][1]):
            self.pi += 1
        elif self.gi + 1 < len(self.groups):
            self.gi, self.pi = self.gi + 1, 0
        else:
            self.accept()
            return
        self._show()

    def _prev(self) -> None:
        if self.pi > 0:
            self.pi -= 1
        elif self.gi > 0:
            self.gi -= 1
            self.pi = len(self.groups[self.gi][1]) - 1
        self._show()

    def _tick(self) -> None:
        if time.monotonic() - self.t0 >= STORY_SECONDS:
            self._next()
        else:
            self.update()

    def mousePressEvent(self, e) -> None:
        (self._next if e.position().x() > self.width() * 0.35 else self._prev)()

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key.Key_Right, Qt.Key.Key_Space):
            self._next()
        elif e.key() == Qt.Key.Key_Left:
            self._prev()
        else:
            super().keyPressEvent(e)

    # -------------------------------------------------------------- drawing
    def paintEvent(self, _e) -> None:
        if not self.groups:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        post = self._cur()
        W, H = self.width(), self.height()
        frame = QRectF(10, 10, W - 20, H - 20)
        clip = QPainterPath()
        clip.addRoundedRect(frame, 18, 18)
        p.setClipPath(clip)
        if post.image:
            pm = QPixmap()
            pm.loadFromData(post.image)
            pm = pm.scaled(int(frame.width()), int(frame.height()), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
            p.drawPixmap(int(frame.x() + (frame.width() - pm.width()) / 2),
                         int(frame.y() + (frame.height() - pm.height()) / 2), pm)
        else:
            a, b = GRADIENTS[hash(post.id) % len(GRADIENTS)]
            g = QLinearGradient(frame.topLeft(), frame.bottomRight())
            g.setColorAt(0, QColor(a))
            g.setColorAt(1, QColor(b))
            p.fillRect(frame, g)
            f = QFont(self.font())
            f.setPointSize(22)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(frame.adjusted(30, 30, -30, -30), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       post.caption)
        # top shade + progress segments
        shade = QLinearGradient(0, frame.y(), 0, frame.y() + 120)
        shade.setColorAt(0, QColor(0, 0, 0, 150))
        shade.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(frame.x(), frame.y(), frame.width(), 120), shade)
        posts = self.groups[self.gi][1]
        n = len(posts)
        gap, x0 = 4, frame.x() + 12
        seg = (frame.width() - 24 - gap * (n - 1)) / n
        frac = min(1.0, (time.monotonic() - self.t0) / STORY_SECONDS)
        for i in range(n):
            r = QRectF(x0 + i * (seg + gap), frame.y() + 12, seg, 3)
            p.fillRect(r, QColor(255, 255, 255, 90))
            done = 1.0 if i < self.pi else (frac if i == self.pi else 0.0)
            p.fillRect(QRectF(r.x(), r.y(), r.width() * done, r.height()), QColor("#FFFFFF"))
        # author line
        uid = self.groups[self.gi][0]
        name = "Your story" if uid == self.node.identity.user_id else self.node.social.author_name(uid)
        f = QFont(self.font())
        f.setPointSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(QRectF(x0, frame.y() + 24, frame.width() - 24, 24), Qt.AlignmentFlag.AlignLeft,
                   f"{name}   ·   {human_time(post.created_at)}")
        # caption / viewers at the bottom
        bottom = []
        if post.image and post.caption:
            bottom.append(post.caption)
        if post.music:
            bottom.append(f"♫ {post.music}")
        if uid == self.node.identity.user_id:
            viewers = len([x for x in (post.viewer_ids or "").split(",") if x])
            bottom.append(f"Seen by {viewers}")
        if bottom:
            shade2 = QLinearGradient(0, frame.bottom() - 140, 0, frame.bottom())
            shade2.setColorAt(0, QColor(0, 0, 0, 0))
            shade2.setColorAt(1, QColor(0, 0, 0, 170))
            p.fillRect(QRectF(frame.x(), frame.bottom() - 140, frame.width(), 140), shade2)
            f.setBold(False)
            p.setFont(f)
            p.drawText(frame.adjusted(18, 0, -18, -18), Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft |
                       Qt.TextFlag.TextWordWrap, "\n".join(bottom))


def new_story_dialog(win) -> None:
    """Photo (from a file or the camera) or a text story on a gradient."""
    d = QDialog(win)
    d.setWindowTitle("Add to your story")
    d.setMinimumWidth(460)
    lay = QVBoxLayout(d)
    lay.setContentsMargins(24, 20, 24, 18)
    lay.setSpacing(10)
    lay.addWidget(label("Add to your story", "h2"))
    lay.addWidget(label("Stories disappear after 24 hours. Your followers see them when they're nearby or online.",
                        "muted", wrap=True))
    state = {"image": None}
    preview = QLabel("Write something, or add a photo")
    preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    preview.setMinimumHeight(220)
    preview.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #1E6BFF, stop:1 #00C2FF);"
                          "color:#FFFFFF; border-radius:14px; font-weight:700;")
    lay.addWidget(preview)
    text = QPlainTextEdit()
    text.setPlaceholderText("Type your story...")
    text.setMaximumHeight(90)
    lay.addWidget(text)

    def set_image(data: bytes) -> None:
        state["image"] = data
        pm = QPixmap()
        pm.loadFromData(data)
        preview.setPixmap(pm.scaled(400, 240, Qt.AspectRatioMode.KeepAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation))

    def pick() -> None:
        path, _ = QFileDialog.getOpenFileName(d, "Choose a photo", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            set_image(Path(path).read_bytes())

    def camera() -> None:
        from .camera import capture_photo
        data = capture_photo(d)
        if data:
            set_image(data)

    row = QHBoxLayout()
    b1 = button("Photo", "image-plus")
    b1.clicked.connect(pick)
    b2 = button("Camera", "camera")
    b2.clicked.connect(camera)
    row.addWidget(b1)
    row.addWidget(b2)
    row.addStretch(1)
    share = button("Share to story", "send", "primary")
    row.addWidget(share)
    lay.addLayout(row)

    def go() -> None:
        if not state["image"] and not text.toPlainText().strip():
            win.toast("Add a photo or write something", "warning")
            return
        win.bridge.run(win.node.social.create_post(text.toPlainText(), state["image"], "", story=True),
                       lambda _p: win.toast("Added to your story", "success"))
        d.accept()

    share.clicked.connect(go)
    d.exec()
