"""Notifications, My Profile, Security & Privacy, Settings and Help pages."""
from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ... import config
from ...backend import backup, secure_store
from ...backend.authentication import EMAIL_RE, PHONE_RE, USERNAME_RE, AuthError, AuthService, shrink_avatar
from .. import system, theme
from ..components.widgets import (
    Avatar,
    Card,
    EmptyState,
    Page,
    Pill,
    SettingRow,
    Toggle,
    button,
    clear_layout,
    divider,
    human_time,
    icon_label,
    label,
)
from ..dialogs.common import IdentityDialog, VerifyDialog, ask_text, confirm, qr_pixmap, show_secret

NOTIF_ICONS = {"request": ("user-plus", "primary"), "accepted": ("user-check", "success"),
               "rejected": ("user-x", "faint"), "message": ("message-square", "primary"),
               "file_offer": ("download", "cyan"), "transfer_done": ("circle-check", "success"),
               "transfer_failed": ("circle-alert", "danger"), "disconnect": ("unlink", "warning"),
               "security": ("shield-alert", "danger")}


# --------------------------------------------------------------------------- notifications
class NotificationsPage(Page):
    def __init__(self, win) -> None:
        super().__init__("Notifications", "Connection requests, incoming files, completed transfers and "
                         "security alerts.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        mr = button("Mark all read", "check-check")
        cl = button("Clear all", "trash-2", "ghost")
        mr.clicked.connect(self._mark)
        cl.clicked.connect(self._clear)
        self.actions.addWidget(mr)
        self.actions.addWidget(cl)
        self.list = QVBoxLayout()
        self.list.setSpacing(8)
        self.content.addLayout(self.list)
        self.content.addStretch(1)
        self.bridge.notification_added.connect(lambda: self.isVisible() and self.refresh())
        self.refresh()

    def on_show(self) -> None:
        self.refresh()
        QTimer.singleShot(1500, self._mark)

    def _mark(self) -> None:
        self.node.repo.mark_notifications_read()
        self.win.update_badges()

    def _clear(self) -> None:
        self.node.repo.clear_notifications()
        self.refresh()
        self.win.update_badges()

    def _go(self, n) -> None:
        if n.kind in ("request", "accepted", "rejected"):
            self.win.navigate("connections")
            if n.kind == "request":
                self.win.pages["connections"].show_requests()
        elif n.kind == "message" and n.ref.isdigit():
            self.win.open_chat(int(n.ref))
        elif n.kind in ("file_offer", "transfer_done", "transfer_failed"):
            self.win.navigate("transfers" if n.kind == "file_offer" else "history")
        elif n.kind == "security":
            self.win.navigate("security")

    def refresh(self) -> None:
        p = theme.palette()
        clear_layout(self.list)
        items = self.node.repo.notifications()
        if not items:
            self.list.addWidget(EmptyState("bell", "You're all caught up", "New notifications will appear here."))
            return
        for n in items:
            card = QFrame()
            card.setObjectName("Card" if not n.read else "SoftCard")
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            r = QHBoxLayout(card)
            r.setContentsMargins(16, 12, 16, 12)
            r.setSpacing(14)
            ic, tone = NOTIF_ICONS.get(n.kind, ("bell", "muted"))
            color = getattr(p, tone if tone != "primary" else "primary_hover", p.muted)
            chip = QLabel()
            chip.setFixedSize(36, 36)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setStyleSheet(f"background:{p.surface3}; border-radius:10px;")
            from .. import icons
            chip.setPixmap(icons.pixmap(ic, 18, color))
            r.addWidget(chip)
            col = QVBoxLayout()
            col.setSpacing(2)
            t = label(n.title, "h3")
            t.setTextFormat(Qt.TextFormat.PlainText)
            col.addWidget(t)
            if n.body:
                b = label(n.body, "muted", wrap=True)
                b.setTextFormat(Qt.TextFormat.PlainText)
                col.addWidget(b)
            r.addLayout(col, 1)
            r.addWidget(label(human_time(n.ts), "faint"), 0, Qt.AlignmentFlag.AlignTop)
            if not n.read:
                r.addWidget(Pill("New", "primary"), 0, Qt.AlignmentFlag.AlignTop)
            card.mousePressEvent = lambda _e, n=n: self._go(n)
            self.list.addWidget(card)


# --------------------------------------------------------------------------- profile
class ProfilePage(Page):
    def __init__(self, win) -> None:
        super().__init__("My Profile", "How you appear to people you connect with.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        p = theme.palette()
        # Instagram-style header + posts grid (rebuilt on every social change)
        self.ig = QVBoxLayout()
        self.ig.setSpacing(14)
        self.content.addLayout(self.ig)
        self.bridge.social_changed.connect(lambda: self.isVisible() and self._build_header())
        row = QHBoxLayout()
        row.setSpacing(14)
        form = Card("Edit profile", "user")
        top = QHBoxLayout()
        self.avatar = Avatar(84)
        top.addWidget(self.avatar)
        col = QVBoxLayout()
        b_pic = button("Change picture", "camera")
        b_rm = button("Remove picture", "x", "ghost")
        b_pic.clicked.connect(self._pick)
        b_rm.clicked.connect(self._remove_pic)
        col.addWidget(b_pic)
        col.addWidget(b_rm)
        top.addLayout(col)
        top.addStretch(1)
        form.add(top)
        self.f_name = QLineEdit()
        self.f_user = QLineEdit()
        self.f_email = QLineEdit()
        self.f_phone = QLineEdit()
        self.f_about = QPlainTextEdit()
        self.f_about.setMaximumHeight(90)
        self.f_about.setPlaceholderText("A short line about you (max 280 characters)")
        for cap, w in (("Display name", self.f_name), ("Username", self.f_user), ("Email", self.f_email),
                       ("Phone (optional)", self.f_phone), ("About", self.f_about)):
            form.add(label(cap, "muted"))
            form.add(w)
        self.err = label("", "error", wrap=True)
        form.add(self.err)
        save = button("Save profile", "save", "primary")
        save.clicked.connect(self._save)
        form.add(save)
        row.addWidget(form, 3)

        ident = Card("Blue Cench Chat identity", "fingerprint")
        self.qr = QLabel()
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setStyleSheet("background:white; border-radius:12px; padding:8px;")
        ident.add(self.qr)
        ident.add(label("YOUR Blue Cench Chat ID", "eyebrow"))
        self.uid = label("", "mono", selectable=True)
        ident.add(self.uid)
        ident.add(label("Your ID is derived from your identity key, so it cannot be forged. Others can scan or "
                        "paste your identity code to connect securely.", "muted", wrap=True))
        cp = button("Copy ID", "copy")
        cp.clicked.connect(lambda: (QGuiApplication.clipboard().setText(self.uid.text()), win.toast("ID copied")))
        full = button("Show identity code", "qr-code")
        full.clicked.connect(lambda: IdentityDialog(win, self.node).exec())
        ident.add(cp)
        ident.add(full)
        ident.body.addStretch(1)
        row.addWidget(ident, 2)
        self.content.addLayout(row)
        self.content.addStretch(1)
        self._avatar_bytes = None
        self.load()

    def on_show(self) -> None:
        self.load()

    def _build_header(self) -> None:
        from ...core import verification as vf
        from ..components.social import PostsGrid, counts_row, edit_note_dialog, name_line, ring_avatar

        clear_layout(self.ig)
        node, win = self.node, self.win
        acc = node.repo.account()
        st = node.social.stats()
        note = node.social.note()
        head = QHBoxLayout()
        head.setSpacing(28)
        head.addWidget(ring_avatar(acc.display_name, acc.avatar, 110, acc.user_id, ring=bool(note["text"] or note["music"])))
        col = QVBoxLayout()
        col.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(name_line(acc.username, node.social.is_verified_me(), "h2"))
        new_post = button("New post", "square-plus", "primary")
        from ..components.social import CreatePostDialog
        new_post.clicked.connect(lambda: CreatePostDialog(win).exec())
        nb = button("Edit note", "music")
        nb.clicked.connect(lambda: edit_note_dialog(win))
        top.addWidget(nb)
        top.addWidget(new_post)
        col.addLayout(top)
        col.addLayout(counts_row(st["posts"], st["followers"], st["following"]))
        nm = label(acc.display_name, "h3")
        nm.setTextFormat(Qt.TextFormat.PlainText)
        col.addWidget(nm)
        if acc.about:
            ab = label(acc.about, wrap=True)
            ab.setTextFormat(Qt.TextFormat.PlainText)
            col.addWidget(ab)
        if note["text"] or note["music"]:
            nt = label("Note: " + note["text"] + (f"   ♫ {note['music']}" if note["music"] else ""), "muted", wrap=True)
            nt.setTextFormat(Qt.TextFormat.PlainText)
            col.addWidget(nt)
        # blue tick status / request
        tick = QHBoxLayout()
        if node.social.is_verified_me():
            tick.addWidget(label("Your account is verified.", "success"))
        elif node.settings.get("tick_request"):
            tick.addWidget(label("Blue tick requested - " + ("delivered, waiting for review."
                                 if node.settings.get("tick_request_sent") else
                                 "it will be delivered when you meet the official account."), "muted", wrap=True), 1)
        else:
            need = vf.MIN_FOLLOWERS_FOR_REQUEST
            req = button("Request blue tick", "badge-check", "follow" if st["followers"] >= need else None)
            req.setEnabled(st["followers"] >= need)
            req.setToolTip(f"Available at {need} followers (you have {st['followers']})")
            req.clicked.connect(lambda: win.bridge.run(node.social.request_tick(), lambda m: win.toast(m, "success")))
            tick.addWidget(req)
            if st["followers"] < need:
                tick.addWidget(label(f"{st['followers']}/{need} followers needed", "faint"))
        tick.addStretch(1)
        col.addLayout(tick)
        head.addLayout(col, 1)
        self.ig.addLayout(head)
        posts = node.social.posts_by(acc.user_id)
        if posts:
            self.ig.addWidget(PostsGrid(win, posts, cell=200), 0, Qt.AlignmentFlag.AlignLeft)
        else:
            self.ig.addWidget(label("No posts yet. Share your first photo with New post (Ctrl+P).", "muted"))

    def load(self) -> None:
        self._build_header()
        acc = self.node.repo.account()
        self._avatar_bytes = acc.avatar
        self.avatar.set(acc.display_name, acc.avatar)
        self.f_name.setText(acc.full_name)
        self.f_user.setText(acc.username)
        self.f_email.setText(acc.email)
        self.f_phone.setText(acc.phone)
        self.f_about.setPlainText(acc.about)
        self.uid.setText(acc.user_id)
        self.qr.setPixmap(qr_pixmap(self.node.identity_code(), 190))
        self.f_user.setEnabled(not acc.is_guest)
        self.f_email.setEnabled(not acc.is_guest)

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose profile picture", "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            try:
                self._avatar_bytes = shrink_avatar(Path(path).read_bytes())
                self.avatar.set(self.f_name.text(), self._avatar_bytes)
            except (OSError, AuthError) as exc:
                self.err.setText(str(exc))

    def _remove_pic(self) -> None:
        self._avatar_bytes = None
        self.avatar.set(self.f_name.text(), None)

    def _save(self) -> None:
        name = " ".join(self.f_name.text().split())
        user = self.f_user.text().strip().lower()
        email = self.f_email.text().strip().lower()
        phone = self.f_phone.text().strip()
        about = self.f_about.toPlainText().strip()
        if not 2 <= len(name) <= 80:
            return self.err.setText("Display name must be 2-80 characters")
        if not USERNAME_RE.match(user):
            return self.err.setText("Username: 3-24 characters, letters, numbers, _ or .")
        if not EMAIL_RE.match(email):
            return self.err.setText("Enter a valid email address")
        if phone and not PHONE_RE.match(phone):
            return self.err.setText("Enter a valid phone number")
        if len(about) > 280:
            return self.err.setText("About is limited to 280 characters")
        acc = self.node.repo.account()
        others = [a for a in AuthService(self.node.db).list_accounts() if a.id != acc.id]
        if any(a.username == user for a in others):
            return self.err.setText("That username is used by another account on this PC")
        self.err.setText("")
        self.node.repo.update_profile(full_name=name, username=user, email=email, phone=phone, about=about,
                                      avatar=self._avatar_bytes)
        self.node.apply_visibility()
        self.bridge.run(self.node.broadcast_profile())
        self.win.refresh_identity()
        self.win.toast("Profile saved and shared with connected contacts", "success")


# --------------------------------------------------------------------------- security
class SecurityPage(Page):
    def __init__(self, win) -> None:
        super().__init__("Security & Privacy", "Control who can find you, who you trust and how your account "
                         "is protected.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        p = theme.palette()
        vis = Card("Visibility", "eye")
        self.t_visible = Toggle(self.node.settings.get("visible", True))
        self.t_visible.toggled.connect(lambda v: (self.node.update_settings(visible=v),
                                                  win.toast("You are now visible nearby" if v else "You are now hidden")))
        vis.add(SettingRow("Discoverable by nearby Blue Cench Chat users",
                           "Broadcast a Bluetooth LE beacon and local-network presence. When off, nobody new can "
                           "find you; existing contacts can still reconnect to you.", self.t_visible))
        vis.add(label("Privacy note: while visible, your beacon carries a stable identity hint so your contacts "
                      "can recognise you. Turn visibility off when you are not using Blue Cench Chat in a public place.",
                      "faint", wrap=True))
        self.content.addWidget(vis)

        enc = Card("Encryption", "lock")
        for ic, t, d in (
            ("key-round", "Identity", "Ed25519 key generated on this PC; stored encrypted with Argon2id + "
                                      "ChaCha20-Poly1305 under your password."),
            ("arrow-left-right", "Sessions", "Ephemeral X25519 key exchange, transcript signed by both identities, "
                                             "HKDF-SHA256 session keys, ChaCha20-Poly1305 on every frame."),
            ("shield-check", "Files", "SHA-256 verified on arrival, file names sanitised, received files marked as "
                                      "coming from another device so Windows SmartScreen checks executables."),
        ):
            r = QHBoxLayout()
            r.setSpacing(12)
            r.addWidget(icon_label(ic, 18, p.cyan), 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(1)
            col.addWidget(label(t, "h3"))
            col.addWidget(label(d, "muted", wrap=True))
            r.addLayout(col, 1)
            enc.add(r)
        self.content.addWidget(enc)

        self.trusted = Card("Trusted (verified) devices", "badge-check")
        self.trusted_list = QVBoxLayout()
        self.trusted.add(self.trusted_list)
        self.content.addWidget(self.trusted)
        self.blocked = Card("Blocked accounts", "ban")
        self.blocked_list = QVBoxLayout()
        self.blocked.add(self.blocked_list)
        self.content.addWidget(self.blocked)

        acc_card = Card("Account protection", "shield")
        b_pw = button("Change password", "key-round")
        b_rk = button("Generate new recovery key", "rotate-cw")
        b_forget = button("Forget 'keep me signed in'", "log-out")
        b_pw.clicked.connect(self._change_pw)
        b_rk.clicked.connect(self._new_rk)
        b_forget.clicked.connect(lambda: (secure_store.clear(), win.toast("Saved sign-in removed", "success")))
        b_forget.setVisible(secure_store.available())
        r = QHBoxLayout()
        for b in (b_pw, b_rk, b_forget):
            r.addWidget(b)
        r.addStretch(1)
        acc_card.add(label(f"After {config.MAX_FAILED_LOGINS} wrong passwords the account is locked for "
                           f"{config.LOCKOUT_SECONDS // 60} minutes.", "muted", wrap=True))
        acc_card.add(r)
        self.content.addWidget(acc_card)

        self.log_card = Card("Security log", "history")
        self.log_list = QVBoxLayout()
        self.log_card.add(self.log_list)
        self.content.addWidget(self.log_card)
        self.content.addStretch(1)
        self.bridge.contacts_changed.connect(lambda: self.isVisible() and self.refresh())
        self.refresh()

    def on_show(self) -> None:
        self.t_visible.setChecked(self.node.settings.get("visible", True))
        self.refresh()

    def refresh(self) -> None:
        p = theme.palette()
        clear_layout(self.trusted_list)
        verified = [c for c in self.node.repo.contacts(("accepted",)) if c.verified]
        if not verified:
            self.trusted_list.addWidget(label("No verified contacts yet. Open a contact and compare the safety "
                                              "number to verify them.", "muted", wrap=True))
        for c in verified:
            r = QHBoxLayout()
            r.addWidget(Avatar(30).set(c.name, c.avatar, seed=c.peer_user_id))
            r.addWidget(label(c.name, "h3"))
            r.addWidget(label(c.peer_user_id, "mono"))
            r.addStretch(1)
            b = button("Review", "shield-check", "ghost")
            b.clicked.connect(lambda _=False, c=c: VerifyDialog(self.win, self.node, c).exec())
            r.addWidget(b)
            w = QWidget()
            w.setLayout(r)
            self.trusted_list.addWidget(w)
        clear_layout(self.blocked_list)
        blocked = self.node.repo.contacts(("blocked",))
        if not blocked:
            self.blocked_list.addWidget(label("Nobody is blocked.", "muted"))
        for c in blocked:
            r = QHBoxLayout()
            r.addWidget(icon_label("ban", 16, p.danger))
            r.addWidget(label(c.name, "h3"))
            r.addWidget(label(c.peer_user_id, "mono"))
            r.addStretch(1)
            b = button("Unblock", "user-check", "ghost")
            b.clicked.connect(lambda _=False, c=c: self.node.connections.unblock(c.id))
            r.addWidget(b)
            w = QWidget()
            w.setLayout(r)
            self.blocked_list.addWidget(w)
        clear_layout(self.log_list)
        items = self.node.repo.activity(25, kind="security")
        if not items:
            self.log_list.addWidget(label("No security events.", "muted"))
        for a in items:
            r = QHBoxLayout()
            r.addWidget(icon_label("shield-alert", 15, p.warning))
            r.addWidget(label(a.text, wrap=True), 1)
            r.addWidget(label(human_time(a.ts), "faint"))
            w = QWidget()
            w.setLayout(r)
            self.log_list.addWidget(w)

    def _change_pw(self) -> None:
        old = ask_text(self.win, "Change password", "Enter your current password.", password=True)
        if not old:
            return
        new = ask_text(self.win, "Change password", "Choose a new password (8+ characters, a letter and a number).",
                       password=True)
        if not new:
            return
        again = ask_text(self.win, "Change password", "Repeat the new password.", password=True)
        if new != again:
            self.win.toast("Passwords do not match", "error")
            return
        try:
            AuthService(self.node.db).change_password(self.node.repo.account_id, old, new)
            secure_store.clear()
            self.node.repo.log("security", "Password changed")
            self.win.toast("Password changed", "success")
        except AuthError as exc:
            self.win.toast(str(exc), "error")

    def _new_rk(self) -> None:
        pw = ask_text(self.win, "New recovery key", "Enter your password to generate a new recovery key. The old "
                      "key stops working.", password=True)
        if not pw:
            return
        try:
            rk = AuthService(self.node.db).regenerate_recovery_key(self.node.repo.account_id, pw)
        except AuthError as exc:
            self.win.toast(str(exc), "error")
            return
        self.node.repo.log("security", "Recovery key regenerated")
        show_secret(self.win, "Your new recovery key", "Store it somewhere safe. It is the only way to reset your "
                    "password.", rk)


# --------------------------------------------------------------------------- settings
class SettingsPage(Page):
    def __init__(self, win) -> None:
        super().__init__("Settings", "Appearance, notifications, transfers, connectivity and startup.")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        s = self.node.settings

        def tog(key, title, desc, icon=None, on_change=None):
            t = Toggle(bool(s.get(key, True)))

            def changed(v):
                self.node.update_settings(**{key: v})
                if on_change:
                    on_change(v)

            t.toggled.connect(changed)
            return SettingRow(title, desc, t, icon)

        app = Card("Appearance & accessibility", "sun")
        self.theme = QComboBox()
        for key, title in theme.THEME_NAMES:
            self.theme.addItem(title, key)
        keys = [k for k, _ in theme.THEME_NAMES]
        self.theme.setCurrentIndex(keys.index(s.get("theme")) if s.get("theme") in keys else 0)
        self.theme.currentIndexChanged.connect(self._theme)
        app.add(SettingRow("Appearance", "Light, Dark, or the Blue Cench Midnight Blue signature look. "
                                         "Ctrl+D switches between them.", self.theme))
        self.scale = QComboBox()
        for v in (90, 100, 115, 130):
            self.scale.addItem(f"{v}%", v)
        self.scale.setCurrentIndex(max(0, self.scale.findData(s.get("font_scale", 100))))
        self.scale.currentIndexChanged.connect(self._theme)
        app.add(SettingRow("Text size", "Scales all interface text for readability.", self.scale))
        app.add(tog("reduce_motion", "Reduce motion", "Turns off fade animations and the scanning animation."))
        self.content.addWidget(app)

        notif = Card("Notifications", "bell")
        notif.add(tog("notify_requests", "Connection requests", "Requests, acceptances and disconnections."))
        notif.add(tog("notify_messages", "New messages", "When a chat is not open in front of you."))
        notif.add(tog("notify_files", "File transfers", "Incoming files, completed and failed transfers."))
        notif.add(tog("notify_security", "Security warnings", "Identity mismatches and integrity failures."))
        self.content.addWidget(notif)

        tr = Card("File transfers", "arrow-left-right")
        self.dl = label(s.get("download_dir") or str(config.default_download_dir()), "mono", wrap=True)
        ch = button("Change", "folder-open")
        ch.clicked.connect(self._change_dl)
        tr.add(SettingRow("Download location", "Where received files are saved.", ch))
        tr.add(self.dl)
        tr.add(tog("skip_duplicates", "Skip duplicate files",
                   "If an identical file (same SHA-256) was already received and still exists, it is not "
                   "transferred again."))
        tr.add(tog("auto_accept_verified", "Auto-accept from verified contacts",
                   "Files from verified contacts start immediately (executables still need approval)."))
        tr.add(tog("battery_saver", "Battery-aware transfers",
                   "Warn before large transfers when the battery is below 20%."))
        self.content.addWidget(tr)

        con = Card("Connectivity", "radio")
        restart = lambda _v: win.toast("Restart Blue Cench Chat to apply this change", "warning")
        con.add(tog("lan_enabled", "Local network transport", "Fast transfers over Wi-Fi, Ethernet or a Mobile Hotspot "
                    "(no internet needed).", on_change=restart))
        con.add(tog("ble_enabled", "Bluetooth LE discovery", "Advertise and scan with Bluetooth Low Energy."))
        con.add(tog("rfcomm_enabled", "Bluetooth RFCOMM transport", "Chat and transfer files over Bluetooth Classic "
                    "with paired PCs.", on_change=restart))
        con.add(tog("auto_reconnect", "Automatic reconnection", "Reconnect to your contacts when they come back in range."))
        self.content.addWidget(con)

        st = Card("Startup", "power")
        st.add(tog("start_with_windows", "Start with Windows", "Launch Blue Cench Chat minimised to the tray when you sign in "
                   "to Windows (installed version only).", on_change=self._startup))
        st.add(tog("minimize_to_tray", "Keep running in the tray", "Closing the window keeps Blue Cench Chat reachable for "
                   "incoming messages and files."))
        self.content.addWidget(st)

        data = Card("Backup & restore", "database")
        data.add(label("Backups contain your accounts, contacts, messages and history. Identity keys inside stay "
                       "encrypted with your password. Received files themselves are not included.", "muted", wrap=True))
        r = QHBoxLayout()
        b1 = button("Create backup...", "save")
        b2 = button("Restore from backup...", "archive-restore")
        b1.clicked.connect(self._backup)
        b2.clicked.connect(self._restore)
        r.addWidget(b1)
        r.addWidget(b2)
        r.addStretch(1)
        data.add(r)
        self.content.addWidget(data)
        self.content.addStretch(1)

    def _theme(self) -> None:
        self.node.update_settings(theme=self.theme.currentData() or "light",
                                  font_scale=self.scale.currentData())
        self.win.apply_theme(rebuild=True)

    def _change_dl(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose download folder", self.dl.text())
        if d:
            self.node.update_settings(download_dir=d)
            self.dl.setText(d)

    def _startup(self, v: bool) -> None:
        if not system.set_start_with_windows(v):
            self.win.toast("Start with Windows works in the installed version on Windows", "warning")

    def _backup(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save backup", str(Path.home() / "BlueCenchChat-backup.nxbackup"),
                                              "Blue Cench Chat backup (*.nxbackup)")
        if path:
            try:
                out = backup.create_backup(Path(path))
                self.win.toast(f"Backup saved to {out}", "success")
            except Exception as exc:
                self.win.toast(f"Backup failed: {exc}", "error")

    def _restore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose backup", str(Path.home()), "Blue Cench Chat backup (*.nxbackup)")
        if not path:
            return
        if not confirm(self.win, "Restore backup?", "All local Blue Cench Chat data is replaced with the backup the next "
                       "time Blue Cench Chat starts. Your current data is kept as a .before-restore file.", "Restore", True):
            return
        try:
            backup.stage_restore(Path(path))
            self.win.toast("Backup verified. Restart Blue Cench Chat to complete the restore.", "success")
        except Exception as exc:
            self.win.toast(f"Restore failed: {exc}", "error")


# --------------------------------------------------------------------------- help
FAQ = [
    ("Can I text people who are far away?",
     "Yes - open Everyone. While you're online, every Blue Cench Chat user appears there and you can follow and "
     "message them over the internet. Messages are end-to-end encrypted: the online database only ever holds sealed "
     "envelopes, deleted as soon as they arrive. People nearby still work with no internet over Bluetooth or Wi-Fi."),
    ("How do calls work?",
     "Open a chat and press the phone button (voice) or the camera button (video). Voice calls work over Bluetooth "
     "and Wi-Fi. Video needs both PCs on the same Wi-Fi or LAN, because Bluetooth is too slow for video. Calls are "
     "end-to-end encrypted like messages. Phones can't take calls yet - they ring on the PC."),
    ("How do I get a blue tick?",
     "Once you have 40 followers, open My Profile and press Request blue tick. The request reaches the official "
     "@bluecenchchat account the next time your devices meet, and they approve it from their Verification page. "
     "Ticks are cryptographically signed, so they can't be faked."),
    ("Where do posts and notes go?",
     "There is no server. Posts, notes, likes and comments travel directly between devices - your followers "
     "receive them when you're connected over Bluetooth or the same Wi-Fi."),
    ("Nobody shows up in Discover People",
     "Both PCs need Blue Cench Chat open with visibility on. Bluetooth LE discovery needs adapters that can advertise "
     "(check Bluetooth Devices > Run compatibility test). On a shared network, presence beacons work even without "
     "Bluetooth. If the network blocks broadcasts, use Connect with code instead."),
    ("Bluetooth connection fails",
     "Windows requires the two PCs to be paired before an RFCOMM link to a custom service: Settings > Bluetooth & "
     "devices > Add device on one PC while the other is discoverable, confirm the PIN on both, then connect again "
     "in Blue Cench Chat."),
    ("Transfers over Bluetooth are slow",
     "Bluetooth RFCOMM carries roughly 50-250 KB/s. For big files, turn on Mobile hotspot on one PC (Settings > "
     "Network & internet > Mobile hotspot) and connect the other PC to it. No internet is needed - Blue Cench Chat detects "
     "the shared network and uses it automatically."),
    ("Windows Firewall asked about Blue Cench Chat",
     "Allow Blue Cench Chat on private networks so the other PC can reach it. The installer adds this rule when installed "
     "for all users."),
    ("A transfer was interrupted",
     "Partial data is kept. When the two devices reconnect, the sender re-offers the transfer and only the missing "
     "bytes are sent. Every file is verified with SHA-256 before it is saved."),
    ("I forgot my password",
     "Use Forgot password on the sign-in screen with the recovery key you saved at registration. Without it the "
     "account cannot be recovered - there is no server holding a copy."),
]

TWO_PC = """1. Install Blue Cench Chat on both Windows 10/11 PCs and create an account on each.
2. On both: Bluetooth Devices > Run compatibility test.
3. Fast path (recommended for files): join both PCs to the same Wi-Fi, or enable Mobile hotspot on PC A and join it from PC B.
4. Bluetooth path: pair the PCs once in Windows Settings > Bluetooth & devices.
5. PC A: Discover People > Start scanning. PC B appears within a few seconds. Press Connect.
6. PC B: accept the request in Notifications or My Connections.
7. Both: open the contact, compare the safety number, mark verified.
8. Chat, then send a large file and a folder. Pull the network cable or disable Wi-Fi mid-transfer, reconnect, and watch it resume."""


class HelpPage(Page):
    def __init__(self, win) -> None:
        super().__init__("Help & Support", "Getting started, troubleshooting and testing with two PCs.")
        self.win = win
        start = Card("Getting started", "book-open")
        steps = QVBoxLayout()
        steps.addWidget(label(TWO_PC, wrap=True, selectable=True))
        start.add(steps)
        tour = button("Replay welcome tour", "play")
        tour.clicked.connect(win.show_onboarding)
        start.add(tour)
        self.content.addWidget(start)
        keys = Card("Keyboard shortcuts", "keyboard")
        from PySide6.QtWidgets import QGridLayout
        g = QGridLayout()
        g.setHorizontalSpacing(24)
        for i, (k, what) in enumerate(win.SHORTCUTS):
            g.addWidget(label(k, "mono"), i, 0)
            g.addWidget(label(what, "muted"), i, 1)
        g.setColumnStretch(1, 1)
        keys.add(g)
        self.content.addWidget(keys)
        faq = Card("Troubleshooting", "circle-help")
        for q, a in FAQ:
            faq.add(label(q, "h3"))
            faq.add(label(a, "muted", wrap=True))
            faq.add(divider())
        self.content.addWidget(faq)
        about = Card("About Blue Cench Chat", "info")
        about.add(label(f"Blue Cench Chat {config.APP_VERSION} - {config.APP_TAGLINE}", "h3"))
        about.add(label("Built with Python, PySide6 (Qt), SQLAlchemy, cryptography, argon2-cffi and the Windows "
                        "Runtime Bluetooth APIs. Icons: Lucide (ISC licence).", "muted", wrap=True))
        r = QHBoxLayout()
        logs = button("Open log folder", "folder-open")
        logs.clicked.connect(lambda: system.open_path(config.log_dir()))
        data = button("Open data folder", "database")
        data.clicked.connect(lambda: system.open_path(config.data_dir()))
        r.addWidget(logs)
        r.addWidget(data)
        from ...core import updates
        upd = button("Download update", "download", "primary", "Opens the latest installer on GitHub")
        upd.clicked.connect(lambda: __import__("webbrowser").open(updates.SETUP_URL))
        r.addWidget(upd)
        r.addStretch(1)
        about.add(r)
        self.content.addWidget(about)
        self.content.addStretch(1)
