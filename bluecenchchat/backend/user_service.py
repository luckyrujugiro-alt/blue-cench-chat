"""Account-scoped data access used by the core engine and the UI."""
from __future__ import annotations

import json
import time

from sqlalchemy import delete, func, select, update

from .database import Database
from .models import Account, Activity, Contact, Message, Notification, SuspiciousReport, Transfer


class UserRepository:
    def __init__(self, db: Database, account_id: int) -> None:
        self.db = db
        self.account_id = account_id

    # -- account -------------------------------------------------------------
    def account(self) -> Account:
        with self.db.session() as s:
            return s.get(Account, self.account_id)

    def update_profile(self, **fields) -> Account:
        allowed = {"full_name", "username", "email", "phone", "about", "avatar"}
        with self.db.session() as s:
            acc = s.get(Account, self.account_id)
            for k, v in fields.items():
                if k in allowed:
                    setattr(acc, k, v)
            s.commit()
            return acc

    def settings(self) -> dict:
        from .authentication import DEFAULT_SETTINGS

        merged = dict(DEFAULT_SETTINGS)
        merged.update(self.account().settings)
        return merged

    def save_settings(self, **changes) -> dict:
        with self.db.session() as s:
            acc = s.get(Account, self.account_id)
            current = acc.settings
            current.update(changes)
            acc.settings_json = json.dumps(current)
            s.commit()
        return self.settings()

    # -- contacts ------------------------------------------------------------
    def contacts(self, statuses: tuple[str, ...] | None = None) -> list[Contact]:
        with self.db.session() as s:
            q = select(Contact).where(Contact.account_id == self.account_id)
            if statuses:
                q = q.where(Contact.status.in_(statuses))
            return list(s.scalars(q.order_by(Contact.favorite.desc(), Contact.display_name)))

    def contact(self, contact_id: int) -> Contact | None:
        with self.db.session() as s:
            c = s.get(Contact, contact_id)
            return c if c and c.account_id == self.account_id else None

    def contact_by_peer(self, peer_user_id: str) -> Contact | None:
        with self.db.session() as s:
            return s.scalar(
                select(Contact).where(Contact.account_id == self.account_id, Contact.peer_user_id == peer_user_id)
            )

    def upsert_contact(self, peer_user_id: str, identity_pub: bytes, **fields) -> Contact:
        with self.db.session() as s:
            c = s.scalar(
                select(Contact).where(Contact.account_id == self.account_id, Contact.peer_user_id == peer_user_id)
            )
            if c is None:
                c = Contact(account_id=self.account_id, peer_user_id=peer_user_id, identity_pub=identity_pub)
                s.add(c)
            for k, v in fields.items():
                if k == "address":
                    merged = c.address if c.id else {}
                    merged.update({kk: vv for kk, vv in v.items() if vv is not None})
                    c.address_json = json.dumps(merged)
                elif v is not None:
                    setattr(c, k, v)
            s.commit()
            return c

    def set_contact(self, contact_id: int, **fields) -> None:
        with self.db.session() as s:
            c = s.get(Contact, contact_id)
            if c and c.account_id == self.account_id:
                for k, v in fields.items():
                    setattr(c, k, v)
                s.commit()

    def remove_contact(self, contact_id: int) -> None:
        with self.db.session() as s:
            s.execute(delete(Contact).where(Contact.id == contact_id, Contact.account_id == self.account_id))
            s.commit()

    def report(self, peer_user_id: str, reason: str) -> None:
        with self.db.session() as s:
            s.add(SuspiciousReport(account_id=self.account_id, peer_user_id=peer_user_id, reason=reason[:500]))
            s.commit()

    # -- messages ------------------------------------------------------------
    def add_message(self, **fields) -> Message:
        with self.db.session() as s:
            m = Message(account_id=self.account_id, **fields)
            s.add(m)
            s.commit()
            return m

    def message(self, msg_id: str) -> Message | None:
        with self.db.session() as s:
            m = s.get(Message, msg_id)
            return m if m and m.account_id == self.account_id else None

    def set_message(self, msg_id: str, **fields) -> Message | None:
        with self.db.session() as s:
            m = s.get(Message, msg_id)
            if not m or m.account_id != self.account_id:
                return None
            for k, v in fields.items():
                setattr(m, k, v)
            s.commit()
            return m

    def messages(self, contact_id: int, search: str = "", limit: int = 500) -> list[Message]:
        with self.db.session() as s:
            q = select(Message).where(
                Message.account_id == self.account_id, Message.contact_id == contact_id, Message.deleted.is_(False)
            )
            if search:
                q = q.where(Message.body.ilike(f"%{search}%"))
            rows = list(s.scalars(q.order_by(Message.ts.desc()).limit(limit)))
            return rows[::-1]

    def search_messages(self, text: str, limit: int = 100) -> list[Message]:
        with self.db.session() as s:
            return list(
                s.scalars(
                    select(Message)
                    .where(Message.account_id == self.account_id, Message.deleted.is_(False), Message.body.ilike(f"%{text}%"))
                    .order_by(Message.ts.desc())
                    .limit(limit)
                )
            )

    def queued_messages(self, contact_id: int) -> list[Message]:
        with self.db.session() as s:
            return list(
                s.scalars(
                    select(Message)
                    .where(
                        Message.account_id == self.account_id,
                        Message.contact_id == contact_id,
                        Message.direction == "out",
                        Message.status.in_(("queued", "failed")),
                        Message.kind == "text",
                        Message.deleted.is_(False),
                    )
                    .order_by(Message.ts)
                )
            )

    def mark_incoming_read(self, contact_id: int) -> list[str]:
        with self.db.session() as s:
            ids = list(
                s.scalars(
                    select(Message.id).where(
                        Message.account_id == self.account_id,
                        Message.contact_id == contact_id,
                        Message.direction == "in",
                        Message.status != "read",
                    )
                )
            )
            if ids:
                s.execute(update(Message).where(Message.id.in_(ids)).values(status="read"))
                s.commit()
            return ids

    def conversations(self) -> list[tuple[Contact, Message | None, int]]:
        """(contact, last message, unread count) for accepted contacts with history first."""
        out = []
        with self.db.session() as s:
            for c in s.scalars(
                select(Contact).where(Contact.account_id == self.account_id, Contact.status == "accepted")
            ):
                last = s.scalar(
                    select(Message)
                    .where(Message.contact_id == c.id, Message.deleted.is_(False))
                    .order_by(Message.ts.desc())
                    .limit(1)
                )
                unread = s.scalar(
                    select(func.count()).where(
                        Message.contact_id == c.id, Message.direction == "in", Message.status != "read",
                        Message.deleted.is_(False),
                    )
                )
                out.append((c, last, unread or 0))
        out.sort(key=lambda t: (t[1].ts if t[1] else 0), reverse=True)
        return out

    def unread_total(self) -> int:
        with self.db.session() as s:
            return s.scalar(
                select(func.count()).where(
                    Message.account_id == self.account_id, Message.direction == "in", Message.status != "read",
                    Message.deleted.is_(False),
                )
            ) or 0

    # -- transfers -----------------------------------------------------------
    def add_transfer(self, **fields) -> Transfer:
        files = fields.pop("files", [])
        with self.db.session() as s:
            t = Transfer(account_id=self.account_id, **fields)
            t.files = files
            s.add(t)
            s.commit()
            return t

    def transfer(self, transfer_id: str) -> Transfer | None:
        with self.db.session() as s:
            t = s.get(Transfer, transfer_id)
            return t if t and t.account_id == self.account_id else None

    def set_transfer(self, transfer_id: str, **fields) -> Transfer | None:
        files = fields.pop("files", None)
        with self.db.session() as s:
            t = s.get(Transfer, transfer_id)
            if not t or t.account_id != self.account_id:
                return None
            for k, v in fields.items():
                setattr(t, k, v)
            if files is not None:
                t.files = files
            s.commit()
            return t

    def transfers(self, statuses: tuple[str, ...] | None = None, limit: int = 300) -> list[Transfer]:
        with self.db.session() as s:
            q = select(Transfer).where(Transfer.account_id == self.account_id)
            if statuses:
                q = q.where(Transfer.status.in_(statuses))
            return list(s.scalars(q.order_by(Transfer.created_at.desc()).limit(limit)))

    def delete_transfer(self, transfer_id: str) -> None:
        with self.db.session() as s:
            s.execute(delete(Transfer).where(Transfer.id == transfer_id, Transfer.account_id == self.account_id))
            s.commit()

    def received_hashes(self) -> dict[str, str]:
        """sha256 -> stored path for completed incoming files (duplicate detection)."""
        out: dict[str, str] = {}
        for t in self.transfers(("completed", "failed", "cancelled", "interrupted")):
            if t.direction != "in":
                continue
            for f in t.files:
                if f.get("status") == "verified" and f.get("dest_path"):
                    out[f["sha256"]] = f["dest_path"]
        return out

    def transfer_stats(self, days: int = 7) -> dict:
        now = time.time()
        start_day = int(now // 86400) - days + 1
        per_day_in = [0] * days
        per_day_out = [0] * days
        files_in = files_out = bytes_in = bytes_out = 0
        for t in self.transfers(limit=100000):
            ok_files = [f for f in t.files if f.get("status") in ("verified", "sent", "duplicate")]
            moved = sum(f.get("size", 0) for f in ok_files)
            if t.direction == "in":
                files_in += len(ok_files)
                bytes_in += moved
            else:
                files_out += len(ok_files)
                bytes_out += moved
            day = int(t.created_at // 86400) - start_day
            if 0 <= day < days:
                (per_day_in if t.direction == "in" else per_day_out)[day] += t.done_bytes
        return {
            "files_in": files_in,
            "files_out": files_out,
            "bytes_in": bytes_in,
            "bytes_out": bytes_out,
            "per_day_in": per_day_in,
            "per_day_out": per_day_out,
            "day_starts": [(start_day + i) * 86400 for i in range(days)],
        }

    # -- notifications / activity -------------------------------------------
    def notify(self, kind: str, title: str, body: str = "", ref: str = "") -> Notification:
        with self.db.session() as s:
            n = Notification(account_id=self.account_id, kind=kind, title=title[:120], body=body[:400], ref=ref)
            s.add(n)
            s.commit()
            return n

    def notifications(self, limit: int = 200) -> list[Notification]:
        with self.db.session() as s:
            return list(
                s.scalars(
                    select(Notification)
                    .where(Notification.account_id == self.account_id)
                    .order_by(Notification.ts.desc())
                    .limit(limit)
                )
            )

    def unread_notifications(self) -> int:
        with self.db.session() as s:
            return s.scalar(
                select(func.count()).where(Notification.account_id == self.account_id, Notification.read.is_(False))
            ) or 0

    def mark_notifications_read(self) -> None:
        with self.db.session() as s:
            s.execute(update(Notification).where(Notification.account_id == self.account_id).values(read=True))
            s.commit()

    def clear_notifications(self) -> None:
        with self.db.session() as s:
            s.execute(delete(Notification).where(Notification.account_id == self.account_id))
            s.commit()

    def log(self, kind: str, text: str) -> None:
        with self.db.session() as s:
            s.add(Activity(account_id=self.account_id, kind=kind, text=text[:300]))
            s.commit()

    def activity(self, limit: int = 30, kind: str | None = None) -> list[Activity]:
        with self.db.session() as s:
            q = select(Activity).where(Activity.account_id == self.account_id)
            if kind:
                q = q.where(Activity.kind == kind)
            return list(s.scalars(q.order_by(Activity.ts.desc()).limit(limit)))
