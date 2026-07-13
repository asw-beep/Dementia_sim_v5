"""Where retrieval gets its candidate memories from.

The engine depends on this protocol rather than on a repository, so retrieval can
be exercised against an in-memory persona with no database, and so a Phase 2
wrapper can substitute a degraded source without touching the engine.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from personasim.models.memory import Memory, MemoryId, MemoryType, RelationshipMemory
from personasim.models.persona import Persona, PersonaId
from personasim.storage.repositories.memory import MemoryRepository


class MemorySource(Protocol):
    """The read surface retrieval needs. Deliberately narrow."""

    def get(self, memory_id: MemoryId) -> Memory | None: ...

    def find_by_keywords(
        self, keywords: Sequence[str], types: Sequence[MemoryType] | None = None
    ) -> list[Memory]: ...

    def find_by_person(self, person_name: str) -> list[Memory]: ...

    def person_names(self) -> list[str]:
        """Every person the persona knows, for matching mentions in a question."""
        ...


class PersonaMemorySource:
    """Serves a persona already held in memory. No database."""

    def __init__(self, persona: Persona) -> None:
        self._persona = persona

    def get(self, memory_id: MemoryId) -> Memory | None:
        try:
            return self._persona.by_id(memory_id)
        except KeyError:
            return None

    def find_by_keywords(
        self, keywords: Sequence[str], types: Sequence[MemoryType] | None = None
    ) -> list[Memory]:
        wanted = _normalize(keywords)
        if not wanted:
            return []
        return [
            memory
            for memory in self._persona.memories
            if (types is None or memory.type in types) and wanted.intersection(memory.keywords)
        ]

    def find_by_person(self, person_name: str) -> list[Memory]:
        return [
            memory
            for memory in self._persona.memories
            if isinstance(memory, RelationshipMemory) and memory.person_name == person_name
        ]

    def person_names(self) -> list[str]:
        return [
            memory.person_name
            for memory in self._persona.memories
            if isinstance(memory, RelationshipMemory)
        ]


class RepositoryMemorySource:
    """Serves a persona from the database."""

    def __init__(self, repository: MemoryRepository, persona_id: PersonaId) -> None:
        self._repository = repository
        self._persona_id = persona_id

    def get(self, memory_id: MemoryId) -> Memory | None:
        return self._repository.get(memory_id)

    def find_by_keywords(
        self, keywords: Sequence[str], types: Sequence[MemoryType] | None = None
    ) -> list[Memory]:
        return self._repository.find_by_keywords(self._persona_id, keywords, types=types)

    def find_by_person(self, person_name: str) -> list[Memory]:
        return self._repository.find_by_person(self._persona_id, person_name)

    def person_names(self) -> list[str]:
        return [
            memory.person_name
            for memory in self._repository.list_memories(
                self._persona_id, types=[MemoryType.RELATIONSHIP]
            )
            if isinstance(memory, RelationshipMemory)
        ]


def _normalize(keywords: Sequence[str]) -> set[str]:
    return {keyword.strip().lower() for keyword in keywords if keyword.strip()}
