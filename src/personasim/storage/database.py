"""Engine and session management.

This module owns the connection. It knows nothing about personas, memories, or
retrieval — those live above it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from personasim.storage.schemas import Base

IN_MEMORY_URL = "sqlite://"


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    """SQLite ignores foreign keys unless asked, per connection.

    Without this, `memory_links` would happily reference deleted memories and the
    persona's memory graph could go dangling.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


class Database:
    """Owns the engine and hands out transactional sessions."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.url = url
        self._engine: Engine = create_engine(url, echo=echo, future=True)
        event.listen(self._engine, "connect", _enable_sqlite_foreign_keys)
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    @classmethod
    def from_path(cls, path: Path, *, echo: bool = False) -> Database:
        path.parent.mkdir(parents=True, exist_ok=True)
        return cls(f"sqlite:///{path}", echo=echo)

    @classmethod
    def in_memory(cls, *, echo: bool = False) -> Database:
        return cls(IN_MEMORY_URL, echo=echo)

    @property
    def engine(self) -> Engine:
        return self._engine

    def create_schema(self) -> None:
        Base.metadata.create_all(self._engine)

    def drop_schema(self) -> None:
        Base.metadata.drop_all(self._engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        """A unit of work: commits on success, rolls back on any exception."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self._engine.dispose()
