"""Application-wide configuration, paths and protocol constants.

Blue Cench Chat stores everything per Windows user under %APPDATA%\\Blue Cench Chat.  A
"profile" name may be supplied (``--profile alice``) to run several isolated
instances on one machine - this is the clearly labelled *development test
mode*; the instances still talk over real sockets.
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

APP_NAME = "Blue Cench Chat"
APP_TAGLINE = "Connect Beyond Limits."
APP_VERSION = "1.1.0"
ORG_NAME = "Blue Cench Chat"

PROTOCOL_VERSION = 1

# Bluetooth --------------------------------------------------------------
# Custom 128-bit RFCOMM service UUID that identifies a Blue Cench Chat endpoint in SDP.
RFCOMM_SERVICE_UUID = uuid.UUID("6e78a1c2-4b1f-4f3e-9d3a-2a7c0e5b9f41")
RFCOMM_SERVICE_NAME = "Blue Cench Chat Secure Link"
# 0xFFFF is the Bluetooth SIG "test / internal use" company identifier.  A
# commercial release must register its own company ID with the Bluetooth SIG.
BLE_COMPANY_ID = 0xFFFF
BLE_MAGIC = 0x4E  # 'N'

# Local network ---------------------------------------------------------
LAN_BEACON_PORT = 47820
LAN_BEACON_INTERVAL = 2.0  # seconds
PEER_STALE_AFTER = 12.0  # seconds without a beacon -> peer disappears

# Transfer tuning per transport (bytes)
CHUNK_SIZE = {"lan": 256 * 1024, "rfcomm": 24 * 1024, "loopback": 256 * 1024}
WINDOW_CHUNKS = {"lan": 16, "rfcomm": 12, "loopback": 16}
MAX_FRAME = 2 * 1024 * 1024
MAX_TEXT_LEN = 16_000

# Wi-Fi companion for phones / tablets / watches (HTTPS)
WEB_PORT = 8765

# Auth --------------------------------------------------------------------
MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 5 * 60


def _base_dir() -> Path:
    if env := os.environ.get("BLUECENCHCHAT_HOME"):
        return Path(env)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
    return Path.home() / ".bluecenchchat"


_profile: str | None = None


def set_profile(name: str | None) -> None:
    global _profile
    _profile = name


def profile() -> str | None:
    return _profile


def data_dir() -> Path:
    base = _base_dir()
    if _profile:
        base = base / "profiles" / _profile
    base.mkdir(parents=True, exist_ok=True)
    return base


def db_path() -> Path:
    return data_dir() / "bluecenchchat.db"


def log_dir() -> Path:
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_download_dir() -> Path:
    base = Path.home() / "Downloads" / APP_NAME
    if _profile:
        base = base / _profile
    return base


def resource_path(*parts: str) -> Path:
    """Resolve bundled assets both from source and from a PyInstaller build."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return root.joinpath(*parts)


IS_WINDOWS = sys.platform == "win32"
