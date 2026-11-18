"""HTTP + WebSocket API used by the Blue Cench Chat web app on phones, tablets and watches."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.websockets import WebSocketDisconnect

from .. import config
from ..core import file_safety, voice
from ..core.messaging import REACTIONS
from .companion import COOKIE, WebCompanion

STATIC = Path(__file__).resolve().parent / "static"
MAX_UPLOAD = 4 * 1024 * 1024 * 1024  # 4 GB per request


class PairIn(BaseModel):
    code: str | None = Field(default=None, max_length=12)
    token: str | None = Field(default=None, max_length=64)
    name: str = Field(default="Phone", max_length=60)


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=config.MAX_TEXT_LEN)
    reply_to: str | None = Field(default=None, max_length=36)


class FlagIn(BaseModel):
    on: bool


class ReactIn(BaseModel):
    r: str = Field(default="", max_length=16)


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


class NoteIn(BaseModel):
    text: str = Field(default="", max_length=60)
    music: str = Field(default="", max_length=80)


class TickIn(BaseModel):
    message: str = Field(default="", max_length=200)


class ConnectIn(BaseModel):
    key: str = Field(max_length=80)


def _contact(node, c) -> dict:
    s = node.connections.session_for_contact(c.id)
    return {
        "id": c.id, "uid": c.peer_user_id, "name": c.name, "username": c.username, "about": c.about,
        "status": c.status, "verified": c.verified, "favorite": c.favorite, "online": s is not None,
        "transport": node.transport_label(s.transport) if s else "", "last_seen": c.last_seen,
        "has_avatar": bool(c.avatar), "tick": node.social.badge(c), "i_follow": c.i_follow,
        "follows_me": c.follows_me, "followers": c.followers_count, "following": c.following_count,
        "posts": c.posts_count, "note": c.note_text, "music": c.note_music,
    }


def _post(node, p) -> dict:
    me = p.author_uid == node.identity.user_id
    c = None if me else node.repo.contact_by_peer(p.author_uid)
    acc = node.repo.account()
    return {"id": p.id, "mine": me, "author": acc.display_name if me else (c.name if c else p.author_uid),
            "author_id": c.id if c else None, "uid": p.author_uid,
            "tick": node.social.badge() if me else (node.social.badge(c) if c else ""),
            "caption": p.caption, "music": p.music, "has_image": bool(p.image), "ts": p.created_at,
            "likes": p.likes, "comments": p.comments, "liked": p.liked, "saved": p.saved}


def _message(m) -> dict:
    return {"id": m.id, "dir": m.direction, "kind": m.kind, "body": m.body, "reply_to": m.reply_to,
            "status": m.status, "reaction": m.reaction, "ts": m.ts, "transfer_id": m.transfer_id,
            "preview": m.preview}


def _transfer(node, t) -> dict:
    st = node.transfers.stats_for(t.id)
    c = node.repo.contact(t.contact_id)
    return {
        "id": t.id, "dir": t.direction, "status": t.status, "label": t.label, "contact": c.name if c else "",
        "contact_id": t.contact_id, "transport": node.transport_label(t.transport) if t.transport else "",
        "total": t.total_bytes, "done": st["done"], "speed": st["speed"], "eta": st["eta"], "error": t.error,
        "created": t.created_at,
        "files": [{"i": f["i"], "path": f["path"], "size": f["size"], "status": f.get("status", ""),
                   "downloadable": bool(t.direction == "in" and f.get("dest_path") and
                                        f.get("status") in ("verified", "duplicate"))} for f in t.files[:500]],
    }


def create_app(comp: WebCompanion) -> FastAPI:
    node = comp.node
    app = FastAPI(title="Blue Cench Chat", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.url.path.startswith("/api/") \
                and request.headers.get("x-bluecenchchat") != "1":
            return JSONResponse({"detail": "missing X-BlueCenchChat header"}, status_code=403)
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; style-src 'self'; script-src 'self'; "
            "connect-src 'self' wss: ws:; frame-ancestors 'none'")
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    def device(request: Request):
        ip = request.client.host if request.client else ""
        dev = comp.authenticate(request.cookies.get(COOKIE), ip)
        if dev is None:
            raise HTTPException(401, "Not paired")
        return dev

    auth = Depends(device)

    # ---------------------------------------------------------------- pages
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/manifest.webmanifest")
    async def manifest():
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")

    # ---------------------------------------------------------------- pairing
    @app.get("/api/session")
    async def session(request: Request):
        dev = comp.authenticate(request.cookies.get(COOKIE))
        return {"paired": dev is not None, "app": config.APP_NAME, "version": config.APP_VERSION,
                "device": dev.name if dev else None}

    @app.post("/api/pair")
    async def pair(body: PairIn, request: Request, response: Response):
        ip = request.client.host if request.client else "?"
        try:
            token = comp.try_pair(ip, body.code, body.token, body.name, request.headers.get("user-agent", ""))
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        response.set_cookie(COOKIE, token, max_age=365 * 86400, httponly=True, secure=comp.use_tls,
                            samesite="strict", path="/")
        return {"ok": True}

    @app.post("/api/logout")
    async def logout(response: Response, dev=auth):
        comp.revoke(dev.id)
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    # ---------------------------------------------------------------- me / status
    @app.get("/api/me")
    async def me(dev=auth):
        acc = node.repo.account()
        st = node.status()
        a = st["adapter"]
        return {
            "name": acc.display_name, "username": acc.username, "uid": acc.user_id, "about": acc.about,
            "device": dev.name, "visible": st["visible"], "scanning": st["scanning"],
            "bluetooth": "on" if a.available and a.radio_on else ("off" if a.available else "unavailable"),
            "ble_advertising": st["ble_publishing"], "rfcomm": st["rfcomm"], "lan": st["lan"], "ips": st["ips"],
            "unread": node.repo.unread_total(), "alerts": node.repo.unread_notifications(),
            "requests": len(node.repo.contacts(("pending_in",))),
            "offers": len(node.repo.transfers(("offered",))),
        }

    @app.get("/api/avatar/me")
    async def my_avatar(dev=auth):
        acc = node.repo.account()
        if not acc.avatar:
            raise HTTPException(404)
        return Response(acc.avatar, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})

    @app.post("/api/visible")
    async def visible(body: FlagIn, dev=auth):
        node.update_settings(visible=body.on)
        return {"ok": True}

    # ---------------------------------------------------------------- contacts
    def get_contact(cid: int):
        c = node.repo.contact(cid)
        if c is None:
            raise HTTPException(404, "Unknown contact")
        return c

    @app.get("/api/contacts")
    async def contacts(group: str = "accepted", dev=auth):
        statuses = {"accepted": ("accepted",), "requests": ("pending_in", "pending_out"),
                    "blocked": ("blocked",)}.get(group, ("accepted",))
        return [_contact(node, c) for c in node.repo.contacts(statuses)]

    @app.get("/api/contacts/{cid}")
    async def contact(cid: int, dev=auth):
        c = get_contact(cid)
        return {**_contact(node, c), "safety": node.safety_number(cid)}

    @app.get("/api/avatar/{cid}")
    async def avatar(cid: int, dev=auth):
        c = get_contact(cid)
        if not c.avatar:
            raise HTTPException(404)
        return Response(c.avatar, media_type="image/png", headers={"Cache-Control": "private, max-age=60"})

    @app.post("/api/contacts/{cid}/{action}")
    async def contact_action(cid: int, action: str, dev=auth):
        c = get_contact(cid)
        cm = node.connections
        if action == "accept":
            if not cm.is_online(cid):
                raise HTTPException(409, f"{c.name} is offline. Accept when they reconnect.")
            await cm.accept(cid)
        elif action == "reject":
            await cm.reject(cid)
        elif action == "block":
            await cm.block(cid)
        elif action == "unblock":
            cm.unblock(cid)
        elif action == "disconnect":
            await cm.disconnect(cid)
        elif action == "verify":
            node.repo.set_contact(cid, verified=not c.verified)
            node.bus.emit("contacts")
        elif action == "favorite":
            node.repo.set_contact(cid, favorite=not c.favorite)
            node.bus.emit("contacts")
        elif action == "connect":
            route = node.discovery.find_contact_route(c)
            addr = c.address
            lan = (route.lan_ip, route.lan_port) if route and route.lan_ip and route.lan_port else (
                (addr["ip"], addr["port"]) if addr.get("ip") and addr.get("port") else None)
            bt = (route.bt_addr if route else None) or addr.get("bt_addr")
            try:
                await cm.connect(lan=lan, bt_addr=bt, expect_user_id=c.peer_user_id)
            except Exception as exc:
                raise HTTPException(409, f"Could not reach {c.name}: {exc}")
        else:
            raise HTTPException(404)
        return {"ok": True}

    # ---------------------------------------------------------------- chats
    @app.get("/api/conversations")
    async def conversations(dev=auth):
        out = []
        for c, last, unread in node.repo.conversations():
            out.append({**_contact(node, c), "last": _message(last) if last else None, "unread": unread})
        return out

    @app.get("/api/messages/{cid}")
    async def messages(cid: int, search: str = "", dev=auth):
        get_contact(cid)
        return [_message(m) for m in node.repo.messages(cid, search=search[:100], limit=300)]

    @app.post("/api/messages/{cid}")
    async def send(cid: int, body: MessageIn, dev=auth):
        get_contact(cid)
        try:
            mid = await node.messaging.send_text(cid, body.text, body.reply_to)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return _message(node.repo.message(mid))

    @app.post("/api/messages/{cid}/voice")
    async def send_voice(cid: int, request: Request, dev=auth):
        """Phone recorded a voice message: raw 16-bit mono PCM at 8 kHz in the body."""
        get_contact(cid)
        if request.headers.get("x-bluecenchchat") != "1":
            raise HTTPException(403, "Missing header")
        data = await request.body()
        if len(data) > voice.MAX_BYTES * 2 + 1024:
            raise HTTPException(413, f"Voice messages are limited to {voice.MAX_SECONDS} seconds")
        try:
            mid = await node.messaging.send_voice(cid, data, voice.RATE)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return _message(node.repo.message(mid))

    @app.get("/api/voice/{mid}")
    async def voice_audio(mid: str, dev=auth):
        m = node.repo.message(mid)
        audio = voice.load(mid) if m and m.kind == "voice" else None
        if audio is None:
            raise HTTPException(404)
        return Response(voice.wav(voice.decode(audio)), media_type="audio/wav",
                        headers={"Cache-Control": "private, max-age=86400"})

    @app.post("/api/messages/{cid}/read")
    async def read(cid: int, dev=auth):
        get_contact(cid)
        await node.messaging.mark_read(cid)
        return {"ok": True}

    @app.post("/api/messages/{cid}/typing")
    async def typing(cid: int, body: FlagIn, dev=auth):
        get_contact(cid)
        await node.messaging.set_typing(cid, body.on)
        return {"ok": True}

    def own_message(mid: str):
        m = node.repo.message(mid)
        if m is None:
            raise HTTPException(404)
        return m

    @app.post("/api/message/{mid}/react")
    async def react(mid: str, body: ReactIn, dev=auth):
        own_message(mid)
        if body.r and body.r not in REACTIONS:
            raise HTTPException(400, "Unknown reaction")
        await node.messaging.react(mid, body.r)
        return {"ok": True}

    @app.post("/api/message/{mid}/delete")
    async def delete(mid: str, everyone: bool = False, dev=auth):
        own_message(mid)
        await node.messaging.delete(mid, everyone)
        return {"ok": True}

    # ---------------------------------------------------------------- nearby
    @app.get("/api/nearby")
    async def nearby(dev=auth):
        out = []
        for p in node.discovery.list():
            cid = node.discovery.contact_for_hint(p.hint) if p.hint else None
            c = node.repo.contact(cid) if cid else (node.repo.contact_by_peer(p.user_id) if p.user_id else None)
            out.append({"key": p.key, "name": c.name if c else p.display_name(), "username": p.username,
                        "uid": p.user_id, "rssi": p.rssi, "bars": p.signal_bars, "transports": p.transports,
                        "sources": sorted(p.sources), "contact_id": c.id if c else None,
                        "status": c.status if c else "new",
                        "online": bool(c and node.connections.is_online(c.id))})
        return {"scanning": node.discovery.scanning, "peers": out}

    @app.post("/api/scan")
    async def scan(body: FlagIn, dev=auth):
        node.discovery.start_scan() if body.on else node.discovery.stop_scan()
        return {"ok": True}

    @app.post("/api/nearby/connect")
    async def nearby_connect(body: ConnectIn, dev=auth):
        p = node.discovery.peers.get(body.key)
        if p is None:
            raise HTTPException(404, "That device is no longer nearby")
        lan = (p.lan_ip, p.lan_port) if p.lan_ip and p.lan_port else None
        if not lan and not p.bt_addr:
            raise HTTPException(409, "No route to this device yet")
        try:
            cid = await node.connections.connect(lan=lan, bt_addr=p.bt_addr, prefer="lan" if lan else "rfcomm",
                                                 expect_user_id=p.user_id or None)
            c = node.repo.contact(cid)
            if c.status != "accepted":
                await node.connections.send_request(cid, "")
        except Exception as exc:
            raise HTTPException(409, f"Could not connect: {exc}")
        return _contact(node, node.repo.contact(cid))

    # ---------------------------------------------------------------- files
    @app.get("/api/transfers")
    async def transfers(dev=auth):
        return [_transfer(node, t) for t in node.repo.transfers(limit=100)]

    @app.post("/api/transfers/{tid}/{action}")
    async def transfer_action(tid: str, action: str, dev=auth):
        t = node.repo.transfer(tid)
        if t is None:
            raise HTTPException(404)
        eng = node.transfers
        fn = {"accept": eng.accept, "decline": eng.decline, "pause": eng.pause, "resume": eng.resume,
              "cancel": eng.cancel, "retry": eng.retry}.get(action)
        if fn is None:
            raise HTTPException(404)
        await fn(tid)
        return _transfer(node, node.repo.transfer(tid))

    @app.post("/api/send/{cid}")
    async def upload(cid: int, request: Request, files: list[UploadFile] = File(...), dev=auth):
        c = get_contact(cid)
        if c.status != "accepted":
            raise HTTPException(400, "You can only send files to accepted connections")
        if not files or len(files) > 200:
            raise HTTPException(400, "Choose between 1 and 200 files")
        folder = comp.upload_dir() / uuid.uuid4().hex
        folder.mkdir(parents=True)
        paths, total = [], 0
        for f in files:
            try:
                rel = file_safety.sanitize_relative_path(Path(f.filename or "file").name)
            except file_safety.UnsafePathError:
                rel = Path("file")
            target = file_safety.unique_path(folder / rel)
            with open(target, "wb") as out:
                while chunk := await f.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD:
                        raise HTTPException(413, "Upload too large (4 GB limit per send)")
                    await asyncio.to_thread(out.write, chunk)
            paths.append(str(target))
        tid = await node.transfers.send_paths(cid, paths)
        return {"id": tid}

    @app.get("/api/files/{tid}/{index}")
    async def download(tid: str, index: int, dev=auth):
        t = node.repo.transfer(tid)
        if t is None or t.direction != "in" or not 0 <= index < len(t.files):
            raise HTTPException(404)
        f = t.files[index]
        p = f.get("dest_path")
        if not p or f.get("status") not in ("verified", "duplicate") or not Path(p).is_file():
            raise HTTPException(404, "File is not available")
        return FileResponse(p, filename=Path(p).name)

    # ---------------------------------------------------------------- social (Instagram-style)
    def get_post(pid: str):
        p = node.social.post(pid)
        if p is None:
            raise HTTPException(404, "Post not found")
        return p

    @app.get("/api/feed")
    async def feed(dev=auth):
        return [_post(node, p) for p in node.social.feed(60)]

    @app.get("/api/notes")
    async def notes(dev=auth):
        acc = node.repo.account()
        mine = node.social.note()
        people = [c for c in node.repo.contacts() if (c.note_text or c.note_music) and c.status != "blocked"]
        people.sort(key=lambda c: -c.note_ts)
        return {"me": {"name": acc.display_name, **mine},
                "people": [{"id": c.id, "name": c.name, "note": c.note_text, "music": c.note_music,
                            "has_avatar": bool(c.avatar), "tick": node.social.badge(c)} for c in people[:40]]}

    @app.post("/api/note")
    async def set_note(body: NoteIn, dev=auth):
        await node.social.set_note(body.text, body.music)
        return {"ok": True}

    @app.post("/api/posts")
    async def create_post(caption: str = Form(default="", max_length=2200), music: str = Form(default="", max_length=80),
                          image: UploadFile | None = File(default=None), dev=auth):
        data = None
        if image is not None and image.filename:
            data = await image.read(25 * 1024 * 1024 + 1)
            if len(data) > 25 * 1024 * 1024:
                raise HTTPException(413, "Photo too large (25 MB limit)")
        if not caption.strip() and not data:
            raise HTTPException(400, "Add a photo or write a caption")
        try:
            pid = await node.social.create_post(caption, data, music)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return _post(node, node.social.post(pid))

    @app.get("/api/posts/{pid}/image")
    async def post_image(pid: str, dev=auth):
        p = get_post(pid)
        if not p.image:
            raise HTTPException(404)
        return Response(p.image, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/api/posts/{pid}/comments")
    async def comments(pid: str, dev=auth):
        get_post(pid)
        asyncio.ensure_future(node.social.refresh_comments(pid))
        return [{"name": c.author_name, "uid": c.author_uid, "text": c.text, "ts": c.ts}
                for c in node.social.comments(pid)]

    @app.post("/api/posts/{pid}/comments")
    async def comment(pid: str, body: CommentIn, dev=auth):
        get_post(pid)
        await node.social.add_comment(pid, body.text)
        return {"ok": True}

    @app.post("/api/posts/{pid}/{action}")
    async def post_action(pid: str, action: str, dev=auth):
        get_post(pid)
        if action == "like":
            await node.social.toggle_like(pid)
        elif action == "save":
            await node.social.toggle_save(pid)
        elif action == "delete":
            await node.social.delete_post(pid)
            return {"ok": True}
        else:
            raise HTTPException(404)
        return _post(node, node.social.post(pid))

    @app.get("/api/everyone")
    async def everyone(q: str = "", dev=auth):
        cloud = node.cloud
        if not cloud.online:
            return {"online": False, "status": cloud.status, "error": cloud.error, "people": []}
        q = q.strip().lower().lstrip("@")[:40]
        out = []
        for p in await cloud.directory():
            if q and q not in p.get("name", "").lower() and q not in p.get("username", "").lower():
                continue
            c = node.repo.contact_by_peer(p["uid"])
            out.append({"fuid": p["fuid"], "name": p.get("name", ""), "username": p.get("username", ""),
                        "about": p.get("about", ""), "followers": p.get("followers", 0),
                        "following": p.get("following", 0), "posts": p.get("posts", 0), "note": p.get("note", ""),
                        "online": cloud.is_recent(p), "id": c.id if c else None,
                        "i_follow": bool(c and c.i_follow), "follows_me": bool(c and c.follows_me),
                        "blocked": bool(c and c.status == "blocked"), "uid": p["uid"],
                        "tick": (node.social.badge(c) if c else "") or ("verified" if cloud.profile_verified(p) else "")})
        return {"online": True, "status": "online", "people": out[:300]}

    @app.post("/api/everyone/{fuid}/open")
    async def everyone_open(fuid: str, dev=auth):
        if not node.cloud.online or len(fuid) > 128:
            raise HTTPException(409, "You're offline - turn on online mode on the PC")
        try:
            cid = await node.cloud.open_person(fuid)
        except Exception as exc:
            raise HTTPException(404, str(exc))
        return {"id": cid}

    @app.get("/api/profile")
    async def my_profile(dev=auth):
        from ..core import verification as vf
        acc = node.repo.account()
        st = node.social.stats()
        return {"name": acc.display_name, "username": acc.username, "uid": acc.user_id, "about": acc.about,
                "tick": node.social.badge(), "admin": node.social.is_admin(), **st,
                "note": node.social.note(), "need": vf.MIN_FOLLOWERS_FOR_REQUEST,
                "tick_requested": bool(node.settings.get("tick_request")),
                "posts_list": [_post(node, p) for p in node.social.posts_by(acc.user_id)]}

    @app.get("/api/profile/{cid}")
    async def profile(cid: int, dev=auth):
        c = get_contact(cid)
        return {**_contact(node, c), "posts_list": [_post(node, p) for p in node.social.posts_by(c.peer_user_id)]}

    @app.post("/api/follow/{cid}")
    async def follow(cid: int, body: FlagIn, dev=auth):
        get_contact(cid)
        try:
            await node.social.follow(cid, body.on)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True}

    @app.post("/api/tick/request")
    async def tick_request(body: TickIn, dev=auth):
        try:
            msg = await node.social.request_tick(body.message)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "message": msg}

    # ---------------------------------------------------------------- notifications
    @app.get("/api/notifications")
    async def notifications(dev=auth):
        return [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "ref": n.ref, "ts": n.ts,
                 "read": n.read} for n in node.repo.notifications(100)]

    @app.post("/api/notifications/read")
    async def notifications_read(dev=auth):
        node.repo.mark_notifications_read()
        node.bus.emit("notification", None)
        return {"ok": True}

    # ---------------------------------------------------------------- live events
    @app.websocket("/api/ws")
    async def ws(socket: WebSocket):
        ip = socket.client.host if socket.client else ""
        dev = comp.authenticate(socket.cookies.get(COOKIE), ip)
        origin = socket.headers.get("origin", "")
        host = socket.headers.get("host", "")
        if dev is None or (origin and origin.split("://", 1)[-1] != host):
            await socket.close(code=4401)
            return
        await socket.accept()
        socket.device_id = dev.id
        comp.sockets.add(socket)
        queue: asyncio.Queue = asyncio.Queue(maxsize=500)
        last: dict[str, float] = {}

        def push(event: str):
            def cb(*args):
                key = event + json.dumps([a for a in args if isinstance(a, (int, str, bool))])
                now = time.monotonic()
                if event in ("transfer", "peers", "status") and now - last.get(key, 0) < 0.4:
                    return
                last[key] = now
                safe = [a if isinstance(a, (int, str, bool)) or a is None else None for a in args]
                try:
                    queue.put_nowait({"e": event, "a": safe})
                except asyncio.QueueFull:
                    pass
            return cb

        subs = [(e, push(e)) for e in ("messages", "message", "contacts", "session", "peers", "transfer",
                                       "transfer_offer", "notification", "typing", "request", "status", "social", "cloud")]
        for e, cb in subs:
            node.bus.on(e, cb)

        async def reader():
            while True:
                await socket.receive_text()  # keep-alive pings from the page

        rtask = asyncio.create_task(reader())
        try:
            while True:
                get = asyncio.create_task(queue.get())
                done, _ = await asyncio.wait({get, rtask}, timeout=25, return_when=asyncio.FIRST_COMPLETED)
                if rtask in done:
                    get.cancel()
                    break
                if get in done:
                    await socket.send_json(get.result())
                else:
                    get.cancel()
                    await socket.send_json({"e": "ping", "a": []})
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass
        finally:
            rtask.cancel()
            for e, cb in subs:
                node.bus.off(e, cb)
            comp.sockets.discard(socket)

    return app
