"""Voice and video calls over the encrypted peer session.

* Voice works over Bluetooth RFCOMM *and* the local network.  Audio is raw
  16-bit mono PCM in 40 ms packets: 8 kHz on Bluetooth (16 KB/s - well inside
  RFCOMM's real throughput) and 16 kHz on the local network.
* Video needs the local network (Wi-Fi / Ethernet / Mobile Hotspot): frames
  are JPEG at ~12 fps, far more than Bluetooth can carry.  Asking for video on
  a Bluetooth link is refused with a clear message.
* Voice also works over the INTERNET (online mode) when the two people aren't nearby:
  signalling goes through the sealed online mailbox, audio through cloud.OnlineCallLink
  (8 kHz mu-law, end-to-end encrypted with a per-call key sent inside the sealed invite).
* Signalling: call_invite -> call_accept | call_decline | call_busy, call_end.
* Media frames are only accepted from the peer of the active call.

The engine is device-free: the desktop UI captures/plays audio and video and
feeds bytes in/out, so calls are testable without microphones.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import time
import uuid
from dataclasses import dataclass, field

log = logging.getLogger("bluecenchchat.calls")

RING_TIMEOUT = 45
AUDIO = 1
VIDEO = 2


@dataclass
class Call:
    id: str
    contact_id: int
    video: bool
    outgoing: bool
    state: str  # ringing | active | ended
    transport: str
    rate: int
    created: float = field(default_factory=time.time)
    started: float = 0.0
    ended_reason: str = ""
    seq: int = 0
    rx_bytes: int = 0
    camera_off: bool = False
    key: bytes = b""          # online calls: per-call encryption key

    @property
    def online(self) -> bool:
        return self.transport == "online"

    @property
    def duration(self) -> float:
        return (time.time() - self.started) if self.started else 0.0


def fmt_duration(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}" if sec < 3600 else f"{sec // 3600}:{(sec % 3600) // 60:02d}:{sec % 60:02d}"


class CallManager:
    def __init__(self, node) -> None:
        self.node = node
        self.current: Call | None = None
        self._timer: asyncio.Task | None = None
        self.on_audio = None   # callback(bytes) set by the UI
        self.on_video = None   # callback(bytes) set by the UI
        self._link = None      # OnlineCallLink for internet calls
        self._ulaw_buf = bytearray()

    def _session(self, contact_id: int):
        s = self.node.connections.session_for_contact(contact_id)
        return s

    def _emit(self) -> None:
        self.node.bus.emit("call", self.current)

    # ------------------------------------------------------------------ outgoing
    async def start(self, contact_id: int, video: bool) -> Call:
        c = self.node.repo.contact(contact_id)
        if not c or c.status != "accepted":
            raise ValueError("You can only call accepted connections")
        if self.current and self.current.state != "ended":
            raise ValueError("You are already in a call")
        s = self._session(contact_id)
        cloud = getattr(self.node, "cloud", None)
        if s is None:
            if cloud is None or not cloud.can_reach(c):
                raise ValueError(f"{c.name} isn't nearby and isn't reachable online. Connect over Bluetooth or "
                                 "Wi-Fi, or make sure you're both online.")
            if video:
                raise ValueError("Video calls need you both on the same Wi-Fi or hotspot. Over the internet "
                                 "you can make a voice call.")
            call = Call(str(uuid.uuid4()), contact_id, False, True, "ringing", "online", 8000, key=os.urandom(32))
            self.current = call
            ok = await cloud.send(c, {"t": "call_invite", "id": call.id, "video": False, "rate": 8000,
                                      "key": base64.b64encode(call.key).decode()})
            if not ok:
                self.current = None
                raise ValueError("Couldn't reach them online - check your internet and try again.")
            self._arm_timeout(call)
            self._emit()
            return call
        if video and s.transport != "lan":
            raise ValueError("Video calls need Wi-Fi or a hotspot (local network). This connection is Bluetooth, "
                             "so start a voice call instead.")
        rate = 16000 if s.transport == "lan" else 8000
        call = Call(str(uuid.uuid4()), contact_id, video, True, "ringing", s.transport, rate)
        self.current = call
        await s.session.send_json({"t": "call_invite", "id": call.id, "video": video, "rate": rate})
        self._arm_timeout(call)
        self._emit()
        return call

    def _arm_timeout(self, call: Call) -> None:
        if self._timer:
            self._timer.cancel()

        async def ring_timeout():
            await asyncio.sleep(RING_TIMEOUT)
            if self.current is call and call.state == "ringing":
                if call.outgoing:
                    await self._send(call, {"t": "call_end", "id": call.id})
                self._finish(call, "No answer" if call.outgoing else "Missed")

        self._timer = asyncio.ensure_future(ring_timeout())

    # ------------------------------------------------------------------ incoming
    async def accept(self) -> None:
        call = self.current
        if not call or call.outgoing or call.state != "ringing":
            return
        call.state, call.started = "active", time.time()
        await self._send(call, {"t": "call_accept", "id": call.id})
        self._open_link(call)
        self._emit()

    async def decline(self) -> None:
        call = self.current
        if not call or call.state != "ringing":
            return
        await self._send(call, {"t": "call_decline" if not call.outgoing else "call_end", "id": call.id})
        self._finish(call, "Declined" if not call.outgoing else "Cancelled")

    async def hangup(self) -> None:
        call = self.current
        if not call or call.state == "ended":
            return
        await self._send(call, {"t": "call_end", "id": call.id})
        self._finish(call, "Ended")

    async def _send(self, call: Call, obj: dict) -> None:
        if call.online:
            c = self.node.repo.contact(call.contact_id)
            if c is not None:
                try:
                    await self.node.cloud.send(c, obj)
                except Exception:
                    pass
            return
        s = self._session(call.contact_id)
        if s:
            try:
                await s.session.send_json(obj)
            except Exception:
                pass

    def _finish(self, call: Call, reason: str) -> None:
        if call.state == "ended":
            return
        was_active = call.state == "active"
        call.state, call.ended_reason = "ended", reason
        if self._timer:
            self._timer.cancel()
        if self._link is not None:
            asyncio.ensure_future(self._link.close())
            self._link = None
        kind = "Video call" if call.video else "Voice call"
        if was_active:
            text = f"{kind} · {fmt_duration(call.duration)}"
        elif reason == "Missed":
            text = f"Missed {kind.lower()}"
            c = self.node.repo.contact(call.contact_id)
            self.node.notify("call_missed", f"Missed {kind.lower()}", c.name if c else "", "notify_messages",
                             ref=str(call.contact_id))
        else:
            text = f"{kind} · {reason.lower()}"
        self.node.repo.add_message(contact_id=call.contact_id, direction="out" if call.outgoing else "in",
                                   kind="call", body=text, status="read")
        self.node.bus.emit("messages", call.contact_id)
        self._emit()

    # ------------------------------------------------------------------ media
    async def send_audio(self, pcm: bytes) -> None:
        await self._send_media(AUDIO, pcm)

    async def send_video(self, jpeg: bytes) -> None:
        call = self.current
        if call and call.video and not call.camera_off:
            await self._send_media(VIDEO, jpeg)

    async def _send_media(self, kind: int, data: bytes) -> None:
        call = self.current
        if not call or call.state != "active" or len(data) > 900_000:
            return
        if call.online:
            if kind == AUDIO and self._link is not None:
                from . import voice
                self._ulaw_buf += voice.encode(data)
                frame = 8 * self._link.FRAME_MS
                while len(self._ulaw_buf) >= frame:
                    self._link.send(AUDIO, bytes(self._ulaw_buf[:frame]))
                    del self._ulaw_buf[:frame]
            return
        s = self._session(call.contact_id)
        if not s:
            return
        call.seq += 1
        try:
            await s.session.send_media(kind, call.seq, data)
        except Exception:
            pass

    def on_media(self, contact, kind: int, seq: int, data: bytes) -> None:
        call = self.current
        if not call or call.state != "active" or call.contact_id != contact.id:
            return
        call.rx_bytes += len(data)
        if kind == AUDIO and self.on_audio:
            self.on_audio(data)
        elif kind == VIDEO and call.video and self.on_video:
            self.on_video(data)

    def _open_link(self, call: Call) -> None:
        if not call.online or self._link is not None:
            return
        from .cloud import OnlineCallLink
        from . import voice

        c = self.node.repo.contact(call.contact_id)
        fuid = (c.address or {}).get("fuid") if c else None
        if not fuid:
            return
        self._ulaw_buf.clear()

        def on_frame(kind: int, seq: int, data: bytes) -> None:
            if kind == AUDIO and c is not None:
                self.on_media(c, AUDIO, seq, voice.decode(data))

        self._link = OnlineCallLink(self.node.cloud, call.id, fuid, call.key, on_frame)
        self._link.start()

    # ------------------------------------------------------------------ signalling
    async def on_message(self, contact, msg: dict, via: str = "session") -> None:
        t, cid = msg["t"], str(msg.get("id", ""))[:36]
        call = self.current
        if t == "call_invite" and via == "online":
            busy = call is not None and call.state != "ended"
            try:
                key = base64.b64decode(str(msg.get("key", "")))
            except ValueError:
                key = b""
            if len(key) != 32 or not cid:
                return
            if busy:
                await self.node.cloud.send(contact, {"t": "call_busy", "id": cid})
                return
            self.current = Call(cid, contact.id, False, False, "ringing", "online", 8000, key=key)
            self._arm_timeout(self.current)
            self.node.notify("call", "Incoming voice call", contact.name, "notify_messages",
                             ref=str(contact.id), store=False)
            self._emit()
            return
        if t == "call_invite":
            s = self._session(contact.id)
            busy = call is not None and call.state != "ended"
            if busy or s is None:
                if s:
                    await s.session.send_json({"t": "call_busy", "id": cid})
                return
            video = bool(msg.get("video")) and s.transport == "lan"
            rate = 16000 if msg.get("rate") == 16000 else 8000
            self.current = Call(cid, contact.id, video, False, "ringing", s.transport, rate)
            self._arm_timeout(self.current)
            self.node.notify("call", f"Incoming {'video' if video else 'voice'} call", contact.name,
                             "notify_messages", ref=str(contact.id), store=False)
            self._emit()
            return
        if not call or call.id != cid or call.contact_id != contact.id:
            return
        if t == "call_accept" and call.outgoing and call.state == "ringing":
            call.state, call.started = "active", time.time()
            if self._timer:
                self._timer.cancel()
            self._open_link(call)
            self._emit()
        elif t == "call_decline":
            self._finish(call, "Declined")
        elif t == "call_busy":
            self._finish(call, "Busy")
        elif t == "call_end":
            self._finish(call, "Ended" if call.state == "active" else ("Missed" if not call.outgoing else "Cancelled"))
        elif t == "call_camera":
            call.camera_off = not bool(msg.get("on", True))
            self._emit()

    async def set_camera(self, on: bool) -> None:
        call = self.current
        if call and call.video:
            call.camera_off = not on
            await self._send(call, {"t": "call_camera", "id": call.id, "on": on})
            self._emit()

    def on_session_lost(self, contact_id: int) -> None:
        call = self.current
        if call and call.contact_id == contact_id and call.state != "ended" and not call.online:
            self._finish(call, "Connection lost" if call.state == "active" else
                         ("Missed" if not call.outgoing else "Connection lost"))
