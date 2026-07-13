"""Persona: identity plus the memories that constitute a life.

Persona = Identity + Experiences + Memory. The LLM is nowhere in this definition.
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
    MemoryType,
)

PersonaId = str


class Persona(BaseModel):
    """An in-memory view of a persona and its complete long-term memory."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: PersonaId = Field(default_factory=lambda: str(uuid.uuid4()))
    identity: Identity
    memories: list[Memory] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_memory_graph(self) -> Self:
        """Memory ids are unique and every link resolves to a memory we hold.

        A dangling link would let retrieval surface a memory that does not exist,
        which is a Phase 2 failure mode (false association) and must not be
        reachable in Phase 1.
        """
        ids = [memory.id for memory in self.memories]
        if len(set(ids)) != len(ids):
            raise ValueError("memory ids must be unique within a persona")

        known = set(ids)
        for memory in self.memories:
            dangling = sorted({link.target for link in memory.links} - known)
            if dangling:
                raise ValueError(f"memory {memory.id} links to unknown memories: {dangling}")
        return self

    @model_validator(mode="after")
    def _validate_causal_chronology(self) -> Self:
        """A cause must not postdate its effect.

        This checks that the authored life story is *possible*, catching a seed
        file that says an event was caused by something that had not happened yet.
        It is not a simulation of temporal reasoning — a persona whose timeline is
        incoherent is an authoring bug, not a cognitive one.
        """
        dated = {
            memory.id: memory.occurred_on
            for memory in self.memories
            if isinstance(memory, EpisodicMemory) and memory.occurred_on is not None
        }

        for memory in self.memories:
            when = dated.get(memory.id)
            if when is None:
                continue
            for link in memory.links:
                other = dated.get(link.target)
                if other is None:
                    continue
                if link.relation is LinkRelation.CAUSED_BY and other > when:
                    raise ValueError(
                        f"memory {memory.id} ({when}) is caused_by "
                        f"{link.target} ({other}), which happens later"
                    )
                if link.relation is LinkRelation.LED_TO and other < when:
                    raise ValueError(
                        f"memory {memory.id} ({when}) led_to "
                        f"{link.target} ({other}), which happened earlier"
                    )
        return self

    def by_id(self, memory_id: MemoryId) -> Memory:
        for memory in self.memories:
            if memory.id == memory_id:
                return memory
        raise KeyError(memory_id)

    def of_type(self, memory_type: MemoryType) -> list[Memory]:
        return [memory for memory in self.memories if memory.type is memory_type]

    def linked_to(self, memory_id: MemoryId, relation: LinkRelation | None = None) -> list[Memory]:
        """The memories a given memory points at, optionally filtered by relation."""
        return [self.by_id(target) for target in self.by_id(memory_id).linked_ids(relation)]

    def timeline(self) -> list[EpisodicMemory]:
        """Dated experiences in the order they were lived — the narrative spine."""
        episodes = [
            memory
            for memory in self.memories
            if isinstance(memory, EpisodicMemory) and memory.occurred_on is not None
        ]
        return sorted(episodes, key=lambda memory: (memory.occurred_on or date.min, memory.id))
