"""Self-signed TLS certificate for the Wi-Fi companion.

Phones talk to the PC over HTTPS so messages and files are encrypted on the
Wi-Fi even when the network itself is open.  Because there is no internet
certificate authority involved, browsers show a one-time "not private"
warning; the certificate fingerprint is displayed on the PC so users can
check they reached their own computer.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import os
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def ensure_certificate(folder: Path, ips: list[str]) -> tuple[Path, Path, str]:
    """Return (cert, key, sha256 fingerprint); regenerate when IPs change."""
    folder.mkdir(parents=True, exist_ok=True)
    cert_p, key_p, meta_p = folder / "cert.pem", folder / "key.pem", folder / "cert.json"
    wanted = sorted(set(ips) | {"127.0.0.1"})
    if cert_p.exists() and key_p.exists() and meta_p.exists():
        try:
            meta = json.loads(meta_p.read_text())
            cert = x509.load_pem_x509_certificate(cert_p.read_bytes())
            still_valid = cert.not_valid_after_utc > dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)
            if meta.get("ips") == wanted and still_valid:
                return cert_p, key_p, meta["fingerprint"]
        except Exception:
            pass
    key = ec.generate_private_key(ec.SECP256R1())
    host = socket.gethostname() or "bluecenchchat"
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Blue Cench Chat on " + host[:40]),
                      x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Blue Cench Chat")])
    sans: list[x509.GeneralName] = [x509.DNSName("localhost")]
    try:
        sans.append(x509.DNSName(host.lower()))
    except Exception:
        pass
    for ip in wanted:
        try:
            sans.append(x509.IPAddress(ipaddress.ip_address(ip)))
        except ValueError:
            continue
    now = dt.datetime.now(dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=825))
        .add_extension(x509.SubjectAlternativeName(sans), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    fp = hashlib.sha256(der).hexdigest().upper()
    fingerprint = ":".join(fp[i:i + 2] for i in range(0, 32, 2))  # first 16 bytes, readable
    # write to temporary files, then swap in, so cert and key always match
    tmp_key, tmp_cert = key_p.with_suffix(".tmp-key"), cert_p.with_suffix(".tmp-cert")
    tmp_key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    try:
        os.chmod(tmp_key, 0o600)
    except OSError:
        pass
    tmp_cert.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    os.replace(tmp_key, key_p)
    os.replace(tmp_cert, cert_p)
    meta_p.write_text(json.dumps({"ips": wanted, "fingerprint": fingerprint}))
    return cert_p, key_p, fingerprint
