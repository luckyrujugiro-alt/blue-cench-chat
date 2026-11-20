from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QTabBar, QVBoxLayout

from .. import actions, theme
from ..components.widgets import (
    Avatar,
    EmptyState,
    Page,
    Pill,
    SearchBox,
    button,
    clear_layout,
    human_time,
    icon_label,
    label,
    tool_button,
)
from ..dialogs.common import VerifyDialog


class ContactRow(QFrame):
    def __init__(self, win, contact) -> None:
        super().__init__()
        self.setObjectName("Card")
        node, p = win.node, theme.palette()
        online = node.connections.is_online(contact.id)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 14, 12)
        lay.setSpacing(14)
        lay.addWidget(Avatar(46).set(contact.name, contact.avatar, online if contact.status == "accepted" else None,
                                     contact.peer_user_id))
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(6)
        nm = label(contact.name, "h3")
        nm.setTextFormat(Qt.TextFormat.PlainText)
        top.addWidget(nm)
        if contact.verified:
            v = icon_label("badge-check", 16, p.success)
            v.setToolTip("Verified with safety number or identity code")
            top.addWidget(v)
        if contact.favorite:
            top.addWidget(icon_label("star", 15, p.warning))
        top.addStretch(1)
        col.addLayout(top)
        detail = f"@{contact.username}  |  {contact.peer_user_id}"
        col.addWidget(label(detail, "muted"))
        if contact.about:
            ab = label(contact.about[:120], "faint")
            ab.setTextFormat(Qt.TextFormat.PlainText)
            col.addWidget(ab)
        lay.addLayout(col, 1)
        state = QVBoxLayout()
        state.setSpacing(4)
        if contact.status == "accepted":
            if online:
                s = node.connections.session_for_contact(contact.id)
                state.addWidget(Pill(f"Online - {node.transport_label(s.transport)}", "success"), 0, Qt.AlignmentFlag.AlignRight)
            else:
                state.addWidget(Pill("Offline", "neutral"), 0, Qt.AlignmentFlag.AlignRight)
                state.addWidget(label(f"Last seen {human_time(contact.last_seen)}", "faint"), 0, Qt.AlignmentFlag.AlignRight)
        lay.addLayout(state)

        if contact.status == "pending_in":
            acc = button("Accept", "check", "primary")
            rej = button("Decline", "x")
            acc.clicked.connect(lambda: win.bridge.run(node.connections.accept(contact.id),
                                                       lambda _: win.toast(f"You are now connected with {contact.name}", "success")))
            rej.clicked.connect(lambda: win.bridge.run(node.connections.reject(contact.id)))
            if not online:
                acc.setToolTip("They are away - they will be told as soon as you connect again")
            lay.addWidget(acc)
            lay.addWidget(rej)
        elif contact.status == "pending_out":
            lay.addWidget(Pill("Waiting for response", "primary"))
        elif contact.status == "accepted":
            m = tool_button("message-square", "Message")
            m.clicked.connect(lambda: win.open_chat(contact.id))
            f = tool_button("paperclip", "Send files")
            f.clicked.connect(lambda: actions.send_files(win, contact.id))
            v = tool_button("shield-check", "Verify safety number")
            v.clicked.connect(lambda: VerifyDialog(win, node, contact).exec())
            for b in (m, f, v):
                lay.addWidget(b)
        elif contact.status == "blocked":
            u = button("Unblock", "user-check")
            u.clicked.connect(lambda: node.connections.unblock(contact.id))
            lay.addWidget(u)
        more = tool_button("ellipsis-vertical", "More actions")
        more.clicked.connect(lambda: actions.contact_menu(win, contact, more).exec(
            more.mapToGlobal(QPoint(0, more.height()))))
        lay.addWidget(more)


class ConnectionsPage(Page):
    TABS = [("Connections", ("accepted",)), ("Requests", ("pending_in", "pending_out")),
            ("Blocked", ("blocked",))]

    def __init__(self, win) -> None:
        super().__init__("My Connections", "People you have connected with. Nothing is trusted until you accept it.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        add = button("Add connection", "user-plus", "primary")
        add.clicked.connect(lambda: win.navigate("discover"))
        code = button("Connect with code", "qr-code")
        code.clicked.connect(lambda: actions.connect_dialog(win))
        self.actions.addWidget(code)
        self.actions.addWidget(add)
        bar = QHBoxLayout()
        self.tabs = QTabBar()
        for t, _ in self.TABS:
            self.tabs.addTab(t)
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.tabs)
        bar.addStretch(1)
        self.search = SearchBox("Search connections")
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.search)
        self.content.addLayout(bar)
        self.list = QVBoxLayout()
        self.list.setSpacing(10)
        self.content.addLayout(self.list)
        self.content.addStretch(1)
        self._pending = False
        for sig in (self.bridge.contacts_changed, self.bridge.session_changed):
            sig.connect(self._schedule)
        self.refresh()

    def show_requests(self) -> None:
        self.tabs.setCurrentIndex(1)

    def _schedule(self, *_a) -> None:
        if not self._pending and self.isVisible():
            self._pending = True
            QTimer.singleShot(250, self.refresh)

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self._pending = False
        n_req = len(self.node.repo.contacts(("pending_in",)))
        self.tabs.setTabText(1, f"Requests ({n_req})" if n_req else "Requests")
        statuses = self.TABS[self.tabs.currentIndex()][1]
        q = self.search.text().strip().lower()
        contacts = [c for c in self.node.repo.contacts(statuses)
                    if not q or q in c.name.lower() or q in c.username.lower() or q in c.peer_user_id.lower()]
        contacts.sort(key=lambda c: (not c.favorite, not self.node.connections.is_online(c.id), c.name.lower()))
        clear_layout(self.list)
        if not contacts:
            texts = {
                0: ("users", "No connections yet", "Discover people nearby and send a connection request."),
                1: ("inbox", "No pending requests", "Incoming and outgoing connection requests appear here."),
                2: ("ban", "No blocked users", "People you block cannot connect to you."),
            }
            self.list.addWidget(EmptyState(*texts[self.tabs.currentIndex()]))
            return
        for c in contacts:
            self.list.addWidget(ContactRow(self.win, c))
