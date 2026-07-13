"""ORM tables.

All three memory types share one `memories` table with a discriminating `type`
column. Subtype-specific columns are nullable. This is deliberate: Phase 2 must
be able to alter retrieval behaviour without a schema migration, so the schema
must already accommodate every memory type it will ever see.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from personasim.storage.schemas.types import UTCDateTime


class Base(DeclarativeBase):
    pass


class PersonaRow(Base):
    """A persona and its identity. One row per persona."""

    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    age: Mapped[int] = mapped_column(Integer, nullable=False)
    occupation: Mapped[str] = mapped_column(String(255), nullable=False)
    personality: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    values: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    speech_style: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class MemoryRow(Base):
    __tablename__ = "memories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    persona_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("personas.id", ondelete="CASCADE"), nullable=False
    )

    # Shared fields, present on every memory.
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    importance: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # Semantic.
    subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attribute: Mapped[str | None] = mapped_column(String(255), nullable=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Episodic.
    occurred_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    participants: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Relationship.
    person_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    relation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    closeness: Mapped[float | None] = mapped_column(Float, nullable=True)
    known_since: Mapped[date | None] = mapped_column(Date, nullable=True)

    __table_args__ = (
        Index("ix_memories_persona_type", "persona_id", "type"),
        Index("ix_memories_person_name", "persona_id", "person_name"),
    )


class MemoryLinkRow(Base):
    """A typed, directed edge between two memories of the same persona.

    `relation` is part of the primary key: two memories may stand in more than one
    relation to each other (a wedding both `involves` a spouse and `concerns` her).
    """

    __tablename__ = "memory_links"

    source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True
    )
    target_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True
    )
    relation: Mapped[str] = mapped_column(String(32), primary_key=True)


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    persona_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("personas.id", ondelete="CASCADE"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class TurnRow(Base):
    """A persisted exchange, with the trace that produced the reply.

    The trace is stored as JSON rather than a relational structure: nothing
    queries into it, `persona trace` only replays it.
    """

    __tablename__ = "turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    user_content: Mapped[str] = mapped_column(Text, nullable=False)
    user_timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    persona_content: Mapped[str] = mapped_column(Text, nullable=False)
    persona_timestamp: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    trace: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    __table_args__ = (Index("ix_turns_session_ordinal", "session_id", "ordinal", unique=True),)
