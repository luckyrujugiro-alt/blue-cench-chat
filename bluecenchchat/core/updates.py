"""Checks GitHub for a newer Blue Cench Chat release (one small HTTPS request, no data sent)."""
from __future__ import annotations

import json
import urllib.request

from .. import config

REPO = "luckyrujugiro-alt/blue-cench-chat"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
SETUP_URL = f"https://github.com/{REPO}/releases/latest/download/BlueCenchChat-Setup.exe"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"


def _parse(v: str) -> tuple[int, ...]:
    out = []
    for part in v.lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def is_newer(remote: str, local: str = config.APP_VERSION) -> bool:
    return _parse(remote) > _parse(local)


def latest_version(timeout: float = 6.0) -> str | None:
    """Blocking - call from a worker thread. Returns the latest tag (e.g. '1.1.12') or None."""
    req = urllib.request.Request(LATEST_API, headers={"Accept": "application/vnd.github+json",
                                                      "User-Agent": f"BlueCenchChat/{config.APP_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https URL
            data = json.loads(r.read(200_000))
        tag = str(data.get("tag_name", "")).lstrip("vV")
        return tag or None
    except Exception:
        return None


# --------------------------------------------------------------------------- one-click updates
SHA_URL = SETUP_URL + ".sha256"


def expected_sha256(timeout: float = 15.0) -> str | None:
    """The installer's fingerprint, published next to it by the build. Blocking."""
    req = urllib.request.Request(SHA_URL, headers={"User-Agent": f"BlueCenchChat/{config.APP_VERSION}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https URL
            text = r.read(512).decode("ascii", "replace").strip()
    except Exception:
        return None
    token = text.split()[0].lower() if text else ""
    return token if len(token) == 64 and all(c in "0123456789abcdef" for c in token) else None


def download_installer(dest, progress=None, cancelled=lambda: False, timeout: float = 30.0) -> str:
    """Download the latest installer to `dest` (a pathlib.Path), verifying its SHA-256.

    `progress(done, total)` is called as bytes arrive. Returns the hex digest.
    Raises RuntimeError with a friendly message on any problem. Blocking - run in a thread.
    """
    import hashlib
    from pathlib import Path

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    want = expected_sha256()
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(SETUP_URL, headers={"User-Agent": f"BlueCenchChat/{config.APP_VERSION}"})
    h = hashlib.sha256()
    done = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:  # noqa: S310
            total = int(r.headers.get("Content-Length") or 0)
            while True:
                if cancelled():
                    raise RuntimeError("Update cancelled")
                block = r.read(256 * 1024)
                if not block:
                    break
                f.write(block)
                h.update(block)
                done += len(block)
                if progress:
                    progress(done, total)
        if total and done != total:
            raise RuntimeError("The download was interrupted - check your internet and try again.")
    except RuntimeError:
        part.unlink(missing_ok=True)
        raise
    except Exception as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Couldn't download the update: {exc}") from exc
    digest = h.hexdigest()
    if want and digest != want:
        part.unlink(missing_ok=True)
        raise RuntimeError("The downloaded installer was damaged (fingerprint mismatch), so it was deleted. "
                           "Try again - if it keeps happening, check the disk.")
    if done < 1_000_000:
        part.unlink(missing_ok=True)
        raise RuntimeError("The download is too small to be the installer - try again later.")
    part.replace(dest)
    return digest


def install_silently(installer) -> None:
    """Start the installer in silent mode; it closes this app, upgrades, and starts the new version."""
    import subprocess
    import sys

    args = [str(installer), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
    if sys.platform == "win32":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(args, creationflags=flags, close_fds=True)  # noqa: S603 - our own verified installer
    else:  # pragma: no cover - Windows only
        raise RuntimeError("Automatic install works on Windows only")
