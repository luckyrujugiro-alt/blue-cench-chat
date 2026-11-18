"""Home: notes, a share box, the feed, and a profile + suggestions column - centred like a real social app."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme
from ..components.social import CreatePostDialog, NotesBar, PostCard, ProfileDialog, edit_note_dialog, name_line
from ..components.widgets import Avatar, Card, EmptyState, Page, button, clear_layout, icon_label, label

FEED_W = 600
SIDE_W = 330


class HomePage(Page):
    def __init__(self, win) -> None:
        super().__init__("Home", "Posts and notes from people you follow - nearby, or online.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        new = button("New post", "square-plus", "primary", "Create a post (Ctrl+P)")
        new.clicked.connect(lambda: CreatePostDialog(win).exec())
        self.actions.addWidget(new)

        # everything sits in one centred column, so wide screens don't leave things floating
        outer = QHBoxLayout()
        outer.addStretch(1)
        center = QWidget()
        center.setMaximumWidth(FEED_W + SIDE_W + 32)
        outer.addWidget(center, 100)
        outer.addStretch(1)
        self.content.addLayout(outer)
        self.content.addStretch(1)

        col = QVBoxLayout(center)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(18)

        self.notes_card = Card(padding=12)
        self.notes = NotesBar(win)
        self.notes_card.add(self.notes)
        col.addWidget(self.notes_card)

        row = QHBoxLayout()
        row.setSpacing(32)
        feed_host = QWidget()
        feed_host.setMaximumWidth(FEED_W)
        self.feed_col = QVBoxLayout(feed_host)
        self.feed_col.setContentsMargins(0, 0, 0, 0)
        self.feed_col.setSpacing(18)
        self.feed_col.addWidget(self._share_box())
        self.feed = QVBoxLayout()
        self.feed.setSpacing(18)
        self.feed_col.addLayout(self.feed)
        self.feed_col.addStretch(1)
        row.addWidget(feed_host, 3, Qt.AlignmentFlag.AlignTop)

        side_host = QWidget()
        side_host.setFixedWidth(SIDE_W)
        self.side = QVBoxLayout(side_host)
        self.side.setContentsMargins(0, 0, 0, 0)
        self.side.setSpacing(14)
        row.addWidget(side_host, 0, Qt.AlignmentFlag.AlignTop)
        col.addLayout(row)

        self._pending = False
        for sig in (self.bridge.social_changed, self.bridge.contacts_changed):
            sig.connect(self._schedule)
        self.refresh()

    # ------------------------------------------------------------------ pieces
    def _share_box(self) -> QWidget:
        """'What's new?' box at the top of the feed - opens the post composer."""
        acc = self.node.repo.account()
        card = Card(padding=14, spacing=10)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.share_av = Avatar(42).set(acc.display_name, acc.avatar, seed=acc.user_id)
        top.addWidget(self.share_av)
        prompt = QLabel(f"What's new, {acc.display_name.split()[0] if acc.display_name else 'you'}?")
        prompt.setCursor(Qt.CursorShape.PointingHandCursor)
        p = theme.palette()
        prompt.setStyleSheet(f"background:{p.surface2}; border:1px solid {p.border}; border-radius:21px;"
                             f"padding:10px 16px; color:{p.muted};")
        prompt.mousePressEvent = lambda _e: CreatePostDialog(self.win).exec()
        top.addWidget(prompt, 1)
        card.add(top)
        acts = QHBoxLayout()
        acts.setSpacing(6)
        for ic, text, fn in (("image-plus", "Photo", lambda: CreatePostDialog(self.win).exec()),
                             ("music", "Note with music", lambda: edit_note_dialog(self.win)),
                             ("radar", "Find people", lambda: self.win.navigate("discover")),
                             ("globe", "Everyone", lambda: self.win.navigate("everyone"))):
            b = button(text, ic, "ghost")
            b.clicked.connect(fn)
            acts.addWidget(b)
        acts.addStretch(1)
        card.add(acts)
        return card

    def _profile_card(self) -> QWidget:
        node = self.node
        acc = node.repo.account()
        st = node.social.stats()
        card = Card(padding=16, spacing=10)
        top = QHBoxLayout()
        top.setSpacing(12)
        top.addWidget(Avatar(52).set(acc.display_name, acc.avatar, seed=acc.user_id))
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(name_line(acc.display_name, node.social.is_verified_me()))
        col.addWidget(label(f"@{acc.username}", "muted"))
        top.addLayout(col, 1)
        card.add(top)
        nums = QHBoxLayout()
        nums.setSpacing(0)
        for n, what in ((st["posts"], "posts"), (st["followers"], "followers"), (st["following"], "following")):
            c = QVBoxLayout()
            c.setSpacing(0)
            v = label(f"{n:,}", "h3")
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t = label(what, "faint")
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            c.addWidget(v)
            c.addWidget(t)
            nums.addLayout(c, 1)
        card.add(nums)
        b = button("View profile", "user")
        b.clicked.connect(lambda: self.win.navigate("profile"))
        card.add(b)
        return card

    def _suggestions_card(self) -> QWidget | None:
        node = self.node
        sugg = [c for c in node.repo.contacts() if not c.i_follow and c.status not in ("blocked",)]
        sugg.sort(key=lambda c: (not c.follows_me, -c.followers_count))
        card = Card("Suggested for you", "sparkles", padding=16, spacing=10)
        if not sugg:
            card.add(label("People you meet nearby or online show up here.", "muted", wrap=True))
            b = button("Find people nearby", "radar", "primary")
            b.clicked.connect(lambda: self.win.navigate("discover"))
            card.add(b)
            return card
        for c in sugg[:6]:
            r = QHBoxLayout()
            r.setSpacing(10)
            r.addWidget(Avatar(36).set(c.name, c.avatar, node.connections.is_online(c.id), c.peer_user_id))
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
            card.add(w)
        return card

    def _status_card(self) -> QWidget:
        """Where your messages can travel right now."""
        node = self.node
        p = theme.palette()
        card = Card(padding=14, spacing=8)
        nearby = sum(1 for c in node.repo.contacts(("accepted",)) if node.connections.is_online(c.id))
        rows = [
            ("bluetooth", f"{nearby} connected nearby" if nearby else "Nobody connected nearby", p.primary),
            ("globe", "Online - reachable anywhere" if node.cloud.online else "Online mode off",
             p.success if node.cloud.online else p.faint),
            ("radio", "Extended range on" if node.settings.get("mesh_enabled", True) else "Extended range off",
             p.cyan),
        ]
        for ic, text, color in rows:
            r = QHBoxLayout()
            r.setSpacing(10)
            r.addWidget(icon_label(ic, 16, color))
            r.addWidget(label(text, "muted"), 1)
            card.add(r)
        return card

    # ------------------------------------------------------------------ refresh
    def _schedule(self, *_a) -> None:
        if not self._pending and self.isVisible():
            self._pending = True
            QTimer.singleShot(250, self.refresh)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self._pending = False
        node = self.node
        acc = node.repo.account()
        self.share_av.set(acc.display_name, acc.avatar, seed=acc.user_id)
        self.notes.refresh()
        clear_layout(self.feed)
        posts = node.social.feed(60)
        if not posts:
            empty = Card(padding=24)
            act = button("Share your first post", "square-plus", "primary")
            act.clicked.connect(lambda: CreatePostDialog(self.win).exec())
            empty.add(EmptyState("house", "Your feed is empty",
                                 "Follow people you meet nearby or on Everyone to see their posts here.", act))
            self.feed.addWidget(empty)
        for p in posts:
            card = PostCard(self.win, p)
            card.setMaximumWidth(FEED_W)
            self.feed.addWidget(card)
        clear_layout(self.side)
        self.side.addWidget(self._profile_card())
        self.side.addWidget(self._status_card())
        s = self._suggestions_card()
        if s is not None:
            self.side.addWidget(s)
        foot = label("Blue Cench Chat · end-to-end encrypted · works without internet", "faint", wrap=True)
        self.side.addWidget(foot)
        self.side.addStretch(1)
