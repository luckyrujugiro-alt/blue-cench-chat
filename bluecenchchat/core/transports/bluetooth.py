"""Windows Bluetooth via the Windows Runtime (pywinrt bindings).

Three pieces:

* :func:`adapter_info`   - radio/adapter capabilities for diagnostics.
* :class:`BleBeacon`     - BLE advertisement publisher + watcher.  This is
  how Blue Cench Chat users find each other: each running instance publishes a small
  manufacturer-specific advertisement (company ID + 23-byte payload) and
  watches for others.  Requires an adapter that supports the BLE
  *peripheral* role for publishing; scanning only needs the central role.
* :class:`RfcommTransport` - Bluetooth Classic RFCOMM stream sockets.  The
  server publishes the Blue Cench Chat service UUID in SDP; clients look it up on the
  remote device and connect.  Windows normally requires the two PCs to be
  paired (Settings > Bluetooth & devices > Add device) before an RFCOMM
  connection to a custom service succeeds.

BLE advertisement payload (23 bytes, fits a legacy 31-byte advertisement):

    magic u8 | version u8 | identity hint 8B | flags u8 | lan port u16 |
    lan ipv4 4B | classic BT address 6B
    flags: bit0 = LAN reachable, bit1 = RFCOMM listening

All WinRT events arrive on thread-pool threads; they are marshalled back to
the asyncio loop with ``call_soon_threadsafe``.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import struct
import sys
from dataclasses import dataclass
from typing import Awaitable, Callable

from ... import config
from .base import Stream, TransportError

log = logging.getLogger("bluecenchchat.bluetooth")

WINRT_AVAILABLE = False
WINRT_IMPORT_ERROR = "Windows Runtime Bluetooth APIs are only available on Windows 10/11."
if sys.platform == "win32":  # pragma: no cover - Windows only
    try:
        from winrt.windows.devices.bluetooth import (
            BluetoothAdapter,
            BluetoothCacheMode,
            BluetoothDevice,
            BluetoothError,
        )
        from winrt.windows.devices.bluetooth.advertisement import (
            BluetoothLEAdvertisementPublisher,
            BluetoothLEAdvertisementWatcher,
            BluetoothLEManufacturerData,
            BluetoothLEScanningMode,
        )
        from winrt.windows.devices.bluetooth.rfcomm import (
            RfcommDeviceService,
            RfcommServiceId,
            RfcommServiceProvider,
        )
        from winrt.windows.devices.enumeration import DeviceInformation
        from winrt.windows.devices.radios import RadioState
        from winrt.windows.networking.sockets import (
            SocketProtectionLevel,
            StreamSocket,
            StreamSocketListener,
        )
        from winrt.windows.storage.streams import DataReader, DataWriter, InputStreamOptions

        WINRT_AVAILABLE = True
        WINRT_IMPORT_ERROR = ""
    except Exception as exc:  # missing packages / old Windows
        WINRT_IMPORT_ERROR = f"WinRT Bluetooth bindings unavailable: {exc}"

BLE_PAYLOAD = struct.Struct(">BB8sBH4s6s")


def format_bt_address(addr: int) -> str:
    return ":".join(f"{(addr >> (8 * i)) & 0xFF:02X}" for i in reversed(range(6)))


def _buffer_bytes(buf) -> bytes:
    try:
        return bytes(buf)
    except TypeError:  # pragma: no cover - older pywinrt
        reader = DataReader.from_buffer(buf)
        out = bytearray(buf.length)
        reader.read_bytes(out)
        return bytes(out)


def _to_buffer(data: bytes):
    w = DataWriter()
    w.write_bytes(data)
    return w.detach_buffer()


@dataclass
class AdapterInfo:
    available: bool
    reason: str = ""
    name: str = ""
    address: int = 0
    radio_on: bool = False
    classic: bool = False
    low_energy: bool = False
    central: bool = False
    peripheral: bool = False
    advertisement_offload: bool = False

    @property
    def address_str(self) -> str:
        return format_bt_address(self.address) if self.address else "-"


async def adapter_info() -> AdapterInfo:
    if not WINRT_AVAILABLE:
        return AdapterInfo(False, WINRT_IMPORT_ERROR)
    try:  # pragma: no cover - Windows only
        adapter = await BluetoothAdapter.get_default_async()
        if adapter is None:
            return AdapterInfo(False, "No Bluetooth adapter found on this PC.")
        radio = await adapter.get_radio_async()
        info = AdapterInfo(
            True,
            name=radio.name if radio else "Bluetooth",
            address=adapter.bluetooth_address,
            radio_on=bool(radio and radio.state == RadioState.ON),
            classic=adapter.is_classic_supported,
            low_energy=adapter.is_low_energy_supported,
            central=adapter.is_central_role_supported,
            peripheral=adapter.is_peripheral_role_supported,
        )
        try:
            info.advertisement_offload = adapter.is_advertisement_offload_supported
        except Exception:
            pass
        if not info.radio_on:
            info.reason = "Bluetooth is turned off. Turn it on in Windows Settings."
        return info
    except Exception as exc:  # pragma: no cover
        return AdapterInfo(False, f"Bluetooth error: {exc}")


async def paired_devices() -> list[dict]:
    """All Bluetooth devices paired with Windows (Classic + LE)."""
    if not WINRT_AVAILABLE:
        return []
    out = []
    try:  # pragma: no cover - Windows only
        for paired_flag, kind in ((True, "classic"),):
            sel = BluetoothDevice.get_device_selector_from_pairing_state(paired_flag)
            for di in await DeviceInformation.find_all_async(sel):
                out.append({"name": di.name or "Unknown device", "id": di.id, "kind": kind, "paired": True})
    except Exception as exc:
        log.warning("paired device enumeration failed: %s", exc)
    return out


async def bluecenchchat_rfcomm_peers() -> list[dict]:
    """Paired devices whose SDP record advertises the Blue Cench Chat service."""
    if not WINRT_AVAILABLE:
        return []
    out = []
    try:  # pragma: no cover - Windows only
        sid = RfcommServiceId.from_uuid(config.RFCOMM_SERVICE_UUID)
        sel = RfcommDeviceService.get_device_selector(sid)
        for di in await DeviceInformation.find_all_async(sel):
            try:
                svc = await RfcommDeviceService.from_id_async(di.id)
                if svc is None:
                    continue
                out.append(
                    {
                        "name": svc.device.name,
                        "bt_addr": svc.device.bluetooth_address,
                        "connected": int(svc.device.connection_status) == 1,
                    }
                )
            except Exception as exc:
                log.debug("rfcomm service lookup failed: %s", exc)
    except Exception as exc:
        log.warning("rfcomm enumeration failed: %s", exc)
    return out


# ---------------------------------------------------------------------------
# BLE beacon
# ---------------------------------------------------------------------------
class BleBeacon:
    def __init__(self, on_sighting: Callable[[dict], None]) -> None:
        self._on_sighting = on_sighting
        self._publisher = None
        self._watcher = None
        self._token = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.publishing = False
        self.scanning = False
        self.last_error = ""

    @staticmethod
    def encode(hint: bytes, lan_port: int, lan_ip: str | None, bt_addr: int, rfcomm: bool) -> bytes:
        flags = (1 if lan_ip and lan_port else 0) | (2 if rfcomm else 0)
        ip_bytes = ipaddress.IPv4Address(lan_ip).packed if lan_ip else b"\x00" * 4
        return BLE_PAYLOAD.pack(
            config.BLE_MAGIC, config.PROTOCOL_VERSION, hint, flags, lan_port & 0xFFFF, ip_bytes,
            bt_addr.to_bytes(6, "big"),
        )

    @staticmethod
    def decode(data: bytes) -> dict | None:
        if len(data) != BLE_PAYLOAD.size:
            return None
        magic, ver, hint, flags, port, ip, bt = BLE_PAYLOAD.unpack(data)
        if magic != config.BLE_MAGIC or ver != config.PROTOCOL_VERSION:
            return None
        ip_str = str(ipaddress.IPv4Address(ip)) if flags & 1 else None
        return {
            "hint": hint.hex(),
            "lan_ip": ip_str,
            "lan_port": port if flags & 1 else None,
            "bt_addr": int.from_bytes(bt, "big") or None,
            "rfcomm": bool(flags & 2),
        }

    def start_publishing(self, payload: bytes) -> None:
        if not WINRT_AVAILABLE:
            self.last_error = WINRT_IMPORT_ERROR
            return
        self.stop_publishing()
        try:  # pragma: no cover - Windows only
            pub = BluetoothLEAdvertisementPublisher()
            md = BluetoothLEManufacturerData()
            md.company_id = config.BLE_COMPANY_ID
            md.data = _to_buffer(payload)
            pub.advertisement.manufacturer_data.append(md)
            pub.start()
            self._publisher = pub
            self.publishing = True
            self.last_error = ""
        except Exception as exc:  # pragma: no cover
            self.publishing = False
            self.last_error = (
                f"BLE advertising failed ({exc}). Your adapter may not support the peripheral role; "
                "other users can still find you over the local network or paired RFCOMM."
            )
            log.warning(self.last_error)

    def stop_publishing(self) -> None:
        if self._publisher is not None:
            try:
                self._publisher.stop()
            except Exception:
                pass
        self._publisher = None
        self.publishing = False

    def start_scanning(self) -> None:
        if not WINRT_AVAILABLE:
            self.last_error = WINRT_IMPORT_ERROR
            return
        if self.scanning:
            return
        self._loop = asyncio.get_running_loop()
        try:  # pragma: no cover - Windows only
            w = BluetoothLEAdvertisementWatcher()
            w.scanning_mode = BluetoothLEScanningMode.ACTIVE
            md = BluetoothLEManufacturerData()
            md.company_id = config.BLE_COMPANY_ID
            w.advertisement_filter.advertisement.manufacturer_data.append(md)
            self._token = w.add_received(self._received)
            w.start()
            self._watcher = w
            self.scanning = True
        except Exception as exc:  # pragma: no cover
            self.last_error = f"BLE scanning failed: {exc}"
            log.warning(self.last_error)

    def _received(self, _sender, args) -> None:  # pragma: no cover - WinRT thread
        try:
            for md in args.advertisement.manufacturer_data:
                if md.company_id != config.BLE_COMPANY_ID:
                    continue
                info = self.decode(_buffer_bytes(md.data))
                if info is None:
                    continue
                info["rssi"] = args.raw_signal_strength_in_d_bm
                info["ble_addr"] = args.bluetooth_address
                if self._loop:
                    self._loop.call_soon_threadsafe(self._on_sighting, info)
        except Exception as exc:
            log.debug("ble parse error %s", exc)

    def stop_scanning(self) -> None:
        if self._watcher is not None:
            try:
                self._watcher.stop()
                if self._token is not None:
                    self._watcher.remove_received(self._token)
            except Exception:
                pass
        self._watcher = None
        self.scanning = False

    def stop(self) -> None:
        self.stop_publishing()
        self.stop_scanning()


# ---------------------------------------------------------------------------
# RFCOMM
# ---------------------------------------------------------------------------
class WinRtSocketStream(Stream):  # pragma: no cover - Windows only
    kind = "rfcomm"

    def __init__(self, sock, label: str, bt_addr: int | None = None) -> None:
        self.sock = sock
        self.remote_label = label
        self.remote_address = {"bt_addr": bt_addr} if bt_addr else {}
        self._reader = DataReader(sock.input_stream)
        self._reader.input_stream_options = InputStreamOptions.PARTIAL
        self._writer = DataWriter(sock.output_stream)
        self._buf = bytearray()
        self._wlock = asyncio.Lock()
        self._closed = False

    async def read_exactly(self, n: int) -> bytes:
        while len(self._buf) < n:
            if self._closed:
                raise TransportError("connection closed")
            try:
                got = await self._reader.load_async(max(n - len(self._buf), 64 * 1024))
            except Exception as exc:
                raise TransportError(f"Bluetooth link lost: {exc}") from exc
            if got == 0:
                raise TransportError("connection closed by peer")
            self._buf += _buffer_bytes(self._reader.read_buffer(got))
        out = bytes(self._buf[:n])
        del self._buf[:n]
        return out

    async def write(self, data: bytes) -> None:
        async with self._wlock:
            try:
                self._writer.write_bytes(data)
                await self._writer.store_async()
            except Exception as exc:
                raise TransportError(f"Bluetooth link lost: {exc}") from exc

    async def close(self) -> None:
        self._closed = True
        for obj in (self._reader, self._writer, self.sock):
            try:
                obj.close()
            except Exception:
                pass


class RfcommTransport:
    kind = "rfcomm"

    def __init__(self, on_stream: Callable[[Stream], Awaitable[None]]) -> None:
        self._on_stream = on_stream
        self._provider = None
        self._listener = None
        self._token = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.running = False
        self.last_error = ""

    async def start(self) -> None:
        if not WINRT_AVAILABLE:
            self.last_error = WINRT_IMPORT_ERROR
            return
        self._loop = asyncio.get_running_loop()
        try:  # pragma: no cover - Windows only
            sid = RfcommServiceId.from_uuid(config.RFCOMM_SERVICE_UUID)
            self._provider = await RfcommServiceProvider.create_async(sid)
            self._listener = StreamSocketListener()
            self._token = self._listener.add_connection_received(self._accepted)
            await self._listener.bind_service_name_async(
                self._provider.service_id.as_string(),
                SocketProtectionLevel.BLUETOOTH_ENCRYPTION_ALLOW_NULL_AUTHENTICATION,
            )
            w = DataWriter()
            name = config.RFCOMM_SERVICE_NAME.encode()
            w.write_byte(0x25)  # SDP: text string, 8-bit length
            w.write_byte(len(name))
            w.write_bytes(name)
            self._provider.sdp_raw_attributes.insert(0x100, w.detach_buffer())
            try:
                self._provider.start_advertising(self._listener, True)
            except TypeError:
                self._provider.start_advertising(self._listener)
            self.running = True
            self.last_error = ""
            log.info("RFCOMM service published")
        except Exception as exc:
            self.last_error = f"RFCOMM service could not start: {exc}"
            log.warning(self.last_error)

    def _accepted(self, _listener, args) -> None:  # pragma: no cover - WinRT thread
        sock = args.socket
        label = f"BT {sock.information.remote_host_name.display_name}"

        def _go():
            asyncio.ensure_future(self._on_stream(WinRtSocketStream(sock, label)))

        if self._loop:
            self._loop.call_soon_threadsafe(_go)

    async def connect(self, bt_addr: int, timeout: float = 25.0) -> Stream:
        if not WINRT_AVAILABLE:
            raise TransportError(WINRT_IMPORT_ERROR)
        return await asyncio.wait_for(self._connect(bt_addr), timeout)

    async def _connect(self, bt_addr: int) -> Stream:  # pragma: no cover - Windows only
        device = await BluetoothDevice.from_bluetooth_address_async(bt_addr)
        if device is None:
            raise TransportError("Bluetooth device not reachable. Is it nearby with Bluetooth on?")
        sid = RfcommServiceId.from_uuid(config.RFCOMM_SERVICE_UUID)
        result = await device.get_rfcomm_services_for_id_async(sid, BluetoothCacheMode.UNCACHED)
        services = list(result.services) if result and result.services is not None else []
        if result is None or result.error != BluetoothError.SUCCESS or not services:
            raise TransportError(
                "Blue Cench Chat service not found on that device. Pair the two PCs once in Windows "
                "Settings > Bluetooth & devices, and make sure Blue Cench Chat is running on both."
            )
        svc = services[0]
        sock = StreamSocket()
        try:
            await sock.connect_async(
                svc.connection_host_name,
                svc.connection_service_name,
                SocketProtectionLevel.BLUETOOTH_ENCRYPTION_ALLOW_NULL_AUTHENTICATION,
            )
        except Exception as exc:
            raise TransportError(f"Bluetooth connection refused: {exc}") from exc
        return WinRtSocketStream(sock, f"BT {device.name}", bt_addr)

    async def stop(self) -> None:
        self.running = False
        try:  # pragma: no cover
            if self._provider:
                self._provider.stop_advertising()
            if self._listener:
                self._listener.close()
        except Exception:
            pass
        self._provider = self._listener = None
