"""Identity persistence."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from personasim.models.identity import Identity
from personasim.models.persona import PersonaId
from personasim.storage.mappers import identity_to_row, row_to_identity
from personasim.storage.schemas import PersonaRow


class IdentityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, persona_id: PersonaId, identity: Identity) -> None:
        row = self._session.get(PersonaRow, persona_id)
        if row is None:
            self._session.add(identity_to_row(persona_id, identity))
            return
        row.name = identity.name
        row.age = identity.age
        row.occupation = identity.occupation
        row.personality = list(identity.personality)
        row.values = list(identity.values)
        row.speech_style = identity.speech_style
        row.description = identity.description

    def get(self, persona_id: PersonaId) -> Identity | None:
        row = self._session.get(PersonaRow, persona_id)
        return None if row is None else row_to_identity(row)

    def find_by_name(self, name: str) -> PersonaId | None:
        stmt = select(PersonaRow.id).where(PersonaRow.name == name)
        return self._session.execute(stmt).scalar_one_or_none()

    def list_ids(self) -> list[PersonaId]:
        return list(self._session.execute(select(PersonaRow.id)).scalars())

    def delete(self, persona_id: PersonaId) -> bool:
        row = self._session.get(PersonaRow, persona_id)
        if row is None:
            return False
        self._session.delete(row)
        return True
