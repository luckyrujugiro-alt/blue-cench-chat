"""Wi-Fi companion: real HTTPS server + real browser-like client against two live nodes."""
import asyncio
import json
import ssl

import httpx
import pytest
import websockets

from .conftest import connect_and_accept, wait_for

H = {"X-BlueCenchChat": "1"}


@pytest.fixture
async def web(pair):
    a, b = pair
    await a.web.start(port=0)
    assert a.web.running and a.web.port
    base = f"https://127.0.0.1:{a.web.port}"
    async with httpx.AsyncClient(base_url=base, verify=False, timeout=20) as client:
        yield a, b, client
    await a.web.stop()


async def pair_client(a, client):
    r = await client.post("/api/pair", json={"code": a.web.current_code(), "name": "Test iPhone"}, headers=H)
    assert r.status_code == 200, r.text
    assert "bc_session" in client.cookies


async def test_pairing_and_auth(web):
    a, b, client = web
    r = await client.get("/")
    assert r.status_code == 200 and "Blue Cench Chat" in r.text
    assert r.headers["x-frame-options"] == "DENY"
    assert (await client.get("/api/me")).status_code == 401
    assert (await client.get("/api/session")).json()["paired"] is False
    r = await client.post("/api/pair", json={"code": "000000" if a.web.current_code() != "000000" else "111111"}, headers=H)
    assert r.status_code == 403
    # CSRF guard: state-changing call without header is refused
    r = await client.post("/api/pair", json={"code": a.web.current_code()})
    assert r.status_code == 403
    used = a.web.current_code()
    await pair_client(a, client)
    assert a.web.current_code() != used  # one-time code
    me = (await client.get("/api/me")).json()
    assert me["uid"] == a.identity.user_id and me["device"] == "Test iPhone"
    assert len(a.web.devices()) == 1
    # QR token pairing works once
    tok = a.web.qr_token
    async with httpx.AsyncClient(base_url=client.base_url, verify=False) as c2:
        assert (await c2.post("/api/pair", json={"token": tok, "name": "iPad"}, headers=H)).status_code == 200
        assert (await c2.get("/api/me")).status_code == 200
        # revoking signs that device out
        dev = next(d for d in a.web.devices() if d.name == "iPad")
        a.web.revoke(dev.id)
        assert (await c2.get("/api/me")).status_code == 401
    async with httpx.AsyncClient(base_url=client.base_url, verify=False) as c3:
        assert (await c3.post("/api/pair", json={"token": tok}, headers=H)).status_code == 403


async def test_rate_limit(web):
    a, b, client = web
    codes = []
    for _ in range(7):
        r = await client.post("/api/pair", json={"code": "999999" if a.web.current_code() != "999999" else "888888"},
                              headers=H)
        codes.append(r.status_code)
    assert codes[-1] == 403 and "Too many" in r.json()["detail"]


async def test_chat_and_files_from_phone(web, tmp_path):
    a, b, client = web
    ab, ba = await connect_and_accept(a, b)
    await pair_client(a, client)
    convs = (await client.get("/api/conversations")).json()
    assert convs[0]["id"] == ab and convs[0]["online"]
    # phone sends a message -> arrives at Bob's PC
    r = await client.post(f"/api/messages/{ab}", json={"text": "Hello from my phone"}, headers=H)
    assert r.status_code == 200
    await wait_for(lambda: any(m.body == "Hello from my phone" for m in b.repo.messages(ba)))
    # Bob replies -> phone sees it
    await b.messaging.send_text(ba, "Hi phone")
    await wait_for(lambda: any(m.body == "Hi phone" for m in a.repo.messages(ab)))
    msgs = (await client.get(f"/api/messages/{ab}")).json()
    assert [m["body"] for m in msgs][-2:] == ["Hello from my phone", "Hi phone"]
    # phone uploads a photo -> transfer to Bob
    offers = []
    b.bus.on("transfer_offer", offers.append)
    r = await client.post(f"/api/send/{ab}", files={"files": ("../../photo.jpg", b"\xff\xd8 jpeg bytes", "image/jpeg")},
                          headers=H)
    assert r.status_code == 200, r.text
    await wait_for(lambda: offers)
    await b.transfers.accept(offers[0])
    await wait_for(lambda: b.repo.transfer(offers[0]).status == "completed")
    assert (tmp_path / "bob_downloads" / "photo.jpg").read_bytes() == b"\xff\xd8 jpeg bytes"
    # Bob sends a file -> phone accepts and downloads it
    f = tmp_path / "report.pdf"
    f.write_bytes(b"%PDF-1.7 test")
    tid = await b.transfers.send_paths(ba, [str(f)])
    await wait_for(lambda: a.repo.transfer(tid) is not None and a.repo.transfer(tid).status == "offered")
    r = await client.post(f"/api/transfers/{tid}/accept", headers=H)
    assert r.status_code == 200
    await wait_for(lambda: a.repo.transfer(tid).status == "completed")
    t = next(x for x in (await client.get("/api/transfers")).json() if x["id"] == tid)
    assert t["files"][0]["downloadable"]
    r = await client.get(f"/api/files/{tid}/0")
    assert r.content == b"%PDF-1.7 test"
    assert (await client.get(f"/api/files/{tid}/5")).status_code == 404


async def test_requests_and_nearby_from_phone(web):
    a, b, client = web
    await pair_client(a, client)
    cid = await b.connections.connect(lan=("127.0.0.1", a.lan.port))
    await b.connections.send_request(cid)
    await wait_for(lambda: (c := a.repo.contact_by_peer(b.identity.user_id)) and c.status == "pending_in")
    reqs = (await client.get("/api/contacts?group=requests")).json()
    assert reqs[0]["status"] == "pending_in"
    r = await client.post(f"/api/contacts/{reqs[0]['id']}/accept", headers=H)
    assert r.status_code == 200
    await wait_for(lambda: b.repo.contact(cid).status == "accepted")
    near = (await client.get("/api/nearby")).json()
    assert "peers" in near and "scanning" in near


async def test_live_events_websocket(web):
    a, b, client = web
    ab, ba = await connect_and_accept(a, b)
    await pair_client(a, client)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    cookie = f"bc_session={client.cookies['bc_session']}"
    url = f"wss://127.0.0.1:{a.web.port}/api/ws"
    async with websockets.connect(url, ssl=ctx, additional_headers={"Cookie": cookie}) as ws:
        await b.messaging.send_text(ba, "live!")
        got = []
        while not any(e["e"] == "message" for e in got):
            got.append(json.loads(await asyncio.wait_for(ws.recv(), 10)))
        ev = next(e for e in got if e["e"] == "message")
        assert ev["a"][0] == ab
    # without a session cookie the socket is refused
    with pytest.raises(Exception):
        async with websockets.connect(url, ssl=ctx) as ws2:
            await asyncio.wait_for(ws2.recv(), 5)


async def test_concurrent_start_is_safe(pair):
    a, b = pair
    await asyncio.gather(a.web.start(port=0), a.web.start(port=0), a.web.start(port=0))
    assert a.web.running and a.web.port
    async with httpx.AsyncClient(verify=False) as c:
        assert (await c.get(f"https://127.0.0.1:{a.web.port}/api/session")).status_code == 200
    await asyncio.gather(a.web.stop(), a.web.stop())
    assert not a.web.running


async def test_beacon_announces_phone_access(pair):
    a, b = pair
    await a.web.start(port=0)
    payload = a.lan._beacon_payload
    assert payload["web"] == a.web.port and len(payload["fp"].split(":")) == 16
    await a.web.stop()
    assert a.lan._beacon_payload["web"] == 0


async def test_social_from_phone(web):
    """Phone: follow, note, post with a photo, like, comment, profile, tick-request rule."""
    import io

    from PIL import Image

    a, b, client = web
    ab, ba = await connect_and_accept(a, b)
    await pair_client(a, client)
    # follow Bob from the phone -> Bob sees a follower
    assert (await client.post(f"/api/follow/{ab}", json={"on": True}, headers=H)).status_code == 200
    await wait_for(lambda: b.repo.contact(ba).follows_me)
    await wait_for(lambda: a.repo.contact(ab).followers_count == 1)
    # note
    assert (await client.post("/api/note", json={"text": "Hello world", "music": "Song - Artist"}, headers=H)).status_code == 200
    await wait_for(lambda: b.repo.contact(ba).note_text == "Hello world")
    notes = (await client.get("/api/notes")).json()
    assert notes["me"]["text"] == "Hello world"
    # post with a photo
    bio = io.BytesIO()
    Image.new("RGB", (1600, 1200), (30, 140, 240)).save(bio, "PNG")
    r = await client.post("/api/posts", data={"caption": "First post", "music": ""},
                          files={"image": ("pic.png", bio.getvalue(), "image/png")}, headers=H)
    assert r.status_code == 200, r.text
    pid = r.json()["id"]
    img = await client.get(f"/api/posts/{pid}/image")
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(img.content)).size) <= 1080
    # empty post rejected; CSRF header required
    assert (await client.post("/api/posts", data={"caption": " "}, headers=H)).status_code == 400
    assert (await client.post(f"/api/posts/{pid}/like")).status_code in (401, 403)
    # Bob follows back and sees the post, likes and comments from his side
    await b.social.follow(ba, True)
    await wait_for(lambda: b.social.post(pid) is not None)
    await b.social.toggle_like(pid)
    await b.social.add_comment(pid, "Nice!")
    await wait_for(lambda: a.social.post(pid).likes == 1 and a.social.post(pid).comments == 1)
    # phone likes Bob's post
    bp = await b.social.create_post("Bob's post", None)
    await wait_for(lambda: a.social.post(bp) is not None)
    feed = (await client.get("/api/feed")).json()
    assert {p["id"] for p in feed} >= {pid, bp}
    r = await client.post(f"/api/posts/{bp}/like", headers=H)
    assert r.json()["liked"] is True
    await wait_for(lambda: b.social.post(bp).likes == 1)
    assert (await client.post(f"/api/posts/{bp}/comments", json={"text": "From my phone"}, headers=H)).status_code == 200
    await wait_for(lambda: any(c.text == "From my phone" for c in b.social.comments(bp)))
    comments = (await client.get(f"/api/posts/{pid}/comments")).json()
    assert comments[0]["text"] == "Nice!"
    # profiles
    me = (await client.get("/api/profile")).json()
    assert me["followers"] == 1 and me["posts"] == 1 and not me["tick"]
    other = (await client.get(f"/api/profile/{ab}")).json()
    assert other["i_follow"] and other["follows_me"] and other["posts_list"][0]["id"] == bp
    # blue tick needs 40 followers
    r = await client.post("/api/tick/request", json={"message": "please"}, headers=H)
    assert r.status_code == 400 and "40 followers" in r.json()["detail"]
    # delete own post
    assert (await client.post(f"/api/posts/{pid}/delete", headers=H)).status_code == 200
    assert a.social.post(pid) is None


async def test_voice_from_phone(web, tmp_path, monkeypatch):
    import math
    import struct

    from bluecenchchat.core import voice
    monkeypatch.setattr(voice.config, "data_dir", lambda: tmp_path)
    a, b, client = web
    ab, ba = await connect_and_accept(a, b)
    await pair_client(a, client)
    pcm = b"".join(struct.pack("<h", int(9000 * math.sin(i / 4))) for i in range(8000 * 2))
    assert (await client.post(f"/api/messages/{ab}/voice", content=pcm)).status_code == 403  # header required
    r = await client.post(f"/api/messages/{ab}/voice", content=pcm, headers=H)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["kind"] == "voice" and m["preview"].startswith("Voice message")
    await wait_for(lambda: b.repo.message(m["id"]) is not None)
    w = await client.get(f"/api/voice/{m['id']}")
    assert w.status_code == 200 and w.headers["content-type"] == "audio/wav" and w.content[:4] == b"RIFF"
    assert (await client.post(f"/api/messages/{ab}/voice", content=pcm[:2000], headers=H)).status_code == 400
