"""Memory persistence.

CRUD plus metadata-filtered lookups. No ranking, no scoring, no intent — those
belong to `retrieval/`. A lookup here answers "which memories *could* match";
deciding which ones *win* is somebody else's job.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from personasim.models.memory import LinkRelation, Memory, MemoryId, MemoryLink, MemoryType
from personasim.models.persona import PersonaId
from personasim.storage.mappers import memory_to_row, row_to_memory
from personasim.storage.schemas import MemoryLinkRow, MemoryRow


class MemoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # --- writes ------------------------------------------------------------

    def add(self, persona_id: PersonaId, memory: Memory) -> None:
        self.add_many(persona_id, [memory])

    def add_many(self, persona_id: PersonaId, memories: Sequence[Memory]) -> None:
        """Insert memories, then their links.

        Links are written second because the foreign key requires both endpoints
        to exist, and a batch may contain memories that link to one another.
        """
        for memory in memories:
            self._session.add(memory_to_row(persona_id, memory))
        self._session.flush()

        for memory in memories:
            self._write_links(memory.id, memory.links)
        self._session.flush()

    def _write_links(self, source_id: MemoryId, links: Iterable[MemoryLink]) -> None:
        for link in links:
            self._session.add(
                MemoryLinkRow(
                    source_id=source_id,
                    target_id=link.target,
                    relation=link.relation.value,
                )
            )

    def update(self, memory: Memory) -> bool:
        """Overwrite a stored memory in place, links included.

        The id is the identity of the memory, so this revises what a memory *says*
        without making it a different memory — which is what consolidation needs
        when it folds a superseded fact's keywords into the one that replaced it.
        Returns False if there was nothing there to revise.
        """
        row = self._session.get(MemoryRow, memory.id)
        if row is None:
            return False

        fresh = memory_to_row(row.persona_id, memory)
        for column in MemoryRow.__table__.columns.keys():  # noqa: SIM118 - Column collection, not a dict
            if column not in ("id", "persona_id"):
                setattr(row, column, getattr(fresh, column))

        self._session.flush()
        self.replace_links(memory.id, memory.links)
        return True

    def replace_links(self, memory_id: MemoryId, links: Sequence[MemoryLink]) -> None:
        self._session.execute(delete(MemoryLinkRow).where(MemoryLinkRow.source_id == memory_id))
        self._write_links(memory_id, links)
        self._session.flush()

    def delete(self, memory_id: MemoryId) -> bool:
        row = self._session.get(MemoryRow, memory_id)
        if row is None:
            return False
        self._session.delete(row)
        return True

    # --- reads -------------------------------------------------------------

    def get(self, memory_id: MemoryId) -> Memory | None:
        row = self._session.get(MemoryRow, memory_id)
        if row is None:
            return None
        return row_to_memory(row, self._links_for(row.id))

    def list_memories(
        self,
        persona_id: PersonaId,
        *,
        types: Sequence[MemoryType] | None = None,
    ) -> list[Memory]:
        stmt = select(MemoryRow).where(MemoryRow.persona_id == persona_id)
        if types:
            stmt = stmt.where(MemoryRow.type.in_([t.value for t in types]))
        rows = list(self._session.execute(stmt).scalars())
        return self._hydrate(rows)

    def find_by_keywords(
        self,
        persona_id: PersonaId,
        keywords: Sequence[str],
        *,
        types: Sequence[MemoryType] | None = None,
    ) -> list[Memory]:
        """Candidate memories sharing at least one keyword.

        Keywords live in a JSON column, so the overlap check happens in Python.
        At Phase 1 memory volumes this is a non-issue; if it ever becomes one,
        that is the signal to revisit the deferred vector-search decision.
        """
        if not keywords:
            return []
        wanted = {keyword.strip().lower() for keyword in keywords if keyword.strip()}
        if not wanted:
            return []
        return [
            memory
            for memory in self.list_memories(persona_id, types=types)
            if wanted.intersection(memory.keywords)
        ]

    def find_by_person(self, persona_id: PersonaId, person_name: str) -> list[Memory]:
        stmt = select(MemoryRow).where(
            MemoryRow.persona_id == persona_id,
            MemoryRow.person_name == person_name,
        )
        return self._hydrate(list(self._session.execute(stmt).scalars()))

    def count(self, persona_id: PersonaId, *, memory_type: MemoryType | None = None) -> int:
        return len(self.list_memories(persona_id, types=[memory_type] if memory_type else None))

    # --- internals ---------------------------------------------------------

    def _links_for(self, memory_id: MemoryId) -> list[MemoryLink]:
        stmt = select(MemoryLinkRow).where(MemoryLinkRow.source_id == memory_id)
        return [_to_link(row) for row in self._session.execute(stmt).scalars()]

    def _hydrate(self, rows: Sequence[MemoryRow]) -> list[Memory]:
        """Attach links to rows using one query rather than one per memory."""
        if not rows:
            return []
        ids = [row.id for row in rows]
        stmt = select(MemoryLinkRow).where(MemoryLinkRow.source_id.in_(ids))
        links: dict[MemoryId, list[MemoryLink]] = {}
        for row in self._session.execute(stmt).scalars():
            links.setdefault(row.source_id, []).append(_to_link(row))
        return [row_to_memory(row, links.get(row.id, [])) for row in rows]


def _to_link(row: MemoryLinkRow) -> MemoryLink:
    return MemoryLink(target=row.target_id, relation=LinkRelation(row.relation))
