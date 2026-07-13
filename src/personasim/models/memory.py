"""Memory domain models.

Every memory carries the eight fields required by `docs/architecture.md`:
`id`, `type`, `created_at`, `summary`, `keywords`, `importance`, `confidence`, `links`.

Memory is structured, never free text. `summary` exists so a memory can be
rendered into prompt context, but the *content* of each memory type lives in
typed fields, so retrieval never has to parse prose.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MemoryId = str

# Bounded scores. Importance drives ranking; confidence records how certain the
# persona is of the memory. Neither is ever decayed in Phase 1.
UnitFloat = Annotated[float, Field(ge=0.0, le=1.0)]


def new_memory_id() -> MemoryId:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class MemoryType(StrEnum):
    SEMANTIC = "semantic"
    EPISODIC = "episodic"
    RELATIONSHIP = "relationship"


class LinkRelation(StrEnum):
    """How one memory stands to another.

    Untyped links say only that two memories are *associated*, which leaves the
    LLM to invent the relation between them — and to invent it differently each
    session. Typing the relation makes the persona's story authored data rather
    than generated prose.
    """

    CAUSED_BY = "caused_by"
    LED_TO = "led_to"
    OCCURRED_DURING = "occurred_during"
    INVOLVES = "involves"
    CONCERNS = "concerns"


# A relation and its logical inverse. Asserting both between the same pair is a
# contradiction: A cannot both cause and be caused by B.
_OPPOSITES: dict[LinkRelation, LinkRelation] = {
    LinkRelation.CAUSED_BY: LinkRelation.LED_TO,
    LinkRelation.LED_TO: LinkRelation.CAUSED_BY,
}


class MemoryLink(BaseModel):
    """A typed, directed edge from one memory to another."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: MemoryId
    relation: LinkRelation

    def __repr__(self) -> str:
        return f"--{self.relation.value}-->{self.target}"


class MemoryBase(BaseModel):
    """Fields shared by every long-term memory."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: MemoryId = Field(default_factory=new_memory_id)
    type: MemoryType
    created_at: datetime = Field(default_factory=utc_now)
    summary: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    importance: UnitFloat = 0.5
    confidence: UnitFloat = 1.0
    links: list[MemoryLink] = Field(default_factory=list)

    @field_validator("summary")
    @classmethod
    def _strip_summary(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("summary must not be blank")
        return stripped

    @field_validator("keywords")
    @classmethod
    def _normalize_keywords(cls, values: list[str]) -> list[str]:
        """Lowercase, strip, drop blanks, de-duplicate — order preserved.

        Retrieval matches keywords literally, so normalizing at the boundary keeps
        the search layer free of casing concerns.
        """
        seen: dict[str, None] = {}
        for raw in values:
            cleaned = raw.strip().lower()
            if cleaned:
                seen[cleaned] = None
        if not seen:
            raise ValueError("keywords must contain at least one non-blank entry")
        return list(seen)

    @field_validator("created_at")
    @classmethod
    def _require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @field_validator("links")
    @classmethod
    def _canonicalize_links(cls, values: list[MemoryLink]) -> list[MemoryLink]:
        """Links are a set, not a sequence: no link precedes another.

        Sorting them gives a memory one canonical form, so a memory read back from
        storage (which returns links in row order) compares equal to the one that
        was written.
        """
        if len(set(values)) != len(values):
            raise ValueError("links must not contain duplicates")

        by_target: dict[MemoryId, set[LinkRelation]] = {}
        for link in values:
            by_target.setdefault(link.target, set()).add(link.relation)

        for target, relations in by_target.items():
            for relation in relations:
                opposite = _OPPOSITES.get(relation)
                if opposite is not None and opposite in relations:
                    raise ValueError(
                        f"contradictory relations to {target!r}: "
                        f"{relation.value} and {opposite.value}"
                    )

        return sorted(values, key=lambda link: (link.relation.value, link.target))

    @model_validator(mode="after")
    def _reject_self_link(self) -> Self:
        if any(link.target == self.id for link in self.links):
            raise ValueError("a memory must not link to itself")
        return self

    def linked_ids(self, relation: LinkRelation | None = None) -> list[MemoryId]:
        return [link.target for link in self.links if relation is None or link.relation is relation]


class SemanticMemory(MemoryBase):
    """A fact the persona knows: "lives in Boston", "owns a dog"."""

    type: Literal[MemoryType.SEMANTIC] = MemoryType.SEMANTIC

    subject: str = Field(min_length=1)
    attribute: str = Field(min_length=1)
    value: str = Field(min_length=1)


class EpisodicMemory(MemoryBase):
    """An experience the persona lived through: a graduation, a wedding."""

    type: Literal[MemoryType.EPISODIC] = MemoryType.EPISODIC

    occurred_on: date | None = None
    location: str | None = None
    participants: list[str] = Field(default_factory=list)


class RelationshipMemory(MemoryBase):
    """A person the persona knows, and the shape of that relationship."""

    type: Literal[MemoryType.RELATIONSHIP] = MemoryType.RELATIONSHIP

    person_name: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    closeness: UnitFloat = 0.5
    known_since: date | None = None


Memory = Annotated[
    SemanticMemory | EpisodicMemory | RelationshipMemory,
    Field(discriminator="type"),
]

MEMORY_CLASSES: dict[MemoryType, type[MemoryBase]] = {
    MemoryType.SEMANTIC: SemanticMemory,
    MemoryType.EPISODIC: EpisodicMemory,
    MemoryType.RELATIONSHIP: RelationshipMemory,
}
