"""Assessment persistence: the drawn severity, and the rating committed against it.

Persistence only, like every repository here. The draw is *recorded*, never
decided, in this package; the reveal logic that compares rating to actuality
belongs to `assessment/`, which cannot reach storage — an adapter hands it what it
needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from personasim.models.conversation import SessionId
from personasim.models.memory import utc_now
from personasim.models.persona import PersonaId
from personasim.storage.schemas import AssessmentRow


@dataclass(frozen=True)
class AssessmentRecord:
    """One blind interview, as history lists it: what she was, what was rated."""

    session_id: SessionId
    persona_id: PersonaId
    actual_profile: str
    actual_label: str
    drawn_at: datetime
    ratings: dict[str, object] | None
    committed_at: datetime | None


class AssessmentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record_draw(
        self,
        session_id: SessionId,
        persona_id: PersonaId,
        actual_profile: str,
        actual_label: str,
    ) -> None:
        """The answer key, written at session open and readable only by the reveal."""
        self._session.add(
            AssessmentRow(
                session_id=session_id,
                persona_id=persona_id,
                actual_profile=actual_profile,
                actual_label=actual_label,
                drawn_at=utc_now(),
            )
        )
        self._session.flush()

    def commit_rating(self, session_id: SessionId, ratings: dict[str, object]) -> bool:
        """The trainee's committed worksheet. False when no draw was recorded, and a
        no-op on a second commit — a rating revised after the reveal is not a rating."""
        row = self._session.get(AssessmentRow, session_id)
        if row is None:
            return False
        if row.committed_at is not None:
            return True
        row.ratings = ratings
        row.committed_at = utc_now()
        return True

    def get(self, session_id: SessionId) -> AssessmentRecord | None:
        row = self._session.get(AssessmentRow, session_id)
        return None if row is None else _to_record(row)

    def history(self, persona_id: PersonaId) -> list[AssessmentRecord]:
        """Every blind interview for this persona, newest first — the mirror the
        3C history view reads."""
        stmt = (
            select(AssessmentRow)
            .where(AssessmentRow.persona_id == persona_id)
            .order_by(AssessmentRow.drawn_at.desc())
        )
        return [_to_record(row) for row in self._session.execute(stmt).scalars()]

    def committed(self) -> list[AssessmentRecord]:
        """Every *committed* interview, newest first, across all personas.

        Committed only, and that is the whole filter: opening the gallery draws a
        severity, so an interview someone opened and walked away from leaves a row
        with no rating and no turns. Listing those would pad a training history
        with interviews that never happened.
        """
        stmt = (
            select(AssessmentRow)
            .where(AssessmentRow.committed_at.is_not(None))
            .order_by(AssessmentRow.drawn_at.desc())
        )
        return [_to_record(row) for row in self._session.execute(stmt).scalars()]


def _to_record(row: AssessmentRow) -> AssessmentRecord:
    return AssessmentRecord(
        session_id=row.session_id,
        persona_id=row.persona_id,
        actual_profile=row.actual_profile,
        actual_label=row.actual_label,
        drawn_at=row.drawn_at,
        ratings=row.ratings,
        committed_at=row.committed_at,
    )
