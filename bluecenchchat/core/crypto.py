"""Cryptographic primitives for Blue Cench Chat.

Nothing here invents cryptography.  We compose well-reviewed primitives from
the ``cryptography`` package and ``argon2-cffi``:

* Ed25519            - long-term account identity (signatures)
* X25519             - ephemeral Diffie-Hellman per session (forward secrecy)
* HKDF-SHA256        - session key derivation bound to the handshake transcript
* ChaCha20-Poly1305  - authenticated encryption of every frame
* Argon2id           - password / recovery-key hashing and key wrapping

The session handshake is a SIGMA-style "sign-and-MAC" design (as used by TLS
1.3 and IKEv2): both sides exchange ephemeral keys, derive traffic keys, and
then each proves possession of its identity key by signing the full
transcript inside the encrypted channel.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class CryptoError(Exception):
    """Raised for any authentication / integrity failure."""


def b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"), validate=True)


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------
_B32 = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I ambiguity


def user_id_from_pub(identity_pub: bytes) -> str:
    """Derive the public Blue Cench Chat ID from an identity key.

    Because the ID is a hash of the key, a peer can never claim someone
    else's ID without also holding their private key.
    """
    digest = hashlib.sha256(b"bluecenchchat-id" + identity_pub).digest()
    n = int.from_bytes(digest[:8], "big")
    chars = []
    for _ in range(10):
        chars.append(_B32[n & 31])
        n >>= 5
    s = "".join(chars)
    return f"NX-{s[:5]}-{s[5:]}"


def identity_hint(identity_pub: bytes) -> bytes:
    """8-byte hint broadcast in discovery beacons."""
    return hashlib.sha256(b"bluecenchchat-hint" + identity_pub).digest()[:8]


def safety_number(pub_a: bytes, pub_b: bytes) -> str:
    """Symmetric 12-digit code both users compare face-to-face."""
    lo, hi = sorted([pub_a, pub_b])
    digest = hashlib.sha256(b"bluecenchchat-safety" + lo + hi).digest()
    num = int.from_bytes(digest[:8], "big") % 10**12
    s = f"{num:012d}"
    return " ".join(s[i : i + 4] for i in range(0, 12, 4))


@dataclass
class Identity:
    private: Ed25519PrivateKey

    @classmethod
    def generate(cls) -> "Identity":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Identity":
        return cls(Ed25519PrivateKey.from_private_bytes(raw))

    def private_bytes(self) -> bytes:
        return self.private.private_bytes(
            serialization.Encoding.Raw,
            serialization.PrivateFormat.Raw,
            serialization.NoEncryption(),
        )

    @property
    def public_bytes(self) -> bytes:
        return self.private.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    @property
    def user_id(self) -> str:
        return user_id_from_pub(self.public_bytes)

    def sign(self, data: bytes) -> bytes:
        return self.private.sign(data)


def verify_signature(pub: bytes, sig: bytes, data: bytes) -> None:
    try:
        Ed25519PublicKey.from_public_bytes(pub).verify(sig, data)
    except (InvalidSignature, ValueError) as exc:
        raise CryptoError("invalid signature") from exc


# --------------------------------------------------------------------------
# Password based key wrapping (Argon2id + ChaCha20-Poly1305)
# --------------------------------------------------------------------------
ARGON_TIME = 3
ARGON_MEM_KIB = 64 * 1024
ARGON_PAR = 2


def derive_wrap_key(secret: str, salt: bytes) -> bytes:
    return hash_secret_raw(
        secret.encode("utf-8"),
        salt,
        time_cost=ARGON_TIME,
        memory_cost=ARGON_MEM_KIB,
        parallelism=ARGON_PAR,
        hash_len=32,
        type=Type.ID,
    )


def wrap_secret(secret: str, plaintext: bytes) -> tuple[bytes, bytes]:
    """Encrypt ``plaintext`` under a key derived from ``secret``.

    Returns (salt, nonce||ciphertext).
    """
    salt = os.urandom(16)
    key = derive_wrap_key(secret, salt)
    nonce = os.urandom(12)
    return salt, nonce + ChaCha20Poly1305(key).encrypt(nonce, plaintext, b"bluecenchchat-wrap")


def unwrap_secret(secret: str, salt: bytes, blob: bytes) -> bytes:
    key = derive_wrap_key(secret, salt)
    try:
        return ChaCha20Poly1305(key).decrypt(blob[:12], blob[12:], b"bluecenchchat-wrap")
    except InvalidTag as exc:
        raise CryptoError("wrong secret") from exc


def generate_recovery_key() -> str:
    """Human-transcribable 100-bit recovery key, e.g. ``K7QM-...``."""
    raw = "".join(secrets.choice(_B32) for _ in range(20))
    return "-".join(raw[i : i + 4] for i in range(0, 20, 4))


def normalize_recovery_key(key: str) -> str:
    raw = "".join(ch for ch in key.upper() if ch in _B32)
    return "-".join(raw[i : i + 4] for i in range(0, len(raw), 4))


# --------------------------------------------------------------------------
# Session handshake + channel
# --------------------------------------------------------------------------
class EphemeralKey:
    def __init__(self) -> None:
        self._priv = X25519PrivateKey.generate()
        self.public_bytes = self._priv.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    def exchange(self, peer_pub: bytes) -> bytes:
        try:
            shared = self._priv.exchange(X25519PublicKey.from_public_bytes(peer_pub))
        except ValueError as exc:
            raise CryptoError("bad ephemeral key") from exc
        if shared == b"\x00" * 32:
            raise CryptoError("low-order point")
        return shared


def derive_session_keys(shared: bytes, transcript: bytes) -> tuple[bytes, bytes]:
    """Return (initiator->responder key, responder->initiator key)."""
    okm = HKDF(
        algorithm=hashes.SHA256(), length=64, salt=transcript, info=b"bluecenchchat v1 session"
    ).derive(shared)
    return okm[:32], okm[32:]


def auth_payload(role: str, transcript: bytes) -> bytes:
    return b"Blue Cench Chat-AUTH|" + role.encode() + b"|" + transcript


class SecureChannel:
    """Per-direction AEAD with strictly increasing 64-bit counters.

    The underlying transport is an ordered byte stream, so any replayed,
    dropped, reordered or modified frame fails authentication.
    """

    def __init__(self, send_key: bytes, recv_key: bytes) -> None:
        self._send = ChaCha20Poly1305(send_key)
        self._recv = ChaCha20Poly1305(recv_key)
        self._send_ctr = 0
        self._recv_ctr = 0

    @staticmethod
    def _nonce(counter: int) -> bytes:
        return b"\x00\x00\x00\x00" + struct.pack(">Q", counter)

    def encrypt(self, plaintext: bytes) -> bytes:
        if self._send_ctr >= 2**63:
            raise CryptoError("nonce space exhausted")
        ct = self._send.encrypt(self._nonce(self._send_ctr), plaintext, None)
        self._send_ctr += 1
        return ct

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            pt = self._recv.decrypt(self._nonce(self._recv_ctr), ciphertext, None)
        except InvalidTag as exc:
            raise CryptoError("frame authentication failed") from exc
        self._recv_ctr += 1
        return pt


def constant_time_eq(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)


def sha256_file(path, chunk: int = 1024 * 1024, limit: int | None = None) -> str:
    h = hashlib.sha256()
    remaining = limit
    with open(path, "rb") as fh:
        while True:
            want = chunk if remaining is None else min(chunk, remaining)
            if want == 0:
                break
            data = fh.read(want)
            if not data:
                break
            h.update(data)
            if remaining is not None:
                remaining -= len(data)
    return h.hexdigest()
