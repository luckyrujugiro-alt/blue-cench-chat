"""Transport abstraction.

A transport delivers an ordered, reliable byte stream between two machines.
All security (authentication, encryption, integrity) is layered on top in
``core.session`` so every transport gets identical protection.
"""
from __future__ import annotations

import abc
import asyncio


class TransportError(Exception):
    pass


class Stream(abc.ABC):
    #: "lan" or "rfcomm"
    kind: str = "unknown"
    #: human readable remote endpoint, e.g. "192.168.1.20:51334"
    remote_label: str = ""
    #: transport-specific address used for reconnection
    remote_address: dict = {}

    @abc.abstractmethod
    async def read_exactly(self, n: int) -> bytes: ...

    @abc.abstractmethod
    async def write(self, data: bytes) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


class AsyncioStream(Stream):
    """Wraps asyncio StreamReader/StreamWriter (TCP)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, kind: str = "lan"):
        self.reader = reader
        self.writer = writer
        self.kind = kind
        peer = writer.get_extra_info("peername") or ("?", 0)
        self.remote_label = f"{peer[0]}:{peer[1]}"
        self.remote_address = {"ip": peer[0]}
        self._lock = asyncio.Lock()

    async def read_exactly(self, n: int) -> bytes:
        try:
            return await self.reader.readexactly(n)
        except (asyncio.IncompleteReadError, ConnectionError, OSError) as exc:
            raise TransportError("connection closed") from exc

    async def write(self, data: bytes) -> None:
        async with self._lock:
            try:
                self.writer.write(data)
                await self.writer.drain()
            except (ConnectionError, OSError) as exc:
                raise TransportError("connection lost") from exc

    async def close(self) -> None:
        try:
            self.writer.close()
            await asyncio.wait_for(self.writer.wait_closed(), 2)
        except Exception:
            pass
