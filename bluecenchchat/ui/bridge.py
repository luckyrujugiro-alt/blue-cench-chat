"""Bridges the asyncio engine (BlueCenchChatNode) and the Qt interface.

qasync runs asyncio *inside* the Qt event loop, so bus callbacks already run
on the GUI thread; this class simply re-emits them as Qt signals and offers
``run()`` to fire coroutines from button handlers with error reporting.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

from PySide6.QtCore import QObject, Signal

from ..core.node import BlueCenchChatNode

log = logging.getLogger("bluecenchchat.ui")


class Bridge(QObject):
    peers_changed = Signal()
    contacts_changed = Signal()
    session_changed = Signal(int, bool)
    request_received = Signal(int)
    message_received = Signal(int, str)
    messages_changed = Signal(int)
    typing = Signal(int, bool)
    transfer_changed = Signal(str)
    transfer_offer = Signal(str)
    notification_added = Signal()
    status_changed = Signal()
    web_changed = Signal()
    social_changed = Signal()
    call_changed = Signal(object)
    cloud_changed = Signal()
    error = Signal(str)
    info = Signal(str, str)  # text, tone

    def __init__(self, node: BlueCenchChatNode) -> None:
        super().__init__()
        self.node = node
        self._subs: list[tuple[str, object]] = []
        sub = self._sub
        sub("peers", self.peers_changed.emit)
        sub("contacts", self.contacts_changed.emit)
        sub("session", lambda cid, on: self.session_changed.emit(cid, on))
        sub("request", self.request_received.emit)
        sub("message", lambda cid, mid: self.message_received.emit(cid, mid))
        sub("messages", self.messages_changed.emit)
        sub("typing", lambda cid, on: self.typing.emit(cid, on))
        sub("transfer", self.transfer_changed.emit)
        sub("transfer_offer", self.transfer_offer.emit)
        sub("notification", lambda _n: self.notification_added.emit())
        sub("status", self.status_changed.emit)
        sub("web", self.web_changed.emit)
        sub("social", self.social_changed.emit)
        sub("call", self.call_changed.emit)
        sub("cloud", self.cloud_changed.emit)

    def _sub(self, event: str, cb) -> None:
        self.node.bus.on(event, cb)
        self._subs.append((event, cb))

    def detach(self) -> None:
        """Stop receiving engine events (window closing or being rebuilt)."""
        for event, cb in self._subs:
            self.node.bus.off(event, cb)
        self._subs.clear()

    def run(self, coro: Awaitable, on_done: Callable[[Any], None] | None = None,
            on_error: Callable[[Exception], None] | None = None) -> asyncio.Task:
        task = asyncio.ensure_future(coro)

        def _finish(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                log.info("action failed: %s", exc)
                if on_error:
                    on_error(exc)
                else:
                    self.error.emit(str(exc) or exc.__class__.__name__)
            elif on_done:
                on_done(t.result())

        task.add_done_callback(_finish)
        return task

    def toast(self, text: str, tone: str = "info") -> None:
        self.info.emit(text, tone)
