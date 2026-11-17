"""Database engine / session factory (SQLite, WAL mode)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


class Database:
    def __init__(self, path: Path | str | None) -> None:
        url = "sqlite://" if path is None else f"sqlite:///{Path(path).as_posix()}"
        # check_same_thread=False: slow Argon2 work runs in a worker thread
        # (asyncio.to_thread) so the UI stays responsive; each call opens its
        # own short-lived session, so connections are never shared concurrently.
        self.engine: Engine = create_engine(url, future=True, connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            if path is not None:
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA synchronous=NORMAL")
            cur.close()

        Base.metadata.create_all(self.engine)
        self._factory = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def session(self) -> Session:
        return self._factory()

    def dispose(self) -> None:
        self.engine.dispose()
