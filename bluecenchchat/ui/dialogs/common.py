"""Dialogs: identity QR card, connect-by-code, safety-number verification,
confirmation prompts and the first-run onboarding tour."""
from __future__ import annotations

import io

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import icons, theme
from ..components.widgets import Avatar, button, icon_label, label


class BaseDialog(QDialog):
    def __init__(self, parent, title: str, width: int = 480) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(26, 24, 26, 22)
        self.lay.setSpacing(12)
        self.lay.addWidget(label(title, "h2"))


def qr_pixmap(text: str, size: int = 240) -> QPixmap:
    import qrcode

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0A1020", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qi = QImage.fromData(buf.getvalue())
    return QPixmap.fromImage(qi).scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.FastTransformation)


class IdentityDialog(BaseDialog):
    """Shows this user's QR identity card and copyable identity code."""

    def __init__(self, parent, node) -> None:
        super().__init__(parent, "My Blue Cench Chat identity", 520)
        acc = node.repo.account()
        code = node.identity_code()
        head = QHBoxLayout()
        head.addWidget(Avatar(52).set(acc.display_name, acc.avatar, seed=acc.user_id))
        col = QVBoxLayout()
        col.addWidget(label(acc.display_name, "h3"))
        col.addWidget(label(f"@{acc.username}  |  {acc.user_id}", "muted"))
        head.addLayout(col, 1)
        self.lay.addLayout(head)
        qr = QLabel()
        qr.setPixmap(qr_pixmap(code))
        qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr.setStyleSheet("background:white; border-radius:12px; padding:10px;")
        self.lay.addWidget(qr, 0, Qt.AlignmentFlag.AlignHCenter)
        self.lay.addWidget(label(
            "Share this code with someone next to you (in person or by a channel you trust). When they connect "
            "with it, Blue Cench Chat checks that your device presents exactly this identity key, so the contact is "
            "marked as verified. The code also carries your local network address for a direct connection.",
            "muted", wrap=True))
        box = QPlainTextEdit(code)
        box.setReadOnly(True)
        box.setMaximumHeight(70)
        self.lay.addWidget(box)
        row = QHBoxLayout()
        cp = button("Copy identity code", "copy", "primary")
        cp.clicked.connect(lambda: (QGuiApplication.clipboard().setText(code), cp.setText("Copied")))
        close = button("Close")
        close.clicked.connect(self.accept)
        row.addWidget(cp)
        row.addStretch(1)
        row.addWidget(close)
        self.lay.addLayout(row)


class ConnectDialog(BaseDialog):
    """Connect with a pasted identity code or a manual IP:port."""

    def __init__(self, parent) -> None:
        super().__init__(parent, "Connect to a device", 520)
        self.result_kind = None
        self.value = None
        tabs = QTabWidget()
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        l1.setContentsMargins(0, 12, 0, 0)
        l1.addWidget(label("Paste the identity code from the other person's My Identity screen. "
                           "This is the most secure way to connect: the contact is verified automatically.",
                           "muted", wrap=True))
        self.code = QPlainTextEdit()
        self.code.setPlaceholderText("bluecenchchat:...")
        self.code.setMaximumHeight(90)
        l1.addWidget(self.code)
        tabs.addTab(w1, "Identity code")
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        l2.setContentsMargins(0, 12, 0, 0)
        l2.addWidget(label("Use this when both PCs are on the same network but broadcasts are blocked "
                           "(some office or hotel Wi-Fi). The other PC shows its address on Bluetooth Devices "
                           "> Diagnostics.", "muted", wrap=True))
        self.addr = QLineEdit()
        self.addr.setPlaceholderText("192.168.1.20:51234")
        l2.addWidget(self.addr)
        tabs.addTab(w2, "Network address")
        self.tabs = tabs
        self.lay.addWidget(tabs)
        self.err = label("", "error", wrap=True)
        self.lay.addWidget(self.err)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("Cancel")
        ok = button("Connect", "link", "primary")
        row.addWidget(cancel)
        row.addWidget(ok)
        self.lay.addLayout(row)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self._ok)

    def _ok(self) -> None:
        if self.tabs.currentIndex() == 0:
            code = self.code.toPlainText().strip()
            if not code.startswith("bluecenchchat:"):
                self.err.setText("That is not a Blue Cench Chat identity code")
                return
            self.result_kind, self.value = "code", code
        else:
            txt = self.addr.text().strip()
            host, _, port = txt.rpartition(":")
            if not host or not port.isdigit() or not 0 < int(port) < 65536:
                self.err.setText("Enter an address like 192.168.1.20:51234")
                return
            self.result_kind, self.value = "addr", (host, int(port))
        self.accept()


class VerifyDialog(BaseDialog):
    def __init__(self, parent, node, contact) -> None:
        super().__init__(parent, f"Verify {contact.name}", 500)
        self.node, self.contact = node, contact
        p = theme.palette()
        self.lay.addWidget(label(
            "Meet in person (or call) and compare this safety number with the one shown on the other device. "
            "If they match exactly, nobody is intercepting your connection.", "muted", wrap=True))
        box = QFrame()
        box.setObjectName("Hero")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(18, 18, 18, 18)
        bl.addWidget(label("SAFETY NUMBER", "eyebrow"))
        num = label(node.safety_number(contact.id), "safety", selectable=True)
        bl.addWidget(num)
        bl.addWidget(label(f"Their ID: {contact.peer_user_id}", "mono"))
        bl.addWidget(label(f"Your ID:  {node.identity.user_id}", "mono"))
        self.lay.addWidget(box)
        state = QHBoxLayout()
        if contact.verified:
            state.addWidget(icon_label("badge-check", 18, p.success))
            state.addWidget(label("You have verified this contact.", "success"))
        else:
            state.addWidget(icon_label("shield-alert", 18, p.warning))
            state.addWidget(label("Not verified yet.", "warning"))
        state.addStretch(1)
        self.lay.addLayout(state)
        row = QHBoxLayout()
        self.toggled = False
        if contact.verified:
            b = button("Remove verification", "x")
        else:
            b = button("Numbers match - mark verified", "badge-check", "primary")
        b.clicked.connect(self._toggle)
        close = button("Close")
        close.clicked.connect(self.reject)
        row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        self.lay.addLayout(row)

    def _toggle(self) -> None:
        self.node.repo.set_contact(self.contact.id, verified=not self.contact.verified)
        self.node.repo.log("security", f"{'Removed verification for' if self.contact.verified else 'Verified'} "
                                       f"{self.contact.name} ({self.contact.peer_user_id})")
        self.node.bus.emit("contacts")
        self.accept()


def confirm(parent, title: str, text: str, ok_text: str = "Confirm", danger: bool = False) -> bool:
    d = BaseDialog(parent, title, 440)
    d.lay.addWidget(label(text, "muted", wrap=True))
    row = QHBoxLayout()
    row.addStretch(1)
    c = button("Cancel")
    o = button(ok_text, variant="danger" if danger else "primary")
    c.clicked.connect(d.reject)
    o.clicked.connect(d.accept)
    row.addWidget(c)
    row.addWidget(o)
    d.lay.addLayout(row)
    return d.exec() == QDialog.DialogCode.Accepted


def ask_text(parent, title: str, text: str, placeholder: str = "", password: bool = False) -> str | None:
    d = BaseDialog(parent, title, 440)
    d.lay.addWidget(label(text, "muted", wrap=True))
    edit = QLineEdit()
    edit.setPlaceholderText(placeholder)
    if password:
        edit.setEchoMode(QLineEdit.EchoMode.Password)
    d.lay.addWidget(edit)
    row = QHBoxLayout()
    row.addStretch(1)
    c = button("Cancel")
    o = button("OK", variant="primary")
    c.clicked.connect(d.reject)
    o.clicked.connect(d.accept)
    edit.returnPressed.connect(d.accept)
    row.addWidget(c)
    row.addWidget(o)
    d.lay.addLayout(row)
    return edit.text() if d.exec() == QDialog.DialogCode.Accepted else None


def show_secret(parent, title: str, text: str, secret: str) -> None:
    d = BaseDialog(parent, title, 480)
    d.lay.addWidget(label(text, "muted", wrap=True))
    d.lay.addWidget(label(secret, "safety", selectable=True))
    row = QHBoxLayout()
    cp = button("Copy", "copy")
    cp.clicked.connect(lambda: QGuiApplication.clipboard().setText(secret))
    ok = button("I have saved it", variant="primary")
    ok.clicked.connect(d.accept)
    row.addWidget(cp)
    row.addStretch(1)
    row.addWidget(ok)
    d.lay.addLayout(row)
    d.exec()


ONBOARDING = [
    ("radar", "Find people nearby",
     "Open Discover People and press Start scanning. Blue Cench Chat finds other Blue Cench Chat users through Bluetooth LE "
     "advertisements and presence beacons on your local network."),
    ("user-plus", "Connect with consent",
     "Send a connection request. Nothing is trusted automatically - the other person must accept before "
     "you can chat or share files."),
    ("badge-check", "Verify who you talk to",
     "Compare the 12-digit safety number in person, or connect with an identity code, to rule out "
     "impostors. Verified contacts get a green badge."),
    ("arrow-left-right", "Pick the right link",
     "Bluetooth RFCOMM works without any network but is slow (about 0.1-0.2 MB/s). For large files, put both "
     "PCs on the same Wi-Fi or a Windows Mobile Hotspot - no internet needed - and Blue Cench Chat uses the fast local "
     "network link automatically. The transport in use is always shown."),
]


class OnboardingDialog(QDialog):
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.setWindowTitle("Welcome to Blue Cench Chat")
        self.setFixedSize(560, 420)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(30, 28, 30, 24)
        self.stack = QStackedWidget()
        p = theme.palette()
        for i, (ic, title, text) in enumerate(ONBOARDING):
            w = QWidget()
            wl = QVBoxLayout(w)
            wl.setSpacing(12)
            chip = QLabel()
            chip.setFixedSize(72, 72)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setStyleSheet(f"background:{p.primary_soft}; border-radius:20px;")
            chip.setPixmap(icons.pixmap(ic, 34, p.primary_hover))
            wl.addWidget(chip)
            wl.addWidget(label(f"STEP {i + 1} OF {len(ONBOARDING)}", "eyebrow"))
            wl.addWidget(label(title, "h1"))
            wl.addWidget(label(text, "muted", wrap=True))
            wl.addStretch(1)
            self.stack.addWidget(w)
        lay.addWidget(self.stack, 1)
        row = QHBoxLayout()
        self.skip = button("Skip tour", variant="ghost")
        self.back = button("Back", "chevron-left")
        self.next = button("Next", "chevron-right", "primary")
        row.addWidget(self.skip)
        row.addStretch(1)
        row.addWidget(self.back)
        row.addWidget(self.next)
        lay.addLayout(row)
        self.skip.clicked.connect(self.accept)
        self.back.clicked.connect(lambda: self._go(-1))
        self.next.clicked.connect(lambda: self._go(1))
        self._go(0)

    def _go(self, d: int) -> None:
        i = self.stack.currentIndex() + d
        if i >= self.stack.count():
            self.accept()
            return
        self.stack.setCurrentIndex(max(0, i))
        self.back.setEnabled(self.stack.currentIndex() > 0)
        self.next.setText("Get started" if self.stack.currentIndex() == self.stack.count() - 1 else "Next")
