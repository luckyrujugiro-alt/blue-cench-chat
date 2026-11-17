"""Wi-Fi companion: lets phones, tablets and watches use Blue Cench Chat in a browser.

The PC stays the Blue Cench Chat device that owns the identity key and the
Bluetooth / LAN links.  Paired browsers on the same Wi-Fi (or the PC's Mobile
Hotspot) act as remote screens for that account: they read and send messages,
answer connection requests, send files from the phone and download received
files.  No internet is used.

Security
--------
* HTTPS with a self-signed certificate generated on the PC.
* Pairing needs physical access to the PC: a 6-digit code (rotates every
  5 minutes) or the one-time token inside the QR code shown on the PC.
* Each paired browser gets a random 256-bit token in an HttpOnly, Secure,
  SameSite=Strict cookie; only its SHA-256 is stored, and it can be revoked
  from the PC at any time.
* State-changing requests must carry an ``X-BlueCenchChat`` header (CSRF guard).
* Pairing attempts are rate-limited per address.
* Off by default; turned on from the "Phones & Tablets" page.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import logging
import secrets
import shutil
import time
from pathlib import Path

from sqlalchemy import delete, select

from .. import config
from ..backend.models import WebDevice
from ..core.transports.lan import local_ipv4_interfaces
from .certs import ensure_certificate

log = logging.getLogger("bluecenchchat.web")

CODE_TTL = 300
COOKIE = "bc_session"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class WebCompanion:
    def __init__(self, node) -> None:
        self.node = node
        self.server = None
        self.task: asyncio.Task | None = None
        self.port = 0
        self.running = False
        self.error = ""
        self.fingerprint = ""
        self.code = ""
        self.qr_token = ""
        self._code_born = 0.0
        self._attempts: dict[str, list[float]] = {}
        self.sockets: set = set()
        self.use_tls = True
        self._lock: asyncio.Lock | None = None

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    # ------------------------------------------------------------------ pairing
    def _rotate(self) -> None:
        self.code = f"{secrets.randbelow(10**6):06d}"
        self.qr_token = secrets.token_urlsafe(18)
        self._code_born = time.time()

    def current_code(self) -> str:
        if time.time() - self._code_born > CODE_TTL or not self.code:
            self._rotate()
            self.node.bus.emit("web")
        return self.code

    def code_expires_in(self) -> int:
        return max(0, int(CODE_TTL - (time.time() - self._code_born)))

    def urls(self) -> list[str]:
        scheme = "https" if self.use_tls else "http"
        return [f"{scheme}://{ip}:{self.port}/" for ip, _ in local_ipv4_interfaces()]

    def pairing_url(self) -> str:
        urls = self.urls()
        self.current_code()
        return (urls[0] if urls else "") + f"#pair={self.qr_token}"

    def try_pair(self, ip: str, code: str | None, token: str | None, name: str, user_agent: str) -> str:
        now = time.time()
        recent = [t for t in self._attempts.get(ip, []) if now - t < 60]
        if len(recent) >= 6:
            raise PermissionError("Too many attempts. Wait a minute and try again.")
        recent.append(now)
        self._attempts[ip] = recent
        self.current_code()
        ok = False
        if code and hmac.compare_digest(code.strip(), self.code):
            ok = True
        if token and hmac.compare_digest(token.strip(), self.qr_token):
            ok = True
        if not ok:
            raise PermissionError("That code is not correct or has expired.")
        self._rotate()  # every code / QR works exactly once
        session = secrets.token_urlsafe(32)
        with self.node.db.session() as s:
            s.add(WebDevice(account_id=self.node.repo.account_id, name=(name.strip() or "Phone")[:60],
                            token_hash=_hash(session), user_agent=user_agent[:300], last_ip=ip))
            s.commit()
        self._attempts.pop(ip, None)
        self.node.repo.log("security", f"New phone/tablet paired: {name[:60] or 'Phone'} ({ip})")
        self.node.notify("security", "New device paired", f"{name[:60] or 'A phone'} can now use Blue Cench Chat over Wi-Fi.",
                         "notify_security")
        self.node.bus.emit("web")
        return session

    def authenticate(self, token: str | None, ip: str = "") -> WebDevice | None:
        if not token or len(token) > 100:
            return None
        h = _hash(token)
        with self.node.db.session() as s:
            dev = s.scalar(select(WebDevice).where(WebDevice.token_hash == h,
                                                   WebDevice.account_id == self.node.repo.account_id))
            if dev is None:
                return None
            if time.time() - dev.last_seen > 30:
                dev.last_seen = time.time()
                dev.last_ip = ip or dev.last_ip
                s.commit()
            return dev

    def devices(self) -> list[WebDevice]:
        with self.node.db.session() as s:
            return list(s.scalars(select(WebDevice).where(WebDevice.account_id == self.node.repo.account_id)
                                  .order_by(WebDevice.last_seen.desc())))

    def revoke(self, device_id: int) -> None:
        with self.node.db.session() as s:
            s.execute(delete(WebDevice).where(WebDevice.id == device_id,
                                              WebDevice.account_id == self.node.repo.account_id))
            s.commit()
        for ws in list(self.sockets):
            if getattr(ws, "device_id", None) == device_id:
                asyncio.ensure_future(ws.close(code=4401))
        self.node.repo.log("security", "Removed a paired phone/tablet")
        self.node.bus.emit("web")

    # ------------------------------------------------------------------ uploads
    def upload_dir(self) -> Path:
        p = config.data_dir() / "web_uploads"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def cleanup_uploads(self, max_age_days: int = 7) -> None:
        cutoff = time.time() - max_age_days * 86400
        for d in self.upload_dir().iterdir():
            try:
                if d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            except OSError:
                pass

    # ------------------------------------------------------------------ server
    async def start(self, port: int | None = None, tls: bool = True, host: str = "0.0.0.0") -> None:
        # serialise start/stop: toggling quickly must never run two servers or
        # write the certificate twice at the same time
        async with self._get_lock():
            await self._start(port, tls, host)

    async def _start(self, port: int | None, tls: bool, host: str) -> None:
        if self.running:
            return
        import uvicorn

        from .api import create_app

        self.use_tls = tls
        port = config.WEB_PORT if port is None else port
        self._rotate()
        self.cleanup_uploads()
        ssl_kwargs = {}
        if tls:
            ips = [ip for ip, _ in local_ipv4_interfaces()]
            cert, key, self.fingerprint = await asyncio.to_thread(
                ensure_certificate, config.data_dir() / "web", ips)
            ssl_kwargs = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        app = create_app(self)
        cfg = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False, lifespan="off",
                             log_config=None, ws="websockets-sansio", ws_max_size=64 * 1024, **ssl_kwargs)

        class _Server(uvicorn.Server):
            @contextlib.contextmanager
            def capture_signals(self):  # the desktop app owns process signals
                yield

        self.server = _Server(cfg)
        self.task = asyncio.create_task(self.server.serve())
        for _ in range(100):
            await asyncio.sleep(0.05)
            if self.server.started:
                break
            if self.task.done():
                break
        if not self.server.started and port != 0:
            # preferred port busy (e.g. a second Blue Cench Chat profile) - use any free port
            self.server = None
            if self.task.done():
                self.task.exception()
            return await self._fallback(host, tls)
        if not self.server.started:
            exc = self.task.exception() if self.task.done() else None
            self.error = f"Could not start on port {port}: {exc or 'port in use?'}"
            log.warning(self.error)
            self.server = None
            self.node.bus.emit("web")
            return
        sock = self.server.servers[0].sockets[0]
        self.port = sock.getsockname()[1]
        self.running = True
        self.error = ""
        log.info("Wi-Fi companion listening on %s", self.port)
        self.node.apply_visibility()
        self.node.bus.emit("web")

    async def _fallback(self, host: str, tls: bool) -> None:
        log.info("port busy, trying a random free port")
        await self._start(port=0, tls=tls, host=host)

    async def stop(self) -> None:
        async with self._get_lock():
            await self._stop()

    async def _stop(self) -> None:
        if not self.server:
            return
        for ws in list(self.sockets):
            with contextlib.suppress(Exception):
                await ws.close()
        self.server.should_exit = True
        if self.task:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.task, 5)
        self.server = None
        self.running = False
        self.port = 0
        self.node.apply_visibility()
        self.node.bus.emit("web")
