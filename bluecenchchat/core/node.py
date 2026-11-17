"""BlueCenchChatNode - the running communication engine for one signed-in account.

The node owns the transports, discovery, connection manager, messaging and
transfer engine.  It is UI-agnostic: the Qt layer subscribes to ``bus``
events.  Tests run two nodes against each other over real sockets.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections import defaultdict
from typing import Callable

from .. import config
from ..backend.database import Database
from ..backend.user_service import UserRepository
from . import crypto
from .connection_manager import ConnectionManager
from .discovery_engine import DiscoveryEngine
from .calls import CallManager
from .messaging import MessagingService
from .social import SocialService
from .transfer_engine import TransferEngine
from .transports import bluetooth
from .transports.bluetooth import BleBeacon, RfcommTransport
from .transports.lan import LanTransport, local_ipv4_interfaces

log = logging.getLogger("bluecenchchat.node")

TRANSPORT_LABELS = {"lan": "Local Network", "rfcomm": "Bluetooth RFCOMM", "ble": "Bluetooth LE"}


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, list[Callable]] = defaultdict(list)

    def on(self, event: str, cb: Callable) -> None:
        self._subs[event].append(cb)

    def off(self, event: str, cb: Callable) -> None:
        try:
            self._subs[event].remove(cb)
        except ValueError:
            pass

    def emit(self, event: str, *args) -> None:
        for cb in list(self._subs.get(event, ())):
            try:
                cb(*args)
            except Exception:  # pragma: no cover - a UI bug must not kill the engine
                log.exception("event handler for %s failed", event)


class BlueCenchChatNode:
    def __init__(self, db: Database, account_id: int, identity: crypto.Identity,
                 beacon_port: int = config.LAN_BEACON_PORT) -> None:
        self.db = db
        self.repo = UserRepository(db, account_id)
        self.identity = identity
        self.bus = EventBus()
        self.settings = self.repo.settings()
        self.connections = ConnectionManager(self)
        self.discovery = DiscoveryEngine(self)
        self.messaging = MessagingService(self)
        self.transfers = TransferEngine(self)
        self.social = SocialService(self)
        self.calls = CallManager(self)
        self.lan = LanTransport(self.connections.handle_incoming, self.discovery.on_lan_beacon, beacon_port)
        self.rfcomm = RfcommTransport(self.connections.handle_incoming)
        self.ble = BleBeacon(self.discovery.on_ble_sighting)
        from ..web.companion import WebCompanion

        self.web = WebCompanion(self)
        self.adapter: bluetooth.AdapterInfo = bluetooth.AdapterInfo(False, "Not checked yet")
        self.started = False
        self.window_active: Callable[[], bool] = lambda: True
        self.on_notify: Callable | None = None  # UI hook for desktop notifications

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self._recover_stale_transfers()
        if self.settings.get("lan_enabled", True):
            try:
                await self.lan.start()
            except OSError as exc:
                self.lan.last_error = f"Local network transport failed: {exc}"
                log.warning(self.lan.last_error)
        self.adapter = await bluetooth.adapter_info()
        if self.adapter.available and self.adapter.radio_on and self.settings.get("rfcomm_enabled", True):
            await self.rfcomm.start()
        await self.discovery.start()
        await self.connections.start()
        self.apply_visibility()
        self.discovery.start_scan()
        if self.settings.get("web_enabled"):
            await self.web.start(self.settings.get("web_port", config.WEB_PORT))
        self.started = True
        self.repo.log("system", "Blue Cench Chat engine started")
        self.bus.emit("status")

    async def stop(self) -> None:
        await self.web.stop()
        self.ble.stop()
        await self.discovery.stop()
        await self.connections.stop()
        await self.lan.stop()
        await self.rfcomm.stop()
        self.started = False

    def _recover_stale_transfers(self) -> None:
        """After a crash/restart nothing is 'active' any more."""
        for t in self.repo.transfers(("active", "paused", "waiting", "preparing")):
            self.repo.set_transfer(t.id, status="interrupted", error="Application was closed - resumes on reconnect")

    async def refresh_adapter(self) -> bluetooth.AdapterInfo:
        self.adapter = await bluetooth.adapter_info()
        if self.adapter.available and self.adapter.radio_on and not self.rfcomm.running \
                and self.settings.get("rfcomm_enabled", True):
            await self.rfcomm.start()
        self.apply_visibility()
        self.bus.emit("status")
        return self.adapter

    # ------------------------------------------------------------------ identity
    def local_profile(self) -> dict:
        acc = self.repo.account()
        return {
            "username": acc.username,
            "display_name": acc.display_name,
            "lan_port": self.lan.port or None,
            "bt_addr": self.adapter.address if self.adapter.available else None,
        }

    def profile_card(self) -> dict:
        acc = self.repo.account()
        card = {"display_name": acc.display_name, "about": acc.about[:280]}
        if acc.avatar and len(acc.avatar) < 60_000:
            card["avatar"] = base64.b64encode(acc.avatar).decode()
        return card

    def apply_profile_card(self, contact_id: int, card: dict) -> None:
        fields = {}
        if isinstance(card.get("display_name"), str):
            fields["display_name"] = card["display_name"][:80]
        if isinstance(card.get("about"), str):
            fields["about"] = card["about"][:280]
        if isinstance(card.get("avatar"), str) and len(card["avatar"]) < 90_000:
            try:
                raw = base64.b64decode(card["avatar"], validate=True)
                if raw[:8] == b"\x89PNG\r\n\x1a\n":
                    fields["avatar"] = raw
            except ValueError:
                pass
        if fields:
            self.repo.set_contact(contact_id, **fields)
            self.bus.emit("contacts")

    async def broadcast_profile(self) -> None:
        card = {"t": "profile", **self.profile_card()}
        for s in list(self.connections.sessions.values()):
            c = self.repo.contact(s.contact_id)
            if c and c.status == "accepted":
                try:
                    await s.session.send_json(card)
                except Exception:
                    pass

    def identity_code(self) -> str:
        """Shareable code (also rendered as QR) for verified first contact."""
        acc = self.repo.account()
        ips = [ip for ip, _ in local_ipv4_interfaces()]
        payload = {
            "v": 1,
            "uid": self.identity.user_id,
            "pub": crypto.b64e(self.identity.public_bytes),
            "name": acc.display_name,
            "ip": ips[0] if ips else None,
            "port": self.lan.port or None,
            "bt": self.adapter.address if self.adapter.available else None,
        }
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return "bluecenchchat:" + base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @staticmethod
    def parse_identity_code(code: str) -> dict:
        code = code.strip()
        if not code.startswith("bluecenchchat:"):
            raise ValueError("Not a Blue Cench Chat identity code")
        b = code[len("bluecenchchat:"):]
        try:
            data = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
            pub = crypto.b64d(data["pub"])
        except Exception as exc:
            raise ValueError("Identity code is damaged") from exc
        if len(pub) != 32 or crypto.user_id_from_pub(pub) != data.get("uid"):
            raise ValueError("Identity code failed its integrity check")
        data["pub_bytes"] = pub
        return data

    async def connect_with_code(self, code: str) -> int:
        data = self.parse_identity_code(code)
        lan = (data["ip"], data["port"]) if data.get("ip") and data.get("port") else None
        cid = await self.connections.connect(lan=lan, bt_addr=data.get("bt"), expect_user_id=data["uid"],
                                             pinned_pub=data["pub_bytes"])
        return cid

    def safety_number(self, contact_id: int) -> str:
        c = self.repo.contact(contact_id)
        return crypto.safety_number(self.identity.public_bytes, c.identity_pub)

    # ------------------------------------------------------------------ settings
    def update_settings(self, **changes) -> None:
        self.settings = self.repo.save_settings(**changes)
        if {"visible", "ble_enabled", "lan_enabled"} & changes.keys():
            self.apply_visibility()
        if "web_enabled" in changes and self.started:
            if changes["web_enabled"]:
                asyncio.ensure_future(self.web.start(self.settings.get("web_port", config.WEB_PORT)))
            else:
                asyncio.ensure_future(self.web.stop())
        self.bus.emit("status")

    def apply_visibility(self) -> None:
        acc = self.repo.account()
        visible = self.settings.get("visible", True)
        hint = crypto.identity_hint(self.identity.public_bytes)
        if visible and self.lan.running:
            self.lan.set_beacon({
                "uid": self.identity.user_id, "hint": hint.hex(), "name": acc.display_name, "user": acc.username,
                "bt": self.adapter.address if self.adapter.available else 0, "rfcomm": self.rfcomm.running,
                # lets the Android app find this PC's phone access and pin its certificate
                "web": self.web.port if self.web.running else 0,
                "fp": self.web.fingerprint if self.web.running else "",
            })
        else:
            self.lan.set_beacon(None)
            self.lan.own_uid = self.identity.user_id
        if visible and self.settings.get("ble_enabled", True) and self.adapter.available and self.adapter.radio_on:
            ips = [ip for ip, _ in local_ipv4_interfaces()]
            payload = BleBeacon.encode(hint, self.lan.port, ips[0] if ips and self.lan.running else None,
                                       self.adapter.address, self.rfcomm.running)
            self.ble.start_publishing(payload)
        else:
            self.ble.stop_publishing()

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def transport_label(kind: str) -> str:
        return TRANSPORT_LABELS.get(kind, kind)

    def notify(self, kind: str, title: str, body: str, setting: str, ref: str = "", store: bool = True) -> None:
        n = self.repo.notify(kind, title, body, ref) if store else None
        if store:
            self.bus.emit("notification", n)
        if self.settings.get(setting, True) and self.on_notify:
            self.on_notify(kind, title, body, ref)

    async def on_contact_online(self, contact_id: int) -> None:
        await self.messaging.flush_queue(contact_id)
        await self.transfers.on_contact_online(contact_id)
        s = self.connections.session_for_contact(contact_id)
        if s:
            try:
                await s.session.send_json({"t": "profile", **self.profile_card()})
            except Exception:
                pass

    def status(self) -> dict:
        return {
            "adapter": self.adapter,
            "lan": self.lan.running,
            "lan_port": self.lan.port,
            "lan_error": self.lan.last_error,
            "rfcomm": self.rfcomm.running,
            "rfcomm_error": self.rfcomm.last_error,
            "ble_publishing": self.ble.publishing,
            "ble_scanning": self.ble.scanning,
            "ble_error": self.ble.last_error,
            "scanning": self.discovery.scanning,
            "visible": self.settings.get("visible", True),
            "sessions": len(self.connections.sessions),
            "ips": [ip for ip, _ in local_ipv4_interfaces()],
        }

    @staticmethod
    def battery() -> dict | None:
        try:
            import psutil

            b = psutil.sensors_battery()
            if b is None:
                return None
            return {"percent": b.percent, "plugged": b.power_plugged}
        except Exception:
            return None

    def low_battery(self) -> bool:
        b = self.battery()
        return bool(b and not b["plugged"] and b["percent"] < 20 and self.settings.get("battery_saver", True))
