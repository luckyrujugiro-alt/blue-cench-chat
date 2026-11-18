"""Blue-tick verification without a server.

A blue tick is a small certificate signed by the official verifier account
(username ``bluecenchchat``).  Every copy of Blue Cench Chat ships with the
verifier's *public* key in ``bluecenchchat/verifiers.json``; any device can
therefore check a tick offline, and nobody can forge one without the
verifier's private key - which never leaves the verifier's PC (it is stored
encrypted under that account's password like every identity key).

Certificate (JSON):  {"p": base64(payload), "s": base64(signature), "k": base64(verifier key)}
payload:            {"v":1, "kind":"tick", "uid":..., "pub":..., "name":..., "ts":...}
Revocations use the same envelope with kind "revoke" and are gossiped between
peers so a removed tick disappears across the network over time.
"""
from __future__ import annotations

import base64
import json
import time
from functools import lru_cache

from .. import config
from . import crypto

ADMIN_USERNAME = "bluecenchchat"
MIN_FOLLOWERS_FOR_REQUEST = 40


@lru_cache(maxsize=1)
def verifier_keys() -> frozenset[bytes]:
    try:
        data = json.loads(config.resource_path("bluecenchchat", "verifiers.json").read_text(encoding="utf-8"))
        return frozenset(base64.b64decode(k) for k in data.get("keys", []) if k)
    except (OSError, ValueError):
        return frozenset()


def reload_keys() -> None:
    verifier_keys.cache_clear()


def is_published_verifier(pub: bytes) -> bool:
    return pub in verifier_keys()


def can_verify(username: str, pub: bytes) -> bool:
    """The official account may use the dashboard; its signatures are trusted
    network-wide once its public key is published in verifiers.json."""
    return is_published_verifier(pub) or username == ADMIN_USERNAME


def _envelope(identity: crypto.Identity, payload: dict) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return json.dumps({"p": base64.b64encode(raw).decode(), "s": base64.b64encode(identity.sign(raw)).decode(),
                       "k": base64.b64encode(identity.public_bytes).decode()}, separators=(",", ":"))


def _open(blob: str) -> dict | None:
    try:
        env = json.loads(blob)
        raw, sig, key = (base64.b64decode(env[x]) for x in ("p", "s", "k"))
    except (ValueError, KeyError, TypeError):
        return None
    if key not in verifier_keys():
        return None
    try:
        crypto.verify_signature(key, sig, raw)
        return json.loads(raw)
    except (crypto.CryptoError, ValueError):
        return None


def issue_tick(verifier: crypto.Identity, uid: str, pub: bytes, name: str) -> str:
    return _envelope(verifier, {"v": 1, "kind": "tick", "uid": uid, "pub": crypto.b64e(pub),
                                "name": name[:80], "ts": int(time.time())})


def check_tick(blob: str, uid: str, pub: bytes) -> bool:
    if not blob:
        return False
    p = _open(blob)
    return bool(p and p.get("kind") == "tick" and p.get("uid") == uid and p.get("pub") == crypto.b64e(pub))


def issue_revocation(verifier: crypto.Identity, uid: str) -> str:
    return _envelope(verifier, {"v": 1, "kind": "revoke", "uid": uid, "ts": int(time.time())})


def check_revocation(blob: str) -> tuple[str, int] | None:
    p = _open(blob)
    if p and p.get("kind") == "revoke" and isinstance(p.get("uid"), str):
        return p["uid"], int(p.get("ts", 0))
    return None


def tick_time(blob: str) -> int:
    p = _open(blob)
    return int(p.get("ts", 0)) if p else 0


# --------------------------------------------------------------------------- suspensions
FOREVER = 2 ** 31 - 1


def issue_suspension(verifier: crypto.Identity, uid: str, until: int, reason: str = "") -> str:
    """Signed by the official account. until = unix time it ends (FOREVER = permanent, 0 = lifted).
    The newest one (by ts) wins, so lifting a suspension is just issuing one with until=0."""
    return _envelope(verifier, {"v": 1, "kind": "suspend", "uid": uid, "until": int(until),
                                "reason": reason[:140], "ts": time.time()})


def check_suspension(blob: str) -> dict | None:
    p = _open(blob)
    if p and p.get("kind") == "suspend" and isinstance(p.get("uid"), str) and isinstance(p.get("until"), int):
        return {"uid": p["uid"], "until": p["until"], "reason": str(p.get("reason", ""))[:140],
                "ts": float(p.get("ts", 0))}
    return None
