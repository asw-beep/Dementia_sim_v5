"""The seed-file format and its translation into a `Persona`.

Seed files address memories by human-readable `key` rather than by UUID, so an
author can write `links: [maya]` instead of pasting an identifier. Keys are
resolved to deterministic ids (UUID5 over persona id + key), which is what makes
re-seeding idempotent: the same seed file always produces the same memory ids.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from personasim.models.identity import Identity
from personasim.models.memory import (
    EpisodicMemory,
    LinkRelation,
    Memory,
    MemoryId,
    MemoryLink,
    RelationshipMemory,
    SemanticMemory,
    UnitFloat,
)
from personasim.models.persona import Persona, PersonaId

# Any fixed namespace works; this one just must never change, or previously
# seeded databases would stop matching their seed files.
_SEED_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

SeedKey = str


def memory_id_for(persona_id: PersonaId, key: SeedKey) -> MemoryId:
    """The stable id a seeded memory will always receive."""
    return str(uuid.uuid5(_SEED_NAMESPACE, f"{persona_id}:{key}"))


class SeedLink(BaseModel):
    """An authored edge, naming its target by key rather than by id."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target: SeedKey = Field(min_length=1)
    relation: LinkRelation


class SeedMemory(BaseModel):
    """Fields common to every seeded memory."""

    model_config = ConfigDict(extra="forbid")

    key: SeedKey = Field(min_length=1)
    summary: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    importance: UnitFloat = 0.5
    confidence: UnitFloat = 1.0
    links: list[SeedLink] = Field(default_factory=list)


class SeedSemantic(SeedMemory):
    subject: str = Field(min_length=1)
    attribute: str = Field(min_length=1)
    value: str = Field(min_length=1)


class SeedEpisodic(SeedMemory):
    occurred_on: date | None = None
    location: str | None = None
    participants: list[str] = Field(default_factory=list)


class SeedRelationship(SeedMemory):
    person_name: str = Field(min_length=1)
    relation: str = Field(min_length=1)
    closeness: UnitFloat = 0.5
    known_since: date | None = None


class PersonaSeed(BaseModel):
    """A persona as authored on disk."""

    model_config = ConfigDict(extra="forbid")

    id: PersonaId = Field(min_length=1)
    identity: Identity
    semantic: list[SeedSemantic] = Field(default_factory=list)
    episodic: list[SeedEpisodic] = Field(default_factory=list)
    relationships: list[SeedRelationship] = Field(default_factory=list)

    @property
    def all_memories(self) -> list[SeedMemory]:
        return [*self.semantic, *self.episodic, *self.relationships]

    @model_validator(mode="after")
    def _validate_keys(self) -> Self:
        """Keys are unique and every link names a key we actually define.

        Caught here rather than in `Persona` so the error message can point at the
        author's key ("maya") instead of a resolved UUID.
        """
        keys = [memory.key for memory in self.all_memories]
        duplicates = sorted({key for key in keys if keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"duplicate memory keys: {duplicates}")

        known = set(keys)
        for memory in self.all_memories:
            targets = {link.target for link in memory.links}
            unknown = sorted(targets - known)
            if unknown:
                raise ValueError(f"memory {memory.key!r} links to unknown keys: {unknown}")
            if memory.key in targets:
                raise ValueError(f"memory {memory.key!r} links to itself")

        self._reject_contradictory_facts()
        return self

    def _reject_contradictory_facts(self) -> None:
        """One subject, one attribute, one value. A seed may not state two.

        A persona cannot both live in Boston and live in Denver, and a seed that
        says so is an authoring error — the same class as a cause that postdates
        its effect.

        It is also what makes a guarantee the roadmap already claims *true*.
        Session-end consolidation reduces each duplicated (subject, attribute) to
        its most recent statement, and it is documented as never touching the
        authored life. That held only by luck: an unlinked authored fact is
        perfectly eligible, and four of Elena's are. Two authored facts sharing a
        pair would have had one of them quietly deleted at the end of a
        conversation. Forbidding the duplicate here makes the group of two
        impossible, so consolidation cannot find one to merge — by construction,
        rather than by the accident of nobody having written one yet.
        """
        seen: dict[tuple[str, str], str] = {}
        for fact in self.semantic:
            pair = (fact.subject.casefold(), fact.attribute.casefold())
            first = seen.get(pair)
            if first is not None:
                raise ValueError(
                    f"memories {first!r} and {fact.key!r} both state "
                    f"{fact.attribute!r} for {fact.subject!r}; a fact may be stated once"
                )
            seen[pair] = fact.key

    def to_persona(self) -> Persona:
        """Resolve keys to ids and build the validated domain object."""

        def resolve(links: list[SeedLink]) -> list[MemoryLink]:
            return [
                MemoryLink(target=memory_id_for(self.id, link.target), relation=link.relation)
                for link in links
            ]

        memories: list[Memory] = []

        for fact in self.semantic:
            memories.append(
                SemanticMemory(
                    id=memory_id_for(self.id, fact.key),
                    summary=fact.summary,
                    keywords=fact.keywords,
                    importance=fact.importance,
                    confidence=fact.confidence,
                    links=resolve(fact.links),
                    subject=fact.subject,
                    attribute=fact.attribute,
                    value=fact.value,
                )
            )

        for event in self.episodic:
            memories.append(
                EpisodicMemory(
                    id=memory_id_for(self.id, event.key),
                    summary=event.summary,
                    keywords=event.keywords,
                    importance=event.importance,
                    confidence=event.confidence,
                    links=resolve(event.links),
                    occurred_on=event.occurred_on,
                    location=event.location,
                    participants=event.participants,
                )
            )

        for person in self.relationships:
            memories.append(
                RelationshipMemory(
                    id=memory_id_for(self.id, person.key),
                    summary=person.summary,
                    keywords=person.keywords,
                    importance=person.importance,
                    confidence=person.confidence,
                    links=resolve(person.links),
                    person_name=person.person_name,
                    relation=person.relation,
                    closeness=person.closeness,
                    known_since=person.known_since,
                )
            )

        return Persona(id=self.id, identity=self.identity, memories=memories)
