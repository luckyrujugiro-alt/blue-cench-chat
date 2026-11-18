"""Instagram-style building blocks: verified names, notes bar, post cards, profiles."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import icons, theme
from .widgets import Avatar, button, clear_layout, human_time, icon_label, label, tool_button


def tick_icon(size: int = 16, kind: str = "verified") -> QLabel:
    from .badges import seal_label
    return seal_label(size, kind)


def name_line(name: str, verified: bool | str, role: str = "h3", extra: str = "") -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(4)
    lb = label(name, role)
    lb.setTextFormat(Qt.TextFormat.PlainText)
    lay.addWidget(lb)
    kind = verified if isinstance(verified, str) else ("verified" if verified else "")
    if kind:
        lay.addWidget(tick_icon(16 if role not in ("h1", "h2") else 20, kind))
    if kind == "founder":
        pill = QLabel("FOUNDER")
        pill.setStyleSheet("background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #FFD54A, stop:1 #F59E0B);"
                           f"color:#3A2500; font-weight:800; font-size:{theme.px(9)}px; letter-spacing:1px;"
                           "border-radius:7px; padding:1px 6px;")
        pill.setToolTip("Official Blue Cench Chat account")
        lay.addWidget(pill)
    if extra:
        lay.addWidget(label(extra, "faint"))
    lay.addStretch(1)
    return w


def ring_avatar(name: str, image: bytes | None, size: int, seed: str = "", ring: bool | str = True) -> QLabel:
    """Avatar inside a painted ring: brand blue-violet (has a note/story), gold (founder), none."""
    from .badges import ring_pixmap
    outer = QLabel()
    outer.setFixedSize(size + 8, size + 8)
    kind = ring if isinstance(ring, str) else ("story" if ring else "")
    if kind:
        outer.setPixmap(ring_pixmap(size + 8, kind, width=3.5 if kind == "founder" else 3.0))
    lay = QHBoxLayout(outer)
    lay.setContentsMargins(4, 4, 4, 4)
    av = Avatar(size).set(name, image, seed=seed)
    lay.addWidget(av)
    return outer


# --------------------------------------------------------------------------- notes
class NotesBar(QScrollArea):
    """Row of avatars with their note bubbles (like Instagram DMs)."""

    def __init__(self, win) -> None:
        super().__init__()
        self.win, self.node = win, win.node
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedHeight(140)
        host = QWidget()
        self.row = QHBoxLayout(host)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(14)
        self.setWidget(host)
        self.refresh()

    def _cell(self, name: str, image: bytes | None, seed: str, note: str, music: str, on_click,
              caption: str | None = None, clip: bytes | None = None) -> QWidget:
        cell = QWidget()
        cell.setFixedWidth(96)
        cell.setCursor(Qt.CursorShape.PointingHandCursor)
        v = QVBoxLayout(cell)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        text = note or ("♫ " + music if music else "") or "Note…"
        if note and music:
            text = f"{note}\n♫ {music}"
        bubble = QLabel(text)
        bubble.setTextFormat(Qt.TextFormat.PlainText)
        bubble.setWordWrap(True)
        bubble.setToolTip(text)
        bubble.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bubble.setFixedHeight(46)
        p = theme.palette()
        bubble.setStyleSheet(f"background:{p.surface3}; color:{p.text if note or music else p.faint}; "
                             f"border-radius:12px; padding:4px 6px; font-size:{theme.px(11)}px;")
        v.addWidget(bubble)
        av = ring_avatar(name, image, 52, seed, ring=bool(note or music))
        v.addWidget(av, 0, Qt.AlignmentFlag.AlignHCenter)
        nm = label(caption if caption is not None else (name.split()[0] if name else ""), "faint")
        nm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(nm)
        cell.mousePressEvent = lambda _e: on_click()
        if clip is not None:
            from . import media
            bubble.setCursor(Qt.CursorShape.PointingHandCursor)
            bubble.setToolTip("Play the song on this note")
            bubble.mousePressEvent = lambda _e: media.play_clip(clip)
        return cell

    def refresh(self) -> None:
        clear_layout(self.row)
        acc = self.node.repo.account()
        n = self.node.social.note()
        self.row.addWidget(self._cell(acc.display_name, acc.avatar, acc.user_id, n["text"], n["music"],
                                      lambda: edit_note_dialog(self.win), caption="Your note"))
        people = [c for c in self.node.repo.contacts() if (c.note_text or c.note_music) and c.status != "blocked"]
        people.sort(key=lambda c: -c.note_ts)
        for c in people[:30]:
            self.row.addWidget(self._cell(c.name, c.avatar, c.peer_user_id, c.note_text, c.note_music,
                                          lambda c=c: ProfileDialog(self.win, c.id).exec(), clip=c.note_clip))
        self.row.addStretch(1)


def edit_note_dialog(win) -> None:
    node = win.node
    d = QDialog(win)
    d.setWindowTitle("Your note")
    d.setMinimumWidth(420)
    lay = QVBoxLayout(d)
    lay.setContentsMargins(24, 22, 24, 20)
    lay.addWidget(label("Share a note", "h2"))
    lay.addWidget(label("Notes appear above your photo for people nearby and your followers.", "muted", wrap=True))
    cur = node.social.note()
    t = QLineEdit(cur["text"])
    t.setMaxLength(60)
    t.setPlaceholderText("What's on your mind? (60 characters)")
    m = QLineEdit(cur["music"])
    m.setMaxLength(80)
    m.setPlaceholderText("Add music: song - artist (optional)")
    m.addAction(icons.plain("music", 16, theme.palette().faint), QLineEdit.ActionPosition.LeadingPosition)
    lay.addWidget(t)
    lay.addWidget(m)
    # a real song from this device, played to people who open your note
    from . import media
    song = {"data": False}
    have = node.social.note_clip()
    srow = QHBoxLayout()
    slabel = label("Song attached" if have else "No song attached", "muted")
    pick = button("Choose a song from this PC", "music")
    play = button("Play", "play", "ghost")
    play.setEnabled(bool(have))
    drop = button("Remove song", "x", "ghost")
    drop.setVisible(bool(have))
    srow.addWidget(pick)
    srow.addWidget(play)
    srow.addWidget(drop)
    srow.addStretch(1)
    lay.addLayout(srow)
    lay.addWidget(slabel)

    def choose() -> None:
        path, _ = QFileDialog.getOpenFileName(d, "Choose a song", "", "Audio (*.mp3 *.m4a *.aac *.ogg *.wav *.flac)")
        if not path:
            return
        data = Path(path).read_bytes()
        from ...core.social import looks_like_audio, trim_clip
        if not looks_like_audio(data):
            win.toast("That file doesn't look like a song", "warning")
            return
        try:
            data = trim_clip(data)
        except ValueError as exc:
            win.toast(str(exc), "warning")
            return
        song["data"] = data
        if not m.text().strip():
            m.setText(Path(path).stem[:80])
        slabel.setText(f"{Path(path).name} - {'first ~30 seconds' if len(data) >= 490_000 else 'ready'}")
        play.setEnabled(True)
        drop.setVisible(True)

    def remove() -> None:
        song["data"] = None
        slabel.setText("No song attached")
        play.setEnabled(False)
        drop.setVisible(False)
        media.stop()

    pick.clicked.connect(choose)
    play.clicked.connect(lambda: media.play_clip(song["data"] if song["data"] else node.social.note_clip()))
    drop.clicked.connect(remove)
    row = QHBoxLayout()
    clear = button("Delete note", "trash-2", "ghost")
    share = button("Share", "send", "primary")
    row.addWidget(clear)
    row.addStretch(1)
    row.addWidget(share)
    lay.addLayout(row)

    def do_share() -> None:
        try:
            win.bridge.run(node.social.set_note(t.text(), m.text(), song["data"]))
        finally:
            media.stop()
            d.accept()

    share.clicked.connect(do_share)
    clear.clicked.connect(lambda: (media.stop(), win.bridge.run(node.social.set_note("", "", None)), d.accept()))
    d.exec()


# --------------------------------------------------------------------------- posts
class PostCard(QFrame):
    def __init__(self, win, post, compact: bool = False) -> None:
        super().__init__()
        self.win, self.node, self.post_id = win, win.node, post.id
        self.setObjectName("PostCard")
        self.setMaximumWidth(560)
        p = theme.palette()
        node = self.node
        mine = post.author_uid == node.identity.user_id
        contact = None if mine else node.repo.contact_by_peer(post.author_uid)
        acc = node.repo.account()
        name = acc.display_name if mine else (contact.name if contact else post.author_uid)
        verified = node.social.badge() if mine else (node.social.badge(contact) if contact else "")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 10)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(12, 10, 8, 0)
        head.addWidget(Avatar(34).set(name, acc.avatar if mine else (contact.avatar if contact else None),
                                      seed=post.author_uid))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(name_line(name, verified, extra=f"• {human_time(post.created_at)}"))
        if post.music:
            ml = QHBoxLayout()
            ml.setSpacing(4)
            ml.addWidget(icon_label("music", 12, p.muted))
            mt = label(post.music, "faint")
            mt.setTextFormat(Qt.TextFormat.PlainText)
            ml.addWidget(mt)
            ml.addStretch(1)
            col.addLayout(ml)
        head.addLayout(col, 1)
        more = tool_button("ellipsis", "More")
        menu = QMenu(more)
        if mine:
            menu.addAction(icons.plain("trash-2", 16, p.danger), "Delete post",
                           lambda: win.bridge.run(node.social.delete_post(post.id)))
        elif contact:
            menu.addAction(icons.plain("user", 16), "View profile", lambda: ProfileDialog(win, contact.id).exec())
            menu.addAction(icons.plain("user-x", 16), "Unfollow",
                           lambda: win.bridge.run(node.social.follow(contact.id, False)))
        more.clicked.connect(lambda: menu.exec(more.mapToGlobal(QPoint(0, more.height()))))
        head.addWidget(more)
        lay.addLayout(head)

        if post.image:
            img = QLabel()
            pm = QPixmap()
            pm.loadFromData(post.image)
            w = 540 if not compact else 360
            img.setPixmap(pm.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation))
            img.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img.mouseDoubleClickEvent = lambda _e: (not post.liked) and win.bridge.run(node.social.toggle_like(post.id))
            img.setToolTip("Double-click to like")
            lay.addWidget(img)

        acts = QHBoxLayout()
        acts.setContentsMargins(8, 0, 8, 0)
        like = tool_button("heart", "Unlike" if post.liked else "Like (double-click the photo)", 22,
                           p.danger if post.liked else p.text)
        like.clicked.connect(lambda: win.bridge.run(node.social.toggle_like(post.id)))
        com = tool_button("message-circle", "Comment", 22, p.text)
        com.clicked.connect(lambda: CommentsDialog(win, post.id).exec())
        acts.addWidget(like)
        acts.addWidget(com)
        acts.addStretch(1)
        save = tool_button("bookmark", "Remove from saved" if post.saved else "Save", 22,
                           p.primary if post.saved else p.text)
        save.clicked.connect(lambda: win.bridge.run(node.social.toggle_save(post.id)))
        acts.addWidget(save)
        lay.addLayout(acts)
        body = QVBoxLayout()
        body.setContentsMargins(14, 0, 14, 0)
        body.setSpacing(3)
        if post.likes:
            body.addWidget(label(f"{post.likes:,} like{'s' if post.likes != 1 else ''}", "h3"))
        if post.caption:
            cap = label(f"{name}  {post.caption}", wrap=True, selectable=True)
            cap.setTextFormat(Qt.TextFormat.PlainText)
            body.addWidget(cap)
        if post.comments:
            v = button(f"View all {post.comments} comment{'s' if post.comments != 1 else ''}", variant="link")
            v.setStyleSheet(f"color:{p.muted}; font-weight:500; text-align:left;")
            v.clicked.connect(lambda: CommentsDialog(win, post.id).exec())
            body.addWidget(v, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(body)


class CommentsDialog(QDialog):
    def __init__(self, win, post_id: str) -> None:
        super().__init__(win)
        self.win, self.node, self.post_id = win, win.node, post_id
        self.setWindowTitle("Comments")
        self.setMinimumSize(460, 520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.addWidget(label("Comments", "h2"))
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.list = QVBoxLayout(host)
        self.list.setSpacing(10)
        sa.setWidget(host)
        lay.addWidget(sa, 1)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Add a comment…")
        self.edit.setMaxLength(500)
        post = button("Post", variant="link")
        row.addWidget(self.edit, 1)
        row.addWidget(post)
        lay.addLayout(row)
        post.clicked.connect(self._post)
        self.edit.returnPressed.connect(self._post)
        win.bridge.social_changed.connect(self.refresh)
        win.bridge.run(self.node.social.refresh_comments(post_id))
        self.refresh()

    def _post(self) -> None:
        if self.edit.text().strip():
            self.win.bridge.run(self.node.social.add_comment(self.post_id, self.edit.text()))
            self.edit.clear()

    def refresh(self) -> None:
        if not self.isVisible() and self.list.count():
            return
        clear_layout(self.list)
        items = self.node.social.comments(self.post_id)
        if not items:
            self.list.addWidget(label("No comments yet. Start the conversation.", "muted"))
        for c in items:
            r = QHBoxLayout()
            r.addWidget(Avatar(30).set(c.author_name, None, seed=c.author_uid), 0, Qt.AlignmentFlag.AlignTop)
            t = label(f"{c.author_name}  {c.text}", wrap=True, selectable=True)
            t.setTextFormat(Qt.TextFormat.PlainText)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(t)
            col.addWidget(label(human_time(c.ts), "faint"))
            r.addLayout(col, 1)
            w = QWidget()
            w.setLayout(r)
            self.list.addWidget(w)
        self.list.addStretch(1)


class CreatePostDialog(QDialog):
    def __init__(self, win) -> None:
        super().__init__(win)
        self.win = win
        self.image: bytes | None = None
        self.setWindowTitle("Create new post")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)
        lay.addWidget(label("Create new post", "h2"))
        self.preview = QLabel("Choose a photo (optional)")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumHeight(240)
        p = theme.palette()
        self.preview.setStyleSheet(f"background:{p.surface2}; border:1px dashed {p.border_strong}; border-radius:12px;"
                                   f"color:{p.muted};")
        lay.addWidget(self.preview)
        pick = button("Select from computer", "image-plus", "primary")
        pick.clicked.connect(self._pick)
        cam = button("Take photo", "camera")
        cam.clicked.connect(self._camera)
        prow = QHBoxLayout()
        prow.addStretch(1)
        prow.addWidget(pick)
        prow.addWidget(cam)
        prow.addStretch(1)
        lay.addLayout(prow)
        self.caption = QPlainTextEdit()
        self.caption.setPlaceholderText("Write a caption…")
        self.caption.setMaximumHeight(110)
        lay.addWidget(self.caption)
        self.music = QLineEdit()
        self.music.setPlaceholderText("Add music: song - artist (optional)")
        self.music.addAction(icons.plain("music", 16, p.faint), QLineEdit.ActionPosition.LeadingPosition)
        lay.addWidget(self.music)
        lay.addWidget(label("Your post is shared with your followers when they're nearby or on the same network.",
                            "faint", wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel", variant="ghost")
        share = button("Share", "send", "primary")
        row.addWidget(cancel)
        row.addWidget(share)
        lay.addLayout(row)
        cancel.clicked.connect(self.reject)
        share.clicked.connect(self._share)

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose a photo", "", "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if not path:
            return
        try:
            self.image = Path(path).read_bytes()
        except OSError as exc:
            self.win.toast(str(exc), "error")
            return
        pm = QPixmap()
        pm.loadFromData(self.image)
        self.preview.setPixmap(pm.scaled(460, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))

    def _camera(self) -> None:
        from .camera import capture_photo
        data = capture_photo(self)
        if data:
            self.image = data
            pm = QPixmap()
            pm.loadFromData(data)
            self.preview.setPixmap(pm.scaled(460, 300, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))

    def _share(self) -> None:
        text = self.caption.toPlainText()
        if not text.strip() and not self.image:
            self.win.toast("Add a photo or write a caption", "warning")
            return
        self.win.bridge.run(self.win.node.social.create_post(text, self.image, self.music.text()),
                            lambda _p: self.win.toast("Shared", "success"))
        self.accept()


# --------------------------------------------------------------------------- profiles
def counts_row(posts: int, followers: int, following: int, win=None) -> QHBoxLayout:
    """posts · followers · following. With `win`, followers/following open the list of people."""
    row = QHBoxLayout()
    row.setSpacing(28)
    for n, what in ((posts, "posts"), (followers, "followers"), (following, "following")):
        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        col.addWidget(label(f"{n:,}", "h2"))
        col.addWidget(label(what, "muted"))
        if win is not None and what != "posts":
            w.setCursor(Qt.CursorShape.PointingHandCursor)
            w.setToolTip(f"See your {what}")
            w.mousePressEvent = lambda _e, what=what: people_dialog(win, what)
        row.addWidget(w)
    row.addStretch(1)
    return row


def people_dialog(win, which: str) -> None:
    """Your followers or the people you follow, with follow / message buttons."""
    node = win.node
    d = QDialog(win)
    d.setWindowTitle(which.title())
    d.setMinimumSize(420, 520)
    lay = QVBoxLayout(d)
    lay.setContentsMargins(20, 18, 20, 16)
    lay.addWidget(label(which.title(), "h2"))
    people = [c for c in node.repo.contacts() if c.status != "blocked" and
              (c.follows_me if which == "followers" else c.i_follow)]
    sa = QScrollArea()
    sa.setWidgetResizable(True)
    sa.setFrameShape(QFrame.Shape.NoFrame)
    host = QWidget()
    lst = QVBoxLayout(host)
    lst.setSpacing(8)
    if not people:
        lst.addWidget(label("Nobody yet." if which == "followers" else "You're not following anyone yet.", "muted"))
    for c in people:
        r = QHBoxLayout()
        r.addWidget(Avatar(40).set(c.name, c.avatar, node.connections.is_online(c.id), c.peer_user_id))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(name_line(c.name, node.social.badge(c)))
        col.addWidget(label(f"@{c.username}", "faint"))
        r.addLayout(col, 1)
        f = button("Following" if c.i_follow else "Follow back", variant="following" if c.i_follow else "follow")
        f.clicked.connect(lambda _=False, c=c: (win.bridge.run(node.social.follow(c.id, not c.i_follow)), d.accept()))
        r.addWidget(f)
        w = QWidget()
        w.setLayout(r)
        w.setCursor(Qt.CursorShape.PointingHandCursor)
        w.mouseDoubleClickEvent = lambda _e, c=c: ProfileDialog(win, c.id).exec()
        lst.addWidget(w)
    lst.addStretch(1)
    sa.setWidget(host)
    lay.addWidget(sa, 1)
    d.exec()


class PostsGrid(QWidget):
    def __init__(self, win, posts, cols: int = 3, cell: int = 180) -> None:
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        p = theme.palette()
        for i, post in enumerate(posts):
            tile = QLabel()
            tile.setFixedSize(cell, cell)
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            if post.image:
                pm = QPixmap()
                pm.loadFromData(post.image)
                pm = pm.scaled(cell, cell, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)
                tile.setPixmap(pm.copy((pm.width() - cell) // 2, (pm.height() - cell) // 2, cell, cell))
            else:
                tile.setText(post.caption[:90])
                tile.setWordWrap(True)
                tile.setStyleSheet(f"background:{p.surface3}; padding:10px; color:{p.text};")
            tile.setToolTip(f"{post.likes} likes · {post.comments} comments")
            tile.mousePressEvent = lambda _e, post=post: PostDialog(win, post.id).exec()
            grid.addWidget(tile, i // cols, i % cols)


class PostDialog(QDialog):
    def __init__(self, win, post_id: str) -> None:
        super().__init__(win)
        self.setWindowTitle("Post")
        lay = QVBoxLayout(self)
        post = win.node.social.post(post_id)
        if post:
            lay.addWidget(PostCard(win, post))


class ProfileDialog(QDialog):
    """Someone else's profile: counts, note, follow / message / call, their posts."""

    def __init__(self, win, contact_id: int) -> None:
        super().__init__(win)
        self.win, self.node, self.cid = win, win.node, contact_id
        c = self.node.repo.contact(contact_id)
        self.setWindowTitle(c.name if c else "Profile")
        self.setMinimumSize(640, 600)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        self.lay = QVBoxLayout(host)
        self.lay.setContentsMargins(28, 24, 28, 24)
        self.lay.setSpacing(14)
        sa.setWidget(host)
        outer.addWidget(sa)
        self.build()

    def build(self) -> None:
        node, win = self.node, self.win
        clear_layout(self.lay)
        c = node.repo.contact(self.cid)
        if not c:
            return
        head = QHBoxLayout()
        head.setSpacing(24)
        founder = node.social.badge(c) == "founder"
        head.addWidget(ring_avatar(c.name, c.avatar, 96, c.peer_user_id,
                                   ring="founder" if founder else bool(c.note_text or c.note_music)))
        col = QVBoxLayout()
        col.setSpacing(8)
        col.addWidget(name_line(c.name, node.social.badge(c), "h2"))
        col.addWidget(label(f"@{c.username}  ·  {c.peer_user_id}", "muted"))
        col.addLayout(counts_row(c.posts_count, c.followers_count, c.following_count))
        btns = QHBoxLayout()
        if c.status != "blocked":
            f = button("Following" if c.i_follow else ("Follow back" if c.follows_me else "Follow"),
                       variant="following" if c.i_follow else "follow")
            f.clicked.connect(lambda: win.bridge.run(node.social.follow(c.id, not c.i_follow),
                                                     lambda _r: self.build()))
            btns.addWidget(f)
        if node.social.is_admin() and c.status != "blocked":
            from .. import actions
            from PySide6.QtWidgets import QMenu
            sb = button("Suspend", "ban", "ghost")
            smenu = QMenu(sb)
            actions.fill_suspend_menu(win, smenu, c.peer_user_id, c.name)
            sb.clicked.connect(lambda: smenu.exec(sb.mapToGlobal(QPoint(0, sb.height()))))
            btns.addWidget(sb)
            ticked = node.social.is_verified(c)
            tb = button("Remove blue tick" if ticked else "Give blue tick", "badge-check",
                        "danger" if ticked else "primary")
            tb.clicked.connect(lambda: actions.toggle_tick(win, c.id, self.build))
            btns.addWidget(tb)
        if c.status == "accepted":
            m = button("Message", "message-square")
            m.clicked.connect(lambda: (self.accept(), win.open_chat(c.id)))
            btns.addWidget(m)
            v = tool_button("phone", "Voice call", 20)
            v.clicked.connect(lambda: win.start_call(c.id, False))
            vv = tool_button("video", "Video call (Wi-Fi/LAN)", 20)
            vv.clicked.connect(lambda: win.start_call(c.id, True))
            btns.addWidget(v)
            btns.addWidget(vv)
        btns.addStretch(1)
        col.addLayout(btns)
        head.addLayout(col, 1)
        self.lay.addLayout(head)
        if c.about:
            ab = label(c.about, wrap=True)
            ab.setTextFormat(Qt.TextFormat.PlainText)
            self.lay.addWidget(ab)
        if c.note_text or c.note_music:
            note = c.note_text + (f"   ♫ {c.note_music}" if c.note_music else "")
            n = label(f"Note: {note}", "muted", wrap=True)
            n.setTextFormat(Qt.TextFormat.PlainText)
            self.lay.addWidget(n)
        if c.follows_me:
            self.lay.addWidget(label("Follows you", "faint"))
        posts = node.social.posts_by(c.peer_user_id)
        if posts:
            self.lay.addWidget(PostsGrid(win, posts, cell=190), 0, Qt.AlignmentFlag.AlignLeft)
        elif c.i_follow:
            self.lay.addWidget(label("No posts yet - new posts arrive when you're connected.", "muted"))
        else:
            self.lay.addWidget(label("Follow to see their posts.", "muted"))
        self.lay.addStretch(1)
