"""Conversation models: the shape of a live session.

Nothing here is persisted as long-term memory. A turn becomes a memory only if
the formation step (Stage 7) explicitly promotes it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from personasim.models.memory import utc_now
from personasim.models.persona import PersonaId
from personasim.models.trace import MemoryTrace

SessionId = str


class Role(StrEnum):
    USER = "user"
    PERSONA = "persona"


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    role: Role
    content: str = Field(min_length=1)
    timestamp: datetime = Field(default_factory=utc_now)


class Turn(BaseModel):
    """One complete exchange, paired with the trace that produced the reply."""

    model_config = ConfigDict(extra="forbid")

    user_message: Message
    persona_message: Message
    trace: MemoryTrace


class TemporaryFact(BaseModel):
    """Something learned mid-conversation. Lives in working memory only.

    It reaches long-term memory only by passing through memory formation.
    """

    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1)
    stated_by: Role
    timestamp: datetime = Field(default_factory=utc_now)


class ConversationState(BaseModel):
    """Working memory's payload: the current session, and nothing older."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    session_id: SessionId = Field(default_factory=lambda: str(uuid.uuid4()))
    persona_id: PersonaId
    started_at: datetime = Field(default_factory=utc_now)
    turns: list[Turn] = Field(default_factory=list)
    active_topic: str | None = None
    temporary_facts: list[TemporaryFact] = Field(default_factory=list)
