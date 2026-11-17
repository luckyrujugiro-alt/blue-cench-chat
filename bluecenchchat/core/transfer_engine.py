"""Secure, resumable file transfer engine.

Protocol (all control messages travel inside the encrypted session)::

    sender                                   receiver
    x_offer {id,label,files[i,path,size,sha256]}  ->
                                              <-  x_accept {id, offsets{i:bytes}}  | x_reject
    FT_CHUNK (id, i, offset, data) ...        ->
                                              <-  x_ack {id, got}   (every ~1 MiB)
                                              <-  x_fdone {id,i,ok} (after SHA-256 check)
    x_pause / x_resume / x_cancel / x_retry   <->

* Chunk size and in-flight window adapt to the transport (LAN vs RFCOMM).
* Flow control: the sender never has more than ``window`` bytes un-acked.
* Resume: the receiver keeps ``<download>/.bluecenchchat-partial/<id>/<i>.part``;
  when the sender re-offers the same transfer id the receiver answers with
  the byte offsets it already holds and only the rest is sent.
* Integrity: every file is verified against the SHA-256 from the offer
  before it is moved into place.  Corrupt files are deleted and reported.
* Duplicate detection: files whose hash matches something already received
  (and still present) are skipped when the setting is on.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from .. import config
from . import file_safety
from .crypto import sha256_file
from .session import ProtocolError
from .transports.base import TransportError

log = logging.getLogger("bluecenchchat.transfer")

ACTIVE_STATES = ("active", "paused", "waiting")
MAX_FILES = 10_000
ACK_EVERY = 1024 * 1024


@dataclass
class Progress:
    total: int = 0
    done: int = 0
    samples: deque = field(default_factory=lambda: deque(maxlen=40))

    def update(self, done: int) -> None:
        self.done = done
        self.samples.append((time.monotonic(), done))

    @property
    def speed(self) -> float:
        now = time.monotonic()
        pts = [(t, d) for t, d in self.samples if now - t < 4]
        if len(pts) < 2 or pts[-1][0] - pts[0][0] < 0.2:
            return 0.0
        return max(0.0, (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0]))

    @property
    def eta(self) -> float | None:
        sp = self.speed
        return (self.total - self.done) / sp if sp > 0 else None


@dataclass
class OutJob:
    tid: str
    contact_id: int
    files: list
    offsets: dict
    chunk: int
    window: int
    sent: int = 0
    acked: int = 0
    base: int = 0
    ack_evt: asyncio.Event = field(default_factory=asyncio.Event)
    run_evt: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: bool = False
    task: asyncio.Task | None = None
    finished: set = field(default_factory=set)


@dataclass
class InHandle:
    fh: object
    hasher: object
    written: int


@dataclass
class InJob:
    tid: str
    contact_id: int
    files: list
    dest_root: Path
    part_dir: Path
    base: int = 0
    got: int = 0
    last_ack: int = 0
    handles: dict = field(default_factory=dict)


def expand_paths(paths: list[str]) -> tuple[list[dict], str]:
    """Expand user-selected files/folders into a transfer manifest."""
    files: list[dict] = []
    labels = []
    for raw in paths:
        p = Path(raw)
        if p.is_symlink():
            continue
        if p.is_dir():
            labels.append(p.name + "/")
            for root, dirs, names in os.walk(p):
                dirs[:] = [d for d in dirs if not Path(root, d).is_symlink()]
                for n in sorted(names):
                    fp = Path(root, n)
                    if fp.is_symlink() or not fp.is_file():
                        continue
                    rel = Path(p.name) / fp.relative_to(p)
                    files.append({"path": rel.as_posix(), "src_path": str(fp), "size": fp.stat().st_size})
        elif p.is_file():
            labels.append(p.name)
            files.append({"path": p.name, "src_path": str(p), "size": p.stat().st_size})
        if len(files) > MAX_FILES:
            raise ValueError(f"A transfer can contain at most {MAX_FILES} files")
    if not files:
        raise ValueError("Nothing to send (empty folder or unreadable files)")
    for i, f in enumerate(files):
        f.update(i=i, status="pending", done=0)
    label = labels[0] if len(labels) == 1 else f"{len(files)} files"
    if len(labels) == 1 and labels[0].endswith("/"):
        label = f"{labels[0][:-1]} ({len(files)} files)"
    return files, label


class TransferEngine:
    def __init__(self, node) -> None:
        self.node = node
        self.out_jobs: dict[str, OutJob] = {}
        self.in_jobs: dict[str, InJob] = {}
        self.progress: dict[str, Progress] = {}
        self._last_emit: dict[str, float] = {}
        self._last_persist: dict[str, float] = {}

    @property
    def repo(self):
        return self.node.repo

    # ------------------------------------------------------------------ utils
    def _emit(self, tid: str, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_emit.get(tid, 0) > 0.25:
            self._last_emit[tid] = now
            self.node.bus.emit("transfer", tid)

    def _persist(self, tid: str, force: bool = False, **fields) -> None:
        now = time.monotonic()
        if force or fields or now - self._last_persist.get(tid, 0) > 1.5:
            self._last_persist[tid] = now
            job = self.out_jobs.get(tid) or self.in_jobs.get(tid)
            if job is not None:
                fields.setdefault("files", job.files)
            prog = self.progress.get(tid)
            if prog is not None:
                fields.setdefault("done_bytes", prog.done)
            self.repo.set_transfer(tid, **fields)

    def _session(self, contact_id: int):
        s = self.node.connections.session_for_contact(contact_id)
        return s.session if s else None

    async def _send(self, contact_id: int, obj: dict) -> bool:
        sess = self._session(contact_id)
        if not sess:
            return False
        try:
            await sess.send_json(obj)
            return True
        except TransportError:
            return False

    def stats_for(self, tid: str) -> dict:
        p = self.progress.get(tid)
        if p is None:
            t = self.repo.transfer(tid)
            return {"done": t.done_bytes if t else 0, "total": t.total_bytes if t else 0, "speed": 0.0, "eta": None}
        return {"done": p.done, "total": p.total, "speed": p.speed, "eta": p.eta}

    # ------------------------------------------------------------ outgoing
    async def send_paths(self, contact_id: int, paths: list[str]) -> str:
        c = self.repo.contact(contact_id)
        if not c or c.status != "accepted":
            raise ValueError("You can only send files to accepted connections")
        files, label = await asyncio.to_thread(expand_paths, paths)
        total = sum(f["size"] for f in files)
        t = self.repo.add_transfer(
            contact_id=contact_id, direction="out", status="preparing", total_bytes=total, files=files, label=label,
        )
        self.repo.log("transfer", f"Preparing {label} for {c.name}")
        await self.node.messaging.file_note(contact_id, t.id, label, "out")
        self._emit(t.id, True)
        asyncio.create_task(self._prepare(t.id))
        return t.id

    async def _prepare(self, tid: str) -> None:
        t = self.repo.transfer(tid)
        files = t.files
        try:
            for f in files:
                if not f.get("sha256"):
                    f["sha256"] = await asyncio.to_thread(sha256_file, f["src_path"])
        except OSError as exc:
            self.repo.set_transfer(tid, status="failed", error=f"Cannot read file: {exc}"[:300], files=files)
            self._emit(tid, True)
            return
        self.repo.set_transfer(tid, status="queued", files=files)
        await self._offer(tid)

    async def _offer(self, tid: str) -> None:
        t = self.repo.transfer(tid)
        if t is None or t.status in ("completed", "cancelled", "rejected"):
            return
        sess = self._session(t.contact_id)
        if sess is None:
            self.repo.set_transfer(tid, status="queued" if t.status in ("queued", "preparing") else "interrupted",
                                   error="Waiting for the contact to come online")
            self._emit(tid, True)
            return
        manifest = [{"i": f["i"], "path": f["path"], "size": f["size"], "sha256": f["sha256"]} for f in t.files]
        transport = sess.stream.kind
        ok = await self._send(t.contact_id, {"t": "x_offer", "id": tid, "label": t.label, "total": t.total_bytes,
                                             "files": manifest})
        if ok:
            self.repo.set_transfer(tid, status="waiting", transport=transport, error="")
        self._emit(tid, True)

    async def _start_sender(self, tid: str, offsets: dict) -> None:
        t = self.repo.transfer(tid)
        sess = self._session(t.contact_id)
        if sess is None:
            return
        kind = sess.stream.kind
        chunk = config.CHUNK_SIZE.get(kind, 64 * 1024)
        job = OutJob(tid, t.contact_id, t.files, offsets, chunk, chunk * config.WINDOW_CHUNKS.get(kind, 8))
        job.base = sum(min(int(offsets.get(str(f["i"]), 0)), f["size"]) for f in job.files)
        job.run_evt.set()
        old = self.out_jobs.pop(tid, None)
        if old and old.task:
            old.cancelled = True
            old.task.cancel()
        self.out_jobs[tid] = job
        prog = Progress(total=t.total_bytes)
        prog.update(job.base)
        self.progress[tid] = prog
        self.repo.set_transfer(tid, status="active", transport=kind, error="")
        self.repo.log("transfer", f"Sending {t.label} over {self.node.transport_label(kind)}")
        job.task = asyncio.create_task(self._sender(job))
        self._emit(tid, True)

    async def _sender(self, job: OutJob) -> None:
        tid_bytes = uuid.UUID(job.tid).bytes
        try:
            for f in job.files:
                i, size = f["i"], f["size"]
                pos = min(int(job.offsets.get(str(i), 0)), size)
                if pos >= size or f.get("status") in ("sent", "duplicate"):
                    continue
                f["status"] = "sending"
                with open(f["src_path"], "rb") as fh:
                    fh.seek(pos)
                    while pos < size:
                        await job.run_evt.wait()
                        if job.cancelled:
                            return
                        while job.sent - job.acked >= job.window:
                            job.ack_evt.clear()
                            await asyncio.wait_for(job.ack_evt.wait(), 90)
                            if job.cancelled:
                                return
                        data = await asyncio.to_thread(fh.read, min(job.chunk, size - pos))
                        if not data:
                            raise OSError(f"{f['path']} became shorter while sending")
                        sess = self._session(job.contact_id)
                        if sess is None:
                            raise TransportError("connection lost")
                        await sess.send_chunk(tid_bytes, i, pos, data)
                        pos += len(data)
                        job.sent += len(data)
                        f["done"] = pos
        except asyncio.CancelledError:
            return
        except asyncio.TimeoutError:
            self._fail_out(job, "Receiver stopped acknowledging data", interrupted=True)
        except TransportError as exc:
            self._fail_out(job, str(exc), interrupted=True)
        except OSError as exc:
            self._fail_out(job, f"Read error: {exc}", interrupted=False)
            await self._send(job.contact_id, {"t": "x_cancel", "id": job.tid, "reason": "sender read error"})

    def _fail_out(self, job: OutJob, reason: str, interrupted: bool) -> None:
        job.cancelled = True
        self.out_jobs.pop(job.tid, None)
        self._persist(job.tid, force=True, status="interrupted" if interrupted else "failed", error=reason[:300])
        self._emit(job.tid, True)

    # ------------------------------------------------------------ controls
    async def pause(self, tid: str) -> None:
        t = self.repo.transfer(tid)
        if not t or t.status != "active":
            return
        if tid in self.out_jobs:
            self.out_jobs[tid].run_evt.clear()
        await self._send(t.contact_id, {"t": "x_pause", "id": tid})
        self._persist(tid, force=True, status="paused")
        self._emit(tid, True)

    async def resume(self, tid: str) -> None:
        t = self.repo.transfer(tid)
        if not t or t.status != "paused":
            return
        if tid in self.out_jobs:
            self.out_jobs[tid].run_evt.set()
        await self._send(t.contact_id, {"t": "x_resume", "id": tid})
        self._persist(tid, force=True, status="active")
        self._emit(tid, True)

    async def cancel(self, tid: str, notify_peer: bool = True) -> None:
        t = self.repo.transfer(tid)
        if not t or t.status in ("completed", "cancelled", "rejected"):
            return
        if notify_peer:
            await self._send(t.contact_id, {"t": "x_cancel", "id": tid})
        self._stop_local(tid, "cancelled", "Cancelled")

    def _stop_local(self, tid: str, status: str, error: str = "") -> None:
        job = self.out_jobs.pop(tid, None)
        if job:
            job.cancelled = True
            job.run_evt.set()
            job.ack_evt.set()
            if job.task:
                job.task.cancel()
        ijob = self.in_jobs.pop(tid, None)
        if ijob:
            for h in ijob.handles.values():
                try:
                    h.fh.close()
                except Exception:
                    pass
            if status == "cancelled":
                shutil.rmtree(ijob.part_dir, ignore_errors=True)
        self._persist(tid, force=True, status=status, error=error, finished_at=time.time())
        self._emit(tid, True)

    def cancel_all_for(self, contact_id: int) -> None:
        for t in self.repo.transfers(("active", "paused", "waiting", "offered", "queued", "interrupted")):
            if t.contact_id == contact_id:
                self._stop_local(t.id, "cancelled", "Contact blocked")

    async def retry(self, tid: str) -> None:
        t = self.repo.transfer(tid)
        if not t or t.status not in ("interrupted", "failed", "queued"):
            return
        if t.direction == "out":
            files = t.files
            for f in files:
                if f.get("status") in ("corrupt", "sending", "pending"):
                    f["status"] = "pending"
            self.repo.set_transfer(tid, files=files, error="")
            if any(not f.get("sha256") for f in files):
                await self._prepare(tid)
            else:
                await self._offer(tid)
        else:
            if not await self._send(t.contact_id, {"t": "x_retry", "id": tid}):
                self.repo.set_transfer(tid, error="Contact is offline - retry when connected")
            self._emit(tid, True)

    def on_session_lost(self, contact_id: int) -> None:
        for tid, job in list(self.out_jobs.items()):
            if job.contact_id == contact_id:
                if job.task:
                    job.task.cancel()
                self.out_jobs.pop(tid, None)
                self._persist(tid, force=True, status="interrupted", error="Connection lost - will resume")
                self._emit(tid, True)
        for tid, job in list(self.in_jobs.items()):
            if job.contact_id == contact_id:
                for h in job.handles.values():
                    try:
                        h.fh.close()
                    except Exception:
                        pass
                self.in_jobs.pop(tid, None)
                self._persist(tid, force=True, status="interrupted", error="Connection lost - partial data kept")
                self._emit(tid, True)
        for t in self.repo.transfers(("waiting",)):
            if t.contact_id == contact_id:
                self.repo.set_transfer(t.id, status="interrupted", error="Connection lost before start")
                self._emit(t.id, True)

    async def on_contact_online(self, contact_id: int) -> None:
        """Offer queued transfers and automatically resume interrupted ones."""
        for t in self.repo.transfers(("queued", "interrupted")):
            if t.contact_id == contact_id and t.direction == "out":
                await self._offer(t.id)

    # ------------------------------------------------------------ incoming
    async def accept(self, tid: str) -> None:
        t = self.repo.transfer(tid)
        if not t or t.direction != "in" or t.status not in ("offered", "interrupted", "failed"):
            return
        settings = self.node.settings
        dest_root = Path(settings.get("download_dir") or config.default_download_dir())
        part_dir = dest_root / ".bluecenchchat-partial" / tid
        try:
            part_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.repo.set_transfer(tid, status="failed", error=f"Download folder not writable: {exc}"[:300])
            self._emit(tid, True)
            return
        need = sum(f["size"] for f in t.files if f.get("status") not in ("verified", "duplicate"))
        free = shutil.disk_usage(dest_root).free
        if need > free:
            await self._send(t.contact_id, {"t": "x_reject", "id": tid, "reason": "not enough disk space"})
            self.repo.set_transfer(tid, status="failed", error="Not enough free disk space")
            self._emit(tid, True)
            return

        known = self.repo.received_hashes() if settings.get("skip_duplicates", True) else {}
        job = InJob(tid, t.contact_id, t.files, dest_root, part_dir)
        offsets: dict[str, int] = {}
        immediately_done = []
        for f in job.files:
            i, size = f["i"], f["size"]
            if f.get("status") in ("verified", "duplicate"):
                offsets[str(i)] = size
                immediately_done.append(f)
                continue
            dup = known.get(f["sha256"])
            if dup and Path(dup).exists() and size > 0:
                f.update(status="duplicate", dest_path=dup, done=size)
                offsets[str(i)] = size
                immediately_done.append(f)
                continue
            if size == 0:
                self._finalize_path(job, f, None)
                offsets[str(i)] = 0
                immediately_done.append(f)
                continue
            part = part_dir / f"{i}.part"
            have = part.stat().st_size if part.exists() else 0
            if have > size:
                part.unlink()
                have = 0
            hasher = hashlib.sha256()
            if have:
                def _rehash(p=part, h=hasher):
                    with open(p, "rb") as fh:
                        for blk in iter(lambda: fh.read(1024 * 1024), b""):
                            h.update(blk)
                await asyncio.to_thread(_rehash)
            job.handles[i] = InHandle(open(part, "ab"), hasher, have)
            f["done"] = have
            f["status"] = "receiving"
            offsets[str(i)] = have
        job.base = sum(min(offsets.get(str(f["i"]), 0), f["size"]) for f in job.files)
        self.in_jobs[tid] = job
        prog = Progress(total=t.total_bytes)
        prog.update(job.base)
        self.progress[tid] = prog
        sess = self._session(t.contact_id)
        self.repo.set_transfer(tid, status="active", files=job.files, transport=sess.stream.kind if sess else "",
                               error="")
        if not await self._send(t.contact_id, {"t": "x_accept", "id": tid, "offsets": offsets}):
            self.on_session_lost(t.contact_id)
            return
        for f in immediately_done:
            await self._send(t.contact_id, {"t": "x_fdone", "id": tid, "i": f["i"], "ok": True})
        self._emit(tid, True)
        await self._check_complete_in(job)

    async def decline(self, tid: str) -> None:
        t = self.repo.transfer(tid)
        if not t or t.direction != "in" or t.status != "offered":
            return
        await self._send(t.contact_id, {"t": "x_reject", "id": tid})
        self.repo.set_transfer(tid, status="rejected", finished_at=time.time())
        self._emit(tid, True)

    def _finalize_path(self, job: InJob, f: dict, part: Path | None) -> Path:
        rel = file_safety.sanitize_relative_path(f["path"])
        target = file_safety.unique_path(file_safety.safe_join(job.dest_root, rel))
        target.parent.mkdir(parents=True, exist_ok=True)
        if part is None:
            target.touch()
        else:
            os.replace(part, target)
        file_safety.mark_from_other_device(target)
        f.update(status="verified", dest_path=str(target), done=f["size"])
        return target

    async def on_chunk(self, contact, tid_bytes: bytes, i: int, offset: int, data: bytes) -> None:
        tid = str(uuid.UUID(bytes=tid_bytes))
        job = self.in_jobs.get(tid)
        if job is None or job.contact_id != contact.id:
            return  # late chunk after cancel - ignore
        h = job.handles.get(i)
        f = job.files[i] if 0 <= i < len(job.files) else None
        if h is None or f is None:
            raise ProtocolError("chunk for unknown file")
        if offset != h.written or h.written + len(data) > f["size"]:
            await self._send(contact.id, {"t": "x_cancel", "id": tid, "reason": "out-of-order data"})
            self._stop_local(tid, "failed", "Peer sent inconsistent data")
            return
        h.fh.write(data)
        h.hasher.update(data)
        h.written += len(data)
        f["done"] = h.written
        job.got += len(data)
        prog = self.progress[tid]
        prog.update(job.base + job.got)
        if job.got - job.last_ack >= ACK_EVERY or h.written == f["size"]:
            job.last_ack = job.got
            await self._send(contact.id, {"t": "x_ack", "id": tid, "got": job.got})
        if h.written == f["size"]:
            h.fh.close()
            del job.handles[i]
            ok = h.hasher.hexdigest() == f["sha256"]
            part = job.part_dir / f"{i}.part"
            if ok:
                try:
                    self._finalize_path(job, f, part)
                except (OSError, file_safety.UnsafePathError) as exc:
                    ok = False
                    f["status"] = "corrupt"
                    log.warning("could not store %s: %s", f["path"], exc)
            else:
                f["status"] = "corrupt"
                part.unlink(missing_ok=True)
                self.repo.log("security", f"Integrity check failed for {f['path']} - file discarded")
            await self._send(contact.id, {"t": "x_fdone", "id": tid, "i": i, "ok": ok})
            self._persist(tid, force=True)
            await self._check_complete_in(job)
        else:
            self._persist(tid)
        self._emit(tid)

    async def _check_complete_in(self, job: InJob) -> None:
        if any(f.get("status") not in ("verified", "duplicate", "corrupt") for f in job.files):
            return
        self.in_jobs.pop(job.tid, None)
        bad = [f for f in job.files if f["status"] == "corrupt"]
        shutil.rmtree(job.part_dir, ignore_errors=True)
        try:
            job.part_dir.parent.rmdir()
        except OSError:
            pass
        t = self.repo.transfer(job.tid)
        c = self.repo.contact(job.contact_id)
        if bad:
            self._persist(job.tid, force=True, status="failed", finished_at=time.time(),
                          error=f"{len(bad)} file(s) failed the SHA-256 integrity check")
            self.node.notify("transfer_failed", "Transfer failed", f"{t.label} from {c.name}: integrity check failed",
                             "notify_files", ref=job.tid)
        else:
            self.progress.setdefault(job.tid, Progress(total=t.total_bytes)).update(t.total_bytes)
            self._persist(job.tid, force=True, status="completed", finished_at=time.time(), done_bytes=t.total_bytes)
            self.node.notify("transfer_done", "File received", f"{t.label} from {c.name} - verified",
                             "notify_files", ref=job.tid)
            self.repo.log("transfer", f"Received {t.label} from {c.name} (SHA-256 verified)")
        self._emit(job.tid, True)

    # ------------------------------------------------------------ control msgs
    async def on_message(self, contact, msg: dict) -> None:
        t = msg["t"]
        tid = str(msg.get("id", ""))
        try:
            uuid.UUID(tid)
        except ValueError:
            return
        rec = self.repo.transfer(tid)
        if rec is not None and rec.contact_id != contact.id:
            raise ProtocolError("transfer id belongs to another contact")

        if t == "x_offer":
            await self._on_offer(contact, tid, rec, msg)
            return
        if rec is None:
            return
        if t == "x_accept" and rec.direction == "out" and rec.status in ("waiting", "interrupted"):
            offsets = msg.get("offsets") if isinstance(msg.get("offsets"), dict) else {}
            clean = {str(k): int(v) for k, v in offsets.items() if isinstance(v, int) and v >= 0}
            await self._start_sender(tid, clean)
        elif t == "x_reject" and rec.direction == "out":
            reason = str(msg.get("reason", ""))[:120]
            self._stop_local(tid, "rejected", f"Declined by {contact.name}" + (f": {reason}" if reason else ""))
        elif t == "x_ack":
            job = self.out_jobs.get(tid)
            got = msg.get("got")
            if job and isinstance(got, int) and job.acked <= got <= job.sent:
                job.acked = got
                job.ack_evt.set()
                self.progress[tid].update(job.base + got)
                self._persist(tid)
                self._emit(tid)
        elif t == "x_fdone" and rec.direction == "out":
            job = self.out_jobs.get(tid)
            i = msg.get("i")
            files = job.files if job else rec.files
            if not isinstance(i, int) or not 0 <= i < len(files):
                return
            files[i]["status"] = "sent" if msg.get("ok") else "corrupt"
            if msg.get("ok"):
                files[i]["done"] = files[i]["size"]
            if job:
                job.finished.add(i)
            if all(f.get("status") in ("sent", "corrupt", "duplicate") for f in files):
                bad = [f for f in files if f["status"] == "corrupt"]
                self.out_jobs.pop(tid, None)
                if bad:
                    self.repo.set_transfer(tid, files=files, status="failed", finished_at=time.time(),
                                           error=f"{len(bad)} file(s) failed verification - press Retry")
                    self.node.notify("transfer_failed", "Transfer failed", f"{rec.label} to {contact.name}",
                                     "notify_files", ref=tid)
                else:
                    self.repo.set_transfer(tid, files=files, status="completed", finished_at=time.time(),
                                           done_bytes=rec.total_bytes)
                    if tid in self.progress:
                        self.progress[tid].update(rec.total_bytes)
                    self.node.notify("transfer_done", "File sent", f"{rec.label} delivered to {contact.name} - verified",
                                     "notify_files", ref=tid)
                    self.repo.log("transfer", f"Sent {rec.label} to {contact.name} (verified by receiver)")
            else:
                self.repo.set_transfer(tid, files=files)
            self._emit(tid, True)
        elif t == "x_pause" and rec.status == "active":
            if tid in self.out_jobs:
                self.out_jobs[tid].run_evt.clear()
            self._persist(tid, force=True, status="paused")
            self._emit(tid, True)
        elif t == "x_resume" and rec.status == "paused":
            if tid in self.out_jobs:
                self.out_jobs[tid].run_evt.set()
            self._persist(tid, force=True, status="active")
            self._emit(tid, True)
        elif t == "x_cancel":
            if rec.status not in ("completed", "cancelled", "rejected"):
                reason = str(msg.get("reason", ""))[:120]
                self._stop_local(tid, "cancelled", f"Cancelled by {contact.name}" + (f" ({reason})" if reason else ""))
        elif t == "x_retry" and rec.direction == "out":
            await self.retry(tid)

    async def _on_offer(self, contact, tid: str, rec, msg: dict) -> None:
        files_in = msg.get("files")
        if not isinstance(files_in, list) or not 0 < len(files_in) <= MAX_FILES:
            raise ProtocolError("bad offer")
        files = []
        for idx, f in enumerate(files_in):
            if not isinstance(f, dict) or f.get("i") != idx:
                raise ProtocolError("bad offer entry")
            size, sha = f.get("size"), f.get("sha256")
            if not isinstance(size, int) or size < 0 or size > 2**46:
                raise ProtocolError("bad file size")
            if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                raise ProtocolError("bad file hash")
            try:
                rel = file_safety.sanitize_relative_path(f.get("path"))
            except file_safety.UnsafePathError as exc:
                raise ProtocolError(f"unsafe path in offer: {exc}") from exc
            files.append({"i": idx, "path": rel.as_posix(), "size": size, "sha256": sha, "status": "pending", "done": 0})
        total = sum(f["size"] for f in files)
        label = str(msg.get("label", ""))[:200] or files[0]["path"]

        if rec is not None:
            if rec.direction != "in":
                raise ProtocolError("offer id collides with own transfer")
            # Re-offer of a known transfer: resume automatically.
            if rec.status in ("completed",):
                for f in rec.files:
                    await self._send(contact.id, {"t": "x_fdone", "id": tid, "i": f["i"], "ok": True})
                return
            if rec.status in ("cancelled", "rejected"):
                await self._send(contact.id, {"t": "x_reject", "id": tid})
                return
            stored = {(f["i"], f["sha256"]) for f in rec.files}
            if stored != {(f["i"], f["sha256"]) for f in files}:
                raise ProtocolError("re-offer manifest changed")
            if rec.status in ("interrupted", "failed", "active", "paused"):
                job = self.in_jobs.pop(tid, None)
                if job:
                    for h in job.handles.values():
                        h.fh.close()
                fl = rec.files
                for f in fl:
                    if f.get("status") == "corrupt" or f.get("status") == "receiving":
                        f["status"] = "pending"
                self.repo.set_transfer(tid, status="offered", files=fl)
                await self.accept(tid)
            return

        risky = [f["path"] for f in files if file_safety.is_risky(f["path"])]
        self.repo.add_transfer(id=tid, contact_id=contact.id, direction="in", status="offered", total_bytes=total,
                               files=files, label=label)
        await self.node.messaging.file_note(contact.id, tid, label, "in")
        body = f"{contact.name} wants to send {label} ({_fmt(total)})"
        if risky:
            body += f". Contains {len(risky)} executable/script file(s) - only accept if you trust the sender."
        self.node.notify("file_offer", "Incoming files", body, "notify_files", ref=tid)
        self.node.bus.emit("transfer_offer", tid)
        self._emit(tid, True)
        if self.node.settings.get("auto_accept_verified") and contact.verified and not risky:
            await self.accept(tid)


def _fmt(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
