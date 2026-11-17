"""A tiny in-process stand-in for Firebase Auth + Realtime Database (REST + streaming),
enforcing the same access rules as firebase/database.rules.json."""
from __future__ import annotations

import asyncio
import json
import secrets
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


def make_app():
    app = FastAPI()
    state = {"accounts": {}, "tokens": {}, "refresh": {}, "db": {}, "rev": 0}

    def err(code, msg):
        return JSONResponse({"error": {"code": code, "message": msg}}, status_code=code)

    def issue(uid):
        tok, ref = secrets.token_hex(16), secrets.token_hex(16)
        state["tokens"][tok] = uid
        state["refresh"][ref] = uid
        return tok, ref

    @app.post("/auth/{op}")
    async def auth(op: str, request: Request):
        body = await request.json()
        email, pw = body.get("email", ""), body.get("password", "")
        accs = state["accounts"]
        if op == "accounts:signUp":
            if email in accs:
                return err(400, "EMAIL_EXISTS")
            if len(pw) < 6:
                return err(400, "WEAK_PASSWORD : Password should be at least 6 characters")
            accs[email] = {"pw": pw, "uid": uuid.uuid4().hex[:28]}
        elif op == "accounts:signInWithPassword":
            a = accs.get(email)
            if not a or a["pw"] != pw:
                return err(400, "INVALID_LOGIN_CREDENTIALS")
        else:
            return err(404, "NOT_FOUND")
        uid = accs[email]["uid"]
        tok, ref = issue(uid)
        return {"localId": uid, "idToken": tok, "refreshToken": ref, "expiresIn": "3600"}

    @app.post("/token/token")
    async def token(request: Request):
        form = await request.form()
        uid = state["refresh"].get(form.get("refresh_token", ""))
        if not uid:
            return err(400, "INVALID_REFRESH_TOKEN")
        tok, ref = issue(uid)
        return {"user_id": uid, "id_token": tok, "refresh_token": ref, "expires_in": "3600"}

    def node(parts, create=False):
        cur = state["db"]
        for p in parts[:-1]:
            if p not in cur or not isinstance(cur[p], dict):
                if not create:
                    return None, None
                cur[p] = {}
            cur = cur[p]
        return cur, parts[-1] if parts else None

    def get(parts):
        cur = state["db"]
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur

    def sv(v):
        if isinstance(v, dict):
            if v == {".sv": "timestamp"}:
                return int(time.time() * 1000)
            return {k: sv(x) for k, x in v.items()}
        return v

    def allowed(uid, method, parts, body):
        if not uid:
            return False
        if parts[:1] == ["users"]:
            return method == "GET" or (len(parts) == 2 and parts[1] == uid)
        if parts[:1] == ["mailbox"] and len(parts) >= 2:
            to = parts[1]
            if method == "GET":
                return to == uid
            if method == "POST" and len(parts) == 2:
                return isinstance(body, dict) and body.get("f") == uid
            if method == "DELETE" and len(parts) == 3:
                return to == uid
        return False

    @app.api_route("/db/{path:path}", methods=["GET", "PUT", "POST", "PATCH", "DELETE"])
    async def db(path: str, request: Request):
        path = path[:-5] if path.endswith(".json") else path
        parts = [p for p in path.split("/") if p]
        uid = state["tokens"].get(request.query_params.get("auth", ""))
        body = None
        if request.method in ("PUT", "POST", "PATCH"):
            body = json.loads(await request.body() or b"null")
        if uid is None:
            return err(401, "Permission denied")
        if not allowed(uid, request.method, parts, body):
            return err(403, "Permission denied")
        if request.method == "GET":
            if "text/event-stream" in request.headers.get("accept", ""):
                return StreamingResponse(stream(parts), media_type="text/event-stream")
            return get(parts)
        body = sv(body)
        if request.method == "POST":
            parent, _ = node(parts + ["x"], create=True)
            key = f"-{int(time.time() * 1000):013d}{secrets.token_hex(4)}"
            parent[key] = body
            state["rev"] += 1
            return {"name": key}
        parent, key = node(parts, create=True)
        if request.method == "PUT":
            parent[key] = body
        elif request.method == "PATCH":
            parent.setdefault(key, {}).update(body)
        elif request.method == "DELETE":
            parent.pop(key, None)
        state["rev"] += 1
        return body

    async def stream(parts):
        sent = set()
        cur = get(parts) or {}
        sent.update(cur.keys())
        yield f"event: put\ndata: {json.dumps({'path': '/', 'data': cur or None})}\n\n"
        last_keep = time.time()
        while True:
            await asyncio.sleep(0.05)
            cur = get(parts) or {}
            for k, v in list(cur.items()):
                if k not in sent:
                    sent.add(k)
                    yield f"event: put\ndata: {json.dumps({'path': '/' + k, 'data': v})}\n\n"
            if time.time() - last_keep > 5:
                last_keep = time.time()
                yield "event: keep-alive\ndata: null\n\n"

    app.state.fb = state
    return app
