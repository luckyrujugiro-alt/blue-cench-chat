from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from .. import actions, theme
from ..components.widgets import (
    Avatar,
    Card,
    EmptyState,
    Page,
    Pill,
    Radar,
    SignalBars,
    button,
    clear_layout,
    icon_label,
    label,
)
from ..dialogs.common import IdentityDialog


class PeerCard(QFrame):
    def __init__(self, win, peer) -> None:
        super().__init__()
        self.setObjectName("Card")
        self.setMinimumWidth(270)
        node = win.node
        p = theme.palette()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 14)
        lay.setSpacing(10)
        contact_id = node.discovery.contact_for_hint(peer.hint) if peer.hint else None
        contact = node.repo.contact(contact_id) if contact_id else None
        if contact is None and peer.user_id:
            contact = node.repo.contact_by_peer(peer.user_id)
        online = bool(contact and node.connections.is_online(contact.id))
        name = contact.name if contact else peer.display_name()
        top = QHBoxLayout()
        top.addWidget(Avatar(44).set(name, contact.avatar if contact else None, online if contact else None,
                                     peer.user_id or peer.key))
        col = QVBoxLayout()
        col.setSpacing(1)
        nm = label(name, "h3")
        nm.setTextFormat(Qt.TextFormat.PlainText)
        col.addWidget(nm)
        sub = f"@{peer.username}" if peer.username else ("Paired with Windows" if peer.paired_only else "Identity via handshake")
        col.addWidget(label(sub, "muted"))
        top.addLayout(col, 1)
        bars = SignalBars()
        bars.set(peer.signal_bars)
        top.addWidget(bars, 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(top)

        # status + security --------------------------------------------------
        chips = QHBoxLayout()
        chips.setSpacing(6)
        if contact is None or contact.status in ("stranger", "rejected"):
            chips.addWidget(Pill("New", "neutral"))
        elif contact.status == "blocked":
            chips.addWidget(Pill("Blocked", "danger"))
        elif contact.status == "pending_out":
            chips.addWidget(Pill("Request sent", "primary"))
        elif contact.status == "pending_in":
            chips.addWidget(Pill("Wants to connect", "warning"))
        else:
            chips.addWidget(Pill("Connected" if online else "Connection", "success" if online else "primary"))
        if contact and contact.verified:
            chips.addWidget(Pill("Verified", "success"))
        elif contact and contact.status == "accepted":
            chips.addWidget(Pill("Unverified", "warning"))
        chips.addStretch(1)
        lay.addLayout(chips)

        info = QVBoxLayout()
        info.setSpacing(4)

        def line(ic, text, color=None):
            r = QHBoxLayout()
            r.setSpacing(8)
            r.addWidget(icon_label(ic, 14, color or p.muted))
            r.addWidget(label(text, "faint"), 1)
            info.addLayout(r)

        if "ble" in peer.sources:
            line("bluetooth", f"Bluetooth LE beacon{f'  |  {peer.rssi} dBm' if peer.rssi is not None else ''}", p.cyan)
        if "lan" in peer.transports:
            line("wifi", f"Local network {peer.lan_ip}", p.cyan)
        if "rfcomm" in peer.transports:
            line("bluetooth-connected", "Bluetooth RFCOMM" + (" (paired)" if "paired" in peer.sources else ""), p.cyan)
        if not peer.transports:
            line("triangle-alert", "No direct route yet - pair in Windows or join the same network", p.warning)
        if peer.user_id:
            line("fingerprint", peer.user_id)
        lay.addLayout(info)

        row = QHBoxLayout()
        has_lan, has_bt = "lan" in peer.transports, "rfcomm" in peer.transports
        if contact and contact.status == "accepted":
            if online:
                b = button("Open chat", "message-square", "primary")
                b.clicked.connect(lambda: win.open_chat(contact.id))
            else:
                b = None
                if has_lan:
                    w = button("Wi-Fi", "wifi", "primary", "Connect over the same Wi-Fi / LAN (fastest)")
                    w.clicked.connect(lambda: actions.connect_peer(win, peer, "lan"))
                    row.addWidget(w, 1)
                if has_bt:
                    bb = button("Bluetooth", "bluetooth", "primary" if not has_lan else None,
                                "Connect over Bluetooth (works without Wi-Fi)")
                    bb.clicked.connect(lambda: actions.connect_peer(win, peer, "bt"))
                    row.addWidget(bb, 1)
                if not (has_lan or has_bt):
                    b = button("Connect", "link", "primary")
                    b.setEnabled(False)
        elif contact and contact.status == "pending_in":
            b = button("Review request", "user-plus", "primary")
            b.clicked.connect(lambda: win.navigate("connections"))
        elif contact and contact.status == "blocked":
            b = button("Blocked", "ban")
            b.setEnabled(False)
        elif contact and contact.status == "pending_out":
            b = button("Resend request", "user-plus")
            b.clicked.connect(lambda: actions.connect_peer(win, peer))
        else:
            b = None
            if has_lan:
                w = button("Request on Wi-Fi", "wifi", "primary", "Send a connection request over the same Wi-Fi / LAN")
                w.clicked.connect(lambda: actions.connect_peer(win, peer, "lan"))
                row.addWidget(w, 1)
            if has_bt:
                bb = button("Bluetooth", "bluetooth", None if has_lan else "primary",
                            "Send a connection request over Bluetooth")
                bb.clicked.connect(lambda: actions.connect_peer(win, peer, "bt"))
                row.addWidget(bb, 1 if not has_lan else 0)
            if not (has_lan or has_bt):
                b = button("Connect", "user-plus", "primary")
                b.setEnabled(False)
        if b is not None:
            b.setEnabled(b.isEnabled() and bool(peer.transports))
            row.addWidget(b, 1)
        lay.addLayout(row)


class DiscoverPage(Page):
    def __init__(self, win) -> None:
        super().__init__("Discover People", "Find Blue Cench Chat users near you over Bluetooth LE, paired Bluetooth and "
                         "your local network.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        self.b_scan = button("Stop scanning", "bluetooth-off")
        self.b_refresh = button("Refresh", "refresh-cw")
        self.b_code = button("Connect with code", "qr-code")
        self.b_me = button("My identity", "fingerprint")
        for b in (self.b_refresh, self.b_code, self.b_me, self.b_scan):
            self.actions.addWidget(b)
        self.b_scan.clicked.connect(self._toggle_scan)
        self.b_refresh.clicked.connect(self._refresh_scan)
        self.b_code.clicked.connect(lambda: actions.connect_dialog(win))
        self.b_me.clicked.connect(lambda: IdentityDialog(win, self.node).exec())

        status = Card(padding=18)
        sl = QHBoxLayout()
        sl.setSpacing(18)
        self.radar = Radar(84)
        sl.addWidget(self.radar)
        col = QVBoxLayout()
        col.setSpacing(4)
        self.scan_title = label("", "h2")
        col.addWidget(self.scan_title)
        self.channels = QVBoxLayout()
        self.channels.setSpacing(3)
        col.addLayout(self.channels)
        sl.addLayout(col, 1)
        status.add(sl)
        self.content.addWidget(status)

        from PySide6.QtWidgets import QTabBar
        fbar = QHBoxLayout()
        self.filter = QTabBar()
        for t in ("Everyone nearby", "Same Wi-Fi", "Bluetooth"):
            self.filter.addTab(t)
        self.filter.currentChanged.connect(lambda _i: self.refresh())
        fbar.addWidget(self.filter)
        fbar.addStretch(1)
        self.req_all = button("Request everyone on this Wi-Fi", "users", None,
                              "Send a connection request to every new person on your Wi-Fi")
        self.req_all.clicked.connect(self._request_all_wifi)
        fbar.addWidget(self.req_all)
        self.content.addLayout(fbar)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self.content.addWidget(self.grid_host)
        self.content.addStretch(1)
        self._cols = 3
        self._pending = False
        for sig in (self.bridge.peers_changed, self.bridge.contacts_changed, self.bridge.session_changed,
                    self.bridge.status_changed):
            sig.connect(self._schedule)
        self.refresh()

    def _schedule(self, *_a) -> None:
        if not self._pending and self.isVisible():
            self._pending = True
            QTimer.singleShot(400, self.refresh)

    def on_show(self) -> None:
        self.refresh()

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        cols = max(1, min(4, (self.width() - 64) // 300))
        if cols != self._cols:
            self._cols = cols
            self.refresh()

    def _new_on_wifi(self) -> list:
        out = []
        for peer in self.node.discovery.list():
            if "lan" not in peer.transports:
                continue
            c = self.node.repo.contact_by_peer(peer.user_id) if peer.user_id else None
            if c is None or c.status in ("stranger", "rejected"):
                out.append(peer)
        return out

    def _request_all_wifi(self) -> None:
        new = self._new_on_wifi()
        if not new:
            self.win.toast("No new people on your Wi-Fi right now", "info")
            return
        for peer in new:
            actions.connect_peer(self.win, peer, "lan")

    def _toggle_scan(self) -> None:
        d = self.node.discovery
        d.stop_scan() if d.scanning else d.start_scan()
        self.refresh()

    def _refresh_scan(self) -> None:
        self.node.discovery.clear()
        if not self.node.discovery.scanning:
            self.node.discovery.start_scan()
        self.bridge.run(self.node.refresh_adapter())
        self.win.toast("Discovery refreshed - nearby devices reappear within a few seconds")

    def refresh(self) -> None:
        self._pending = False
        node, p = self.node, theme.palette()
        st = node.status()
        scanning = node.discovery.scanning
        self.radar.set_active(scanning)
        self.b_scan.setText("Stop scanning" if scanning else "Start scanning")
        peers = node.discovery.list()
        self.scan_title.setText(
            (f"Scanning - {len(peers)} device{'s' if len(peers) != 1 else ''} nearby") if scanning else "Scanning is paused")
        clear_layout(self.channels)
        a = st["adapter"]

        def ch(ok, text, warn=False):
            r = QHBoxLayout()
            r.setSpacing(8)
            r.addWidget(icon_label("circle-check" if ok else ("triangle-alert" if warn else "circle-x"), 15,
                                   p.success if ok else (p.warning if warn else p.danger)))
            r.addWidget(label(text, "muted", wrap=True), 1)
            self.channels.addLayout(r)

        if a.available and a.radio_on:
            ch(st["ble_scanning"], "Bluetooth LE scanning" if st["ble_scanning"] else
               f"Bluetooth LE scanning unavailable. {st['ble_error']}", warn=True)
            if st["visible"]:
                ch(st["ble_publishing"], "Advertising your presence over Bluetooth LE" if st["ble_publishing"] else
                   "This adapter cannot advertise (no BLE peripheral role). Others can still find you on the "
                   "local network or via paired RFCOMM.", warn=True)
            ch(st["rfcomm"], "RFCOMM service published - paired PCs can connect" if st["rfcomm"] else
               f"RFCOMM unavailable. {st['rfcomm_error']}", warn=True)
        else:
            ch(False, a.reason or "Bluetooth is not available on this PC.", warn=True)
        ch(st["lan"] and bool(st["ips"]),
           f"Local network presence on {', '.join(st['ips'])}" if st["lan"] and st["ips"] else
           "Not on a local network. Join the same Wi-Fi or a Mobile Hotspot as the other PC for fast transfers.",
           warn=True)
        if not st["visible"]:
            ch(False, "You are hidden. Others cannot discover you (turn visibility on in Security & Privacy).", warn=True)

        allp = peers
        tab = self.filter.currentIndex()
        if tab == 1:
            peers = [x for x in peers if "lan" in x.transports]
        elif tab == 2:
            peers = [x for x in peers if x.bt_addr or "ble" in x.sources or "rfcomm" in x.transports]
        self.filter.setTabText(1, f"Same Wi-Fi ({sum('lan' in x.transports for x in allp)})")
        self.filter.setTabText(2, f"Bluetooth ({sum(bool(x.bt_addr or 'ble' in x.sources) for x in allp)})")
        n_new = len(self._new_on_wifi())
        self.req_all.setEnabled(n_new > 0)
        self.req_all.setText(f"Request everyone on this Wi-Fi ({n_new})" if n_new else "Request everyone on this Wi-Fi")
        clear_layout(self.grid)
        if not peers:
            self.grid.addWidget(EmptyState(
                "radar", "No one found yet" if scanning else "Start scanning to find people",
                "Make sure Blue Cench Chat is open on the other PC with visibility on. Discovery uses Bluetooth LE "
                "advertising when both adapters support it, and presence beacons on a shared network. You can "
                "always connect with an identity code instead.",
                None), 0, 0)
            return
        for i, peer in enumerate(peers):
            self.grid.addWidget(PeerCard(self.win, peer), i // self._cols, i % self._cols)
        for c in range(self._cols):
            self.grid.setColumnStretch(c, 1)
