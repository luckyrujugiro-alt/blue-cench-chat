"""Discovery engine: merges BLE, LAN and paired-RFCOMM sightings into one list.

Discovery is *not* identity verification.  A beacon only says "a Blue Cench Chat
instance with identity hint X is nearby and reachable at Y".  The real
identity is proven during the session handshake (Ed25519 signature over the
transcript) and the hint is re-checked against the proven key.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from .. import config
from . import crypto
from .transports import bluetooth

log = logging.getLogger("bluecenchchat.discovery")


@dataclass
class NearbyPeer:
    key: str
    hint: str = ""
    user_id: str = ""
    name: str = ""
    username: str = ""
    lan_ip: str | None = None
    lan_port: int | None = None
    bt_addr: int | None = None
    rssi: int | None = None
    rfcomm: bool = False
    sources: set = field(default_factory=set)
    last_seen: float = 0.0
    paired_only: bool = False

    @property
    def transports(self) -> list[str]:
        t = []
        if self.lan_ip and self.lan_port:
            t.append("lan")
        if self.bt_addr and (self.rfcomm or self.paired_only):
            t.append("rfcomm")
        return t

    @property
    def signal_bars(self) -> int:
        if self.rssi is None:
            return 0
        if self.rssi >= -60:
            return 4
        if self.rssi >= -70:
            return 3
        if self.rssi >= -80:
            return 2
        return 1

    def display_name(self) -> str:
        return self.name or self.username or (f"Blue Cench Chat user {self.hint[:6].upper()}" if self.hint else "Blue Cench Chat device")


class DiscoveryEngine:
    def __init__(self, node) -> None:
        self.node = node
        self.peers: dict[str, NearbyPeer] = {}
        self.scanning = False
        self._task: asyncio.Task | None = None
        self._paired_task: asyncio.Task | None = None
        self._hint_map: dict[str, int] = {}

    # -- lifecycle -----------------------------------------------------------
    def refresh_contact_hints(self) -> None:
        self._hint_map = {crypto.identity_hint(c.identity_pub).hex(): c.id for c in self.node.repo.contacts()}

    def contact_for_hint(self, hint: str) -> int | None:
        return self._hint_map.get(hint)

    async def start(self) -> None:
        self.refresh_contact_hints()
        self._task = asyncio.create_task(self._prune_loop())

    async def stop(self) -> None:
        self.stop_scan()
        if self._task:
            self._task.cancel()

    def start_scan(self) -> None:
        if self.scanning:
            return
        self.scanning = True
        self.node.ble.start_scanning()
        self._paired_task = asyncio.create_task(self._paired_loop())
        self.node.bus.emit("status")

    def stop_scan(self) -> None:
        self.scanning = False
        self.node.ble.stop_scanning()
        if self._paired_task:
            self._paired_task.cancel()
            self._paired_task = None
        self.node.bus.emit("status")

    def clear(self) -> None:
        self.peers.clear()
        self.node.bus.emit("peers")

    # -- inputs --------------------------------------------------------------
    def on_lan_beacon(self, msg: dict, ip: str) -> None:
        if not self.scanning:
            return
        hint = str(msg.get("hint", ""))[:16]
        if len(hint) != 16:
            return
        p = self.peers.setdefault(hint, NearbyPeer(key=hint, hint=hint))
        p.user_id = str(msg.get("uid", ""))[:20]
        p.name = str(msg.get("name", ""))[:80]
        p.username = str(msg.get("user", ""))[:32]
        port = msg.get("port")
        if isinstance(port, int) and 0 < port < 65536:
            p.lan_ip, p.lan_port = ip, port
        bt = msg.get("bt")
        if isinstance(bt, int) and bt > 0:
            p.bt_addr = bt
            p.rfcomm = bool(msg.get("rfcomm"))
        p.sources.add("lan")
        p.last_seen = time.time()
        self._merge_paired(p)
        self.node.bus.emit("peers")

    def on_ble_sighting(self, info: dict) -> None:
        if not self.scanning:
            return
        hint = info["hint"]
        p = self.peers.setdefault(hint, NearbyPeer(key=hint, hint=hint))
        p.rssi = info.get("rssi")
        if info.get("lan_ip") and info.get("lan_port"):
            p.lan_ip, p.lan_port = info["lan_ip"], info["lan_port"]
        if info.get("bt_addr"):
            p.bt_addr = info["bt_addr"]
        p.rfcomm = p.rfcomm or info.get("rfcomm", False)
        p.sources.add("ble")
        p.last_seen = time.time()
        self._merge_paired(p)
        self.node.bus.emit("peers")

    def _merge_paired(self, p: NearbyPeer) -> None:
        if p.bt_addr:
            dup = self.peers.pop(f"bt:{p.bt_addr}", None)
            if dup:
                p.sources.add("paired")

    async def _paired_loop(self) -> None:
        while self.scanning:
            try:
                for d in await bluetooth.bluecenchchat_rfcomm_peers():
                    if any(pp.bt_addr == d["bt_addr"] for pp in self.peers.values() if pp.hint):
                        continue
                    key = f"bt:{d['bt_addr']}"
                    p = self.peers.setdefault(key, NearbyPeer(key=key, paired_only=True))
                    p.name = d["name"]
                    p.bt_addr = d["bt_addr"]
                    p.rfcomm = True
                    p.sources.add("paired")
                    p.last_seen = time.time()
                self.node.bus.emit("peers")
            except Exception as exc:  # pragma: no cover
                log.debug("paired scan failed %s", exc)
            await asyncio.sleep(20)

    async def _prune_loop(self) -> None:
        while True:
            await asyncio.sleep(3)
            now = time.time()
            stale = [
                k for k, p in self.peers.items()
                if now - p.last_seen > (60 if p.paired_only else config.PEER_STALE_AFTER)
            ]
            for k in stale:
                del self.peers[k]
            if stale:
                self.node.bus.emit("peers")

    # -- queries -------------------------------------------------------------
    def list(self) -> list[NearbyPeer]:
        return sorted(self.peers.values(), key=lambda p: (-(p.rssi or -200), p.display_name().lower()))

    def find_contact_route(self, contact) -> NearbyPeer | None:
        hint = crypto.identity_hint(contact.identity_pub).hex()
        if hint in self.peers:
            return self.peers[hint]
        bt = contact.address.get("bt_addr")
        if bt and f"bt:{bt}" in self.peers:
            return self.peers[f"bt:{bt}"]
        return None
