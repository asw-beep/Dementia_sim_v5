"""Merging near-duplicate semantic memories at the end of a session.

A user who mentions their city on Monday and moves on Friday leaves the persona
holding two answers to one question. Consolidation keeps the later one and folds
the earlier one's keywords into it, so the memory stays findable by whatever the
old fact was phrased as.

It is deliberately timid about what it will touch. Only *unlinked* semantic
memories are eligible, so nothing that participates in the narrative spine can be
superseded: an authored memory is the persona's ground truth, and merging two of
those would be editing a life, not tidying it. It also means consolidation can
never leave a dangling link, because it never removes a memory anything points at.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from personasim.models.memory import Memory, MemoryId, SemanticMemory


@dataclass(frozen=True)
class ConsolidationPlan:
    """What consolidation would do. Computed before anything is written."""

    superseded: list[MemoryId] = field(default_factory=list)
    survivors: list[SemanticMemory] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.superseded


def consolidate(memories: Sequence[Memory]) -> ConsolidationPlan:
    """Reduce each duplicated (subject, attribute) to its most recent statement.

    The survivor carries the union of the group's keywords, so a memory revised
    from "Chicago" to "Denver" is still reachable by someone who asks about
    Chicago — the persona should recall that the fact *changed*, not lose the
    thread of the conversation that changed it.
    """
    eligible = _eligible(memories)

    groups: dict[tuple[str, str], list[SemanticMemory]] = {}
    for memory in eligible:
        key = (memory.subject.casefold(), memory.attribute.casefold())
        groups.setdefault(key, []).append(memory)

    superseded: list[MemoryId] = []
    survivors: list[SemanticMemory] = []

    for group in groups.values():
        if len(group) < 2:
            continue

        # Most recent wins. `id` breaks a tie, so two memories formed in the same
        # instant still consolidate the same way every run.
        ordered = sorted(group, key=lambda memory: (memory.created_at, memory.id))
        *older, newest = ordered

        superseded.extend(memory.id for memory in older)
        survivors.append(newest.model_copy(update={"keywords": _merged_keywords(ordered, newest)}))

    return ConsolidationPlan(superseded=superseded, survivors=survivors)


def _eligible(memories: Sequence[Memory]) -> list[SemanticMemory]:
    """Semantic memories that no link touches, in either direction.

    Consolidation removes memories. A memory that something links to cannot be
    removed without breaking the graph, and a memory that links to something is
    part of the authored story rather than a fact picked up in conversation.
    """
    linked_to: set[MemoryId] = {link.target for memory in memories for link in memory.links}
    return [
        memory
        for memory in memories
        if isinstance(memory, SemanticMemory) and not memory.links and memory.id not in linked_to
    ]


def _merged_keywords(group: Sequence[SemanticMemory], newest: SemanticMemory) -> list[str]:
    """The survivor's own keywords first, then everything the group knew.

    `MemoryBase` normalizes and de-duplicates these, so order is all that is being
    decided here: the current fact's vocabulary leads, the superseded fact's
    follows, and the memory answers to both.
    """
    merged: dict[str, None] = dict.fromkeys(newest.keywords)
    for memory in group:
        merged.update(dict.fromkeys(memory.keywords))
    return list(merged)
