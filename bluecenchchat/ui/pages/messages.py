from __future__ import annotations

import time

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.messaging import REACTIONS
from .. import actions, icons, theme
from ..components.transfer_row import TransferRow
from ..components.widgets import (
    Avatar,
    EmptyState,
    Pill,
    SearchBox,
    button,
    clear_layout,
    human_time,
    icon_label,
    label,
    tool_button,
)
from ..dialogs.common import VerifyDialog, confirm

STATUS_ICON = {"queued": ("clock", "Queued - will send when connected"), "sent": ("check", "Sent"),
               "delivered": ("check-check", "Delivered"), "read": ("check-check", "Read"),
               "failed": ("circle-alert", "Failed")}


class Composer(QPlainTextEdit):
    def __init__(self, on_send, on_typing) -> None:
        super().__init__()
        self.on_send, self.on_typing = on_send, on_typing
        self.setPlaceholderText("Write a message")
        self.setFixedHeight(44)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.textChanged.connect(self._grow)

    def _grow(self) -> None:
        lines = max(1, min(6, int(self.document().size().height())))
        self.setFixedHeight(28 + lines * self.fontMetrics().lineSpacing())
        if self.toPlainText():
            self.on_typing()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.on_send()
            return
        super().keyPressEvent(e)


class MessageRow(QWidget):
    def __init__(self, chat: "ChatView", m, show_date: bool) -> None:
        super().__init__()
        self.chat, self.m, self.show_date = chat, m, show_date
        p = theme.palette()
        out = m.direction == "out"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(2)
        if show_date:
            d = label(time.strftime("%A, %d %B %Y", time.localtime(m.ts)), "faint")
            d.setAlignment(Qt.AlignmentFlag.AlignCenter)
            d.setContentsMargins(0, 10, 0, 6)
            lay.addWidget(d)
        row = QHBoxLayout()
        row.setSpacing(0)
        if m.kind == "call":
            pill = QFrame()
            pill.setObjectName("SoftCard")
            pl = QHBoxLayout(pill)
            pl.setContentsMargins(12, 6, 14, 6)
            pl.setSpacing(8)
            missed = m.body.startswith("Missed")
            pl.addWidget(icon_label("video" if "Video" in m.body else ("phone-incoming" if m.direction == "in"
                                                                     else "phone"), 15,
                                    p.danger if missed else p.muted))
            pl.addWidget(label(f"{m.body}  ·  {time.strftime('%H:%M', time.localtime(m.ts))}",
                               "muted" if not missed else None))
            row.addStretch(1)
            row.addWidget(pill)
            row.addStretch(1)
            lay.addLayout(row)
            return
        if m.kind == "file" and m.transfer_id:
            card = TransferRow(chat.bridge, m.transfer_id, compact=True)
            card.setMaximumWidth(520)
            chat.file_cards[m.transfer_id] = card
            content = card
        else:
            bubble = QFrame()
            bubble.setObjectName("BubbleOut" if out else "BubbleIn")
            bubble.setMaximumWidth(560)
            bl = QVBoxLayout(bubble)
            bl.setContentsMargins(13, 9, 13, 7)
            bl.setSpacing(4)
            if m.reply_to:
                orig = chat.node.repo.message(m.reply_to)
                q = QFrame()
                q.setObjectName("ReplyQuote")
                ql = QVBoxLayout(q)
                ql.setContentsMargins(8, 4, 8, 4)
                who = "You" if orig and orig.direction == "out" else chat.contact_name
                ql.addWidget(label(who, "faint"))
                qt = label((orig.body if orig and not orig.deleted else "Message deleted")[:140], wrap=True)
                qt.setTextFormat(Qt.TextFormat.PlainText)
                ql.addWidget(qt)
                bl.addWidget(q)
            text = label(m.body, wrap=True, selectable=True)
            text.setTextFormat(Qt.TextFormat.PlainText)
            longest = max((text.fontMetrics().horizontalAdvance(ln) for ln in m.body.splitlines() or [""]), default=0)
            text.setMinimumWidth(min(480, max(60, longest + 4)))
            text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
            bl.addWidget(text)
            meta = QHBoxLayout()
            meta.setSpacing(4)
            meta.addStretch(1)
            tl = QLabel(time.strftime("%H:%M", time.localtime(m.ts)))
            tl.setStyleSheet(f"color:{'rgba(255,255,255,0.7)' if out else p.faint}; font-size:{theme.px(11)}px;")
            meta.addWidget(tl)
            if out:
                ic, tip = STATUS_ICON.get(m.status, ("clock", m.status))
                color = "#7DE3F4" if m.status == "read" else ("#FCA5A5" if m.status == "failed" else "rgba(255,255,255,0.75)")
                s = QLabel()
                s.setPixmap(icons.pixmap(ic, 14, color if not color.startswith("rgba") else "#C9D6F2"))
                s.setToolTip(tip)
                meta.addWidget(s)
            bl.addLayout(meta)
            content = bubble
            bubble.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            bubble.customContextMenuRequested.connect(lambda pos, b=bubble: self._menu(b.mapToGlobal(pos)))
        if out:
            row.addStretch(1)
            row.addWidget(content)
        else:
            row.addWidget(content)
            row.addStretch(1)
        lay.addLayout(row)
        if m.reaction:
            rr = QHBoxLayout()
            chip = QLabel()
            chip.setPixmap(icons.pixmap(m.reaction, 14, p.warning if m.reaction in ("heart", "flame") else p.cyan))
            chip.setStyleSheet(f"background:{p.surface3}; border:1px solid {p.border}; border-radius:10px; padding:3px 7px;")
            chip.setToolTip(f"Reaction: {m.reaction}")
            if out:
                rr.addStretch(1)
                rr.addWidget(chip)
            else:
                rr.addWidget(chip)
                rr.addStretch(1)
            lay.addLayout(rr)

    def _menu(self, pos: QPoint) -> None:
        m, chat = self.m, self.chat
        menu = QMenu(self)
        menu.addAction(icons.plain("reply", 16), "Reply", lambda: chat.set_reply(m))
        menu.addAction(icons.plain("copy", 16), "Copy text", lambda: QGuiApplication.clipboard().setText(m.body))
        react = menu.addMenu(icons.plain("heart", 16), "React")
        for r in REACTIONS:
            react.addAction(icons.plain(r, 16), r.replace("-", " ").title(),
                            lambda r=r: chat.bridge.run(chat.node.messaging.react(m.id, r)))
        menu.addSeparator()
        menu.addAction(icons.plain("trash-2", 16), "Delete for me",
                       lambda: chat.bridge.run(chat.node.messaging.delete(m.id, False)))
        if m.direction == "out":
            def everyone():
                if confirm(chat, "Delete for everyone?", "The message is removed on both devices if the other "
                           "person is connected now.", "Delete", danger=True):
                    chat.bridge.run(chat.node.messaging.delete(m.id, True))
            menu.addAction(icons.plain("trash-2", 16, theme.palette().danger), "Delete for everyone", everyone)
        menu.exec(pos)

    def signature(self) -> tuple:
        return (self.m.status, self.m.reaction, self.m.deleted)


class ChatView(QWidget):
    def __init__(self, win, contact_id: int) -> None:
        super().__init__()
        self.win, self.node, self.bridge = win, win.node, win.bridge
        self.cid = contact_id
        self.reply_to = None
        self.rows: dict[str, MessageRow] = {}
        self.order: list[str] = []
        self.file_cards: dict[str, TransferRow] = {}
        self.setAcceptDrops(True)
        p = theme.palette()
        c = self.node.repo.contact(contact_id)
        self.contact_name = c.name
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QFrame()
        head.setObjectName("ChatHeader")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(20, 12, 14, 12)
        hl.setSpacing(12)
        self.avatar = Avatar(42)
        hl.addWidget(self.avatar)
        col = QVBoxLayout()
        col.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.name = label("", "h3")
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        top.addWidget(self.name)
        self.tick = icon_label("badge-check", 16, theme.VERIFIED_BLUE)
        self.tick.setToolTip("Verified by Blue Cench Chat")
        top.addWidget(self.tick)
        self.verified = icon_label("shield-check", 15, p.success)
        self.verified.setToolTip("You checked this person's safety number")
        top.addWidget(self.verified)
        self.enc = icon_label("lock", 13, p.faint)
        self.enc.setToolTip("End-to-end encrypted session (X25519 + Ed25519, ChaCha20-Poly1305)")
        top.addWidget(self.enc)
        top.addStretch(1)
        col.addLayout(top)
        self.status = label("", "muted")
        col.addWidget(self.status)
        hl.addLayout(col, 1)
        self.transport = Pill("", "cyan")
        hl.addWidget(self.transport)
        self.b_voice = tool_button("phone", "Voice call (Ctrl+Shift+V) - works over Bluetooth and Wi-Fi")
        self.b_video = tool_button("video", "Video call (Ctrl+Shift+E) - needs Wi-Fi / LAN")
        hl.addWidget(self.b_voice)
        hl.addWidget(self.b_video)
        self.b_voice.clicked.connect(lambda: win.start_call(self.cid, False))
        self.b_video.clicked.connect(lambda: win.start_call(self.cid, True))
        b_search = tool_button("search", "Search in conversation")
        b_files = tool_button("paperclip", "Send files")
        b_verify = tool_button("shield-check", "Verify safety number")
        b_more = tool_button("ellipsis-vertical", "More")
        for b in (b_search, b_files, b_verify, b_more):
            hl.addWidget(b)
        lay.addWidget(head)
        b_search.clicked.connect(self._toggle_search)
        b_files.clicked.connect(lambda: actions.send_files(win, self.cid))
        b_verify.clicked.connect(lambda: VerifyDialog(win, self.node, self.node.repo.contact(self.cid)).exec())
        b_more.clicked.connect(lambda: actions.contact_menu(win, self.node.repo.contact(self.cid), b_more).exec(
            b_more.mapToGlobal(QPoint(0, b_more.height()))))

        self.searchbar = QFrame()
        sl = QHBoxLayout(self.searchbar)
        sl.setContentsMargins(20, 8, 20, 8)
        self.search = SearchBox("Search messages")
        self.search.textChanged.connect(lambda _t: self.reload(full=True))
        sl.addWidget(self.search)
        self.searchbar.hide()
        lay.addWidget(self.searchbar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        host = QWidget()
        host.setObjectName("PageInner")
        self.msgs = QVBoxLayout(host)
        self.msgs.setContentsMargins(24, 16, 24, 16)
        self.msgs.setSpacing(4)
        self.msgs.addStretch(1)
        self.scroll.setWidget(host)
        lay.addWidget(self.scroll, 1)

        self.typing_lbl = label("", "faint")
        self.typing_lbl.setContentsMargins(24, 0, 0, 4)
        lay.addWidget(self.typing_lbl)
        self._typing_timer = QTimer(self)
        self._typing_timer.setSingleShot(True)
        self._typing_timer.timeout.connect(lambda: (self.typing_lbl.setText(""), self.update_header()))

        comp = QFrame()
        comp.setObjectName("Composer")
        cl = QVBoxLayout(comp)
        cl.setContentsMargins(16, 10, 16, 12)
        cl.setSpacing(6)
        self.reply_bar = QFrame()
        self.reply_bar.setObjectName("SoftCard")
        rb = QHBoxLayout(self.reply_bar)
        rb.setContentsMargins(10, 6, 6, 6)
        rb.addWidget(icon_label("reply", 15, p.cyan))
        self.reply_text = label("", "muted")
        self.reply_text.setTextFormat(Qt.TextFormat.PlainText)
        rb.addWidget(self.reply_text, 1)
        x = tool_button("x", "Cancel reply", 15)
        x.clicked.connect(lambda: self.set_reply(None))
        rb.addWidget(x)
        self.reply_bar.hide()
        cl.addWidget(self.reply_bar)
        row = QHBoxLayout()
        row.setSpacing(8)
        attach = tool_button("paperclip", "Attach files or a folder", 20)
        am = QMenu(attach)
        am.addAction(icons.plain("file", 16), "Files...", lambda: actions.send_files(win, self.cid))
        am.addAction(icons.plain("folder", 16), "Folder...", lambda: actions.send_files(win, self.cid, True))
        attach.clicked.connect(lambda: am.exec(attach.mapToGlobal(QPoint(0, -am.sizeHint().height()))))
        row.addWidget(attach, 0, Qt.AlignmentFlag.AlignBottom)
        self.edit = Composer(self.send, self._typing)
        row.addWidget(self.edit, 1)
        self.send_btn = button("", "send", "primary", "Send (Enter)")
        self.send_btn.setFixedSize(44, 44)
        self.send_btn.clicked.connect(self.send)
        row.addWidget(self.send_btn, 0, Qt.AlignmentFlag.AlignBottom)
        cl.addLayout(row)
        self.notice = label("", "faint", wrap=True)
        cl.addWidget(self.notice)
        lay.addWidget(comp)

        self.update_header()
        self.reload(full=True)
        QTimer.singleShot(50, self._to_bottom)

    # -- header ------------------------------------------------------------
    def update_header(self) -> None:
        c = self.node.repo.contact(self.cid)
        if c is None:
            return
        self.contact_name = c.name
        s = self.node.connections.session_for_contact(self.cid)
        self.avatar.set(c.name, c.avatar, s is not None, c.peer_user_id)
        self.name.setText(c.name)
        self.verified.setVisible(c.verified)
        self.tick.setVisible(self.node.social.is_verified(c))
        can_call = s is not None and c.status == "accepted"
        self.b_voice.setEnabled(can_call)
        self.b_video.setEnabled(can_call and s.transport == "lan")
        self.b_video.setToolTip("Video call (Ctrl+Shift+E)" if can_call and s.transport == "lan" else
                                "Video calls need both devices on the same Wi-Fi / LAN")
        if self.typing_lbl.text():
            pass
        elif s:
            self.status.setText(f"Online  |  {c.peer_user_id}")
        else:
            self.status.setText(f"Offline - last seen {human_time(c.last_seen)}")
        if s:
            self.transport.setText(self.node.transport_label(s.transport))
            self.transport.show()
        else:
            self.transport.hide()
        accepted = c.status == "accepted"
        self.edit.setEnabled(accepted)
        self.send_btn.setEnabled(accepted)
        if not accepted:
            self.notice.setText("You can message this person once your connection request is accepted.")
        elif not s:
            self.notice.setText("Offline - messages are queued and delivered automatically when you reconnect.")
        else:
            self.notice.setText("")

    def show_typing(self, on: bool) -> None:
        if on:
            self.typing_lbl.setText(f"{self.contact_name} is typing...")
            self._typing_timer.start(5000)
        else:
            self.typing_lbl.setText("")

    # -- messages ------------------------------------------------------------
    def _near_bottom(self) -> bool:
        sb = self.scroll.verticalScrollBar()
        return sb.maximum() - sb.value() < 120

    def _to_bottom(self) -> None:
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def reload(self, full: bool = False) -> None:
        q = self.search.text().strip() if self.searchbar.isVisible() else ""
        msgs = self.node.repo.messages(self.cid, search=q, limit=400)
        ids = [m.id for m in msgs]
        stick = self._near_bottom()
        if full or ids[: len(self.order)] != self.order:
            clear_layout(self.msgs)
            self.msgs.addStretch(1)
            self.rows, self.order, self.file_cards = {}, [], {}
            if q and not msgs:
                self.msgs.addWidget(label("No messages match your search.", "muted"))
        last_day = None
        if self.order:
            last_day = time.localtime(self.rows[self.order[-1]].m.ts).tm_yday
        for idx, m in enumerate(msgs):
            if m.id in self.rows:
                row = self.rows[m.id]
                if row.signature() != (m.status, m.reaction, m.deleted):
                    pos = self.msgs.indexOf(row)
                    new = MessageRow(self, m, show_date=row.show_date)
                    self.msgs.insertWidget(pos, new)
                    row.hide()
                    row.deleteLater()
                    self.rows[m.id] = new
                continue
            day = time.localtime(m.ts).tm_yday
            row = MessageRow(self, m, show_date=(day != last_day))
            last_day = day
            self.msgs.addWidget(row)
            self.rows[m.id] = row
            self.order.append(m.id)
            if m.direction == "out":
                stick = True
        if stick:
            QTimer.singleShot(30, self._to_bottom)

    def transfer_changed(self, tid: str) -> None:
        card = self.file_cards.get(tid)
        if card:
            card.refresh()

    def set_reply(self, m) -> None:
        self.reply_to = m
        if m is None:
            self.reply_bar.hide()
            return
        who = "yourself" if m.direction == "out" else self.contact_name
        self.reply_text.setText(f"Replying to {who}: {m.body[:90]}")
        self.reply_bar.show()
        self.edit.setFocus()

    def send(self) -> None:
        text = self.edit.toPlainText().strip()
        if not text:
            return
        reply = self.reply_to.id if self.reply_to else None
        self.edit.clear()
        self.set_reply(None)
        self.bridge.run(self.node.messaging.send_text(self.cid, text, reply), None,
                        lambda e: self.win.toast(str(e), "error"))
        self.bridge.run(self.node.messaging.set_typing(self.cid, False))

    def _typing(self) -> None:
        self.bridge.run(self.node.messaging.set_typing(self.cid, True))

    def _toggle_search(self) -> None:
        self.searchbar.setVisible(not self.searchbar.isVisible())
        if self.searchbar.isVisible():
            self.search.setFocus()
        else:
            self.search.clear()
            self.reload(full=True)

    # -- drag & drop -----------------------------------------------------------
    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            actions.send_paths(self.win, self.cid, paths)


class ConversationItem(QWidget):
    def __init__(self, node, c, last, unread: int) -> None:
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(10)
        lay.addWidget(Avatar(40).set(c.name, c.avatar, node.connections.is_online(c.id), c.peer_user_id))
        col = QVBoxLayout()
        col.setSpacing(1)
        top = QHBoxLayout()
        nm = label(c.name, "h3")
        nm.setTextFormat(Qt.TextFormat.PlainText)
        top.addWidget(nm, 1)
        if last:
            top.addWidget(label(human_time(last.ts), "faint"))
        col.addLayout(top)
        bot = QHBoxLayout()
        prev = "No messages yet"
        if last:
            prev = ("You: " if last.direction == "out" else "") + (f"File: {last.body}" if last.kind == "file" else last.body)
        pl = label(prev.replace("\n", " ")[:48], "muted")
        pl.setTextFormat(Qt.TextFormat.PlainText)
        bot.addWidget(pl, 1)
        if unread:
            bot.addWidget(Pill(str(unread), "primary"))
        col.addLayout(bot)
        lay.addLayout(col, 1)


class MessagesPage(QWidget):
    def __init__(self, win) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.win, self.node, self.bridge = win, win.node, win.bridge
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        left = QFrame()
        left.setObjectName("Sidebar")
        left.setFixedWidth(320)
        self._left = left
        ll = QVBoxLayout(left)
        ll.setContentsMargins(14, 20, 14, 14)
        ll.setSpacing(10)
        ll.addWidget(label("Messages", "h2"))
        self.search = SearchBox("Search conversations")
        self.search.textChanged.connect(lambda _t: self.refresh_list())
        ll.addWidget(self.search)
        self.list = QListWidget()
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.itemClicked.connect(lambda it: self.open(it.data(Qt.ItemDataRole.UserRole)))
        ll.addWidget(self.list, 1)
        lay.addWidget(left)
        self.stack = QStackedWidget()
        self.empty = EmptyState("message-square", "Your conversations",
                                "Choose a connection on the left. Messages are end-to-end encrypted and travel "
                                "directly between your devices - never through a server.")
        self.stack.addWidget(self.empty)
        lay.addWidget(self.stack, 1)
        self.chat: ChatView | None = None
        self.bridge.messages_changed.connect(self._on_messages)
        self.bridge.contacts_changed.connect(self._on_contacts)
        self.bridge.session_changed.connect(lambda cid, _on: self._on_contacts())
        self.bridge.typing.connect(self._on_typing)
        self.bridge.transfer_changed.connect(lambda tid: self.chat and self.chat.transfer_changed(tid))
        self._list_pending = False
        self.refresh_list()

    def set_compact(self, compact: bool) -> None:
        self._left.setFixedWidth(250 if compact else 320)

    def on_show(self) -> None:
        self.refresh_list()
        if self.chat:
            self.node.messaging.active_contact = self.chat.cid
            self.bridge.run(self.node.messaging.mark_read(self.chat.cid))

    def on_hide(self) -> None:
        self.node.messaging.active_contact = None

    def open(self, contact_id: int) -> None:
        if self.chat and self.chat.cid == contact_id:
            return
        c = self.node.repo.contact(contact_id)
        if c is None:
            return
        if self.chat:
            self.stack.removeWidget(self.chat)
            self.chat.deleteLater()
        self.chat = ChatView(self.win, contact_id)
        self.stack.addWidget(self.chat)
        self.stack.setCurrentWidget(self.chat)
        self.node.messaging.active_contact = contact_id
        self.bridge.run(self.node.messaging.mark_read(contact_id))
        self.chat.edit.setFocus()
        self.refresh_list()

    def _on_messages(self, cid: int) -> None:
        if self.chat and self.chat.cid == cid:
            self.chat.reload()
            if self.isVisible() and self.win.isActiveWindow():
                unread = any(m.direction == "in" and m.status != "read" for m in self.node.repo.messages(cid, limit=20))
                if unread:
                    self.bridge.run(self.node.messaging.mark_read(cid))
        self._schedule_list()

    def _on_contacts(self) -> None:
        if self.chat:
            if self.node.repo.contact(self.chat.cid) is None:
                self.stack.setCurrentWidget(self.empty)
                self.chat.deleteLater()
                self.chat = None
            else:
                self.chat.update_header()
        self._schedule_list()

    def _on_typing(self, cid: int, on: bool) -> None:
        if self.chat and self.chat.cid == cid:
            self.chat.show_typing(on)

    def _schedule_list(self) -> None:
        if not self._list_pending:
            self._list_pending = True
            QTimer.singleShot(200, self.refresh_list)

    def refresh_list(self) -> None:
        self._list_pending = False
        q = self.search.text().strip().lower()
        sel = self.chat.cid if self.chat else None
        self.list.clear()
        for c, last, unread in self.node.repo.conversations():
            if q and q not in c.name.lower() and q not in c.username.lower():
                continue
            it = QListWidgetItem()
            it.setData(Qt.ItemDataRole.UserRole, c.id)
            w = ConversationItem(self.node, c, last, unread)
            it.setSizeHint(QSize(280, 62))
            self.list.addItem(it)
            self.list.setItemWidget(it, w)
            if c.id == sel:
                it.setSelected(True)
        if self.list.count() == 0:
            it = QListWidgetItem("No conversations. Accept or send a connection request first.")
            it.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(it)
