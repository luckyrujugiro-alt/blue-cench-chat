"""Verification dashboard - only for the official @bluecenchchat account."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QTabBar, QVBoxLayout, QWidget

from ...core import verification as vf
from .. import theme
from ..components.social import ProfileDialog, name_line, tick_icon
from ..components.widgets import (
    Avatar,
    Card,
    EmptyState,
    Page,
    Pill,
    SearchBox,
    StatCard,
    button,
    clear_layout,
    human_time,
    icon_label,
    label,
)
from ..dialogs.common import confirm


class VerifyPage(Page):
    def __init__(self, win) -> None:
        super().__init__("Verification", "Give and remove blue ticks. Only the official @bluecenchchat account "
                         "sees this page.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        p = theme.palette()
        self.publish = Card("Blue ticks", "badge-check")
        self.publish_body = QVBoxLayout()
        self.publish.add(self.publish_body)
        self.content.addWidget(self.publish)
        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.s_pending = StatCard("inbox", "Pending requests", "warning")
        self.s_verified = StatCard("badge-check", "Verified accounts", "primary")
        self.s_people = StatCard("users", "People known to this PC", "cyan")
        for w in (self.s_pending, self.s_verified, self.s_people):
            stats.addWidget(w)
        self.content.addLayout(stats)
        bar = QHBoxLayout()
        self.tabs = QTabBar()
        for t in ("Requests", "All people", "Verified"):
            self.tabs.addTab(t)
        self.tabs.currentChanged.connect(lambda _i: self.refresh())
        bar.addWidget(self.tabs)
        bar.addStretch(1)
        self.search = SearchBox("Search people")
        self.search.setMaximumWidth(260)
        self.search.textChanged.connect(lambda _t: self.refresh())
        bar.addWidget(self.search)
        self.content.addLayout(bar)
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        self.content.addLayout(self.list)
        self.content.addWidget(label(
            f"People can ask for a blue tick once they have {vf.MIN_FOLLOWERS_FOR_REQUEST} followers, but you can give "
            "one to anyone at any time. Ticks are signed with your key, so nobody can fake one.", "faint",
            wrap=True))
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

    def _publish_card(self) -> None:
        clear_layout(self.publish_body)
        cloud = self.node.cloud
        r = QHBoxLayout()
        r.addWidget(tick_icon(18))
        if cloud.is_official_owner():
            self.publish.title_label.setText("Your ticks reach everyone")
            text = ("You're online as the official account. A tick you give shows at once for that person and for "
                    "everyone online - no request or follower count needed. Give one from here, from Everyone, or "
                    "from anyone's profile.")
        elif cloud.official_note:
            self.publish.title_label.setText("Official key is held by another device")
            text = cloud.official_note
        else:
            self.publish.title_label.setText("Ticks work on this PC right now")
            text = ("Ticks you give show at once on this PC and on devices you meet. Turn on online mode "
                    "(Settings) once and they reach every Blue Cench Chat user everywhere, automatically.")
        r.addWidget(label(text, "muted", wrap=True), 1)
        self.publish_body.addLayout(r)

    def refresh(self) -> None:
        self._pending = False
        social = self.node.social
        self._publish_card()
        people = social.people()
        pending = [d for d in people if d["request"] and d["request"].status == "pending"]
        verified = [d for d in people if d["verified"]]
        self.s_pending.set(str(len(pending)), "waiting for your review")
        self.s_verified.set(str(len(verified) + (1 if social.is_verified_me() else 0)), "including you")
        self.s_people.set(str(len(people)), "met nearby or connected")
        self.tabs.setTabText(0, f"Requests ({len(pending)})" if pending else "Requests")
        tab = self.tabs.currentIndex()
        rows = pending if tab == 0 else (people if tab == 1 else verified)
        q = self.search.text().strip().lower()
        if q:
            rows = [d for d in rows if q in d["contact"].name.lower() or q in d["contact"].username.lower()
                    or q in d["contact"].peer_user_id.lower()]
        clear_layout(self.list)
        if not rows:
            texts = {0: ("inbox", "No pending requests", f"Requests arrive when someone with "
                         f"{vf.MIN_FOLLOWERS_FOR_REQUEST}+ followers asks and their device meets yours."),
                     1: ("users", "Nobody yet", "People appear here once your PC has met them nearby."),
                     2: ("badge-check", "No verified accounts yet", "Give a blue tick from Requests or All people.")}
            self.list.addWidget(EmptyState(*texts[tab]))
            return
        for d in rows:
            self.list.addWidget(self._row(d))

    def _row(self, d) -> QWidget:
        c, r = d["contact"], d["request"]
        p = theme.palette()
        card = Card(padding=14, spacing=6)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(Avatar(44).set(c.name, c.avatar, d["online"], c.peer_user_id))
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(name_line(c.name, d["verified"]))
        col.addWidget(label(f"@{c.username} · {c.peer_user_id} · {d['followers']:,} followers", "muted"))
        if r and r.status == "pending":
            msg = label(f"“{r.message}” · requested {human_time(r.ts)} with {r.followers} followers", "faint",
                        wrap=True)
            msg.setTextFormat(Qt.TextFormat.PlainText)
            col.addWidget(msg)
        row.addLayout(col, 1)
        sus = self.node.social.suspension(c.peer_user_id)
        if sus:
            row.addWidget(Pill("Suspended forever" if sus["forever"] else
                               "Suspended until " + time.strftime("%d %b %H:%M", time.localtime(sus["until"])),
                               "danger"))
        if r:
            tone = {"pending": "warning", "granted": "success", "declined": "neutral", "revoked": "danger"}[r.status]
            row.addWidget(Pill(r.status.title(), tone))
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QMenu
        from .. import actions
        sb = button("Suspend" if not sus else "Suspended", "ban", "ghost")
        smenu = QMenu(sb)
        actions.fill_suspend_menu(self.win, smenu, c.peer_user_id, c.name)
        sb.clicked.connect(lambda: smenu.exec(sb.mapToGlobal(QPoint(0, sb.height()))))
        row.addWidget(sb)
        view = button("Profile", variant="ghost")
        view.clicked.connect(lambda: ProfileDialog(self.win, c.id).exec())
        row.addWidget(view)
        if d["verified"]:
            rm = button("Remove tick", "x", "danger")
            rm.clicked.connect(lambda: confirm(self.win, f"Remove {c.name}'s blue tick?",
                                               "The removal spreads to every device that meets yours.", "Remove", True)
                               and self.bridge.run(self.node.social.revoke_tick(c.peer_user_id),
                                                   lambda _r: self.win.toast("Blue tick removed")))
            row.addWidget(rm)
        else:
            give = button("Give blue tick", "badge-check", "primary")
            give.clicked.connect(lambda: self.bridge.run(self.node.social.grant_tick(c.peer_user_id),
                                                         lambda _r: self.win.toast(f"{c.name} is now verified",
                                                                                   "success")))
            row.addWidget(give)
            if r and r.status == "pending":
                dec = button("Decline", variant="ghost")
                dec.clicked.connect(lambda: self.bridge.run(self.node.social.decline_tick(c.peer_user_id)))
                row.addWidget(dec)
        card.add(row)
        return card
