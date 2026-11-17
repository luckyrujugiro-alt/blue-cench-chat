from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ... import config
from .. import icons, theme
from ..components.transfer_row import TransferRow
from ..components.widgets import (
    Avatar,
    BarChart,
    Card,
    EmptyState,
    Page,
    Pill,
    RingGauge,
    StatCard,
    button,
    clear_layout,
    human_size,
    human_time,
    icon_label,
    label,
)

ACTIVITY_ICONS = {"connection": "link", "message": "message-square", "transfer": "arrow-left-right",
                  "security": "shield", "system": "monitor"}


class DashboardPage(Page):
    def __init__(self, win) -> None:
        super().__init__("Dashboard")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        p = theme.palette()

        # hero ---------------------------------------------------------------
        hero = QFrame()
        hero.setObjectName("Hero")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(24, 22, 24, 22)
        col = QVBoxLayout()
        col.setSpacing(6)
        self.greet = label("", "h2")
        col.addWidget(self.greet)
        self.hero_text = label("", "muted", wrap=True)
        col.addWidget(self.hero_text)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        self.chip_bt = Pill("", "neutral")
        self.chip_lan = Pill("", "neutral")
        self.chip_vis = Pill("", "neutral")
        for c in (self.chip_bt, self.chip_lan, self.chip_vis):
            chips.addWidget(c)
        chips.addStretch(1)
        col.addSpacing(4)
        col.addLayout(chips)
        hl.addLayout(col, 1)
        acts = QVBoxLayout()
        b1 = button("Discover people", "radar", "primary")
        b2 = button("Send files", "upload")
        b1.clicked.connect(lambda: win.navigate("discover"))
        b2.clicked.connect(lambda: win.navigate("transfers"))
        acts.addWidget(b1)
        acts.addWidget(b2)
        hl.addLayout(acts)
        self.content.addWidget(hero)

        # stats -------------------------------------------------------------
        grid = QGridLayout()
        grid.setSpacing(14)
        self.s_nearby = StatCard("radar", "Nearby Blue Cench Chat users", "cyan")
        self.s_connected = StatCard("link", "Connected devices", "primary")
        self.s_in = StatCard("download", "Files received", "success")
        self.s_out = StatCard("upload", "Files sent", "warning")
        for i, w in enumerate((self.s_nearby, self.s_connected, self.s_in, self.s_out)):
            grid.addWidget(w, 0, i)
        self.content.addLayout(grid)

        # chart + storage ----------------------------------------------------
        row = QHBoxLayout()
        row.setSpacing(14)
        chart_card = Card("Transfer activity - last 7 days", "chart-column")
        self.chart = BarChart()
        chart_card.add(self.chart)
        row.addWidget(chart_card, 3)
        store = Card("Storage", "hard-drive")
        self.gauge = RingGauge(130)
        store.add(self.gauge)
        store.body.setAlignment(self.gauge, Qt.AlignmentFlag.AlignHCenter)
        self.store_text = label("", "muted", wrap=True)
        store.add(self.store_text)
        row.addWidget(store, 1)
        self.content.addLayout(row)

        # lists ---------------------------------------------------------------
        row2 = QHBoxLayout()
        row2.setSpacing(14)
        self.conv_card = Card("Recent conversations", "message-square")
        self.conv_list = QVBoxLayout()
        self.conv_list.setSpacing(4)
        self.conv_card.add(self.conv_list)
        row2.addWidget(self.conv_card, 1)
        self.xfer_card = Card("Active file transfers", "arrow-left-right")
        self.xfer_list = QVBoxLayout()
        self.xfer_list.setSpacing(8)
        self.xfer_card.add(self.xfer_list)
        row2.addWidget(self.xfer_card, 1)
        self.content.addLayout(row2)

        self.act_card = Card("Recent activity", "activity")
        self.act_list = QVBoxLayout()
        self.act_list.setSpacing(2)
        self.act_card.add(self.act_list)
        self.content.addWidget(self.act_card)
        self.content.addStretch(1)

        self._rows: dict[str, TransferRow] = {}
        for sig in (self.bridge.contacts_changed, self.bridge.peers_changed, self.bridge.status_changed,
                    self.bridge.messages_changed, self.bridge.session_changed):
            sig.connect(self._schedule)
        self.bridge.transfer_changed.connect(self._on_transfer)
        self._pending = False
        self.refresh()

    def _schedule(self, *_a) -> None:
        if not self._pending and self.isVisible():
            self._pending = True
            QTimer.singleShot(300, self.refresh)

    def _on_transfer(self, tid: str) -> None:
        r = self._rows.get(tid)
        if r is not None:
            r.refresh()
            t = self.node.repo.transfer(tid)
            if t and t.status in ("completed", "cancelled", "rejected", "failed"):
                self._schedule()
        else:
            self._schedule()

    def on_show(self) -> None:
        self.refresh()

    def refresh(self) -> None:
        self._pending = False
        node, repo, p = self.node, self.node.repo, theme.palette()
        acc = repo.account()
        hour = time.localtime().tm_hour
        part = "morning" if hour < 12 else ("afternoon" if hour < 18 else "evening")
        self.greet.setText(f"Good {part}, {acc.display_name.split()[0]}")
        st = node.status()
        a = st["adapter"]
        online = len(node.connections.sessions)
        self.hero_text.setText(
            f"You are {'visible to' if st['visible'] else 'hidden from'} nearby Blue Cench Chat users. "
            f"{online} secure session{'s' if online != 1 else ''} open. Your Blue Cench Chat ID is {acc.user_id}.")
        if a.available and a.radio_on:
            self.chip_bt.setText("Bluetooth on" + (" - advertising" if st["ble_publishing"] else ""))
            self.chip_bt.set_tone("success")
        elif a.available:
            self.chip_bt.setText("Bluetooth off")
            self.chip_bt.set_tone("warning")
        else:
            self.chip_bt.setText("Bluetooth unavailable")
            self.chip_bt.set_tone("danger")
        self.chip_lan.setText(f"Local network: {', '.join(st['ips'][:2]) or 'not connected'}" if st["lan"]
                              else "Local network off")
        self.chip_lan.set_tone("cyan" if st["lan"] and st["ips"] else "neutral")
        self.chip_vis.setText("Visible" if st["visible"] else "Hidden")
        self.chip_vis.set_tone("primary" if st["visible"] else "neutral")

        peers = node.discovery.list()
        self.s_nearby.set(str(len(peers)), "scanning" if node.discovery.scanning else "scanning paused")
        accepted = len(repo.contacts(("accepted",)))
        self.s_connected.set(str(online), f"{accepted} saved connection{'s' if accepted != 1 else ''}")
        stats = repo.transfer_stats(7)
        self.s_in.set(str(stats["files_in"]), human_size(stats["bytes_in"]) + " total")
        self.s_out.set(str(stats["files_out"]), human_size(stats["bytes_out"]) + " total")
        labels = [time.strftime("%a", time.localtime(d + 43200)) for d in stats["day_starts"]]
        self.chart.set_data(labels, stats["per_day_in"], stats["per_day_out"])

        dl = Path(node.settings.get("download_dir") or config.default_download_dir())
        probe = dl if dl.exists() else dl.anchor or Path.home()
        try:
            du = shutil.disk_usage(probe)
            self.gauge.set(du.used / du.total, f"{du.used / du.total * 100:.0f}%", "disk used")
            self.store_text.setText(f"{human_size(du.free)} free of {human_size(du.total)} on the download drive.\n"
                                    f"Received with Blue Cench Chat: {human_size(stats['bytes_in'])}")
        except OSError:
            self.store_text.setText("Download folder is not available.")

        clear_layout(self.conv_list)
        convs = [c for c in repo.conversations() if c[1] is not None][:5]
        if not convs:
            self.conv_list.addWidget(label("No conversations yet. Connect with someone nearby to start chatting.",
                                           "muted", wrap=True))
        for c, last, unread in convs:
            row = QWidget()
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(4, 6, 4, 6)
            rl.addWidget(Avatar(36).set(c.name, c.avatar, node.connections.is_online(c.id), c.peer_user_id))
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(c.name, "h3"))
            prev = ("You: " if last.direction == "out" else "") + (last.body if last.kind != "file" else f"File: {last.body}")
            pl = label(prev[:70], "muted")
            col.addWidget(pl)
            rl.addLayout(col, 1)
            right = QVBoxLayout()
            right.addWidget(label(human_time(last.ts), "faint"), 0, Qt.AlignmentFlag.AlignRight)
            if unread:
                right.addWidget(Pill(str(unread), "primary"), 0, Qt.AlignmentFlag.AlignRight)
            rl.addLayout(right)
            row.mousePressEvent = lambda _e, cid=c.id: self.win.open_chat(cid)
            self.conv_list.addWidget(row)

        clear_layout(self.xfer_list)
        self._rows = {}
        active = repo.transfers(("active", "paused", "waiting", "offered", "preparing", "interrupted", "queued"))[:4]
        if not active:
            self.xfer_list.addWidget(label("No active transfers.", "muted"))
        for t in active:
            r = TransferRow(self.bridge, t.id, compact=True)
            self._rows[t.id] = r
            self.xfer_list.addWidget(r)

        clear_layout(self.act_list)
        items = repo.activity(8)
        if not items:
            self.act_list.addWidget(label("Nothing yet.", "muted"))
        for a_ in items:
            row = QHBoxLayout()
            row.setSpacing(10)
            tone = p.warning if a_.kind == "security" else p.muted
            row.addWidget(icon_label(ACTIVITY_ICONS.get(a_.kind, "info"), 16, tone))
            row.addWidget(label(a_.text, wrap=True), 1)
            row.addWidget(label(human_time(a_.ts), "faint"))
            w = QWidget()
            w.setLayout(row)
            self.act_list.addWidget(w)
