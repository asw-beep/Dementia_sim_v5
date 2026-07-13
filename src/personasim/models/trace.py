"""Memory trace: why the persona said what it said.

Every response records which memories were retrieved, of which types, and why.
Traces are hidden from the user. They exist for debugging and for the cognitive
simulations of later phases, which will inspect exactly this surface.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from personasim.models.memory import LinkRelation, MemoryId, MemoryType, utc_now


class RetrievalIntent(StrEnum):
    """What kind of remembering the user's message is asking for."""

    FACTUAL_RECALL = "factual_recall"
    EXPERIENTIAL_RECALL = "experiential_recall"
    RELATIONSHIP_QUERY = "relationship_query"
    SMALL_TALK = "small_talk"


class ScoreComponents(BaseModel):
    """The inspectable parts of a ranking score.

    Kept separate from the total so a human (or a Phase 2 wrapper) can see which
    signal actually surfaced a memory.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    keyword_overlap: float = Field(ge=0.0)
    importance: float = Field(ge=0.0)
    confidence: float = Field(ge=0.0)

    @property
    def total(self) -> float:
        return self.keyword_overlap + self.importance + self.confidence


class RetrievedMemory(BaseModel):
    """One memory that made the cut, with the arithmetic that put it there."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: MemoryId
    memory_type: MemoryType
    summary: str
    score: float = Field(ge=0.0)
    components: ScoreComponents
    matched_keywords: list[str] = Field(default_factory=list)

    # Set when this memory was not matched directly but pulled in by following a
    # typed link out of one that was. Records which memory reached it, and how —
    # so the causal claim in a response can be traced back to authored data.
    linked_from: MemoryId | None = None
    via_relation: LinkRelation | None = None

    @property
    def was_expanded(self) -> bool:
        return self.linked_from is not None


class MemoryTrace(BaseModel):
    """The full record of one retrieval pass."""

    model_config = ConfigDict(extra="forbid")

    query: str
    intent: RetrievalIntent
    entities: list[str] = Field(default_factory=list)
    searched_types: list[MemoryType] = Field(default_factory=list)
    retrieved: list[RetrievedMemory] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=utc_now)

    @property
    def memory_ids(self) -> list[MemoryId]:
        return [memory.memory_id for memory in self.retrieved]

    @property
    def is_empty(self) -> bool:
        """No memory supported this response — the persona is speaking from identity alone."""
        return not self.retrieved
