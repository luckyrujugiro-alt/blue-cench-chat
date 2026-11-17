"""Application controller: sign-in -> engine start -> main window -> sign-out."""
from __future__ import annotations

import asyncio
import logging

from PySide6.QtWidgets import QApplication

from . import config
from .backend import secure_store
from .backend.authentication import AuthService
from .backend.database import Database
from .backend.models import Account
from .core import crypto
from .core.node import BlueCenchChatNode
from .ui import icons, theme
from .ui.auth_window import AuthWindow
from .ui.main_window import MainWindow

log = logging.getLogger("bluecenchchat.app")


class AppController:
    def __init__(self, app: QApplication, start_minimized: bool = False) -> None:
        self.app = app
        self.start_minimized = start_minimized
        self.db = Database(config.db_path())
        self.auth = AuthService(self.db)
        self.auth.purge_guests()  # guests never survive a restart
        self.node: BlueCenchChatNode | None = None
        self.window: MainWindow | None = None
        self.auth_window: AuthWindow | None = None
        self.guest_account: int | None = None
        self.finished: asyncio.Future = asyncio.get_event_loop().create_future()

    def start(self) -> None:
        remembered = secure_store.load()
        if remembered:
            account_id, raw = remembered
            with self.db.session() as s:
                acc = s.get(Account, account_id)
            if acc is not None and not acc.is_guest:
                ident = crypto.Identity.from_bytes(raw)
                if ident.public_bytes == acc.identity_pub:
                    asyncio.ensure_future(self._enter(account_id, ident, False, False))
                    return
            secure_store.clear()
        self.show_auth()

    def show_auth(self) -> None:
        theme.set_theme("light")
        icons.clear_cache()
        self.app.setStyleSheet(theme.stylesheet())
        self.auth_window = AuthWindow(self.auth)
        self.auth_window.authenticated.connect(
            lambda aid, ident, guest, remember: asyncio.ensure_future(self._enter(aid, ident, guest, remember)))
        self.auth_window.on_user_close = lambda: asyncio.ensure_future(self.quit())
        self.auth_window.show()

    def bring_to_front(self) -> None:
        w = self.window or self.auth_window
        if w:
            w.showNormal()
            w.raise_()
            w.activateWindow()

    async def _enter(self, account_id: int, ident: crypto.Identity, guest: bool, remember: bool) -> None:
        if remember:
            secure_store.save(account_id, ident.private_bytes())
        self.guest_account = account_id if guest else None
        self.node = BlueCenchChatNode(self.db, account_id, ident)
        s = self.node.settings
        theme.set_theme(s.get("theme", "light"), s.get("font_scale", 100))
        icons.clear_cache()
        self.app.setStyleSheet(theme.stylesheet())
        try:
            await self.node.start()
        except Exception:
            log.exception("engine start failed")
        self.window = MainWindow(self.node, guest)
        self.window.sign_out_requested.connect(lambda: asyncio.ensure_future(self.sign_out()))
        self.window.quit_requested.connect(lambda: asyncio.ensure_future(self.quit()))
        if self.start_minimized and not guest:
            self.start_minimized = False
        else:
            self.window.show()
        if self.auth_window:
            self.auth_window._closing_after_login = True
            self.auth_window.close()
            self.auth_window.deleteLater()
            self.auth_window = None
        self.node.repo.log("security", f"Signed in on this PC{' as guest' if guest else ''}")

    async def _shutdown_session(self) -> None:
        if self.window:
            self.window.teardown()
        if self.node:
            await self.node.stop()
        if self.window:
            self.window.hide()
            self.window.deleteLater()
            self.window = None
        if self.guest_account:
            self.auth.delete_account(self.guest_account)
            self.guest_account = None
        self.node = None

    async def sign_out(self) -> None:
        secure_store.clear()
        await self._shutdown_session()
        self.show_auth()

    async def quit(self) -> None:
        await self._shutdown_session()
        self.db.dispose()
        if not self.finished.done():
            self.finished.set_result(True)
