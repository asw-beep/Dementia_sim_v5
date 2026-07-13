"""Persona persistence: identity and its memory graph as one aggregate."""

from __future__ import annotations

from sqlalchemy.orm import Session

from personasim.models.identity import Identity
from personasim.models.persona import Persona, PersonaId
from personasim.storage.repositories.identity import IdentityRepository
from personasim.storage.repositories.memory import MemoryRepository


class PersonaRepository:
    """Loads and saves a whole persona.

    A persona is only valid as a unit — its `links` must resolve against its own
    memories — so identity and memories are written and read together.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self.identities = IdentityRepository(session)
        self.memories = MemoryRepository(session)

    def save(self, persona: Persona) -> None:
        self.identities.upsert(persona.id, persona.identity)
        self._session.flush()
        self.memories.add_many(persona.id, persona.memories)

    def load(self, persona_id: PersonaId) -> Persona | None:
        identity = self.identities.get(persona_id)
        if identity is None:
            return None
        memories = self.memories.list_memories(persona_id)
        return Persona(id=persona_id, identity=identity, memories=memories)

    def exists(self, persona_id: PersonaId) -> bool:
        return self.identities.get(persona_id) is not None

    def list_identities(self) -> list[tuple[PersonaId, Identity]]:
        """Every persona in the database, identity only.

        The gallery needs to introduce personas without loading their memories —
        and there will be more than one of them.
        """
        pairs = [
            (persona_id, self.identities.get(persona_id))
            for persona_id in self.identities.list_ids()
        ]
        return [(persona_id, identity) for persona_id, identity in pairs if identity is not None]
