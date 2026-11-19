"""Main application window: sidebar navigation, pages, tray and notifications."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import config
from . import icons, theme
from .bridge import Bridge
from .components.widgets import Avatar, Toast, button, fade_in, label, tool_button
from .dialogs.common import OnboardingDialog
from .pages.account import HelpPage, NotificationsPage, ProfilePage, SecurityPage, SettingsPage
from .pages.connections import ConnectionsPage
from .pages.dashboard import DashboardPage
from .pages.everyone import EveryonePage
from .pages.home import HomePage
from .pages.verify import VerifyPage
from .pages.devices import DevicesPage
from .pages.discover import DiscoverPage
from .pages.messages import MessagesPage
from .pages.transfers import HistoryPage, TransfersPage
from .pages.web import WebPage

NAV = [
    ("home", "Home", "house", HomePage),
    ("messages", "Messages", "message-square", MessagesPage),
    ("discover", "Discover People", "radar", DiscoverPage),
    ("everyone", "Everyone", "globe", EveryonePage),
    ("connections", "My Connections", "users", ConnectionsPage),
    ("notifications", "Notifications", "bell", NotificationsPage),
    ("transfers", "File Transfers", "arrow-left-right", TransfersPage),
    ("history", "Transfer History", "history", HistoryPage),
    ("devices", "Bluetooth Devices", "bluetooth", DevicesPage),
    ("web", "Phones && Tablets", "smartphone", WebPage),
    ("profile", "My Profile", "user", ProfilePage),
    ("dashboard", "Dashboard", "layout-dashboard", DashboardPage),
    ("verify", "Verification", "badge-check", VerifyPage),
    ("security", "Security && Privacy", "shield", SecurityPage),
    ("settings", "Settings", "settings", SettingsPage),
    ("help", "Help && Support", "life-buoy", HelpPage),
]
NAV_SECTIONS = {"transfers": "SHARE", "profile": "YOU"}


class NavButton(QPushButton):
    def __init__(self, text: str, icon_name: str) -> None:
        super().__init__(text)
        self.setObjectName("NavButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(icons.icon(icon_name, 18, theme.palette().muted, theme.palette().cyan))
        self.setIconSize(QSize(18, 18))
        self.setMinimumHeight(38)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 10, 0)
        lay.addStretch(1)
        self.badge = QLabel()
        self.badge.setObjectName("NavBadge")
        self.badge.setFixedHeight(18)
        self.badge.setMinimumWidth(18)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.hide()
        lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)

    def set_badge(self, n: int) -> None:
        self.badge.setText(str(n) if n < 100 else "99+")
        self.badge.setVisible(n > 0)


class MainWindow(QMainWindow):
    sign_out_requested = Signal()
    quit_requested = Signal()

    def __init__(self, node, is_guest: bool = False) -> None:
        super().__init__()
        self.node = node
        self.is_guest = is_guest
        self.bridge = Bridge(node)
        self.setWindowTitle("Blue Cench Chat" + (f"  [{config.profile()}]" if config.profile() else ""))
        self.setWindowIcon(QIcon(str(config.resource_path("assets", "logo", "bluecenchchat.png"))))
        self.resize(1360, 860)
        self.setMinimumSize(720, 520)
        self._compact = None
        self._really_quit = False
        node.window_active = lambda: self.isVisible() and self.isActiveWindow() and not self.isMinimized()
        node.on_notify = self._desktop_notify
        self.call_window = None
        self._wire_bridge()
        self._build()
        self._tray()
        self._shortcuts()
        if node.settings.get("check_updates", True) and not is_guest:
            QTimer.singleShot(5000, self._check_updates)
        self._badge_pending = False
        self.update_badges()
        if not node.settings.get("onboarded") and not is_guest:
            QTimer.singleShot(600, self.show_onboarding)

    def _wire_bridge(self) -> None:
        self.bridge.error.connect(lambda t: self.toast(t, "error"))
        self.bridge.info.connect(self.toast)
        self.bridge.request_received.connect(self._on_request)
        self.bridge.transfer_offer.connect(self._on_offer)
        self.bridge.call_changed.connect(self._on_call)
        self.bridge.social_changed.connect(self._update_admin_nav)
        for sig in (self.bridge.notification_added, self.bridge.messages_changed, self.bridge.contacts_changed,
                    self.bridge.social_changed):
            sig.connect(lambda *_: self._schedule_badges())

    SHORTCUTS = [
        ("Ctrl+H", "Home feed"), ("Ctrl+K", "Discover people nearby"), ("Ctrl+M", "Messages"),
        ("Ctrl+P", "New post"), ("Ctrl+N", "Edit your note"), ("Ctrl+D", "Switch light / dark mode"),
        ("Ctrl+,", "Settings"), ("Ctrl+1 … Ctrl+9", "Jump to a sidebar item"),
        ("Ctrl+Shift+V", "Voice call the open chat"), ("Ctrl+Shift+E", "Video call the open chat (Wi-Fi/LAN)"),
        ("Ctrl+F", "Search in Messages"), ("Enter / Shift+Enter", "Send message / new line"),
        ("Esc", "Hang up or close a dialog"), ("Ctrl+U", "Check for updates (one click)"), ("M / V in a call", "Mute / camera on-off"), ("F1", "Keyboard shortcuts"),
    ]

    def _shortcuts(self) -> None:
        def sc(keys, fn):
            QShortcut(QKeySequence(keys), self, activated=fn)
        sc("Ctrl+H", lambda: self.navigate("home"))
        sc("Ctrl+K", lambda: self.navigate("discover"))
        sc("Ctrl+M", lambda: self.navigate("messages"))
        sc("Ctrl+,", lambda: self.navigate("settings"))
        sc("Ctrl+D", self.toggle_theme)
        sc("F1", self.show_shortcuts)
        sc("Ctrl+U", self.show_update)
        sc("Ctrl+P", self._new_post)
        sc("Ctrl+N", self._edit_note)
        sc("Ctrl+Shift+V", lambda: self._call_open_chat(False))
        sc("Ctrl+Shift+E", lambda: self._call_open_chat(True))
        sc("Ctrl+F", self._focus_search)
        for i in range(1, 10):
            sc(f"Ctrl+{i}", lambda i=i: self._nav_index(i - 1))

    def _nav_index(self, i: int) -> None:
        keys = [k for k, b in self.nav.items() if not b.isHidden()]
        if i < len(keys):
            self.navigate(keys[i])

    def _new_post(self) -> None:
        from .components.social import CreatePostDialog
        CreatePostDialog(self).exec()

    def _edit_note(self) -> None:
        from .components.social import edit_note_dialog
        edit_note_dialog(self)

    def _focus_search(self) -> None:
        self.navigate("messages")
        page = self.pages["messages"]
        if getattr(page, "chat", None) is not None:
            page.chat._toggle_search()
            return
        box = getattr(page, "search", None)
        if box is not None:
            box.setFocus()
            box.selectAll()

    def _call_open_chat(self, video: bool) -> None:
        page = self.pages.get("messages")
        if self._current == "messages" and page is not None and getattr(page, "chat", None):
            self.start_call(page.chat.cid, video)
        else:
            self.toast("Open a chat first, then press the shortcut to call", "warning")

    THEME_CYCLE = ["light", "dark", "midnight"]

    def toggle_theme(self) -> None:
        """Ctrl+D / the sidebar button: Light -> Dark -> Midnight Blue -> Light."""
        cur = self.node.settings.get("theme", "light")
        nxt = self.THEME_CYCLE[(self.THEME_CYCLE.index(cur) + 1) % 3] if cur in self.THEME_CYCLE else "dark"
        self.node.update_settings(theme=nxt)
        self.apply_theme(rebuild=True)

    def show_shortcuts(self) -> None:
        from PySide6.QtWidgets import QDialog, QGridLayout
        d = QDialog(self)
        d.setWindowTitle("Keyboard shortcuts")
        lay = QVBoxLayout(d)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.addWidget(label("Keyboard shortcuts", "h2"))
        g = QGridLayout()
        g.setHorizontalSpacing(24)
        for r, (k, what) in enumerate(self.SHORTCUTS):
            key = label(k, "mono")
            g.addWidget(key, r, 0)
            g.addWidget(label(what), r, 1)
        lay.addLayout(g)
        d.exec()

    def _check_updates(self) -> None:
        import asyncio

        from ..core import updates

        async def check():
            v = await asyncio.to_thread(updates.latest_version)
            if v and updates.is_newer(v):
                self.node.notify("update", f"Update available: {v}", "One click installs it (Help & Support).",
                                 "notify_messages", ref=updates.SETUP_URL)
                self.show_update()
        self.bridge.run(check())

    def show_update(self) -> None:
        """One-click updater (also Ctrl+U, the Start-menu "Update Blue Cench Chat" shortcut, and Help)."""
        from .update_dialog import UpdateDialog

        if getattr(self, "_update_dlg", None) is not None and self._update_dlg.isVisible():
            self._update_dlg.raise_()
            return
        self._update_dlg = UpdateDialog(self)
        self._update_dlg.show()

    def _confirm_sign_out(self) -> None:
        """A proper sign-out sheet: who you are, what happens, and a clear choice."""
        from PySide6.QtWidgets import QDialog
        acc = self.node.repo.account()
        d = QDialog(self)
        d.setWindowTitle("Sign out")
        d.setFixedWidth(400)
        lay = QVBoxLayout(d)
        lay.setContentsMargins(28, 26, 28, 22)
        lay.setSpacing(10)
        av = Avatar(72).set(acc.display_name, acc.avatar, seed=acc.user_id)
        lay.addWidget(av, 0, Qt.AlignmentFlag.AlignHCenter)
        t = label("End guest session?" if self.is_guest else f"Sign out of @{acc.username}?", "h2")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        msg = ("Everything from this guest session will be erased." if self.is_guest else
               "Your chats, files and keys stay safely on this PC, encrypted with your password. "
               "People can't reach you until you sign in again.")
        m = label(msg, "muted", wrap=True)
        m.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(m)
        lay.addSpacing(6)
        go = button("End session" if self.is_guest else "Sign out", "log-out", "danger")
        stay = button("Stay signed in", variant="ghost")
        go.clicked.connect(lambda: (d.accept(), self.sign_out_requested.emit()))
        stay.clicked.connect(d.reject)
        lay.addWidget(go)
        lay.addWidget(stay)
        d.exec()

    # ------------------------------------------------------------------ calls
    def start_call(self, contact_id: int, video: bool) -> None:
        nearby = self.node.connections.session_for_contact(contact_id)
        if not nearby:
            c = self.node.repo.contact(contact_id)
            if not self.node.cloud.can_reach(c):
                self.toast("They aren't nearby or online. Connect over Bluetooth / Wi-Fi, or turn on online "
                           "mode (both of you) to call over the internet.", "warning")
                return
            if video:
                self.toast("Over the internet you can make a voice call. Video needs the same Wi-Fi.", "warning")
                return
        cur = self.node.calls.current
        if cur and cur.state != "ended":
            self.toast("You're already in a call", "warning")
            return
        self.bridge.run(self.node.calls.start(contact_id, video))

    def _on_call(self, call) -> None:
        from .calls_ui import CallWindow
        if call is None:
            return
        w = self.call_window
        if w is not None and w.call.id == call.id:
            w.update_state(call)
            return
        if call.state == "ended":
            return
        if w is not None:
            w.close()
        self.call_window = CallWindow(self, call)
        self.call_window.finished.connect(lambda _r: setattr(self, "call_window", None))
        if not call.outgoing:
            self.show_window()
            c = self.node.repo.contact(call.contact_id)
            if hasattr(self, "tray") and not self.window_focused():
                self.tray.showMessage("Incoming call", c.name if c else "", QSystemTrayIcon.MessageIcon.Information,
                                      8000)
        self.call_window.show()
        self.call_window.raise_()

    def _update_admin_nav(self) -> None:
        if "verify" in self.nav:
            self.nav["verify"].setVisible(self.node.social.is_admin())
        from ..core.social import suspension_text
        sus = self.node.social.my_suspension()
        banner = getattr(self, "_susp_banner", None)
        if banner is not None:
            banner.setVisible(bool(sus))
            if sus:
                banner.setText("  " + suspension_text(sus) + "  You can still read your chats.")

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        theme.REDUCE_MOTION = bool(self.node.settings.get("reduce_motion"))
        p = theme.palette()
        root = QWidget()
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        side = QFrame()
        side.setObjectName("Sidebar")
        self._side = side
        self._nav_labels: dict[str, str] = {}
        self._eyebrows: list = []
        side.setFixedWidth(248)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.setSpacing(2)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(config.resource_path("assets", "logo", "bluecenchchat.png"))).scaled(
            30, 30, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        brand.addWidget(logo)
        name = QLabel(f'Blue <span style="color:{theme.palette().primary}">Cench</span>')
        name.setTextFormat(Qt.TextFormat.RichText)
        name.setObjectName("SidebarBrand")
        name.setToolTip("Blue Cench Chat")
        self._brand_name = name
        brand.addWidget(name)
        brand.addStretch(1)
        cur = self.node.settings.get("theme", "light")
        nxt = {"light": "Dark", "dark": "Midnight Blue", "midnight": "Light"}.get(cur, "Dark")
        tt = tool_button({"light": "moon", "dark": "sparkles", "midnight": "sun"}.get(cur, "moon"),
                         f"Switch to {nxt} (Ctrl+D)")
        tt.clicked.connect(self.toggle_theme)
        self._theme_btn = tt
        brand.addWidget(tt)
        sl.addLayout(brand)
        sl.addSpacing(16)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav: dict[str, NavButton] = {}
        self.pages: dict[str, QWidget] = {}
        self.stack = QStackedWidget()
        self.stack.setObjectName("Pages")
        for i, (key, text, ic, cls) in enumerate(NAV):
            if key in NAV_SECTIONS:
                sl.addSpacing(10)
                eb = label(NAV_SECTIONS[key], "eyebrow")
                self._eyebrows.append(eb)
                sl.addWidget(eb)
                sl.addSpacing(2)
            b = NavButton(text, ic)
            b.setToolTip(text.replace("&&", "&"))
            self._nav_labels[key] = text
            b.clicked.connect(lambda _=False, k=key: self.navigate(k))
            self.nav_group.addButton(b)
            self.nav[key] = b
            sl.addWidget(b)
            page = cls(self)
            self.pages[key] = page
            self.stack.addWidget(page)
        sl.addStretch(1)
        me = QFrame()
        me.setObjectName("SoftCard")
        ml = QHBoxLayout(me)
        ml.setContentsMargins(10, 8, 6, 8)
        self.me_avatar = Avatar(34)
        ml.addWidget(self.me_avatar)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.me_name = label("", "h3")
        self.me_id = label("", "faint")
        col.addWidget(self.me_name)
        col.addWidget(self.me_id)
        ml.addLayout(col, 1)
        out = tool_button("log-out", "Sign out" if not self.is_guest else "End guest session (data is erased)")
        out.clicked.connect(self._confirm_sign_out)
        ml.addWidget(out)
        sl.addWidget(me)
        lay.addWidget(side)
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self._susp_banner = QLabel()
        self._susp_banner.setStyleSheet("background:#F4212E; color:#FFFFFF; font-weight:700; padding:10px 16px;")
        self._susp_banner.setWordWrap(True)
        self._susp_banner.hide()
        right.addWidget(self._susp_banner)
        right.addWidget(self.stack, 1)
        lay.addLayout(right, 1)
        self.setCentralWidget(root)
        self._me_out = out
        self._me_card = me
        self.refresh_identity()
        self._current = None
        self._compact = None
        self._apply_compact(self.width() < 1180)
        self._update_admin_nav()
        self.navigate("home")

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._apply_compact(self.width() < 1180)

    def _apply_compact(self, compact: bool) -> None:
        """Small windows / tablets: icon-only navigation rail and tighter pages."""
        if compact == self._compact or not hasattr(self, "_side"):
            return
        self._compact = compact
        self._side.setFixedWidth(76 if compact else 248)
        self._brand_name.setVisible(not compact)
        self._theme_btn.setVisible(not compact)
        for eb in self._eyebrows:
            eb.setVisible(not compact)
        for key, b in self.nav.items():
            b.setText("" if compact else self._nav_labels[key])
        for w in (self.me_name, self.me_id, self._me_out):
            w.setVisible(not compact)
        for page in self.pages.values():
            if hasattr(page, "set_compact"):
                page.set_compact(compact)

    def refresh_identity(self) -> None:
        acc = self.node.repo.account()
        self.me_avatar.set(acc.display_name, acc.avatar, True, acc.user_id)
        self.me_name.setText(acc.display_name if not self.is_guest else f"{acc.display_name} (guest)")
        self.me_id.setText(acc.user_id)

    def apply_theme(self, rebuild: bool = False) -> None:
        s = self.node.settings
        theme.set_theme(s.get("theme", "light"), s.get("font_scale", 100))
        icons.clear_cache()
        QApplication.instance().setStyleSheet(theme.stylesheet())
        if rebuild:
            current = self._current
            old = self.centralWidget()
            # disconnect page signal handlers by rebuilding the bridge
            self.bridge.detach()
            self.bridge.deleteLater()
            self.bridge = Bridge(self.node)
            self._wire_bridge()
            self._build()
            old.deleteLater()
            if current:
                self.navigate(current)
            self.update_badges()

    # ------------------------------------------------------------------ navigation
    def navigate(self, key: str) -> None:
        if key not in self.pages:
            return
        prev = self.pages.get(self._current) if self._current else None
        if prev is not None and hasattr(prev, "on_hide"):
            prev.on_hide()
        self._current = key
        self.nav[key].setChecked(True)
        page = self.pages[key]
        self.stack.setCurrentWidget(page)
        if hasattr(page, "on_show"):
            page.on_show()
        fade_in(page, 140)

    def open_chat(self, contact_id: int) -> None:
        self.navigate("messages")
        self.pages["messages"].open(contact_id)

    def toast(self, text: str, tone: str = "info") -> None:
        if self.isVisible():
            Toast(self.centralWidget(), text, tone)

    def show_onboarding(self) -> None:
        OnboardingDialog(self).exec()
        self.node.update_settings(onboarded=True)

    def _schedule_badges(self) -> None:
        if not self._badge_pending:
            self._badge_pending = True
            QTimer.singleShot(250, self.update_badges)

    def update_badges(self) -> None:
        self._badge_pending = False
        repo = self.node.repo
        self.nav["messages"].set_badge(repo.unread_total())
        self.nav["notifications"].set_badge(repo.unread_notifications())
        self.nav["connections"].set_badge(len(repo.contacts(("pending_in",))))
        self.nav["transfers"].set_badge(len(repo.transfers(("offered",))))
        if hasattr(self, "tray"):
            n = repo.unread_total() + repo.unread_notifications()
            self.tray.setToolTip(f"Blue Cench Chat - {n} unread" if n else "Blue Cench Chat")

    # ------------------------------------------------------------------ events
    def _on_request(self, contact_id: int) -> None:
        c = self.node.repo.contact(contact_id)
        if c:
            self.toast(f"{c.name} wants to connect - review in My Connections", "info")

    def _on_offer(self, tid: str) -> None:
        t = self.node.repo.transfer(tid)
        if t and t.status == "offered":
            self.toast(f"Incoming files: {t.label} - accept in File Transfers", "info")

    def _desktop_notify(self, kind: str, title: str, body: str, ref: str) -> None:
        if not hasattr(self, "tray") or not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self.window_focused() and kind == "message":
            return
        icon = QSystemTrayIcon.MessageIcon.Warning if kind in ("security", "transfer_failed") else \
            QSystemTrayIcon.MessageIcon.Information
        self._last_notify = (kind, ref)
        self.tray.showMessage(title, body[:200], icon, 6000)

    def window_focused(self) -> bool:
        return self.isVisible() and self.isActiveWindow() and not self.isMinimized()

    def _notification_clicked(self) -> None:
        self.show_window()
        kind, ref = getattr(self, "_last_notify", ("", ""))
        if kind == "message" and ref.isdigit():
            self.open_chat(int(ref))
        elif kind == "request":
            self.navigate("connections")
            self.pages["connections"].show_requests()
        elif kind in ("file_offer",):
            self.navigate("transfers")
        else:
            self.navigate("notifications")

    # ------------------------------------------------------------------ tray
    def _tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(QIcon(str(config.resource_path("assets", "logo", "bluecenchchat.png"))), self)
        self.tray.setToolTip("Blue Cench Chat")
        m = QMenu()
        m.addAction(icons.plain("monitor", 16), "Open Blue Cench Chat", self.show_window)
        m.addAction(icons.plain("radar", 16), "Discover people", lambda: (self.show_window(), self.navigate("discover")))
        m.addSeparator()
        vis = QAction("Visible to nearby users", m)
        vis.setCheckable(True)
        vis.setChecked(self.node.settings.get("visible", True))
        vis.toggled.connect(lambda v: self.node.update_settings(visible=v))
        m.addAction(vis)
        m.addSeparator()
        m.addAction(icons.plain("power", 16), "Quit Blue Cench Chat", self.quit_app)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(lambda r: self.show_window() if r in (
            QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick) else None)
        self.tray.messageClicked.connect(self._notification_clicked)
        self.tray.show()

    def show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._really_quit = True
        self.quit_requested.emit()

    def closeEvent(self, e) -> None:
        if not self._really_quit and self.node.settings.get("minimize_to_tray", True) and hasattr(self, "tray") \
                and not self.is_guest:
            e.ignore()
            self.hide()
            if not getattr(self, "_tray_hint_shown", False):
                self._tray_hint_shown = True
                self.tray.showMessage("Blue Cench Chat is still running",
                                      "You can still receive messages and files. Right-click the tray icon to quit.",
                                      QSystemTrayIcon.MessageIcon.Information, 4000)
            return
        e.ignore()
        self.quit_app()

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() == e.Type.ActivationChange and self.isActiveWindow() and self._current == "messages":
            page = self.pages["messages"]
            if page.chat:
                self.bridge.run(self.node.messaging.mark_read(page.chat.cid))

    def teardown(self) -> None:
        """Detach from the engine before the window is destroyed."""
        self.bridge.detach()
        self.node.on_notify = None
        self.node.window_active = lambda: False
        if hasattr(self, "tray"):
            self.tray.hide()
