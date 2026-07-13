"""What a seed is missing, measured against the reference persona.

Every gap here is a defect that has actually happened. A persona with a hole in her
does not fail loudly — she refuses, or she invents, and you find out weeks later in
a transcript.
"""

from __future__ import annotations

from personasim.models.memory import RelationshipMemory, SemanticMemory
from personasim.models.persona import Persona
from personasim.persona.checklist import ESSENTIAL, RELATIONS, Gaps


def find_gaps(persona: Persona) -> Gaps:
    """Check a persona against the checklist. Says nothing about style — only holes."""
    attributes = {
        memory.attribute.casefold()
        for memory in persona.memories
        if isinstance(memory, SemanticMemory)
    }
    relations = {
        memory.relation.casefold()
        for memory in persona.memories
        if isinstance(memory, RelationshipMemory)
    }

    gaps = Gaps(
        missing_facts=[fact for fact in ESSENTIAL if fact.attribute.casefold() not in attributes],
        missing_relations=[
            relation
            for relation in RELATIONS
            if relation.essential and relation.relation.casefold() not in relations
        ],
    )

    # A dead relative who cannot be reached from the word "alive". Elena's could not:
    # asked "are they all alive?" she said yes, and both her parents were dead.
    for memory in persona.memories:
        if not isinstance(memory, RelationshipMemory):
            continue
        mentions_death = any(
            word in memory.summary.casefold() for word in ("died", "dead", "passed away")
        )
        reachable = {"alive", "died", "dead"} & set(memory.keywords)
        if mentions_death and not reachable:
            gaps.unreachable_deaths.append(memory.person_name)

    return gaps


def report(gaps: Gaps) -> str:
    if gaps.is_clean:
        return "No gaps. Every essential fact and relation is authored."

    lines: list[str] = []

    if gaps.missing_facts:
        lines.append("Missing facts — she will refuse or invent when asked:")
        lines += [
            f"  - {fact.attribute}: {fact.question}\n      {fact.because}"
            for fact in gaps.missing_facts
        ]

    if gaps.missing_relations:
        lines.append("")
        lines.append("Missing people — the cast is CLOSED, so an omission reads as a DENIAL:")
        lines += [
            f"  - {relation.relation}: {relation.question}\n      {relation.because}"
            for relation in gaps.missing_relations
        ]

    if gaps.unreachable_deaths:
        lines.append("")
        lines.append('Deaths that "is she still alive?" cannot reach:')
        lines += [
            f"  - {name}: add `alive`, `dead`, `died` to their keywords"
            for name in gaps.unreachable_deaths
        ]

    return "\n".join(lines)
