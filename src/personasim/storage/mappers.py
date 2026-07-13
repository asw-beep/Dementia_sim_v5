"""Translation between ORM rows and Pydantic domain models.

The storage boundary is enforced here: repositories return domain models, never
`MemoryRow`. Nothing above `storage/` should ever import from `schemas`.
"""

from __future__ import annotations

from typing import Any

from personasim.models.identity import Identity
from personasim.models.memory import (
    EpisodicMemory,
    Memory,
    MemoryLink,
    MemoryType,
    RelationshipMemory,
    SemanticMemory,
)
from personasim.models.persona import PersonaId
from personasim.storage.schemas import MemoryRow, PersonaRow

# Which subtype columns belong to which memory type.
_SUBTYPE_FIELDS: dict[MemoryType, tuple[str, ...]] = {
    MemoryType.SEMANTIC: ("subject", "attribute", "value"),
    MemoryType.EPISODIC: ("occurred_on", "location", "participants"),
    MemoryType.RELATIONSHIP: ("person_name", "relation", "closeness", "known_since"),
}


def identity_to_row(persona_id: PersonaId, identity: Identity) -> PersonaRow:
    return PersonaRow(
        id=persona_id,
        name=identity.name,
        age=identity.age,
        occupation=identity.occupation,
        personality=list(identity.personality),
        values=list(identity.values),
        speech_style=identity.speech_style,
        description=identity.description,
    )


def row_to_identity(row: PersonaRow) -> Identity:
    return Identity(
        name=row.name,
        age=row.age,
        occupation=row.occupation,
        personality=list(row.personality),
        values=list(row.values),
        speech_style=row.speech_style,
        description=row.description,
    )


def memory_to_row(persona_id: PersonaId, memory: Memory) -> MemoryRow:
    row = MemoryRow(
        id=memory.id,
        persona_id=persona_id,
        type=memory.type.value,
        created_at=memory.created_at,
        summary=memory.summary,
        keywords=list(memory.keywords),
        importance=memory.importance,
        confidence=memory.confidence,
    )
    for field in _SUBTYPE_FIELDS[memory.type]:
        value = getattr(memory, field)
        setattr(row, field, list(value) if isinstance(value, list) else value)
    return row


def row_to_memory(row: MemoryRow, links: list[MemoryLink] | None = None) -> Memory:
    memory_type = MemoryType(row.type)
    fields: dict[str, Any] = {
        "id": row.id,
        "created_at": row.created_at,
        "summary": row.summary,
        "keywords": list(row.keywords),
        "importance": row.importance,
        "confidence": row.confidence,
        "links": list(links or []),
    }
    for field in _SUBTYPE_FIELDS[memory_type]:
        fields[field] = getattr(row, field)

    match memory_type:
        case MemoryType.SEMANTIC:
            return SemanticMemory(**fields)
        case MemoryType.EPISODIC:
            fields["participants"] = list(fields["participants"] or [])
            return EpisodicMemory(**fields)
        case MemoryType.RELATIONSHIP:
            return RelationshipMemory(**fields)
