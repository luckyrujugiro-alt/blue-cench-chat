"""Byte-stream transports. The session layer above them is identical for all."""
from __future__ import annotations

import asyncio
import logging
import socket
import threading
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from typing import Awaitable, Callable, Optional

log = logging.getLogger(__name__)

ConnectionHandler = Callable[["Transport"], Awaitable[None]]


class Transport(ABC):
    """A reliable, ordered byte stream to one peer."""

    kind: str = "unknown"          # "lan" or "bluetooth"
    peer_address: str = ""

    @abstractmethod
    async def read_exactly(self, count: int) -> bytes: ...

    @abstractmethod
    async def write(self, data: bytes) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...


# -- TCP (local network, no internet needed) --------------------------------

class TcpTransport(Transport):
    kind = "lan"

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self._reader, self._writer = reader, writer
        peer = writer.get_extra_info("peername") or ("?", 0)
        self.peer_address = f"{peer[0]}:{peer[1]}"
        self.peer_host = peer[0]

    async def read_exactly(self, count: int) -> bytes:
        try:
            return await self._reader.readexactly(count)
        except (asyncio.IncompleteReadError, OSError) as exc:
            raise ConnectionError("connection closed") from exc

    async def write(self, data: bytes) -> None:
        try:
            self._writer.write(data)
            await self._writer.drain()
        except OSError as exc:
            raise ConnectionError("connection closed") from exc

    async def close(self) -> None:
        try:
            self._writer.close()
            await self._writer.wait_closed()
        except OSError:
            pass


async def open_tcp(host: str, port: int, timeout: float = 8.0) -> TcpTransport:
    reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    return TcpTransport(reader, writer)


async def start_tcp_server(handler: ConnectionHandler, preferred_port: int,
                           host: str = "0.0.0.0") -> tuple[asyncio.AbstractServer, int]:
    async def on_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await handler(TcpTransport(reader, writer))

    for port in (preferred_port, 0):
        try:
            server = await asyncio.start_server(on_client, host, port)
            return server, server.sockets[0].getsockname()[1]
        except OSError:
            continue
    raise OSError("could not open a TCP listening port")


# -- Blocking sockets (Bluetooth RFCOMM) ------------------------------------

class BlockingSocketTransport(Transport):
    """Wraps a blocking socket. Bluetooth sockets are not supported by the
    asyncio proactor loop on Windows, so reads and writes run in two dedicated
    worker threads."""

    def __init__(self, sock: socket.socket, kind: str, peer_address: str):
        self._sock = sock
        self.kind = kind
        self.peer_address = peer_address
        self._reader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nx-rx")
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nx-tx")
        self._closed = False

    def _recv_exact(self, count: int) -> bytes:
        buffer = bytearray()
        while len(buffer) < count:
            try:
                part = self._sock.recv(count - len(buffer))
            except OSError as exc:
                raise ConnectionError("connection closed") from exc
            if not part:
                raise ConnectionError("connection closed")
            buffer += part
        return bytes(buffer)

    def _send_all(self, data: bytes) -> None:
        try:
            self._sock.sendall(data)
        except OSError as exc:
            raise ConnectionError("connection closed") from exc

    async def read_exactly(self, count: int) -> bytes:
        return await asyncio.get_running_loop().run_in_executor(self._reader, self._recv_exact, count)

    async def write(self, data: bytes) -> None:
        await asyncio.get_running_loop().run_in_executor(self._writer, self._send_all, data)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()
        self._reader.shutdown(wait=False)
        self._writer.shutdown(wait=False)


def rfcomm_supported() -> bool:
    """True when this Python build exposes Bluetooth sockets (Windows 10+ with
    CPython 3.9+, or Linux with BlueZ)."""
    return hasattr(socket, "AF_BLUETOOTH") and hasattr(socket, "BTPROTO_RFCOMM")


def _rfcomm_socket() -> socket.socket:
    return socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)  # type: ignore[attr-defined]


async def open_rfcomm(address: str, channel: int, timeout: float = 25.0) -> BlockingSocketTransport:
    """Connect to a Bluetooth Classic device. Windows may show its own pairing
    prompt the first time two PCs connect."""
    def connect() -> socket.socket:
        sock = _rfcomm_socket()
        sock.settimeout(timeout)
        try:
            sock.connect((address, channel))
        except OSError:
            sock.close()
            raise
        sock.settimeout(None)
        return sock

    sock = await asyncio.get_running_loop().run_in_executor(None, connect)
    return BlockingSocketTransport(sock, "bluetooth", address)


class RfcommServer:
    """Listens on an RFCOMM channel in a background thread and hands accepted
    connections to the asyncio loop."""

    def __init__(self, handler: ConnectionHandler, loop: asyncio.AbstractEventLoop):
        self._handler, self._loop = handler, loop
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self.channel: Optional[int] = None
        self.error: str = ""

    def start(self, channels: tuple[int, ...]) -> bool:
        if not rfcomm_supported():
            self.error = "This Python build has no Bluetooth socket support."
            return False
        for channel in channels:
            sock = None
            try:
                sock = _rfcomm_socket()
                sock.bind(("00:00:00:00:00:00", channel))
                sock.listen(4)
                sock.settimeout(1.0)
            except OSError as exc:
                self.error = f"RFCOMM channel {channel}: {exc}"
                if sock is not None:
                    sock.close()
                continue
            self._sock, self.channel, self.error = sock, channel, ""
            threading.Thread(target=self._accept_loop, name="nx-rfcomm-accept", daemon=True).start()
            return True
        return False

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                client, address = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client.settimeout(None)
            transport = BlockingSocketTransport(client, "bluetooth", str(address[0]))
            asyncio.run_coroutine_threadsafe(self._handler(transport), self._loop)

    def stop(self) -> None:
        self._stop.set()
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
