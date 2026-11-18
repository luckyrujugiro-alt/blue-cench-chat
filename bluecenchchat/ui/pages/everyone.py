"""Everyone: every Blue Cench Chat account online - follow and text people anywhere."""
from __future__ import annotations

import base64
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from .. import theme
from ..components.social import name_line
from ..components.widgets import (
    Avatar,
    Card,
    EmptyState,
    Page,
    PasswordField,
    SearchBox,
    button,
    clear_layout,
    icon_label,
    label,
)


class EveryonePage(Page):
    def __init__(self, win) -> None:
        super().__init__("Everyone", "All Blue Cench Chat users online. Follow and text people anywhere - messages "
                         "are end-to-end encrypted.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        self.people: list[dict] = []
        self.search = SearchBox("Search name or @username")
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(lambda _t: self._fill())
        self.actions.addWidget(self.search)
        self.b_refresh = button("Refresh", "refresh-cw")
        self.b_refresh.clicked.connect(lambda: self.load(force=True))
        self.actions.addWidget(self.b_refresh)
        self.b_toggle = button("", "power")
        self.b_toggle.clicked.connect(self._toggle_online)
        self.actions.addWidget(self.b_toggle)

        self.status_card = Card(padding=16)
        self.status_body = QVBoxLayout()
        self.status_card.add(self.status_body)
        self.content.addWidget(self.status_card)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self.content.addWidget(self.grid_host)
        self.content.addStretch(1)
        self._cols = 3
        self.bridge.cloud_changed.connect(self._on_cloud)
        self.bridge.contacts_changed.connect(lambda: self.isVisible() and self._fill())
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.isVisible() and self.load())
        self.timer.start(30_000)
        self._status()

    # ------------------------------------------------------------------ state
    def on_show(self) -> None:
        self._status()
        self.load()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        cols = max(1, min(4, (self.width() - 64) // 300))
        if cols != self._cols:
            self._cols = cols
            self._fill()

    def _on_cloud(self) -> None:
        self._status()
        if self.isVisible():
            self.load(force=True)

    def _toggle_online(self) -> None:
        cloud = self.node.cloud
        if cloud.online or cloud.status == "connecting":
            self.bridge.run(cloud.go_offline())
        else:
            self.bridge.run(cloud.go_online())

    def _status(self) -> None:
        cloud = self.node.cloud
        p = theme.palette()
        clear_layout(self.status_body)
        self.b_toggle.setText("Go offline" if cloud.online else "Go online")
        self.b_toggle.setVisible(cloud.status not in ("unavailable",))
        row = QHBoxLayout()
        row.setSpacing(10)
        icon, color, text = {
            "online": ("globe", p.success, "You're online - everyone can find you, follow you and message you."),
            "connecting": ("refresh-cw", p.warning, "Connecting..."),
            "off": ("wifi-off", p.muted, "You're offline. Only people nearby (Bluetooth / same Wi-Fi) can reach you."),
            "unavailable": ("wifi-off", p.muted, "Online mode isn't switched on in this build yet - update the app."),
            "needs_password": ("lock", p.warning, cloud.error or "Enter your password to go online."),
            "error": ("triangle-alert", p.danger, cloud.error or "Something went wrong."),
        }.get(cloud.status, ("wifi-off", p.muted, cloud.status))
        row.addWidget(icon_label(icon, 18, color))
        row.addWidget(label(text, "muted", wrap=True), 1)
        self.status_body.addLayout(row)
        if cloud.status in ("needs_password", "error") and self.node.repo.account().email:
            f = QHBoxLayout()
            pw = PasswordField("Your Blue Cench Chat password")
            pw.setMaximumWidth(320)
            go = button("Go online", "globe", "primary")
            f.addWidget(pw)
            f.addWidget(go)
            f.addStretch(1)
            self.status_body.addLayout(f)

            def submit():
                if pw.text():
                    self.bridge.run(cloud.go_online(pw.text()))
                    pw.clear()
            go.clicked.connect(submit)
            pw.returnPressed.connect(submit)
        elif cloud.status in ("needs_password", "error"):
            self.status_body.addWidget(label("Add an email address in My Profile first - it's your online login.",
                                             "faint", wrap=True))

    def load(self, force: bool = False) -> None:
        if not self.node.cloud.online:
            self.people = []
            self._fill()
            return

        def done(people):
            self.people = people
            self._fill()
        self.bridge.run(self.node.cloud.directory(force=force), done)

    # ------------------------------------------------------------------ grid
    def _fill(self) -> None:
        clear_layout(self.grid)
        cloud = self.node.cloud
        if not cloud.online:
            self.grid.addWidget(EmptyState("globe", "Go online to see everyone",
                                           "When you're online, every Blue Cench Chat user shows up here - even people "
                                           "far away. People nearby still appear in Discover People without internet."),
                                0, 0)
            return
        q = self.search.text().strip().lower().lstrip("@")
        people = [x for x in self.people if not q or q in x.get("name", "").lower() or q in x.get("username", "").lower()]
        if not people:
            self.grid.addWidget(EmptyState("users", "Nobody yet" if not q else "No matches",
                                           "Share Blue Cench Chat with friends - everyone who creates an account and goes "
                                           "online appears here."), 0, 0)
            return
        for i, person in enumerate(people[:200]):
            self.grid.addWidget(self._card(person), i // self._cols, i % self._cols)
        for c in range(self._cols):
            self.grid.setColumnStretch(c, 1)

    def _card(self, person: dict) -> QWidget:
        node, win = self.node, self.win
        cloud = node.cloud
        contact = node.repo.contact_by_peer(person["uid"])
        card = Card(padding=16, spacing=8)
        top = QHBoxLayout()
        img = None
        if person.get("avatar"):
            try:
                img = base64.b64decode(person["avatar"])
            except Exception:
                img = None
        top.addWidget(Avatar(48).set(person.get("name", ""), img, cloud.is_recent(person), person["uid"]))
        col = QVBoxLayout()
        col.setSpacing(1)
        verified = bool(contact and node.social.is_verified(contact)) or cloud.profile_verified(person)
        col.addWidget(name_line(person.get("name", "") or person.get("username", ""), verified))
        col.addWidget(label(f"@{person.get('username', '')}", "muted"))
        seen = person.get("seen") or 0
        col.addWidget(label("Online now" if cloud.is_recent(person) else
                            (f"Active {_ago(seen / 1000)}" if seen else ""), "faint"))
        top.addLayout(col, 1)
        card.add(top)
        stats = label(f"{person.get('followers', 0)} followers · {person.get('following', 0)} following · "
                      f"{person.get('posts', 0)} posts", "faint")
        card.add(stats)
        if person.get("about"):
            ab = label(person["about"][:140], "muted", wrap=True)
            ab.setTextFormat(Qt.TextFormat.PlainText)
            card.add(ab)
        if person.get("note"):
            nt = label("Note: " + person["note"], "faint", wrap=True)
            nt.setTextFormat(Qt.TextFormat.PlainText)
            card.add(nt)
        row = QHBoxLayout()
        blocked = bool(contact and contact.status == "blocked")
        following = bool(contact and contact.i_follow)
        f = button("Following" if following else ("Follow back" if contact and contact.follows_me else "Follow"),
                   variant="following" if following else "follow")
        f.setEnabled(not blocked)
        msg = button("Message", "message-square")
        msg.setEnabled(not blocked)

        async def ensure():
            return await cloud.open_person(person["fuid"])

        def do_follow():
            async def go():
                cid = await ensure()
                c = node.repo.contact(cid)
                await node.social.follow(cid, not c.i_follow)
            self.bridge.run(go(), lambda _r: self._fill())

        f.clicked.connect(do_follow)
        msg.clicked.connect(lambda: self.bridge.run(ensure(), win.open_chat))
        row.addWidget(f, 1)
        row.addWidget(msg, 1)
        card.add(row)
        if node.social.is_admin() and not blocked:
            from .. import actions
            tb = button("Remove blue tick" if verified else "Give blue tick", "badge-check",
                        "ghost" if verified else "primary")
            tb.clicked.connect(lambda: self.bridge.run(ensure(), lambda cid: actions.toggle_tick(win, cid, self._fill)))
            card.add(tb)
        return card


def _ago(ts: float) -> str:
    d = max(0, time.time() - ts)
    if d < 3600:
        return f"{int(d // 60)} min ago"
    if d < 86400:
        return f"{int(d // 3600)} h ago"
    return f"{int(d // 86400)} days ago"
