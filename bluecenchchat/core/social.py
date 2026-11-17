"""Instagram-style social layer that works without a server.

Everything travels over the same authenticated, encrypted peer sessions as
chat.  Peers exchange a small "s_hello" when they meet (counts, note, follow
state, blue tick, revocations); people you follow send you their posts; likes
and comments go to the post's author, who keeps the authoritative counts.

Counts are honest: your follower count is the number of people who actually
follow you; others see the count you report when you meet.
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
import uuid

from sqlalchemy import delete, func, select

from ..backend.models import Account, Contact, Post, PostComment, PostLike, Revocation, TickRequest
from . import verification as vf

log = logging.getLogger("bluecenchchat.social")

MAX_IMAGE = 900_000
MAX_CAPTION = 2200
FEED_BATCH = 30


def prepare_image(raw: bytes) -> bytes:
    """Resize to Instagram size (max 1080 px) and re-encode as JPEG; strips metadata (location etc.)."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(raw)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((1080, 1080))
        for q in (85, 75, 65, 55):
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q, optimize=True)
            if buf.tell() <= MAX_IMAGE:
                return buf.getvalue()
        im.thumbnail((720, 720))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=60)
        return buf.getvalue()


class SocialService:
    def __init__(self, node) -> None:
        self.node = node

    # ------------------------------------------------------------------ helpers
    @property
    def repo(self):
        return self.node.repo

    @property
    def db(self):
        return self.node.db

    @property
    def me(self) -> str:
        return self.node.identity.user_id

    def _sessions(self, only=None):
        for s in list(self.node.connections.sessions.values()):
            if only is None or s.contact_id in only:
                yield s

    async def _send(self, contact_id: int, obj: dict) -> bool:
        s = self.node.connections.session_for_contact(contact_id)
        if not s:
            return False
        try:
            await s.session.send_json(obj)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ counts / profile
    def stats(self) -> dict:
        aid = self.repo.account_id
        with self.db.session() as s:
            followers = s.scalar(select(func.count()).where(Contact.account_id == aid, Contact.follows_me.is_(True),
                                                             Contact.status != "blocked")) or 0
            following = s.scalar(select(func.count()).where(Contact.account_id == aid, Contact.i_follow.is_(True))) or 0
            posts = s.scalar(select(func.count()).where(Post.account_id == aid, Post.author_uid == self.me)) or 0
        return {"followers": followers, "following": following, "posts": posts}

    def note(self) -> dict:
        st = self.node.settings
        return {"text": st.get("note_text", ""), "music": st.get("note_music", ""), "ts": st.get("note_ts", 0)}

    async def set_note(self, text: str, music: str = "") -> None:
        text, music = text.strip()[:60], music.strip()[:80]
        self.node.update_settings(note_text=text, note_music=music, note_ts=time.time() if (text or music) else 0)
        payload = {"t": "s_note", **self.note()}
        for s in self._sessions():
            try:
                await s.session.send_json(payload)
            except Exception:
                pass
        self.node.bus.emit("social")

    # ------------------------------------------------------------------ verification
    def is_admin(self) -> bool:
        acc = self.repo.account()
        return vf.can_verify(acc.username, self.node.identity.public_bytes)

    def admin_published(self) -> bool:
        return vf.is_published_verifier(self.node.identity.public_bytes)

    def _revoked_after(self, uid: str) -> int:
        with self.db.session() as s:
            r = s.scalar(select(Revocation).where(Revocation.account_id == self.repo.account_id, Revocation.uid == uid))
        if not r:
            return 0
        chk = vf.check_revocation(r.blob)
        return chk[1] if chk else 0

    def my_tick(self) -> str:
        acc = self.repo.account()
        if self.admin_published():
            # the official account is verified by definition
            if not vf.check_tick(acc.tick_cert, self.me, self.node.identity.public_bytes):
                cert = vf.issue_tick(self.node.identity, self.me, self.node.identity.public_bytes, acc.display_name)
                with self.db.session() as s:
                    s.get(Account, acc.id).tick_cert = cert
                    s.commit()
                return cert
        cert = acc.tick_cert or ""
        if cert and vf.check_tick(cert, self.me, self.node.identity.public_bytes) \
                and vf.tick_time(cert) > self._revoked_after(self.me):
            return cert
        return ""

    def is_verified_me(self) -> bool:
        return bool(self.my_tick())

    def is_verified(self, contact: Contact) -> bool:
        cert = contact.tick_cert or ""
        return bool(cert and vf.check_tick(cert, contact.peer_user_id, contact.identity_pub)
                    and vf.tick_time(cert) > self._revoked_after(contact.peer_user_id))

    def is_verifier_contact(self, contact: Contact) -> bool:
        return vf.is_published_verifier(contact.identity_pub)

    async def request_tick(self, message: str = "") -> str:
        if self.is_verified_me():
            return "You are already verified."
        followers = self.stats()["followers"]
        if followers < vf.MIN_FOLLOWERS_FOR_REQUEST:
            raise ValueError(f"You need at least {vf.MIN_FOLLOWERS_FOR_REQUEST} followers to request a blue tick "
                             f"(you have {followers}).")
        self.node.update_settings(tick_request=message[:300] or "Please verify my account", tick_request_ts=time.time(),
                                  tick_request_sent=False)
        sent = await self._deliver_tick_request()
        return ("Request sent to Blue Cench Chat. You'll be notified when it's reviewed." if sent else
                "Request saved. It is delivered automatically the next time you're connected to the official "
                "Blue Cench Chat account.")

    async def _deliver_tick_request(self) -> bool:
        st = self.node.settings
        if not st.get("tick_request") or st.get("tick_request_sent"):
            return False
        for s in self._sessions():
            c = self.repo.contact(s.contact_id)
            if c and self.is_verifier_contact(c):
                ok = await self._send(c.id, {"t": "s_tick_req", "followers": self.stats()["followers"],
                                             "message": st.get("tick_request", "")})
                if ok:
                    self.node.update_settings(tick_request_sent=True)
                    return True
        return False

    def tick_requests(self, status: str | None = None) -> list[TickRequest]:
        with self.db.session() as s:
            q = select(TickRequest).where(TickRequest.account_id == self.repo.account_id)
            if status:
                q = q.where(TickRequest.status == status)
            return list(s.scalars(q.order_by(TickRequest.ts.desc())))

    def people(self) -> list[dict]:
        """Admin dashboard: everyone this device knows, with follower counts and tick status."""
        out = []
        reqs = {r.peer_uid: r for r in self.tick_requests()}
        for c in self.repo.contacts():
            r = reqs.get(c.peer_user_id)
            out.append({"contact": c, "verified": self.is_verified(c), "followers": c.followers_count,
                        "request": r, "online": self.node.connections.is_online(c.id)})
        out.sort(key=lambda d: (d["request"] is None or d["request"].status != "pending", -d["followers"],
                                d["contact"].name.lower()))
        return out

    async def grant_tick(self, peer_uid: str) -> None:
        if not self.is_admin():
            raise PermissionError("Only the official Blue Cench Chat account can give blue ticks")
        c = self.repo.contact_by_peer(peer_uid)
        if c is None:
            raise ValueError("Unknown person")
        cert = vf.issue_tick(self.node.identity, peer_uid, c.identity_pub, c.name)
        with self.db.session() as s:
            r = s.scalar(select(TickRequest).where(TickRequest.account_id == self.repo.account_id,
                                                   TickRequest.peer_uid == peer_uid))
            if r is None:
                r = TickRequest(account_id=self.repo.account_id, peer_uid=peer_uid, name=c.name,
                                followers=c.followers_count, message="Granted by admin")
                s.add(r)
            r.status, r.cert, r.delivered = "granted", cert, False
            s.commit()
        self.repo.set_contact(c.id, tick_cert=cert)
        await self._deliver_grants(c.id)
        self.repo.log("security", f"Blue tick given to {c.name} ({peer_uid})")
        self.node.bus.emit("social")
        self.node.bus.emit("contacts")

    async def decline_tick(self, peer_uid: str) -> None:
        with self.db.session() as s:
            r = s.scalar(select(TickRequest).where(TickRequest.account_id == self.repo.account_id,
                                                   TickRequest.peer_uid == peer_uid))
            if r:
                r.status = "declined"
                s.commit()
        self.node.bus.emit("social")

    async def revoke_tick(self, peer_uid: str) -> None:
        if not self.is_admin():
            raise PermissionError("Only the official Blue Cench Chat account can remove blue ticks")
        blob = vf.issue_revocation(self.node.identity, peer_uid)
        self._store_revocation(blob)
        with self.db.session() as s:
            r = s.scalar(select(TickRequest).where(TickRequest.account_id == self.repo.account_id,
                                                   TickRequest.peer_uid == peer_uid))
            if r:
                r.status = "revoked"
                s.commit()
        for s_ in self._sessions():
            try:
                await s_.session.send_json({"t": "s_tick_rev", "blob": blob})
            except Exception:
                pass
        self.node.bus.emit("social")
        self.node.bus.emit("contacts")

    def _store_revocation(self, blob: str) -> bool:
        chk = vf.check_revocation(blob)
        if not chk:
            return False
        uid, ts = chk
        with self.db.session() as s:
            r = s.scalar(select(Revocation).where(Revocation.account_id == self.repo.account_id, Revocation.uid == uid))
            if r is None:
                s.add(Revocation(account_id=self.repo.account_id, uid=uid, blob=blob, ts=ts))
            elif ts > r.ts:
                r.blob, r.ts = blob, ts
            else:
                return False
            s.commit()
        return True

    def _revocation_blobs(self) -> list[str]:
        with self.db.session() as s:
            return [r.blob for r in s.scalars(select(Revocation).where(Revocation.account_id == self.repo.account_id)
                                              .order_by(Revocation.ts.desc()).limit(50))]

    async def _deliver_grants(self, contact_id: int) -> None:
        c = self.repo.contact(contact_id)
        if not c:
            return
        with self.db.session() as s:
            r = s.scalar(select(TickRequest).where(TickRequest.account_id == self.repo.account_id,
                                                   TickRequest.peer_uid == c.peer_user_id,
                                                   TickRequest.status == "granted", TickRequest.delivered.is_(False)))
            cert = r.cert if r else None
        if cert and await self._send(contact_id, {"t": "s_tick_grant", "cert": cert}):
            with self.db.session() as s:
                r = s.scalar(select(TickRequest).where(TickRequest.account_id == self.repo.account_id,
                                                       TickRequest.peer_uid == c.peer_user_id))
                r.delivered = True
                s.commit()

    # ------------------------------------------------------------------ follow
    async def follow(self, contact_id: int, on: bool = True) -> None:
        c = self.repo.contact(contact_id)
        if not c or c.status == "blocked":
            raise ValueError("You can't follow this person")
        self.repo.set_contact(contact_id, i_follow=on)
        await self._send(contact_id, {"t": "s_follow" if on else "s_unfollow"})
        await self._hello(self.repo.contact(contact_id))  # my "following" count changed
        if on:
            await self._request_feed(contact_id)
        else:
            with self.db.session() as s:
                s.execute(delete(Post).where(Post.account_id == self.repo.account_id, Post.author_uid == c.peer_user_id,
                                             Post.saved.is_(False)))
                s.commit()
        self.node.bus.emit("social")
        self.node.bus.emit("contacts")

    async def _request_feed(self, contact_id: int) -> None:
        c = self.repo.contact(contact_id)
        with self.db.session() as s:
            newest = s.scalar(select(func.max(Post.created_at)).where(Post.account_id == self.repo.account_id,
                                                                       Post.author_uid == c.peer_user_id)) or 0
        await self._send(contact_id, {"t": "s_feed_req", "since": newest})

    # ------------------------------------------------------------------ posts
    async def create_post(self, caption: str, image: bytes | None, music: str = "") -> str:
        caption = caption.strip()[:MAX_CAPTION]
        if not caption and not image:
            raise ValueError("Add a photo or write something")
        img = None
        if image:

            img = await asyncio.to_thread(prepare_image, image)
        pid = str(uuid.uuid4())
        with self.db.session() as s:
            s.add(Post(id=pid, account_id=self.repo.account_id, author_uid=self.me, caption=caption,
                       music=music.strip()[:80], image=img))
            s.commit()
        post = self.post(pid)
        for c in self.repo.contacts():
            if c.follows_me and self.node.connections.is_online(c.id):
                await self._send(c.id, self._post_payload(post, c.peer_user_id))
        self.repo.log("system", "You shared a new post")
        self.node.bus.emit("social")
        return pid

    async def delete_post(self, post_id: str) -> None:
        p = self.post(post_id)
        if not p:
            return
        with self.db.session() as s:
            s.execute(delete(Post).where(Post.id == post_id, Post.account_id == self.repo.account_id))
            s.execute(delete(PostComment).where(PostComment.post_id == post_id,
                                                PostComment.account_id == self.repo.account_id))
            s.execute(delete(PostLike).where(PostLike.post_id == post_id, PostLike.account_id == self.repo.account_id))
            s.commit()
        if p.author_uid == self.me:
            for c in self.repo.contacts():
                if c.follows_me:
                    await self._send(c.id, {"t": "s_post_del", "id": post_id})
        self.node.bus.emit("social")

    def post(self, post_id: str) -> Post | None:
        with self.db.session() as s:
            p = s.get(Post, post_id)
            return p if p and p.account_id == self.repo.account_id else None

    def feed(self, limit: int = 100) -> list[Post]:
        following = {c.peer_user_id for c in self.repo.contacts() if c.i_follow and c.status != "blocked"}
        following.add(self.me)
        with self.db.session() as s:
            rows = s.scalars(select(Post).where(Post.account_id == self.repo.account_id,
                                                Post.author_uid.in_(following))
                             .order_by(Post.created_at.desc()).limit(limit))
            return list(rows)

    def posts_by(self, uid: str) -> list[Post]:
        with self.db.session() as s:
            return list(s.scalars(select(Post).where(Post.account_id == self.repo.account_id, Post.author_uid == uid)
                                  .order_by(Post.created_at.desc())))

    def author_name(self, uid: str) -> str:
        if uid == self.me:
            return self.repo.account().display_name
        c = self.repo.contact_by_peer(uid)
        return c.name if c else uid

    def _post_payload(self, p: Post, for_uid: str) -> dict:
        with self.db.session() as s:
            liked = s.scalar(select(func.count()).where(PostLike.post_id == p.id, PostLike.liker_uid == for_uid)) or 0
        d = {"t": "s_post", "id": p.id, "caption": p.caption, "music": p.music, "ts": p.created_at,
             "likes": p.likes, "comments": p.comments, "liked": bool(liked)}
        if p.image:
            d["img"] = base64.b64encode(p.image).decode()
        return d

    async def toggle_like(self, post_id: str) -> None:
        p = self.post(post_id)
        if not p:
            return
        on = not p.liked
        with self.db.session() as s:
            row = s.get(Post, post_id)
            row.liked = on
            if row.author_uid == self.me:
                if on:
                    s.add(PostLike(account_id=self.repo.account_id, post_id=post_id, liker_uid=self.me))
                else:
                    s.execute(delete(PostLike).where(PostLike.post_id == post_id, PostLike.liker_uid == self.me))
                s.flush()
                row.likes = s.scalar(select(func.count()).where(PostLike.post_id == post_id)) or 0
            else:
                row.likes = max(0, row.likes + (1 if on else -1))
            s.commit()
        if p.author_uid != self.me:
            c = self.repo.contact_by_peer(p.author_uid)
            if c:
                await self._send(c.id, {"t": "s_like", "post_id": post_id, "on": on})
        self.node.bus.emit("social")

    async def toggle_save(self, post_id: str) -> None:
        with self.db.session() as s:
            row = s.get(Post, post_id)
            if row and row.account_id == self.repo.account_id:
                row.saved = not row.saved
                s.commit()
        self.node.bus.emit("social")

    async def add_comment(self, post_id: str, text: str) -> None:
        text = text.strip()[:500]
        p = self.post(post_id)
        if not p or not text:
            return
        cid = str(uuid.uuid4())
        name = self.repo.account().display_name
        with self.db.session() as s:
            s.add(PostComment(id=cid, account_id=self.repo.account_id, post_id=post_id, author_uid=self.me,
                              author_name=name, text=text))
            row = s.get(Post, post_id)
            row.comments += 1
            s.commit()
        if p.author_uid != self.me:
            c = self.repo.contact_by_peer(p.author_uid)
            if c:
                await self._send(c.id, {"t": "s_comment", "post_id": post_id, "id": cid, "text": text})
        self.node.bus.emit("social")

    def comments(self, post_id: str) -> list[PostComment]:
        with self.db.session() as s:
            return list(s.scalars(select(PostComment).where(PostComment.account_id == self.repo.account_id,
                                                            PostComment.post_id == post_id)
                                  .order_by(PostComment.ts)))

    async def refresh_comments(self, post_id: str) -> None:
        p = self.post(post_id)
        if p and p.author_uid != self.me:
            c = self.repo.contact_by_peer(p.author_uid)
            if c:
                await self._send(c.id, {"t": "s_comments_req", "post_id": post_id})

    # ------------------------------------------------------------------ session hooks
    async def _hello(self, c: Contact) -> None:
        await self._send(c.id, {"t": "s_hello", **self.stats(), "note": self.note(), "follow": bool(c.i_follow),
                                "tick": self.my_tick(), "rev": self._revocation_blobs()})

    async def on_session(self, contact_id: int) -> None:
        c = self.repo.contact(contact_id)
        if not c or c.status == "blocked":
            return
        await self._hello(c)
        if c.i_follow:
            await self._request_feed(contact_id)
        if self.is_verifier_contact(c):
            await self._deliver_tick_request()
        if self.is_admin():
            await self._deliver_grants(contact_id)

    async def on_message(self, contact: Contact, msg: dict) -> None:
        t = msg["t"]
        repo = self.repo
        if contact.status == "blocked":
            return
        if t == "s_hello":
            fields = {}
            for k_src, k_dst in (("followers", "followers_count"), ("following", "following_count"),
                                 ("posts", "posts_count")):
                v = msg.get(k_src)
                if isinstance(v, int) and 0 <= v < 10**9:
                    fields[k_dst] = v
            was_following = contact.follows_me
            fields["follows_me"] = bool(msg.get("follow"))
            note = msg.get("note") if isinstance(msg.get("note"), dict) else {}
            fields["note_text"] = str(note.get("text", ""))[:60]
            fields["note_music"] = str(note.get("music", ""))[:80]
            fields["note_ts"] = float(note.get("ts", 0) or 0)
            for blob in (msg.get("rev") or [])[:50]:
                if isinstance(blob, str):
                    self._store_revocation(blob)
            tick = msg.get("tick", "")
            fields["tick_cert"] = tick if isinstance(tick, str) and vf.check_tick(
                tick, contact.peer_user_id, contact.identity_pub) else ""
            repo.set_contact(contact.id, **fields)
            if fields["follows_me"] and not was_following:
                self.node.notify("follow", f"{contact.name} follows you", "", "notify_requests",
                                 ref=str(contact.id), store=True)
            self.node.bus.emit("contacts")
            self.node.bus.emit("social")
        elif t in ("s_follow", "s_unfollow"):
            on = t == "s_follow"
            repo.set_contact(contact.id, follows_me=on)
            if on and not contact.follows_me:
                self.node.notify("follow", f"{contact.name} started following you", "", "notify_requests",
                                 ref=str(contact.id))
                repo.log("social", f"{contact.name} started following you")
            asyncio.ensure_future(self._hello(repo.contact(contact.id)))  # my follower count changed
            self.node.bus.emit("social")
            self.node.bus.emit("contacts")
        elif t == "s_note":
            repo.set_contact(contact.id, note_text=str(msg.get("text", ""))[:60],
                             note_music=str(msg.get("music", ""))[:80], note_ts=float(msg.get("ts", 0) or 0))
            self.node.bus.emit("social")
        elif t == "s_feed_req":
            since = msg.get("since", 0) if isinstance(msg.get("since"), (int, float)) else 0
            with self.db.session() as s:
                rows = list(s.scalars(select(Post).where(Post.account_id == repo.account_id, Post.author_uid == self.me,
                                                         Post.created_at > since)
                                      .order_by(Post.created_at.desc()).limit(FEED_BATCH)))
            for p in reversed(rows):
                await self._send(contact.id, self._post_payload(p, contact.peer_user_id))
        elif t == "s_post":
            if not contact.i_follow:
                return
            pid = str(msg.get("id", ""))
            try:
                uuid.UUID(pid)
            except ValueError:
                return
            img = None
            if isinstance(msg.get("img"), str) and len(msg["img"]) < MAX_IMAGE * 1.4:
                try:
                    img = base64.b64decode(msg["img"], validate=True)
                    if img[:3] != b"\xff\xd8\xff":
                        img = None
                except ValueError:
                    img = None
            with self.db.session() as s:
                p = s.get(Post, pid)
                if p is not None and (p.account_id != repo.account_id or p.author_uid != contact.peer_user_id):
                    return
                if p is None:
                    p = Post(id=pid, account_id=repo.account_id, author_uid=contact.peer_user_id)
                    s.add(p)
                p.caption = str(msg.get("caption", ""))[:MAX_CAPTION]
                p.music = str(msg.get("music", ""))[:80]
                ts = msg.get("ts")
                p.created_at = float(ts) if isinstance(ts, (int, float)) and ts < time.time() + 300 else time.time()
                p.likes = max(0, int(msg.get("likes", 0) or 0))
                p.comments = max(0, int(msg.get("comments", 0) or 0))
                p.liked = bool(msg.get("liked"))
                if img is not None or p.image is None:
                    p.image = img
                s.commit()
            self.node.bus.emit("social")
        elif t == "s_post_del":
            with self.db.session() as s:
                s.execute(delete(Post).where(Post.id == str(msg.get("id", "")), Post.account_id == repo.account_id,
                                             Post.author_uid == contact.peer_user_id))
                s.commit()
            self.node.bus.emit("social")
        elif t == "s_like":
            pid = str(msg.get("post_id", ""))
            p = self.post(pid)
            if not p or p.author_uid != self.me:
                return
            with self.db.session() as s:
                exists = s.scalar(select(PostLike).where(PostLike.post_id == pid,
                                                         PostLike.liker_uid == contact.peer_user_id))
                if msg.get("on") and not exists:
                    s.add(PostLike(account_id=repo.account_id, post_id=pid, liker_uid=contact.peer_user_id))
                    self.node.notify("like", f"{contact.name} liked your post", (p.caption or "")[:80],
                                     "notify_messages", ref=pid)
                elif not msg.get("on") and exists:
                    s.delete(exists)
                s.flush()
                row = s.get(Post, pid)
                row.likes = s.scalar(select(func.count()).where(PostLike.post_id == pid)) or 0
                s.commit()
                likes, comments = row.likes, row.comments
            await self._send(contact.id, {"t": "s_post_stats", "post_id": pid, "likes": likes, "comments": comments})
            self.node.bus.emit("social")
        elif t == "s_comment":
            pid = str(msg.get("post_id", ""))
            text = str(msg.get("text", "")).strip()[:500]
            cid = str(msg.get("id", ""))
            p = self.post(pid)
            if not p or p.author_uid != self.me or not text:
                return
            try:
                uuid.UUID(cid)
            except ValueError:
                return
            with self.db.session() as s:
                if s.get(PostComment, cid) is None:
                    s.add(PostComment(id=cid, account_id=repo.account_id, post_id=pid, author_uid=contact.peer_user_id,
                                      author_name=contact.name, text=text))
                    row = s.get(Post, pid)
                    row.comments += 1
                    s.commit()
                row = s.get(Post, pid)
                likes, comments = row.likes, row.comments
            self.node.notify("comment", f"{contact.name} commented", text[:120], "notify_messages", ref=pid)
            await self._send(contact.id, {"t": "s_post_stats", "post_id": pid, "likes": likes, "comments": comments})
            self.node.bus.emit("social")
        elif t == "s_post_stats":
            pid = str(msg.get("post_id", ""))
            with self.db.session() as s:
                row = s.get(Post, pid)
                if row and row.account_id == repo.account_id and row.author_uid == contact.peer_user_id:
                    row.likes = max(0, int(msg.get("likes", 0) or 0))
                    row.comments = max(0, int(msg.get("comments", 0) or 0))
                    s.commit()
            self.node.bus.emit("social")
        elif t == "s_comments_req":
            pid = str(msg.get("post_id", ""))
            p = self.post(pid)
            if not p or p.author_uid != self.me:
                return
            items = [{"id": c.id, "author_uid": c.author_uid, "author_name": c.author_name, "text": c.text, "ts": c.ts}
                     for c in self.comments(pid)[-100:]]
            await self._send(contact.id, {"t": "s_comments", "post_id": pid, "items": items})
        elif t == "s_comments":
            pid = str(msg.get("post_id", ""))
            p = self.post(pid)
            if not p or p.author_uid != contact.peer_user_id:
                return
            items = msg.get("items") if isinstance(msg.get("items"), list) else []
            with self.db.session() as s:
                s.execute(delete(PostComment).where(PostComment.post_id == pid, PostComment.account_id == repo.account_id))
                for it in items[:100]:
                    if not isinstance(it, dict):
                        continue
                    try:
                        uuid.UUID(str(it.get("id")))
                    except ValueError:
                        continue
                    s.add(PostComment(id=str(it["id"]), account_id=repo.account_id, post_id=pid,
                                      author_uid=str(it.get("author_uid", ""))[:20],
                                      author_name=str(it.get("author_name", ""))[:80],
                                      text=str(it.get("text", ""))[:500],
                                      ts=float(it.get("ts", 0) or 0)))
                row = s.get(Post, pid)
                row.comments = len(items)
                s.commit()
            self.node.bus.emit("social")
        elif t == "s_tick_req":
            if not self.is_admin():
                return
            followers = msg.get("followers") if isinstance(msg.get("followers"), int) else 0
            with self.db.session() as s:
                r = s.scalar(select(TickRequest).where(TickRequest.account_id == repo.account_id,
                                                       TickRequest.peer_uid == contact.peer_user_id))
                if r is None:
                    r = TickRequest(account_id=repo.account_id, peer_uid=contact.peer_user_id)
                    s.add(r)
                if r.status != "granted":
                    r.status = "pending"
                r.name, r.followers = contact.name, followers
                r.message = str(msg.get("message", ""))[:300]
                r.ts = time.time()
                s.commit()
            self.node.notify("tick_request", f"{contact.name} requested a blue tick",
                             f"{followers} followers", "notify_requests", ref=str(contact.id))
            self.node.bus.emit("social")
        elif t == "s_tick_grant":
            cert = msg.get("cert", "")
            if isinstance(cert, str) and self.is_verifier_contact(contact) and \
                    vf.check_tick(cert, self.me, self.node.identity.public_bytes):
                with self.db.session() as s:
                    s.get(Account, repo.account_id).tick_cert = cert
                    s.commit()
                self.node.update_settings(tick_request="", tick_request_sent=False)
                self.node.notify("verified", "You're verified!", "Blue Cench Chat gave your account a blue tick.",
                                 "notify_security")
                await self.on_session(contact.id)
                self.node.bus.emit("social")
        elif t == "s_tick_rev":
            blob = msg.get("blob", "")
            if isinstance(blob, str) and self._store_revocation(blob):
                self.node.bus.emit("social")
                self.node.bus.emit("contacts")
