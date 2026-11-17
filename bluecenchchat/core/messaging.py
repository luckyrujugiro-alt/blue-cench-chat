"""Private one-to-one messaging with delivery/read receipts and offline queue."""
from __future__ import annotations

import logging
import time
import uuid

from .. import config

log = logging.getLogger("bluecenchchat.messaging")

REACTIONS = ("thumbs-up", "heart", "laugh", "party-popper", "check", "flame")


def _valid_uuid(value) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


class MessagingService:
    def __init__(self, node) -> None:
        self.node = node
        self.active_contact: int | None = None  # conversation open in the UI
        self._typing_sent: dict[int, float] = {}

    async def send_text(self, contact_id: int, text: str, reply_to: str | None = None) -> str:
        text = text.strip()
        if not text:
            raise ValueError("Message is empty")
        if len(text) > config.MAX_TEXT_LEN:
            raise ValueError(f"Messages are limited to {config.MAX_TEXT_LEN} characters")
        c = self.node.repo.contact(contact_id)
        if not c or c.status != "accepted":
            raise ValueError("You can only message accepted connections")
        msg = self.node.repo.add_message(
            contact_id=contact_id, direction="out", kind="text", body=text, reply_to=reply_to, status="queued"
        )
        self.node.bus.emit("messages", contact_id)
        await self._deliver(msg)
        return msg.id

    async def _deliver(self, msg) -> None:
        s = self.node.connections.session_for_contact(msg.contact_id)
        if not s:
            return  # stays queued until the contact reconnects
        try:
            await s.session.send_json(
                {"t": "msg", "id": msg.id, "text": msg.body, "reply_to": msg.reply_to, "ts": msg.ts}
            )
            self.node.repo.set_message(msg.id, status="sent")
        except Exception as exc:
            log.info("send failed, keeping queued: %s", exc)
            self.node.repo.set_message(msg.id, status="queued")
        self.node.bus.emit("messages", msg.contact_id)

    async def flush_queue(self, contact_id: int) -> None:
        for m in self.node.repo.queued_messages(contact_id):
            await self._deliver(m)
        # re-send read receipts for anything read while offline is unnecessary;
        # unread incoming will be acknowledged when the chat is opened.

    async def file_note(self, contact_id: int, transfer_id: str, label: str, direction: str) -> None:
        self.node.repo.add_message(
            contact_id=contact_id, direction=direction, kind="file", body=label, transfer_id=transfer_id,
            status="sent" if direction == "out" else "read",
        )
        self.node.bus.emit("messages", contact_id)

    async def mark_read(self, contact_id: int) -> None:
        ids = self.node.repo.mark_incoming_read(contact_id)
        if ids:
            self.node.bus.emit("messages", contact_id)
            s = self.node.connections.session_for_contact(contact_id)
            if s:
                try:
                    await s.session.send_json({"t": "read", "ids": ids[:500]})
                except Exception:
                    pass

    async def set_typing(self, contact_id: int, on: bool) -> None:
        now = time.time()
        if on and now - self._typing_sent.get(contact_id, 0) < 3:
            return
        self._typing_sent[contact_id] = now if on else 0
        s = self.node.connections.session_for_contact(contact_id)
        if s:
            try:
                await s.session.send_json({"t": "typing", "on": bool(on)})
            except Exception:
                pass

    async def delete(self, msg_id: str, for_everyone: bool) -> None:
        m = self.node.repo.message(msg_id)
        if not m:
            return
        self.node.repo.set_message(msg_id, deleted=True)
        if for_everyone and m.direction == "out":
            s = self.node.connections.session_for_contact(m.contact_id)
            if s:
                await s.session.send_json({"t": "msg_del", "id": msg_id})
        self.node.bus.emit("messages", m.contact_id)

    async def react(self, msg_id: str, reaction: str) -> None:
        if reaction and reaction not in REACTIONS:
            return
        m = self.node.repo.message(msg_id)
        if not m:
            return
        reaction = "" if m.reaction == reaction else reaction
        self.node.repo.set_message(msg_id, reaction=reaction)
        s = self.node.connections.session_for_contact(m.contact_id)
        if s:
            await s.session.send_json({"t": "react", "id": msg_id, "r": reaction})
        self.node.bus.emit("messages", m.contact_id)

    # -- incoming ------------------------------------------------------------
    async def on_message(self, contact, msg: dict) -> None:
        t = msg["t"]
        repo = self.node.repo
        if t == "msg":
            mid, text = msg.get("id"), msg.get("text")
            if not _valid_uuid(mid) or not isinstance(text, str) or not text or len(text) > config.MAX_TEXT_LEN:
                return
            reply_to = msg.get("reply_to") if _valid_uuid(msg.get("reply_to") or "") else None
            if repo.message(mid) is None:
                # use local receive time - never trust a peer's clock for ordering
                repo.add_message(id=mid, contact_id=contact.id, direction="in", kind="text", body=text,
                                 reply_to=reply_to, status="received", ts=time.time())
                self.node.bus.emit("message", contact.id, mid)
                self.node.bus.emit("messages", contact.id)
                if self.active_contact != contact.id or not self.node.window_active():
                    preview = text if len(text) < 90 else text[:87] + "..."
                    self.node.notify("message", contact.name, preview, "notify_messages", ref=str(contact.id),
                                     store=False)
            s = self.node.connections.session_for_contact(contact.id)
            if s:
                await s.session.send_json({"t": "ack", "id": mid})
            if self.active_contact == contact.id and self.node.window_active():
                await self.mark_read(contact.id)
        elif t in ("ack", "read"):
            ids = msg.get("ids") if t == "read" else [msg.get("id")]
            if not isinstance(ids, list):
                return
            new_status = "delivered" if t == "ack" else "read"
            for mid in ids[:500]:
                m = repo.message(str(mid))
                if m and m.contact_id == contact.id and m.direction == "out":
                    if new_status == "delivered" and m.status == "read":
                        continue
                    repo.set_message(m.id, status=new_status)
            self.node.bus.emit("messages", contact.id)
        elif t == "typing":
            self.node.bus.emit("typing", contact.id, bool(msg.get("on")))
        elif t == "msg_del":
            m = repo.message(str(msg.get("id")))
            if m and m.contact_id == contact.id and m.direction == "in":
                repo.set_message(m.id, deleted=True)
                self.node.bus.emit("messages", contact.id)
        elif t == "react":
            m = repo.message(str(msg.get("id")))
            r = msg.get("r", "")
            if m and m.contact_id == contact.id and (r == "" or r in REACTIONS):
                repo.set_message(m.id, reaction=r)
                self.node.bus.emit("messages", contact.id)
        elif t == "profile":
            self.node.apply_profile_card(contact.id, msg)
