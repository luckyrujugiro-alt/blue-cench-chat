"""Private one-to-one messaging with delivery/read receipts and offline queue."""
from __future__ import annotations

import asyncio
import base64
import logging
import time
import uuid

from .. import config
from . import voice

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
        self.node.social._check_not_suspended()
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

    async def send_voice(self, contact_id: int, pcm16: bytes, rate: int = voice.RATE) -> str:
        """Record -> send a voice message. Works over Bluetooth, Wi-Fi and online."""
        self.node.social._check_not_suspended()
        c = self.node.repo.contact(contact_id)
        if not c or c.status != "accepted":
            raise ValueError("You can only message accepted connections")
        ulaw = voice.encode(voice.resample_to_8k(pcm16, rate))[: voice.MAX_BYTES]
        if voice.duration(ulaw) < 0.5:
            raise ValueError("Voice message is too short - hold to record")
        mid = str(uuid.uuid4())
        voice.save(mid, ulaw)
        msg = self.node.repo.add_message(id=mid, contact_id=contact_id, direction="out", kind="voice",
                                         body=f"{voice.duration(ulaw):.1f}", status="queued")
        self.node.bus.emit("messages", contact_id)
        await self._deliver(msg)
        return msg.id

    async def _relay(self, contact_id: int, obj: dict) -> str:
        """Pick the best way to reach someone. Returns the route used ("" if none):
        "direct" (Bluetooth / Wi-Fi session), "online" (internet), or "mesh" (carried by friends nearby)."""
        s = self.node.connections.session_for_contact(contact_id)
        if s:
            await s.session.send_json(obj)
            return "direct"
        contact = self.node.repo.contact(contact_id)
        cloud = getattr(self.node, "cloud", None)
        if cloud is not None and await cloud.send(contact, obj):
            return "online"
        mesh = getattr(self.node, "mesh", None)
        if mesh is not None and obj.get("t") in ("msg", "ack", "read", "msg_del", "react") and await mesh.send(contact, obj):
            return "mesh"
        return ""

    async def _deliver(self, msg) -> None:
        try:
            payload = {"t": "msg", "id": msg.id, "text": msg.body, "reply_to": msg.reply_to, "ts": msg.ts}
            if msg.kind == "voice":
                audio = voice.load(msg.id)
                if audio is None:
                    self.node.repo.set_message(msg.id, status="failed")
                    return
                payload.update(kind="voice", audio=base64.b64encode(audio).decode(), text=msg.body)
            route = await self._relay(msg.contact_id, payload)
            if not route:
                return  # stays queued until the contact reconnects or we go online
            self.node.repo.set_message(msg.id, status="relayed" if route == "mesh" else "sent")
        except Exception as exc:
            log.info("send failed, keeping queued: %s", exc)
            self.node.repo.set_message(msg.id, status="queued")
            self._retry_soon(msg.contact_id)
        self.node.bus.emit("messages", msg.contact_id)

    def _retry_soon(self, contact_id: int) -> None:
        """A connection dropped mid-send (e.g. two devices dialled each other at once): try again shortly."""
        pending = self.__dict__.setdefault("_retrying", set())
        if contact_id in pending:
            return
        pending.add(contact_id)

        async def later():
            await asyncio.sleep(1.5)
            pending.discard(contact_id)
            if self.node.connections.session_for_contact(contact_id):
                await self.flush_queue(contact_id)
        asyncio.ensure_future(later())

    async def flush_queue(self, contact_id: int, resend_unconfirmed: bool = True) -> None:
        """Send everything waiting. Messages sent earlier but never confirmed are sent again;
        the receiver ignores duplicates (same message ID) and confirms them."""
        for m in self.node.repo.queued_messages(contact_id, include_unconfirmed=resend_unconfirmed):
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
            try:
                await self._relay(contact_id, {"t": "read", "ids": ids[:500]})
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
            try:
                await self._relay(m.contact_id, {"t": "msg_del", "id": msg_id})
            except Exception:
                pass
        self.node.bus.emit("messages", m.contact_id)

    async def react(self, msg_id: str, reaction: str) -> None:
        if reaction and reaction not in REACTIONS:
            return
        m = self.node.repo.message(msg_id)
        if not m:
            return
        reaction = "" if m.reaction == reaction else reaction
        self.node.repo.set_message(msg_id, reaction=reaction)
        try:
            await self._relay(m.contact_id, {"t": "react", "id": msg_id, "r": reaction})
        except Exception:
            pass
        self.node.bus.emit("messages", m.contact_id)

    # -- incoming ------------------------------------------------------------
    async def on_message(self, contact, msg: dict) -> None:
        t = msg["t"]
        repo = self.node.repo
        if t in ("msg", "react") and self.node.social.is_suspended(contact.peer_user_id):
            return  # messages from a suspended account are dropped (and not confirmed)
        if t == "msg":
            mid, text = msg.get("id"), msg.get("text")
            if not _valid_uuid(mid) or not isinstance(text, str) or not text or len(text) > config.MAX_TEXT_LEN:
                return
            reply_to = msg.get("reply_to") if _valid_uuid(msg.get("reply_to") or "") else None
            kind = "text"
            if msg.get("kind") == "voice":
                try:
                    audio = base64.b64decode(str(msg.get("audio", "")), validate=True)
                except Exception:
                    return
                if not audio or len(audio) > voice.MAX_BYTES:
                    return
                kind, text = "voice", f"{voice.duration(audio):.1f}"
            if repo.message(mid) is None:
                if kind == "voice":
                    voice.save(mid, audio)
                # use local receive time - never trust a peer's clock for ordering
                repo.add_message(id=mid, contact_id=contact.id, direction="in", kind=kind, body=text,
                                 reply_to=reply_to, status="received", ts=time.time())
                self.node.bus.emit("message", contact.id, mid)
                self.node.bus.emit("messages", contact.id)
                if self.active_contact != contact.id or not self.node.window_active():
                    preview = ("🎤 Voice message " + voice.fmt(float(text))) if kind == "voice" else (
                        text if len(text) < 90 else text[:87] + "...")
                    mentioned = kind == "text" and f"@{repo.account().username}".lower() in text.lower()
                    self.node.notify("message", f"{contact.name} mentioned you" if mentioned else contact.name,
                                     preview, "notify_messages", ref=str(contact.id), store=mentioned)
            try:
                await self._relay(contact.id, {"t": "ack", "id": mid})
            except Exception:
                pass
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
