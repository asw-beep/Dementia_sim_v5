"""Candidate search.

Gathers memories that *could* answer the question. Deciding which of them win is
ranking's job, not this module's.

Keyword matching only. No embeddings, no vector store — see the deferred
technology decisions in `docs/tech_stack.md`.
"""

from __future__ import annotations

from collections.abc import Sequence

from personasim.models.memory import Memory, MemoryType
from personasim.retrieval.source import MemorySource


def find_candidates(
    source: MemorySource,
    keywords: Sequence[str],
    person_mentions: Sequence[str],
    types: Sequence[MemoryType],
) -> list[Memory]:
    """Every memory reachable by keyword overlap or by a named person.

    A person's relationship memory is included even when the question shares no
    keyword with it, because naming someone is itself a retrieval signal.
    Results are de-duplicated and ordered by id, so retrieval is reproducible.
    """
    if not types:
        return []

    found: dict[str, Memory] = {}

    for memory in source.find_by_keywords(keywords, types=types):
        found[memory.id] = memory

    for name in person_mentions:
        for memory in source.find_by_person(name):
            if memory.type in types:
                found[memory.id] = memory

    return sorted(found.values(), key=lambda memory: memory.id)
