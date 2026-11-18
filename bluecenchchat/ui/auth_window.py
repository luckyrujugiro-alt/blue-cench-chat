"""Welcome, sign-in, registration and account recovery screens."""
from __future__ import annotations

import asyncio

from pydantic import ValidationError
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import config
from ..backend import secure_store
from ..backend.authentication import AuthError, AuthService, RegistrationData, password_strength
from ..core import crypto
from . import icons, theme
from .components.widgets import (
    Avatar,
    PasswordField,
    StrengthMeter,
    button,
    fade_in,
    icon_label,
    label,
)


def _err_text(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        msgs = []
        for e in exc.errors():
            m = str(e.get("msg", ""))
            msgs.append(m.removeprefix("Value error, "))
        return msgs[0] if msgs else "Please check the form"
    return str(exc)


class BrandPanel(QFrame):
    def __init__(self) -> None:
        super().__init__()
        p = theme.palette()
        self.setStyleSheet(
            f"BrandPanel {{ background: qradialgradient(cx:0.2, cy:0.15, radius:1.1, fx:0.2, fy:0.15, stop:0 #10306A, "
            f"stop:0.45 #081A40, stop:1 #040A1C); border-right: 1px solid {p.border}; }} "
            f"BrandPanel QLabel {{ color: #E7EEF9; background: transparent; }}"
        )
        self.setMinimumWidth(400)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(44, 44, 44, 40)
        lay.setSpacing(14)
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QGraphicsDropShadowEffect

        logo = QLabel()
        logo.setPixmap(QPixmap(str(config.resource_path("assets", "logo", "bluecenchchat.png"))).scaled(
            72, 72, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        glow = QGraphicsDropShadowEffect(logo)  # neon glow, like the brand artwork
        glow.setBlurRadius(46)
        glow.setOffset(0, 0)
        glow.setColor(QColor(30, 139, 255, 210))
        logo.setGraphicsEffect(glow)
        lay.addWidget(logo)
        lay.addSpacing(12)
        name = QLabel('<span style="color:#FFFFFF">Blue </span><span style="color:#2E9BFF">Cench</span>')
        name.setTextFormat(Qt.TextFormat.RichText)
        name.setStyleSheet(f"font-size:{theme.px(38)}px; font-weight:800;")
        lay.addWidget(name)
        chat = label("C h a t")
        chat.setStyleSheet(f"font-size:{theme.px(18)}px; color:#B9C6E0; font-weight:500; letter-spacing:4px;")
        lay.addWidget(chat)
        tag = label(config.APP_TAGLINE)
        tag.setStyleSheet(f"font-size:{theme.px(15)}px; color:#22D3EE; font-weight:600;")
        lay.addWidget(tag)
        lay.addSpacing(20)
        for ic, title, text in (
            ("bluetooth", "Bluetooth, Wi-Fi & online", "Chat nearby with no internet, or with anyone, anywhere."),
            ("lock", "End-to-end encryption", "Curve25519 keys and ChaCha20-Poly1305 on every message and call."),
            ("radio", "Extended range", "Messages hop through friends nearby to reach people out of range."),
            ("mic", "Voice messages & calls", "Voice over Bluetooth or Wi-Fi. Video calls on the same Wi-Fi."),
            ("star", "Favorites & mentions", "Pin the people who matter. @mention someone to get their attention."),
            ("shield-check", "Password protection", "Argon2id-protected account. Your keys never leave your device."),
        ):
            row = QHBoxLayout()
            row.setSpacing(14)
            chip = QLabel()
            chip.setFixedSize(38, 38)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setStyleSheet("background: rgba(30,139,255,0.16); border: 1px solid rgba(46,155,255,0.35);"
                               " border-radius: 11px;")
            chip.setPixmap(icons.pixmap(ic, 19, "#4DB2FF"))
            row.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(1)
            t = label(title)
            t.setStyleSheet(f"font-weight:700; font-size:{theme.px(14)}px;")
            d = label(text, wrap=True)
            d.setStyleSheet("color:#8EA3C8;")
            col.addWidget(t)
            col.addWidget(d)
            row.addLayout(col, 1)
            lay.addLayout(row)
            lay.addSpacing(2)
        lay.addStretch(1)
        ver = label(f"Version {config.APP_VERSION}" + (f"  |  Development profile: {config.profile()}"
                                                        if config.profile() else ""))
        ver.setStyleSheet("color:#5E6B86;")
        lay.addWidget(ver)


class FormPage(QWidget):
    def __init__(self, title: str, subtitle: str = "") -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        box = QWidget()
        box.setMaximumWidth(420)
        self.form = QVBoxLayout(box)
        self.form.setSpacing(10)
        self.form.setContentsMargins(0, 0, 0, 0)
        h = label(title, "h1")
        self.form.addWidget(h)
        if subtitle:
            self.form.addWidget(label(subtitle, "muted", wrap=True))
        self.form.addSpacing(12)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(box, 10)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.error = label("", "error", wrap=True)
        self.error.hide()

    def field(self, caption: str, widget: QWidget) -> QWidget:
        lb = label(caption, "muted")
        lb.setBuddy(widget)
        self.form.addWidget(lb)
        self.form.addWidget(widget)
        return widget

    def show_error(self, text: str) -> None:
        self.error.setText(text)
        self.error.setVisible(bool(text))


class AuthWindow(QWidget):
    authenticated = Signal(int, object, bool, bool)  # account_id, Identity, is_guest, remember

    def __init__(self, auth: AuthService) -> None:
        super().__init__()
        self.auth = auth
        self.setObjectName("AuthRoot")
        self.setWindowTitle("Blue Cench Chat")
        self.setWindowIcon(icons.QIcon(str(config.resource_path("assets", "logo", "bluecenchchat.png"))))
        self.resize(1080, 720)
        self.setMinimumSize(900, 640)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(BrandPanel(), 4)
        self.stack = QStackedWidget()
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(40, 30, 40, 30)
        rl.addWidget(self.stack)
        root.addWidget(right, 5)
        self.on_user_close = None
        self._closing_after_login = False
        self._avatar_bytes: bytes | None = None
        self._pending_rk: tuple | None = None
        self._build_welcome()
        self._build_signin()
        self._build_register()
        self._build_recovery_key()
        self._build_forgot()
        accounts = self.auth.list_accounts()
        self.go(self.signin if accounts else self.welcome)
        if accounts:
            self.si_login.setText(accounts[0].username)
            self.si_password.setFocus()

    def closeEvent(self, e) -> None:
        if self.on_user_close and not self._closing_after_login:
            self.on_user_close()
        super().closeEvent(e)

    def go(self, page: QWidget) -> None:
        self.stack.setCurrentWidget(page)
        fade_in(page, 160)

    def _busy(self, btn: QPushButton, busy: bool, text: str) -> None:
        btn.setEnabled(not busy)
        btn.setText("Please wait..." if busy else text)

    # ----------------------------------------------------------------- welcome
    def _build_welcome(self) -> None:
        pg = FormPage("Welcome to Blue Cench Chat", "Chat nearby over Bluetooth and Wi-Fi with no internet - or with anyone, anywhere online.")
        b1 = button("Sign in", "log-in", "primary")
        b2 = button("Create account", "user-plus")
        b3 = button("Continue as guest", "user-round", "ghost",
                    tooltip="A temporary identity that is erased when you sign out")
        for b in (b1, b2, b3):
            b.setMinimumHeight(42)
            pg.form.addWidget(b)
        note = label("Guest sessions get a fresh identity that is deleted when you sign out. "
                     "Contacts, messages and history are not kept.", "faint", wrap=True)
        pg.form.addWidget(note)
        b1.clicked.connect(lambda: self.go(self.signin))
        b2.clicked.connect(lambda: self.go(self.register))
        b3.clicked.connect(self._guest)
        self.welcome = pg
        self.stack.addWidget(pg)

    def _guest(self) -> None:
        async def go():
            return await asyncio.to_thread(self.auth.create_guest)

        def done(res):
            acc, ident = res
            self.authenticated.emit(acc.id, ident, True, False)

        asyncio.ensure_future(go()).add_done_callback(lambda t: done(t.result()) if not t.exception() else None)

    # ----------------------------------------------------------------- sign in
    def _build_signin(self) -> None:
        pg = FormPage("Sign in", "Use the username or email you registered on this computer.")
        self.si_login = pg.field("Username or email", QLineEdit())
        self.si_password = pg.field("Password", PasswordField())
        self.si_remember = QCheckBox("Keep me signed in on this PC")
        self.si_remember.setToolTip("Protected with Windows DPAPI - only your Windows account can read it")
        self.si_remember.setVisible(secure_store.available())
        pg.form.addWidget(self.si_remember)
        pg.form.addWidget(pg.error)
        self.si_btn = button("Sign in", "log-in", "primary")
        self.si_btn.setMinimumHeight(42)
        pg.form.addWidget(self.si_btn)
        links = QHBoxLayout()
        forgot = button("Forgot password?", variant="link")
        create = button("Create an account", variant="link")
        links.addWidget(forgot)
        links.addStretch(1)
        links.addWidget(create)
        pg.form.addLayout(links)
        back = button("Back", "chevron-left", "ghost")
        pg.form.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        forgot.clicked.connect(lambda: self.go(self.forgot))
        create.clicked.connect(lambda: self.go(self.register))
        back.clicked.connect(lambda: self.go(self.welcome))
        self.si_btn.clicked.connect(self._signin)
        self.si_password.returnPressed.connect(self._signin)
        self.si_login.returnPressed.connect(self.si_password.setFocus)
        self.signin = pg
        self.stack.addWidget(pg)

    def _signin(self) -> None:
        login, pw = self.si_login.text(), self.si_password.text()
        if not login or not pw:
            self.signin.show_error("Enter your username and password")
            return
        self.signin.show_error("")
        self._busy(self.si_btn, True, "Sign in")

        def finish(t: asyncio.Task):
            self._busy(self.si_btn, False, "Sign in")
            if t.exception():
                self.signin.show_error(_err_text(t.exception()))
                self.si_password.selectAll()
                return
            acc, ident = t.result()
            self.last_password = pw  # handed to the online service once, never stored
            self.si_password.clear()
            self.authenticated.emit(acc.id, ident, False, self.si_remember.isChecked())

        asyncio.ensure_future(asyncio.to_thread(self.auth.login, login, pw)).add_done_callback(finish)

    # ----------------------------------------------------------------- register
    def _build_register(self) -> None:
        pg = FormPage("Create your account", "Your account and encryption keys are created and stored on this PC.")
        top = QHBoxLayout()
        self.rg_avatar = Avatar(64).set("?")
        pick = button("Add profile picture", "camera")
        pick.clicked.connect(self._pick_avatar)
        top.addWidget(self.rg_avatar)
        top.addSpacing(8)
        top.addWidget(pick)
        top.addStretch(1)
        pg.form.addLayout(top)
        self.rg_name = pg.field("Full name", QLineEdit())
        row = QHBoxLayout()
        self.rg_user = QLineEdit()
        self.rg_user.setPlaceholderText("letters, numbers, _ .")
        self.rg_phone = QLineEdit()
        self.rg_phone.setPlaceholderText("Optional")
        for cap, w in (("Username", self.rg_user), ("Phone", self.rg_phone)):
            col = QVBoxLayout()
            col.setSpacing(6)
            col.addWidget(label(cap, "muted"))
            col.addWidget(w)
            row.addLayout(col)
        pg.form.addLayout(row)
        self.rg_email = pg.field("Email", QLineEdit())
        self.rg_pw = pg.field("Password", PasswordField("At least 8 characters, a letter and a number"))
        self.rg_meter = StrengthMeter()
        pg.form.addWidget(self.rg_meter)
        self.rg_pw2 = pg.field("Confirm password", PasswordField("Repeat password"))
        pg.form.addWidget(pg.error)
        self.rg_btn = button("Create account", "user-plus", "primary")
        self.rg_btn.setMinimumHeight(42)
        pg.form.addWidget(self.rg_btn)
        back = button("I already have an account", variant="link")
        pg.form.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        back.clicked.connect(lambda: self.go(self.signin))
        self.rg_pw.textChanged.connect(lambda t: self.rg_meter.set_score(password_strength(t)))
        self.rg_name.textChanged.connect(lambda t: self._avatar_bytes is None and self.rg_avatar.set(t or "?"))
        self.rg_btn.clicked.connect(self._register)
        self.register = pg
        self.stack.addWidget(pg)

    def _pick_avatar(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose profile picture", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if not path:
            return
        from ..backend.authentication import shrink_avatar

        try:
            with open(path, "rb") as fh:
                self._avatar_bytes = shrink_avatar(fh.read(20_000_000))
            self.rg_avatar.set(self.rg_name.text(), self._avatar_bytes)
        except (OSError, AuthError) as exc:
            self.register.show_error(f"Could not use that picture: {exc}")

    def _register(self) -> None:
        try:
            data = RegistrationData(
                full_name=self.rg_name.text(), username=self.rg_user.text(), email=self.rg_email.text(),
                password=self.rg_pw.text(), confirm_password=self.rg_pw2.text(), phone=self.rg_phone.text(),
                avatar=self._avatar_bytes,
            )
        except ValidationError as exc:
            self.register.show_error(_err_text(exc))
            return
        self.register.show_error("")
        self._busy(self.rg_btn, True, "Create account")

        def finish(t: asyncio.Task):
            self._busy(self.rg_btn, False, "Create account")
            if t.exception():
                self.register.show_error(_err_text(t.exception()))
                return
            acc, rk, ident = t.result()
            self.rg_pw.clear()
            self.rg_pw2.clear()
            self._pending_rk = (acc.id, ident)
            self.last_password = data.password
            self.rk_value.setText(rk)
            self.rk_uid.setText(acc.user_id)
            self.rk_ack.setChecked(False)
            self.go(self.rk_page)

        asyncio.ensure_future(asyncio.to_thread(self.auth.register, data)).add_done_callback(finish)

    # ----------------------------------------------------------------- recovery key
    def _build_recovery_key(self) -> None:
        pg = FormPage("Save your recovery key",
                      "Blue Cench Chat has no server that can reset your password. This key is the only way to "
                      "recover your account if you forget it. Store it somewhere safe - it is shown only once.")
        box = QFrame()
        box.setObjectName("Hero")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(18, 16, 18, 16)
        bl.addWidget(label("RECOVERY KEY", "eyebrow"))
        self.rk_value = label("", "safety", selectable=True)
        bl.addWidget(self.rk_value)
        bl.addWidget(label("YOUR Blue Cench Chat ID", "eyebrow"))
        self.rk_uid = label("", "mono", selectable=True)
        bl.addWidget(self.rk_uid)
        pg.form.addWidget(box)
        copy = button("Copy recovery key", "copy")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.rk_value.text()))
        pg.form.addWidget(copy, 0, Qt.AlignmentFlag.AlignLeft)
        self.rk_ack = QCheckBox("I have stored my recovery key safely")
        pg.form.addWidget(self.rk_ack)
        go = button("Continue to Blue Cench Chat", "chevron-right", "primary")
        go.setMinimumHeight(42)
        go.setEnabled(False)
        self.rk_ack.toggled.connect(go.setEnabled)

        def proceed():
            if self._pending_rk:
                aid, ident = self._pending_rk
                self._pending_rk = None
                self.rk_value.clear()
                self.authenticated.emit(aid, ident, False, False)

        go.clicked.connect(proceed)
        pg.form.addWidget(go)
        self.rk_page = pg
        self.stack.addWidget(pg)

    # ----------------------------------------------------------------- forgot
    def _build_forgot(self) -> None:
        pg = FormPage("Reset your password",
                      "Enter the recovery key you saved when you created the account. Your identity, contacts "
                      "and messages are kept; you will receive a new recovery key.")
        self.fg_login = pg.field("Username or email", QLineEdit())
        self.fg_key = pg.field("Recovery key", QLineEdit())
        self.fg_key.setPlaceholderText("XXXX-XXXX-XXXX-XXXX-XXXX")
        self.fg_pw = pg.field("New password", PasswordField())
        self.fg_pw2 = pg.field("Confirm new password", PasswordField())
        pg.form.addWidget(pg.error)
        self.fg_btn = button("Reset password", "key-round", "primary")
        self.fg_btn.setMinimumHeight(42)
        pg.form.addWidget(self.fg_btn)
        back = button("Back to sign in", "chevron-left", "ghost")
        pg.form.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)
        back.clicked.connect(lambda: self.go(self.signin))
        self.fg_btn.clicked.connect(self._forgot)
        self.forgot = pg
        self.stack.addWidget(pg)

    def _forgot(self) -> None:
        if self.fg_pw.text() != self.fg_pw2.text():
            self.forgot.show_error("Passwords do not match")
            return
        self._busy(self.fg_btn, True, "Reset password")
        login, key, pw = self.fg_login.text(), self.fg_key.text(), self.fg_pw.text()

        async def work():
            new_rk = await asyncio.to_thread(self.auth.recover, login, key, pw)
            acc, ident = await asyncio.to_thread(self.auth.login, login, pw)
            return new_rk, acc, ident

        def finish(t: asyncio.Task):
            self._busy(self.fg_btn, False, "Reset password")
            if t.exception():
                self.forgot.show_error(_err_text(t.exception()))
                return
            new_rk, acc, ident = t.result()
            for w in (self.fg_key, self.fg_pw, self.fg_pw2):
                w.clear()
            self._pending_rk = (acc.id, ident)
            self.last_password = ""
            self.rk_value.setText(new_rk)
            self.rk_uid.setText(acc.user_id)
            self.rk_ack.setChecked(False)
            self.go(self.rk_page)

        asyncio.ensure_future(work()).add_done_callback(finish)
