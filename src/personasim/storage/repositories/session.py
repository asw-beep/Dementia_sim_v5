"""Session and turn persistence.

Turns are recorded with the trace that produced them so `persona trace` can
replay a session's retrieval decisions after the fact.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from personasim.models.conversation import Message, Role, SessionId, Turn
from personasim.models.memory import utc_now
from personasim.models.persona import PersonaId
from personasim.models.trace import MemoryTrace
from personasim.storage.schemas import SessionRow, TurnRow


@dataclass(frozen=True)
class SessionSummary:
    """A session as it appears in a list of them. No turns, no traces."""

    session_id: SessionId
    started_at: datetime
    ended_at: datetime | None
    turns: int


class SessionRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        session_id: SessionId,
        persona_id: PersonaId,
        started_at: datetime | None = None,
    ) -> None:
        self._session.add(
            SessionRow(
                id=session_id,
                persona_id=persona_id,
                started_at=started_at or utc_now(),
            )
        )
        self._session.flush()

    def end(self, session_id: SessionId, ended_at: datetime | None = None) -> None:
        row = self._session.get(SessionRow, session_id)
        if row is not None:
            row.ended_at = ended_at or utc_now()

    def append_turn(self, session_id: SessionId, turn: Turn) -> None:
        next_ordinal = self._session.execute(
            select(func.count()).select_from(TurnRow).where(TurnRow.session_id == session_id)
        ).scalar_one()

        self._session.add(
            TurnRow(
                session_id=session_id,
                ordinal=next_ordinal,
                user_content=turn.user_message.content,
                user_timestamp=turn.user_message.timestamp,
                persona_content=turn.persona_message.content,
                persona_timestamp=turn.persona_message.timestamp,
                trace=turn.trace.model_dump(mode="json"),
            )
        )
        self._session.flush()

    def get_turns(self, session_id: SessionId) -> list[Turn]:
        stmt = (
            select(TurnRow).where(TurnRow.session_id == session_id).order_by(TurnRow.ordinal.asc())
        )
        return [self._to_turn(row) for row in self._session.execute(stmt).scalars()]

    def list_sessions(self, persona_id: PersonaId) -> list[SessionSummary]:
        """Every session this persona has had, newest first.

        `persona trace` needs to *find* a session before it can replay one, and a
        session id is a UUID nobody has memorised.
        """
        stmt = (
            select(SessionRow)
            .where(SessionRow.persona_id == persona_id)
            .order_by(SessionRow.started_at.desc())
        )
        rows = list(self._session.execute(stmt).scalars())
        counts = self._turn_counts([row.id for row in rows])

        return [
            SessionSummary(
                session_id=row.id,
                started_at=row.started_at,
                ended_at=row.ended_at,
                turns=counts.get(row.id, 0),
            )
            for row in rows
        ]

    def _turn_counts(self, session_ids: Sequence[SessionId]) -> dict[SessionId, int]:
        """One query, not one per session."""
        if not session_ids:
            return {}
        stmt = (
            select(TurnRow.session_id, func.count())
            .where(TurnRow.session_id.in_(session_ids))
            .group_by(TurnRow.session_id)
        )
        return {session_id: count for session_id, count in self._session.execute(stmt)}

    def latest_session_id(self, persona_id: PersonaId) -> SessionId | None:
        stmt = (
            select(SessionRow.id)
            .where(SessionRow.persona_id == persona_id)
            .order_by(SessionRow.started_at.desc())
            .limit(1)
        )
        return self._session.execute(stmt).scalar_one_or_none()

    @staticmethod
    def _to_turn(row: TurnRow) -> Turn:
        return Turn(
            user_message=Message(
                role=Role.USER,
                content=row.user_content,
                timestamp=row.user_timestamp,
            ),
            persona_message=Message(
                role=Role.PERSONA,
                content=row.persona_content,
                timestamp=row.persona_timestamp,
            ),
            trace=MemoryTrace.model_validate(row.trace),
        )
