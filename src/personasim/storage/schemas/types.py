"""Custom column types."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Dialect, TypeDecorator


class UTCDateTime(TypeDecorator[datetime]):
    """A timezone-aware datetime that survives SQLite.

    SQLite has no native timezone support and silently returns naive datetimes.
    The domain models reject naive values, so we normalize to UTC on the way in
    and re-attach UTC on the way out.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("refusing to persist a naive datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        stored: datetime = value
        if stored.tzinfo is None:
            return stored.replace(tzinfo=UTC)
        return stored.astimezone(UTC)
