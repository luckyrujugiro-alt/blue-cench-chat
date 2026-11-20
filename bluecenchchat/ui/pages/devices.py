from __future__ import annotations

import platform
import sys

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ... import config
from ...core.transports import bluetooth
from .. import system, theme
from ..components.widgets import (
    Card,
    Page,
    Pill,
    button,
    clear_layout,
    human_time,
    icon_label,
    label,
)


class DevicesPage(Page):
    def __init__(self, win) -> None:
        super().__init__("Bluetooth Devices", "Adapter capabilities, paired devices, active links and a "
                         "compatibility check for this PC.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        b_refresh = button("Refresh", "refresh-cw")
        b_settings = button("Windows Bluetooth settings", "external-link")
        b_hot = button("Mobile hotspot settings", "router")
        b_test = button("Run compatibility test", "activity", "primary")
        for b in (b_refresh, b_hot, b_settings, b_test):
            self.actions.addWidget(b)
        b_refresh.clicked.connect(self.reload)
        b_settings.clicked.connect(lambda: system.open_bluetooth_settings() or win.toast(
            "Windows Settings are only available on Windows", "warning"))
        b_hot.clicked.connect(lambda: system.open_hotspot_settings() or win.toast(
            "Windows Settings are only available on Windows", "warning"))
        b_test.clicked.connect(self.run_test)

        row = QHBoxLayout()
        row.setSpacing(14)
        self.adapter_card = Card("Bluetooth adapter", "bluetooth")
        self.adapter_body = QGridLayout()
        self.adapter_body.setHorizontalSpacing(18)
        self.adapter_body.setVerticalSpacing(8)
        self.adapter_card.add(self.adapter_body)
        self.adapter_card.body.addStretch(1)
        row.addWidget(self.adapter_card, 1)
        self.links_card = Card("Blue Cench Chat transports", "radio")
        self.links_body = QVBoxLayout()
        self.links_card.add(self.links_body)
        self.links_card.body.addStretch(1)
        row.addWidget(self.links_card, 1)
        self.content.addLayout(row)

        self.sessions_card = Card("Active secure sessions", "lock")
        self.sessions_body = QVBoxLayout()
        self.sessions_card.add(self.sessions_body)
        self.content.addWidget(self.sessions_card)

        self.paired_card = Card("Devices paired with Windows", "bluetooth-connected")
        self.paired_card.add(label("RFCOMM connections between two PCs normally require pairing them once in "
                                   "Windows Settings > Bluetooth & devices > Add device. Blue Cench Chat never pairs or "
                                   "trusts devices silently.", "muted", wrap=True))
        self.paired_body = QVBoxLayout()
        self.paired_card.add(self.paired_body)
        self.content.addWidget(self.paired_card)

        self.test_card = Card("Compatibility test", "activity")
        self.test_body = QVBoxLayout()
        self.test_card.add(self.test_body)
        self.test_body.addWidget(label("Press Run compatibility test to check this PC.", "muted"))
        self.content.addWidget(self.test_card)
        self.content.addStretch(1)
        self.bridge.status_changed.connect(lambda: self.isVisible() and self.render())
        self.bridge.session_changed.connect(lambda *_: self.isVisible() and self.render())
        self._paired: list[dict] = []
        self._bluecenchchat_paired: list[dict] = []
        self.render()

    def on_show(self) -> None:
        self.reload()

    def reload(self) -> None:
        async def go():
            await self.node.refresh_adapter()
            return await bluetooth.paired_devices(), await bluetooth.bluecenchchat_rfcomm_peers()

        def done(res):
            self._paired, self._bluecenchchat_paired = res
            self.render()

        self.bridge.run(go(), done)

    def render(self) -> None:
        p = theme.palette()
        st = self.node.status()
        a = st["adapter"]
        clear_layout(self.adapter_body)

        def kv(r, k, v, ok=None):
            self.adapter_body.addWidget(label(k, "muted"), r, 0)
            if ok is None:
                self.adapter_body.addWidget(label(v), r, 1)
            else:
                self.adapter_body.addWidget(Pill(v, "success" if ok else "warning"), r, 1)

        if not a.available:
            kv(0, "Status", a.reason or "Unavailable", False)
        else:
            kv(0, "Name", a.name)
            kv(1, "Address", a.address_str)
            kv(2, "Radio", "On" if a.radio_on else "Off", a.radio_on)
            kv(3, "Bluetooth Classic (RFCOMM)", "Supported" if a.classic else "Not supported", a.classic)
            kv(4, "Bluetooth Low Energy", "Supported" if a.low_energy else "Not supported", a.low_energy)
            kv(5, "BLE central role (scan)", "Supported" if a.central else "Not supported", a.central)
            kv(6, "BLE peripheral role (advertise)", "Supported" if a.peripheral else "Not supported", a.peripheral)
        bat = self.node.battery()
        if bat:
            kv(8, "Battery", f"{bat['percent']:.0f}% {'(charging)' if bat['plugged'] else '(on battery)'}",
               bat["plugged"] or bat["percent"] >= 20)

        clear_layout(self.links_body)

        def link(ok, title, detail):
            r = QHBoxLayout()
            r.setSpacing(10)
            r.addWidget(icon_label("circle-check" if ok else "circle-x", 17, p.success if ok else p.faint))
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(title, "h3"))
            col.addWidget(label(detail, "muted", wrap=True))
            r.addLayout(col, 1)
            w = QWidget()
            w.setLayout(r)
            self.links_body.addWidget(w)

        link(st["lan"], "Local network (TCP)",
             f"Listening on port {st['lan_port']} at {', '.join(st['ips']) or 'no network'}"
             if st["lan"] else (st["lan_error"] or "Disabled in Settings"))
        link(st["rfcomm"], "Bluetooth RFCOMM service",
             f"Published as '{config.RFCOMM_SERVICE_NAME}'" if st["rfcomm"] else (st["rfcomm_error"] or "Not running"))
        link(st["ble_publishing"], "Bluetooth LE advertising",
             "Broadcasting your Blue Cench Chat beacon" if st["ble_publishing"] else
             (st["ble_error"] or ("Hidden (visibility off)" if not st["visible"] else "Not running")))
        link(st["ble_scanning"], "Bluetooth LE scanning",
             "Listening for nearby Blue Cench Chat beacons" if st["ble_scanning"] else (st["ble_error"] or "Not scanning"))

        clear_layout(self.sessions_body)
        if not self.node.connections.sessions:
            self.sessions_body.addWidget(label("No open sessions.", "muted"))
        for uid, s in self.node.connections.sessions.items():
            c = self.node.repo.contact(s.contact_id)
            r = QHBoxLayout()
            r.addWidget(icon_label("lock", 16, p.success))
            r.addWidget(label(c.name if c else uid, "h3"))
            r.addWidget(Pill(self.node.transport_label(s.transport), "cyan"))
            r.addWidget(label(s.session.stream.remote_label, "mono"))
            r.addStretch(1)
            r.addWidget(label(f"since {human_time(s.session.established_at)}  |  "
                              f"{s.session.bytes_sent // 1024} KB out / {s.session.bytes_recv // 1024} KB in", "faint"))
            w = QWidget()
            w.setLayout(r)
            self.sessions_body.addWidget(w)

        clear_layout(self.paired_body)
        if not bluetooth.WINRT_AVAILABLE:
            self.paired_body.addWidget(label(bluetooth.WINRT_IMPORT_ERROR, "warning", wrap=True))
        elif not self._paired:
            self.paired_body.addWidget(label("No paired devices found.", "muted"))
        nex = {d["name"] for d in self._bluecenchchat_paired}
        for d in self._paired:
            r = QHBoxLayout()
            r.addWidget(icon_label("laptop", 16, p.muted))
            r.addWidget(label(d["name"]))
            if d["name"] in nex:
                r.addWidget(Pill("Blue Cench Chat service found", "success"))
            r.addStretch(1)
            w = QWidget()
            w.setLayout(r)
            self.paired_body.addWidget(w)

    def run_test(self) -> None:
        async def go():
            await self.node.refresh_adapter()
            return self.node.status()

        self.bridge.run(go(), self._show_test)

    def _show_test(self, st: dict) -> None:
        p = theme.palette()
        a = st["adapter"]
        checks = []
        win = sys.platform == "win32"
        ver = platform.version()
        checks.append((win, "Windows 10/11", f"{platform.system()} {platform.release()} ({ver})" if win else
                       "Bluetooth features require Windows 10 1803 or later. Local network features work here."))
        checks.append((bluetooth.WINRT_AVAILABLE, "Windows Runtime Bluetooth APIs",
                       "Available" if bluetooth.WINRT_AVAILABLE else bluetooth.WINRT_IMPORT_ERROR))
        checks.append((a.available, "Bluetooth adapter", a.name if a.available else (a.reason or "Not found")))
        if a.available:
            checks.append((a.radio_on, "Bluetooth radio", "On" if a.radio_on else "Turn Bluetooth on in Windows Settings"))
            checks.append((a.classic, "RFCOMM (Bluetooth Classic)",
                           "Supported - chat and file transfer over Bluetooth possible after pairing" if a.classic
                           else "Not supported - use the local network transport"))
            checks.append((a.central, "Discover nearby users (BLE scanning)",
                           "Supported" if a.central else "Not supported by this adapter"))
            checks.append((a.peripheral, "Be discoverable (BLE advertising)",
                           "Supported" if a.peripheral else "This adapter/driver cannot advertise. Others can still "
                           "find you over the network, via paired RFCOMM, or with your identity code."))
        checks.append((st["lan"] and bool(st["ips"]), "Local network transport",
                       f"Ready on {', '.join(st['ips'])}:{st['lan_port']}" if st["lan"] and st["ips"]
                       else "No network adapter connected. Create a Mobile Hotspot on one PC and join it from the "
                            "other for fast offline transfers."))
        checks.append((not st["lan_error"], "Presence beacons (UDP)", st["lan_error"] or "Working"))
        clear_layout(self.test_body)
        passed = sum(1 for c in checks if c[0])
        self.test_body.addWidget(label(f"{passed} of {len(checks)} checks passed", "h3"))
        for ok, title, detail in checks:
            r = QHBoxLayout()
            r.setSpacing(10)
            r.addWidget(icon_label("circle-check" if ok else "triangle-alert", 17, p.success if ok else p.warning))
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(title, "h3"))
            col.addWidget(label(detail, "muted", wrap=True))
            r.addLayout(col, 1)
            w = QWidget()
            w.setLayout(r)
            self.test_body.addWidget(w)
        verdict = ("Full Bluetooth support." if all(c[0] for c in checks[:7]) else
                   "Partial support - Blue Cench Chat will use the transports marked as working.")
        self.test_body.addWidget(label(verdict, "muted", wrap=True))
        self.node.repo.log("system", f"Compatibility test: {passed}/{len(checks)} checks passed")
