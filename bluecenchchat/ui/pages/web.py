"""Phones & Tablets: turn on the Wi-Fi companion, pair devices, manage them."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .. import theme
from ..components.widgets import (
    Card,
    Page,
    Pill,
    SettingRow,
    Toggle,
    button,
    clear_layout,
    human_time,
    icon_label,
    label,
)
from ..dialogs.common import confirm, qr_pixmap


class WebPage(Page):
    def __init__(self, win) -> None:
        super().__init__("Phones & Tablets", "Use Blue Cench Chat on your phone, iPad or smartwatch browser over the same "
                         "Wi-Fi or this PC's Mobile Hotspot. No app store, no internet.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        p = theme.palette()
        top = QHBoxLayout()
        top.setSpacing(14)

        left = Card("Wi-Fi access", "wifi")
        self.toggle = Toggle(bool(self.node.settings.get("web_enabled")))
        self.toggle.toggled.connect(lambda v: self.node.update_settings(web_enabled=v))
        left.add(SettingRow("Allow phones and tablets", "Starts a secure (HTTPS) Blue Cench Chat page on this PC. Only "
                            "devices you pair with a code shown here can use it.", self.toggle))
        self.state = label("", "muted", wrap=True)
        left.add(self.state)
        left.add(label("ADDRESS TO OPEN ON THE PHONE", "eyebrow"))
        self.urls = label("", "mono", selectable=True, wrap=True)
        left.add(self.urls)
        copy = button("Copy address", "copy")
        copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(self.urls.text().split("\n")[0]),
                                      win.toast("Address copied")))
        left.add(copy)
        left.add(label("PAIRING CODE", "eyebrow"))
        self.code = label("", "safety")
        left.add(self.code)
        self.code_left = label("", "faint")
        left.add(self.code_left)
        left.add(label("CERTIFICATE FINGERPRINT", "eyebrow"))
        self.fp = label("", "mono", selectable=True, wrap=True)
        left.add(self.fp)
        left.body.addStretch(1)
        top.addWidget(left, 3)

        right = Card("Scan to pair", "qr-code")
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setMinimumSize(250, 250)
        right.add(self.qr)
        right.add(label("Point the phone's camera at the code. It opens Blue Cench Chat and pairs automatically. "
                        "Each code works once.", "muted", wrap=True))
        right.body.addStretch(1)
        top.addWidget(right, 2)
        self.content.addLayout(top)

        how = Card("How to connect", "smartphone")
        for i, text in enumerate((
            "Put the phone, iPad or watch on the same Wi-Fi as this PC - or turn on Mobile hotspot on this PC "
            "and join it from the phone (works with no internet).",
            "Scan the QR code, or open the address above in Safari / Chrome and type the pairing code.",
            "The browser warns that the connection is 'not private' because the certificate was made by this PC, "
            "not an internet company. Check the fingerprint if you like, then choose Advanced / Show details > "
            "Proceed (iPhone: 'visit this website').",
            "Add the page to the home screen (Share > Add to Home Screen, or Chrome menu > Install app) to open "
            "Blue Cench Chat like an app.",
        ), 1):
            row = QHBoxLayout()
            row.addWidget(Pill(str(i), "primary"), 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label(text, "muted", wrap=True), 1)
            how.add(row)
        how.add(label("Android: install the Blue Cench Chat app (BlueCenchChat-1.0.0.apk from the GitHub release). "
                      "It finds this PC on the Wi-Fi by itself and checks its certificate automatically - no address, "
                      "QR code or warning page. iPhone/iPad: use the QR code once, then Add to Home Screen.",
                      "muted", wrap=True))
        how.add(label("Bluetooth always stays on this PC: phone browsers - and all iPhone/iPad browsers - cannot use "
                      "Bluetooth for apps like this. The phone is a secure remote screen for your PC's Blue Cench Chat.",
                      "faint", wrap=True))
        self.content.addWidget(how)

        self.dev_card = Card("Paired devices", "monitor")
        self.dev_list = QVBoxLayout()
        self.dev_card.add(self.dev_list)
        self.content.addWidget(self.dev_card)
        self.content.addStretch(1)

        self.bridge.web_changed.connect(self.refresh)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)
        self._last_code = ""
        self.refresh()

    def on_show(self) -> None:
        self.toggle.setChecked(bool(self.node.settings.get("web_enabled")))
        self.refresh()

    def _tick(self) -> None:
        if self.isVisible() and self.node.web.running:
            code = self.node.web.current_code()
            if code != self._last_code:
                self.refresh()
            else:
                self.code_left.setText(f"New code in {self.node.web.code_expires_in()} s")

    def refresh(self) -> None:
        web, p = self.node.web, theme.palette()
        if web.running:
            urls = web.urls()
            self.state.setText(f"Running on port {web.port}. Phones on the same network can open Blue Cench Chat now.")
            self.state.setProperty("role", "success")
            self.urls.setText("\n".join(urls) or "This PC is not on a network. Join Wi-Fi or turn on Mobile hotspot.")
            code = web.current_code()
            self._last_code = code
            self.code.setText(f"{code[:3]} {code[3:]}")
            self.code_left.setText(f"New code in {web.code_expires_in()} s")
            self.fp.setText(web.fingerprint or "-")
            url = web.pairing_url()
            if url.startswith("http"):
                self.qr.setPixmap(qr_pixmap(url, 240))
                self.qr.setStyleSheet("background:white; border-radius:12px; padding:8px;")
            else:
                self.qr.clear()
                self.qr.setText("No network")
        else:
            self.state.setText(web.error or "Off. Turn it on to use Blue Cench Chat from your phone or tablet.")
            self.state.setProperty("role", "warning" if web.error else "muted")
            self.urls.setText("-")
            self.code.setText("--- ---")
            self.code_left.setText("")
            self.fp.setText("-")
            self.qr.clear()
            self.qr.setStyleSheet("")
            self.qr.setText("Turn on Wi-Fi access to show the code")
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)
        clear_layout(self.dev_list)
        devices = web.devices()
        if not devices:
            self.dev_list.addWidget(label("No devices paired yet.", "muted"))
        for d in devices:
            row = QHBoxLayout()
            ua = d.user_agent.lower()
            ic = "smartphone" if any(k in ua for k in ("iphone", "android", "mobile")) else "monitor"
            row.addWidget(icon_label(ic, 18, p.cyan))
            col = QVBoxLayout()
            col.setSpacing(1)
            nm = label(d.name, "h3")
            nm.setTextFormat(Qt.TextFormat.PlainText)
            col.addWidget(nm)
            col.addWidget(label(f"Last used {human_time(d.last_seen)} from {d.last_ip or '?'}  |  paired "
                                f"{human_time(d.created_at)}", "faint"))
            row.addLayout(col, 1)
            rm = button("Remove", "trash-2", "ghost")
            rm.clicked.connect(lambda _=False, d=d: confirm(self.win, f"Remove {d.name}?", "It will be signed out "
                               "immediately and must be paired again.", "Remove", True) and web.revoke(d.id))
            row.addWidget(rm)
            w = QWidget()
            w.setLayout(row)
            self.dev_list.addWidget(w)
