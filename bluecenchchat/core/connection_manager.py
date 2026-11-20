"""Session lifecycle, connection requests, trust and blocking.

Trust model
-----------
* A completed handshake proves *who* the peer is (their Blue Cench Chat ID is the
  hash of the key they proved possession of), but proves nothing about
  whether you want to talk to them.
* Unknown peers are "strangers": the only things they may send are a
  connection request or a reply to yours.  Everything else is dropped.
* A contact becomes "accepted" only after the receiving user explicitly
  accepts.  "Verified" is a separate, stronger flag set after comparing the
  safety number (or connecting through a pinned identity code).
* Blocked peers are disconnected immediately after the handshake.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from . import crypto
from .session import FT_CHUNK, FT_JSON, FT_MEDIA, PeerSession, ProtocolError
from .transports.base import Stream, TransportError

log = logging.getLogger("bluecenchchat.connections")

STRANGER_ALLOWED = {"conn_request", "conn_accept", "conn_reject", "bye", "ping", "pong"}


@dataclass
class ActiveSession:
    session: PeerSession
    contact_id: int
    transport: str
    task: asyncio.Task | None = None
    last_rx: float = field(default_factory=time.time)
    dropped: int = 0


class ConnectionManager:
    def __init__(self, node) -> None:
        self.node = node
        self.sessions: dict[str, ActiveSession] = {}  # peer user id -> session
        self.pins: dict[str, bytes] = {}  # peer user id -> identity pub pinned via identity code
        self._connecting: set[str] = set()
        self._attempts: dict[str, float] = {}
        self._keepalive: asyncio.Task | None = None
        self._reconnect: asyncio.Task | None = None
        self._incoming_by_host: dict[str, list[float]] = {}

    async def start(self) -> None:
        self._keepalive = asyncio.create_task(self._keepalive_loop())
        self._reconnect = asyncio.create_task(self._reconnect_loop())

    async def stop(self) -> None:
        for t in (self._keepalive, self._reconnect):
            if t:
                t.cancel()
        for s in list(self.sessions.values()):
            await s.session.close()
        self.sessions.clear()

    # -- queries -------------------------------------------------------------
    def session_for_contact(self, contact_id: int) -> ActiveSession | None:
        for s in self.sessions.values():
            if s.contact_id == contact_id:
                return s
        return None

    def is_online(self, contact_id: int) -> bool:
        return self.session_for_contact(contact_id) is not None

    # -- establishing ----------------------------------------------------------
    async def handle_incoming(self, stream: Stream) -> None:
        host = stream.remote_label.rsplit(":", 1)[0]
        now = time.time()
        hits = [t for t in self._incoming_by_host.get(host, []) if now - t < 60]
        if len(hits) >= 20:  # basic flood protection per remote host
            log.warning("rate limiting incoming connections from %s", host)
            await stream.close()
            return
        hits.append(now)
        self._incoming_by_host[host] = hits
        session = PeerSession(stream, self.node.identity, self.node.local_profile(), initiator=False)
        try:
            await session.handshake()
        except (ProtocolError, TransportError, crypto.CryptoError) as exc:
            log.info("incoming handshake failed from %s: %s", stream.remote_label, exc)
            self.node.repo.log("security", f"Rejected a connection from {stream.remote_label}: {exc}")
            await stream.close()
            return
        await self._register(session)

    async def connect(self, *, lan: tuple[str, int] | None = None, bt_addr: int | None = None,
                      prefer: str = "lan", expect_user_id: str | None = None,
                      pinned_pub: bytes | None = None) -> int:
        """Dial a peer and complete the handshake. Returns the contact id."""
        key = expect_user_id or (f"{lan}" if lan else str(bt_addr))
        if key in self._connecting:
            raise TransportError("Already connecting to this device")
        self._connecting.add(key)
        try:
            order = ["lan", "rfcomm"] if prefer == "lan" else ["rfcomm", "lan"]
            errors = []
            stream = None
            for kind in order:
                try:
                    if kind == "lan" and lan and self.node.lan.running:
                        stream = await self.node.lan.connect(*lan)
                    elif kind == "rfcomm" and bt_addr and self.node.settings.get("rfcomm_enabled", True):
                        stream = await self.node.rfcomm.connect(bt_addr)
                    if stream:
                        break
                except (TransportError, asyncio.TimeoutError, OSError) as exc:
                    errors.append(str(exc) or exc.__class__.__name__)
            if stream is None:
                raise TransportError("; ".join(errors) or "No usable transport for this device")
            session = PeerSession(stream, self.node.identity, self.node.local_profile(), initiator=True)
            try:
                peer = await session.handshake()
            except (ProtocolError, crypto.CryptoError) as exc:
                await stream.close()
                raise TransportError(f"Secure handshake failed: {exc}") from exc
            if expect_user_id and peer.user_id != expect_user_id:
                await session.close()
                raise TransportError("The device answered with a different Blue Cench Chat identity")
            if pinned_pub is not None:
                if not crypto.constant_time_eq(pinned_pub, peer.identity_pub):
                    await session.close()
                    self.node.notify("security", "Identity mismatch",
                                     "A device did not match the identity code you used. Connection closed.", "notify_security")
                    raise TransportError("Identity code does not match this device")
                self.pins[peer.user_id] = pinned_pub
            if bt_addr and stream.kind == "rfcomm":
                stream.remote_address = {"bt_addr": bt_addr}
            return await self._register(session)
        finally:
            self._connecting.discard(key)

    async def _register(self, session: PeerSession) -> int:
        peer = session.peer
        assert peer is not None
        repo = self.node.repo
        contact = repo.contact_by_peer(peer.user_id)
        if contact and contact.status == "blocked":
            repo.log("security", f"Blocked user {peer.user_id} tried to connect - disconnected")
            await session.close()
            raise TransportError("This user is blocked")

        address = dict(session.stream.remote_address)
        if peer.lan_port and "ip" in address:
            address["port"] = peer.lan_port
        if peer.bt_addr:
            address["bt_addr"] = peer.bt_addr
        fields = dict(
            username=peer.username,
            display_name=peer.display_name,
            last_seen=time.time(),
            last_transport=session.stream.kind,
            address=address,
        )
        if contact is None:
            fields["status"] = "stranger"
        if peer.user_id in self.pins:
            fields["verified"] = True
        contact = repo.upsert_contact(peer.user_id, peer.identity_pub, **fields)

        existing = self.sessions.get(peer.user_id)
        if existing and not existing.session.closed:
            # Deterministic tie-break when both sides dialled at the same time:
            # keep the session initiated by the lower Blue Cench Chat ID.
            me = self.node.identity.user_id
            lower = min(me, peer.user_id)
            new_init = me if session.initiator else peer.user_id
            if new_init != lower:
                await session.close()
                return contact.id
            old = existing
            self.sessions.pop(peer.user_id, None)
            if old.task:
                old.task.cancel()
            await old.session.close()

        active = ActiveSession(session, contact.id, session.stream.kind)
        self.sessions[peer.user_id] = active
        active.task = asyncio.create_task(self._reader(peer.user_id, active))
        self.node.discovery.refresh_contact_hints()
        self.node.bus.emit("contacts")
        self.node.bus.emit("session", contact.id, True)
        repo.log("connection", f"Secure session with {contact.name} over {self.node.transport_label(session.stream.kind)}")
        if contact.status == "accepted":
            try:  # tells a peer that is still waiting (we accepted while they were away)
                await session.send_json({"t": "conn_accept", **self.node.profile_card()})
            except Exception:
                pass
            await self.node.on_contact_online(contact.id)
            asyncio.ensure_future(self.node.mesh.on_session(contact))
        asyncio.ensure_future(self.node.social.on_session(contact.id))
        return contact.id

    # -- reader loop -----------------------------------------------------------
    async def _reader(self, peer_uid: str, active: ActiveSession) -> None:
        session = active.session
        reason = "disconnected"
        try:
            while True:
                ftype, payload = await session.recv()
                active.last_rx = time.time()
                contact = self.node.repo.contact(active.contact_id)
                if contact is None:
                    break
                if ftype == FT_MEDIA:
                    if contact.status == "accepted":
                        self.node.calls.on_media(contact, *payload)
                    continue
                if ftype == FT_CHUNK:
                    if contact.status != "accepted":
                        raise ProtocolError("file data from unaccepted peer")
                    await self.node.transfers.on_chunk(contact, *payload)
                    continue
                t = payload["t"]
                if t == "bye":
                    break
                if t == "ping":
                    await session.send_json({"t": "pong"})
                    continue
                if t == "pong":
                    continue
                if contact.status != "accepted" and t not in STRANGER_ALLOWED and not t.startswith("s_"):
                    active.dropped += 1
                    if active.dropped > 20:
                        raise ProtocolError("peer keeps sending without an accepted connection")
                    continue
                if t.startswith("conn_"):
                    await self._on_conn_message(contact, active, payload)
                elif t.startswith("s_"):
                    await self.node.social.on_message(contact, payload)
                elif t.startswith("call_"):
                    await self.node.calls.on_message(contact, payload)
                elif t.startswith("x_"):
                    await self.node.transfers.on_message(contact, payload)
                elif t == "relay":
                    await self.node.mesh.on_relay(contact, payload)
                else:
                    await self.node.messaging.on_message(contact, payload)
        except asyncio.CancelledError:
            return
        except (TransportError, ProtocolError, crypto.CryptoError) as exc:
            reason = str(exc)
            if isinstance(exc, (ProtocolError, crypto.CryptoError)):
                self.node.repo.log("security", f"Session with {peer_uid} closed: {exc}")
        except Exception as exc:  # defensive: never crash the app on a bad peer
            log.exception("session reader crashed")
            reason = f"internal error: {exc}"
        await self._closed(peer_uid, active, reason)

    async def _closed(self, peer_uid: str, active: ActiveSession, reason: str) -> None:
        if self.sessions.get(peer_uid) is active:
            del self.sessions[peer_uid]
        await active.session.close()
        self.node.transfers.on_session_lost(active.contact_id)
        self.node.calls.on_session_lost(active.contact_id)
        self.node.repo.set_contact(active.contact_id, last_seen=time.time())
        c = self.node.repo.contact(active.contact_id)
        if c and c.status == "accepted" and not self.session_for_contact(c.id):
            self.node.repo.log("connection", f"Disconnected from {c.name}")
            if reason not in ("disconnected", "connection closed by peer"):
                self.node.notify("disconnect", f"{c.name} disconnected", reason, "notify_requests", ref=str(c.id))
        self.node.bus.emit("session", active.contact_id, False)
        self.node.bus.emit("contacts")

    # -- requests --------------------------------------------------------------
    async def send_request(self, contact_id: int, note: str = "") -> None:
        s = self.session_for_contact(contact_id)
        c = self.node.repo.contact(contact_id)
        if not s or not c:
            raise TransportError("Not connected to this device")
        if c.status == "accepted":
            return
        acc = self.node.repo.account()
        await s.session.send_json({"t": "conn_request", "note": note[:200], "about": acc.about[:280]})
        self.node.repo.set_contact(contact_id, status="pending_out")
        self.node.repo.log("connection", f"Connection request sent to {c.name}")
        self.node.bus.emit("contacts")

    async def accept(self, contact_id: int) -> None:
        c = self.node.repo.contact(contact_id)
        if not c:
            return
        self.node.repo.set_contact(contact_id, status="accepted")
        s = self.session_for_contact(contact_id)
        if s:
            await s.session.send_json({"t": "conn_accept", **self.node.profile_card()})
        self.node.repo.log("connection", f"Accepted connection from {c.name}")
        self.node.discovery.refresh_contact_hints()
        self.node.bus.emit("contacts")
        if s:
            await self.node.on_contact_online(contact_id)

    async def reject(self, contact_id: int) -> None:
        c = self.node.repo.contact(contact_id)
        if not c:
            return
        self.node.repo.set_contact(contact_id, status="rejected")
        s = self.session_for_contact(contact_id)
        if s:
            try:
                await s.session.send_json({"t": "conn_reject"})
            finally:
                await self.disconnect(contact_id)
        self.node.bus.emit("contacts")

    async def _on_conn_message(self, contact, active: ActiveSession, msg: dict) -> None:
        t = msg["t"]
        repo = self.node.repo
        if t == "conn_request":
            if contact.status == "accepted":
                await active.session.send_json({"t": "conn_accept", **self.node.profile_card()})
                return
            if contact.status == "pending_out":
                # both asked each other - treat as mutual acceptance
                await self.accept(contact.id)
                return
            repo.set_contact(contact.id, status="pending_in", about=str(msg.get("about", ""))[:280])
            note = str(msg.get("note", ""))[:200]
            self.node.notify(
                "request", f"Connection request from {contact.name}",
                note or f"{contact.name} ({contact.peer_user_id}) wants to connect.", "notify_requests",
                ref=str(contact.id),
            )
            self.node.bus.emit("request", contact.id)
            self.node.bus.emit("contacts")
            if self.node.settings.get("auto_accept_verified") and contact.verified:
                await self.accept(contact.id)
        elif t == "conn_accept":
            if contact.status not in ("pending_out", "accepted"):
                return  # unsolicited accept - ignore
            self.node.apply_profile_card(contact.id, msg)
            was_pending = contact.status == "pending_out"
            repo.set_contact(contact.id, status="accepted")
            self.node.discovery.refresh_contact_hints()
            if was_pending:
                await active.session.send_json({"t": "conn_accept", **self.node.profile_card()})
                self.node.notify("accepted", f"{contact.name} accepted your request",
                                 "You can now chat and share files.", "notify_requests", ref=str(contact.id))
                repo.log("connection", f"{contact.name} accepted your connection request")
                await self.node.on_contact_online(contact.id)
            self.node.bus.emit("contacts")
        elif t == "conn_reject":
            if contact.status == "pending_out":
                repo.set_contact(contact.id, status="rejected")
                self.node.notify("rejected", f"{contact.name} declined your request", "", "notify_requests",
                                 ref=str(contact.id))
                self.node.bus.emit("contacts")

    # -- management ------------------------------------------------------------
    async def disconnect(self, contact_id: int) -> None:
        s = self.session_for_contact(contact_id)
        if s:
            if s.task:
                s.task.cancel()
            uid = s.session.peer.user_id if s.session.peer else None
            await self._closed(uid, s, "disconnected")

    async def block(self, contact_id: int) -> None:
        self.node.repo.set_contact(contact_id, status="blocked", favorite=False)
        c = self.node.repo.contact(contact_id)
        await self.disconnect(contact_id)
        self.node.transfers.cancel_all_for(contact_id)
        if c:
            self.node.repo.log("security", f"Blocked {c.name} ({c.peer_user_id})")
        self.node.bus.emit("contacts")

    def unblock(self, contact_id: int) -> None:
        self.node.repo.set_contact(contact_id, status="rejected")
        self.node.bus.emit("contacts")

    # -- background loops --------------------------------------------------------
    async def _keepalive_loop(self) -> None:
        while True:
            await asyncio.sleep(15)
            now = time.time()
            for uid, s in list(self.sessions.items()):
                try:
                    if now - s.last_rx > 50:
                        if s.task:
                            s.task.cancel()
                        await self._closed(uid, s, "connection timed out")
                    else:
                        await s.session.send_json({"t": "ping"})
                except Exception:
                    pass

    def route_pref(self, contact) -> str:
        """auto | lan | bt - how the user wants to reach this person."""
        r = (contact.address or {}).get("route", "auto") if contact else "auto"
        return r if r in ("auto", "lan", "bt") else "auto"

    def set_route_pref(self, contact_id: int, route: str) -> None:
        c = self.node.repo.contact(contact_id)
        if not c or route not in ("auto", "lan", "bt"):
            return
        self.node.repo.set_contact(contact_id, address={**(c.address or {}), "route": route})
        self.node.bus.emit("contacts")

    async def connect_contact(self, contact_id: int, via: str | None = None) -> int:
        """Connect to a known person nearby, over Wi-Fi/LAN ("lan") or Bluetooth ("bt")."""
        c = self.node.repo.contact(contact_id)
        if not c:
            raise TransportError("Unknown contact")
        if self.is_online(c.id):
            return c.id
        via = via or self.route_pref(c)
        route = self.node.discovery.find_contact_route(c)
        if route is None:
            raise TransportError(f"{c.name} isn't nearby right now. Make sure Blue Cench Chat is open on their "
                                 "device, with Bluetooth on or on the same Wi-Fi.")
        lan = (route.lan_ip, route.lan_port) if route.lan_ip and route.lan_port else None
        bt = route.bt_addr
        if via == "lan":
            bt = None
            if not lan:
                raise TransportError(f"{c.name} isn't on your Wi-Fi. Try Bluetooth.")
        elif via == "bt":
            lan = None
            if not bt:
                raise TransportError(f"{c.name} isn't reachable over Bluetooth. Try Wi-Fi.")
        self._attempts[c.peer_user_id] = time.time()
        return await self.connect(lan=lan, bt_addr=bt, prefer="rfcomm" if via == "bt" else "lan",
                                  expect_user_id=c.peer_user_id)

    async def _reconnect_loop(self) -> None:
        """Automatic reconnection to accepted contacts that are nearby (fast: every 5 s)."""
        while True:
            await asyncio.sleep(5)
            try:
                if not self.node.settings.get("auto_reconnect", True):
                    continue
                for c in self.node.repo.contacts(("accepted",)):
                    if self.is_online(c.id) or c.peer_user_id in self._connecting:
                        continue
                    if time.time() - self._attempts.get(c.peer_user_id, 0) < 15:
                        continue
                    route = self.node.discovery.find_contact_route(c)
                    if route is None or not route.transports:
                        continue
                    self._attempts[c.peer_user_id] = time.time()
                    lan = (route.lan_ip, route.lan_port) if route.lan_ip and route.lan_port else None
                    bt = route.bt_addr
                    pref = self.route_pref(c)
                    if pref == "lan":
                        bt = None
                    elif pref == "bt":
                        lan = None
                    if not lan and not bt:
                        continue
                    try:
                        await self.connect(lan=lan, bt_addr=bt, prefer="rfcomm" if pref == "bt" else "lan",
                                           expect_user_id=c.peer_user_id)
                    except Exception as exc:
                        log.debug("auto-reconnect to %s failed: %s", c.peer_user_id, exc)
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover
                log.exception("reconnect loop")
