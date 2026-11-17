"""Home: notes bar, create post, and the feed of people you follow (Instagram-style)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from ..components.social import CreatePostDialog, NotesBar, PostCard, ProfileDialog, name_line
from ..components.widgets import Avatar, Card, EmptyState, Page, button, clear_layout, label


class HomePage(Page):
    def __init__(self, win) -> None:
        super().__init__("Home", "Posts and notes from people you follow - shared directly, device to device.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        new = button("New post", "square-plus", "primary", "Create a post (Ctrl+P)")
        new.clicked.connect(lambda: CreatePostDialog(win).exec())
        self.actions.addWidget(new)
        self.notes = NotesBar(win)
        self.content.addWidget(self.notes)
        row = QHBoxLayout()
        row.setSpacing(28)
        self.feed = QVBoxLayout()
        self.feed.setSpacing(18)
        fw = QWidget()
        fw.setLayout(self.feed)
        fw.setMaximumWidth(580)
        row.addWidget(fw, 3, Qt.AlignmentFlag.AlignTop)
        self.side = QVBoxLayout()
        self.side.setSpacing(10)
        sw = QWidget()
        sw.setLayout(self.side)
        sw.setMaximumWidth(330)
        row.addWidget(sw, 2, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)
        self.content.addLayout(row)
        self.content.addStretch(1)
        self._pending = False
        for sig in (self.bridge.social_changed, self.bridge.contacts_changed):
            sig.connect(self._schedule)
        self.refresh()

    def _schedule(self, *_a) -> None:
        if not self._pending and self.isVisible():
            self._pending = True
            QTimer.singleShot(250, self.refresh)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self._pending = False
        node = self.node
        self.notes.refresh()
        clear_layout(self.feed)
        posts = node.social.feed(60)
        if not posts:
            act = button("Find people nearby", "radar", "primary")
            act.clicked.connect(lambda: self.win.navigate("discover"))
            self.feed.addWidget(EmptyState("house", "Your feed is empty",
                                           "Follow people you meet nearby to see their posts here, or share your "
                                           "first post with the New post button.", act))
        for p in posts:
            self.feed.addWidget(PostCard(self.win, p))
        # right column: you + suggestions (people met but not followed)
        clear_layout(self.side)
        acc = node.repo.account()
        st = node.social.stats()
        me = QHBoxLayout()
        me.addWidget(Avatar(48).set(acc.display_name, acc.avatar, seed=acc.user_id))
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(name_line(acc.display_name, node.social.is_verified_me()))
        col.addWidget(label(f"@{acc.username} · {st['followers']} followers", "faint"))
        me.addLayout(col, 1)
        sw = button("Profile", variant="link")
        sw.clicked.connect(lambda: self.win.navigate("profile"))
        me.addWidget(sw)
        self.side.addLayout(me)
        sugg = [c for c in node.repo.contacts() if not c.i_follow and c.status not in ("blocked",)]
        sugg.sort(key=lambda c: (not c.follows_me, -c.followers_count))
        if sugg:
            self.side.addWidget(label("Suggested for you", "h3"))
        for c in sugg[:8]:
            r = QHBoxLayout()
            av = Avatar(36).set(c.name, c.avatar, node.connections.is_online(c.id), c.peer_user_id)
            r.addWidget(av)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(name_line(c.name, node.social.is_verified(c)))
            col.addWidget(label("Follows you" if c.follows_me else f"{c.followers_count} followers", "faint"))
            r.addLayout(col, 1)
            f = button("Follow back" if c.follows_me else "Follow", variant="link")
            f.clicked.connect(lambda _=False, c=c: self.bridge.run(node.social.follow(c.id, True)))
            r.addWidget(f)
            w = QWidget()
            w.setLayout(r)
            w.setCursor(Qt.CursorShape.PointingHandCursor)
            w.mouseDoubleClickEvent = lambda _e, c=c: ProfileDialog(self.win, c.id).exec()
            self.side.addWidget(w)
        self.side.addStretch(1)
