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
from .components.widgets import Avatar, Toast, fade_in, label, tool_button
from .dialogs.common import OnboardingDialog
from .pages.account import HelpPage, NotificationsPage, ProfilePage, SecurityPage, SettingsPage
from .pages.connections import ConnectionsPage
from .pages.dashboard import DashboardPage
from .pages.devices import DevicesPage
from .pages.discover import DiscoverPage
from .pages.messages import MessagesPage
from .pages.transfers import HistoryPage, TransfersPage
from .pages.web import WebPage

NAV = [
    ("dashboard", "Dashboard", "layout-dashboard", DashboardPage),
    ("discover", "Discover People", "radar", DiscoverPage),
    ("connections", "My Connections", "users", ConnectionsPage),
    ("messages", "Messages", "message-square", MessagesPage),
    ("transfers", "File Transfers", "arrow-left-right", TransfersPage),
    ("devices", "Bluetooth Devices", "bluetooth", DevicesPage),
    ("web", "Phones && Tablets", "smartphone", WebPage),
    ("history", "Transfer History", "history", HistoryPage),
    ("notifications", "Notifications", "bell", NotificationsPage),
    ("profile", "My Profile", "user", ProfilePage),
    ("security", "Security && Privacy", "shield", SecurityPage),
    ("settings", "Settings", "settings", SettingsPage),
    ("help", "Help && Support", "life-buoy", HelpPage),
]


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
        self.bridge.error.connect(lambda t: self.toast(t, "error"))
        self.bridge.info.connect(self.toast)
        self.bridge.request_received.connect(self._on_request)
        self.bridge.transfer_offer.connect(self._on_offer)
        for sig in (self.bridge.notification_added, self.bridge.messages_changed, self.bridge.contacts_changed):
            sig.connect(lambda *_: self._schedule_badges())
        self._build()
        self._tray()
        QShortcut(QKeySequence("Ctrl+K"), self, activated=lambda: self.navigate("discover"))
        QShortcut(QKeySequence("Ctrl+M"), self, activated=lambda: self.navigate("messages"))
        self._badge_pending = False
        self.update_badges()
        if not node.settings.get("onboarded") and not is_guest:
            QTimer.singleShot(600, self.show_onboarding)

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
        name = QLabel("Blue Cench Chat")
        name.setObjectName("SidebarBrand")
        self._brand_name = name
        brand.addWidget(name)
        brand.addStretch(1)
        sl.addLayout(brand)
        sl.addSpacing(16)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav: dict[str, NavButton] = {}
        self.pages: dict[str, QWidget] = {}
        self.stack = QStackedWidget()
        self.stack.setObjectName("Pages")
        for i, (key, text, ic, cls) in enumerate(NAV):
            if key == "profile":
                sl.addSpacing(10)
                eb = label("ACCOUNT", "eyebrow")
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
        out.clicked.connect(self.sign_out_requested.emit)
        ml.addWidget(out)
        sl.addWidget(me)
        lay.addWidget(side)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(root)
        self._me_out = out
        self._me_card = me
        self.refresh_identity()
        self._current = None
        self._compact = None
        self._apply_compact(self.width() < 1180)
        self.navigate("dashboard")

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
        self.me_avatar.set(acc.display_name, acc.avatar, True)
        self.me_name.setText(acc.display_name if not self.is_guest else f"{acc.display_name} (guest)")
        self.me_id.setText(acc.user_id)

    def apply_theme(self, rebuild: bool = False) -> None:
        s = self.node.settings
        theme.set_theme(s.get("theme", "dark"), s.get("font_scale", 100))
        icons.clear_cache()
        QApplication.instance().setStyleSheet(theme.stylesheet())
        if rebuild:
            current = self._current
            old = self.centralWidget()
            # disconnect page signal handlers by rebuilding the bridge
            self.bridge.detach()
            self.bridge.deleteLater()
            self.bridge = Bridge(self.node)
            self.bridge.error.connect(lambda t: self.toast(t, "error"))
            self.bridge.info.connect(self.toast)
            self.bridge.request_received.connect(self._on_request)
            self.bridge.transfer_offer.connect(self._on_offer)
            for sig in (self.bridge.notification_added, self.bridge.messages_changed, self.bridge.contacts_changed):
                sig.connect(lambda *_: self._schedule_badges())
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
