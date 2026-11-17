"""Blue Cench Chat - Connect Beyond Limits.

Entry point.  Usage:

    python main.py                      normal start
    python main.py --minimized          start in the tray (used by "Start with Windows")
    python main.py --profile alice      DEVELOPMENT TEST MODE: isolated data folder so two
                                        instances can run on one PC and talk over real sockets
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import logging.handlers
import os
import re
import sys
import traceback

from bluecenchchat import config


class _RedactFilter(logging.Filter):
    """Secure logging: never write recovery keys or identity codes to disk."""

    _patterns = [re.compile(r"bluecenchchat:[A-Za-z0-9_-]{20,}"), re.compile(r"\b([A-Z2-9]{4}-){4}[A-Z2-9]{4}\b")]

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        for p in self._patterns:
            msg = p.sub("[redacted]", msg)
        record.msg, record.args = msg, ()
        return True


def setup_logging() -> None:
    handler = logging.handlers.RotatingFileHandler(config.log_dir() / "bluecenchchat.log", maxBytes=2_000_000,
                                                   backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    handler.addFilter(_RedactFilter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if not getattr(sys, "frozen", False):
        console = logging.StreamHandler()
        console.addFilter(_RedactFilter())
        root.addHandler(console)

    def excepthook(et, ev, tb):
        logging.getLogger("bluecenchchat").critical("Unhandled error:\n%s", "".join(traceback.format_exception(et, ev, tb)))

    sys.excepthook = excepthook


def main() -> int:
    ap = argparse.ArgumentParser(description="Blue Cench Chat")
    ap.add_argument("--profile", help="development test mode: isolated data profile name")
    ap.add_argument("--minimized", action="store_true")
    args, _ = ap.parse_known_args()
    if args.profile:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,32}", args.profile):
            print("Profile names may contain letters, numbers, _ and - only")
            return 2
        config.set_profile(args.profile)
    setup_logging()
    log = logging.getLogger("bluecenchchat")
    log.info("Starting Blue Cench Chat %s (profile=%s)", config.APP_VERSION, config.profile())

    if sys.platform == "win32":
        import ctypes

        try:  # own taskbar identity + crisp text on high-DPI screens
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BlueCenchChat.Desktop")
        except Exception:
            pass

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QGuiApplication, QIcon
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication
    import qasync

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setOrganizationName(config.ORG_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    app.setWindowIcon(QIcon(str(config.resource_path("assets", "logo", "bluecenchchat.png"))))
    app.setQuitOnLastWindowClosed(False)
    f = QFont("Segoe UI")
    f.setPixelSize(13)
    app.setFont(f)

    # single instance per profile: a second launch just focuses the first window
    import getpass

    try:
        user = re.sub(r"[^A-Za-z0-9_-]", "_", getpass.getuser())
    except Exception:
        user = "user"
    server_name = f"bluecenchchat-{config.profile() or 'default'}-{user}"
    probe = QLocalSocket()
    probe.connectToServer(server_name)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        return 0
    QLocalServer.removeServer(server_name)
    server = QLocalServer()
    server.listen(server_name)

    from bluecenchchat.backend.backup import apply_pending_restore

    if apply_pending_restore():
        log.info("Backup restored")

    from bluecenchchat.app import AppController
    from bluecenchchat.ui import theme

    theme.set_theme("light")
    app.setStyleSheet(theme.stylesheet())

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    controller = AppController(app, start_minimized=args.minimized)
    server.newConnection.connect(lambda: (server.nextPendingConnection(), controller.bring_to_front()))
    with loop:
        loop.call_soon(controller.start)
        loop.run_until_complete(controller.finished)
    log.info("Blue Cench Chat closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
