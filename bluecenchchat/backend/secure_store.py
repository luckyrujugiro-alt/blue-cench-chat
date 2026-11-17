"""'Keep me signed in' storage protected by Windows DPAPI.

DPAPI (CryptProtectData) encrypts data with a key tied to the current Windows
user's logon credentials, so the remembered session is useless if the file
is copied to another account or machine.  On non-Windows platforms the
feature is reported as unavailable instead of storing secrets insecurely.
"""
from __future__ import annotations

import ctypes
import json
import sys

from .. import config

_ENTROPY = b"Blue Cench Chat-session-v1"


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def available() -> bool:
    return sys.platform == "win32"


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _protect(data: bytes, unprotect: bool) -> bytes:
    crypt32 = ctypes.windll.crypt32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    out = _Blob()
    inp, ent = _blob(data), _blob(_ENTROPY)
    fn = crypt32.CryptUnprotectData if unprotect else crypt32.CryptProtectData
    ok = fn(ctypes.byref(inp), None, ctypes.byref(ent), None, None, 0x01, ctypes.byref(out))
    if not ok:
        raise OSError("DPAPI operation failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)


def _path():
    return config.data_dir() / "session.dat"


def save(account_id: int, identity_raw: bytes) -> None:
    if not available():
        return
    payload = json.dumps({"account_id": account_id, "key": identity_raw.hex()}).encode()
    _path().write_bytes(_protect(payload, unprotect=False))


def load() -> tuple[int, bytes] | None:
    if not available() or not _path().exists():
        return None
    try:
        data = json.loads(_protect(_path().read_bytes(), unprotect=True))
        return int(data["account_id"]), bytes.fromhex(data["key"])
    except Exception:
        clear()
        return None


def clear() -> None:
    try:
        _path().unlink()
    except FileNotFoundError:
        pass
