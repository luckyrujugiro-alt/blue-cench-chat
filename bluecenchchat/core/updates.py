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
