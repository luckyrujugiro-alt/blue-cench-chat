"""Local-network transport (TCP) + UDP broadcast presence beacons.

Works on any shared local network with no internet: home/office Wi-Fi, an
Ethernet cable between two PCs, or a Windows *Mobile Hotspot* created by one
of the two PCs (Settings > Network > Mobile hotspot - set "Share my internet
connection from" to any adapter; internet is not needed for the local link).

Windows Defender Firewall will ask once to allow Blue Cench Chat on private networks;
the installer can add the rule ahead of time.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from typing import Awaitable, Callable

from ... import config
from .base import AsyncioStream, TransportError

log = logging.getLogger("bluecenchchat.lan")


def local_ipv4_interfaces() -> list[tuple[str, str]]:
    """[(ip, broadcast)] for every up, non-loopback IPv4 interface."""
    out: list[tuple[str, str]] = []
    try:
        import psutil

        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            if name in stats and not stats[name].isup:
                continue
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith("127.") and a.netmask:
                    try:
                        net = ipaddress.IPv4Network(f"{a.address}/{a.netmask}", strict=False)
                        out.append((a.address, str(net.broadcast_address)))
                    except ValueError:
                        continue
    except Exception:  # pragma: no cover - psutil missing
        pass
    return out


class _BeaconProtocol(asyncio.DatagramProtocol):
    def __init__(self, owner: "LanTransport") -> None:
        self.owner = owner

    def datagram_received(self, data: bytes, addr) -> None:
        if len(data) > 1024:
            return
        try:
            msg = json.loads(data)
        except ValueError:
            return
        if not isinstance(msg, dict) or msg.get("nx") != config.PROTOCOL_VERSION:
            return
        self.owner._on_beacon(msg, addr[0])


class LanTransport:
    kind = "lan"

    def __init__(
        self,
        on_stream: Callable[[AsyncioStream], Awaitable[None]],
        on_beacon: Callable[[dict, str], None],
        beacon_port: int = config.LAN_BEACON_PORT,
    ) -> None:
        self._on_stream = on_stream
        self._on_beacon_cb = on_beacon
        self.beacon_port = beacon_port
        self.server: asyncio.base_events.Server | None = None
        self.port: int = 0
        self._udp: asyncio.DatagramTransport | None = None
        self._beacon_task: asyncio.Task | None = None
        self._beacon_payload: dict | None = None
        self.own_uid: str | None = None
        self.running = False
        self.last_error = ""

    async def start(self, host: str = "0.0.0.0", port: int = 0) -> None:
        self.server = await asyncio.start_server(self._accept, host, port)
        self.port = self.server.sockets[0].getsockname()[1]
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", self.beacon_port))
            sock.setblocking(False)
            loop = asyncio.get_running_loop()
            self._udp, _ = await loop.create_datagram_endpoint(lambda: _BeaconProtocol(self), sock=sock)
        except OSError as exc:
            self.last_error = f"Presence beacons unavailable: {exc}"
            log.warning(self.last_error)
        self._beacon_task = asyncio.create_task(self._beacon_loop())
        self.running = True
        log.info("LAN transport listening on tcp/%s", self.port)

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        sock = writer.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        await self._on_stream(AsyncioStream(reader, writer, "lan"))

    async def connect(self, ip: str, port: int, timeout: float = 8.0) -> AsyncioStream:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
        except (OSError, asyncio.TimeoutError) as exc:
            raise TransportError(f"Could not reach {ip}:{port} ({exc.__class__.__name__})") from exc
        sock = writer.get_extra_info("socket")
        if sock is not None:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        stream = AsyncioStream(reader, writer, "lan")
        stream.remote_address = {"ip": ip, "port": port}
        return stream

    # -- presence beacons ---------------------------------------------------
    def set_beacon(self, payload: dict | None) -> None:
        """payload=None stops advertising (visibility off)."""
        self._beacon_payload = payload
        self.own_uid = payload.get("uid") if payload else self.own_uid

    def _on_beacon(self, msg: dict, ip: str) -> None:
        if msg.get("uid") == self.own_uid:
            return
        self._on_beacon_cb(msg, ip)

    async def _beacon_loop(self) -> None:
        while True:
            try:
                if self._beacon_payload and self._udp:
                    data = json.dumps({**self._beacon_payload, "nx": config.PROTOCOL_VERSION, "port": self.port}).encode()
                    targets = {"255.255.255.255"} | {b for _, b in local_ipv4_interfaces()}
                    for t in targets:
                        try:
                            self._udp.sendto(data, (t, self.beacon_port))
                        except OSError:
                            pass
                await asyncio.sleep(config.LAN_BEACON_INTERVAL)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover
                log.debug("beacon error %s", exc)
                await asyncio.sleep(config.LAN_BEACON_INTERVAL)

    async def stop(self) -> None:
        self.running = False
        if self._beacon_task:
            self._beacon_task.cancel()
        if self._udp:
            self._udp.close()
        if self.server:
            self.server.close()
            try:
                await asyncio.wait_for(self.server.wait_closed(), 2)
            except Exception:
                pass
