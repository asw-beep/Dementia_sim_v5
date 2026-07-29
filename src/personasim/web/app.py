"""The web adapter.

A second front end over the Stage 7 orchestrator, alongside the CLI. It adds no
memory, no retrieval, no persona logic — it calls `Conversation` exactly as
`persona chat` does, and would be a bug if it did anything else.

The API is deliberately thin. Everything interesting already happened downstairs.

**Assessment mode** (Sprint 3B) is the one place this adapter composes rather than
forwards: it draws the hidden severity (in the session store), seals the leaks —
`/api/profile` says only that the severity is hidden, messages and transcripts
carry no trace — and at commit hands the logged turns to `assessment/` for the
ledger the reveal shows. Blindness is a UI contract, not a security boundary: an
operator with the database can always look, and is trusted not to cheat themselves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from personasim.assessment import build_ledger, coach, render_report
from personasim.assessment.anchors import as_payload, rung_of
from personasim.config import Settings, get_settings
from personasim.impairment import CognitiveProfile, load_profile
from personasim.llm import LLMError, build_client
from personasim.storage.database import Database
from personasim.storage.repositories.assessment import AssessmentRepository
from personasim.storage.repositories.persona import PersonaRepository
from personasim.storage.repositories.session import SessionRepository
from personasim.web.sessions import SessionError, SessionStore

STATIC = Path(__file__).parent / "static"

#: The CDR's own vocabulary — the only values a rating may take.
_CDR_VALUES = {0.0, 0.5, 1.0, 2.0, 3.0}


class PersonaCard(BaseModel):
    """A persona as the gallery introduces her, before anyone has spoken to her."""

    id: str
    name: str
    age: int
    occupation: str
    description: str | None = None


class Said(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class Worksheet(BaseModel):
    """The committed rating: the observable domains, and one global judgment.

    Only what a conversation can show is ratable — the three ADL domains are not
    here, deliberately. The global is required (it is the commitment); a domain
    left blank is honest and stays blank.
    """

    model_config = ConfigDict(populate_by_name=True)

    memory: float | None = None
    orientation: float | None = None
    judgment: float | None = None
    language: float | None = None
    overall: float = Field(alias="global")

    @field_validator("memory", "orientation", "judgment", "language", "overall")
    @classmethod
    def _on_the_scale(cls, value: float | None) -> float | None:
        if value is not None and value not in _CDR_VALUES:
            raise ValueError(f"a CDR rating must be one of {sorted(_CDR_VALUES)}")
        return value

    def as_ratings(self) -> dict[str, float | None]:
        """The rating, keyed by the coach's domain names."""
        return {
            "memory": self.memory,
            "orientation": self.orientation,
            "judgment": self.judgment,
            "language": self.language,
            "global": self.overall,
        }

    def as_record(self) -> dict[str, object]:
        """The same, widened for the JSON column. Separate from `as_ratings` only
        because a `dict[str, float | None]` is not a `dict[str, object]`."""
        return dict(self.as_ratings())


def create_app(
    settings: Settings | None = None,
    database: Database | None = None,
    profile: CognitiveProfile | None = None,
    assessment_pool: list[CognitiveProfile] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    database = database or Database.from_path(settings.database_path)
    database.create_schema()

    # An explicit profile wins; otherwise `PERSONA_PROFILE` selects one; otherwise
    # she is healthy, and no impairment layer is constructed at all. An assessment
    # pool replaces all of that: the profile is drawn per session, and hidden.
    if profile is None and assessment_pool is None and settings.profile is not None:
        profile = load_profile(settings.profile)

    sessions = SessionStore(
        database, build_client(settings), settings, profile=profile, assessment_pool=assessment_pool
    )
    profiles_by_name = {p.name: p for p in assessment_pool or []}
    # The pool indexed by CDR rung, for the coach's two-stage comparison. A profile
    # the scale does not know (a hand-made YAML) simply is not in it, and the coach
    # falls back to anchors alone rather than guessing where it stands.
    profiles_by_rung = {
        rung: profile
        for profile in assessment_pool or []
        if (rung := rung_of(profile.name)) is not None
    }
    app = FastAPI(title="Persona Simulator")

    @app.get("/api/personas")
    def list_personas() -> list[PersonaCard]:
        """The gallery. There is one persona today and there will be more."""
        with database.session() as db:
            found = PersonaRepository(db).list_identities()

        return [
            PersonaCard(
                id=persona_id,
                name=identity.name,
                age=identity.age,
                occupation=identity.occupation,
                description=identity.description,
            )
            for persona_id, identity in found
        ]

    @app.get("/api/profile")
    def current_profile() -> dict[str, object]:
        """Which severity is being served — or, in assessment mode, only that it
        is hidden. The label is the answer key, so it does not leave the server."""
        if sessions.assessing:
            return {
                "name": "assessment",
                "label": "Severity hidden until reveal",
                "assessment": True,
            }
        return {"name": sessions.profile.name, "label": sessions.profile.label, "assessment": False}

    @app.get("/api/anchors")
    def anchors() -> dict[str, object]:
        """The worksheet's domains and their descriptive anchors.

        Served rather than hardcoded in the page because the coach quotes the same
        text back afterwards, and two copies of a clinical description are two
        descriptions. Not blind: an anchor says what a stage looks like in general,
        never which one was drawn.
        """
        return as_payload()

    @app.post("/api/personas/{persona_id}/session")
    def open_session(persona_id: str) -> dict[str, str]:
        with database.session() as db:
            persona = PersonaRepository(db).load(persona_id)
        if persona is None:
            raise HTTPException(404, f"no persona {persona_id!r}")

        return {"session_id": sessions.open(persona)}

    @app.post("/api/session/{session_id}/message")
    def send(session_id: str, said: Said) -> dict[str, Any]:
        try:
            exchange = sessions.send(session_id, said.text)
        except SessionError:
            raise HTTPException(404, "this conversation has ended") from None
        except LLMError as exc:
            # The model is the one part of this that can simply be unavailable, and
            # the browser should say so rather than hang.
            raise HTTPException(503, str(exc)) from exc

        return {
            "content": exchange.content,
            "at": exchange.at.isoformat(),
            "trace": exchange.trace,
            "formed": exchange.formed,
        }

    @app.post("/api/session/{session_id}/end")
    def end(session_id: str) -> dict[str, int]:
        try:
            return {"superseded": sessions.end(session_id)}
        except SessionError:
            raise HTTPException(404, "this conversation has already ended") from None

    @app.post("/api/session/{session_id}/commit")
    def commit(session_id: str, worksheet: Worksheet) -> dict[str, Any]:
        """The commitment, and then — only then — the reveal.

        Ending the conversation is part of committing; a rating entered while the
        interview could still continue is provisional by definition, so the session
        is closed first. The reveal is the actual severity, the committed rating,
        the coach's per-domain reading, and the evidence ledger over the logged
        turns — rendered with the actual profile's intended numbers, exactly as
        `persona assess --profile` would.
        """
        with database.session() as db:
            record = AssessmentRepository(db).get(session_id)
        if record is None:
            raise HTTPException(404, "not an assessment session")
        if record.committed_at is not None:
            raise HTTPException(409, "this assessment is already committed")

        sessions.end_if_live(session_id)

        with database.session() as db:
            AssessmentRepository(db).commit_rating(session_id, worksheet.as_record())
            turns = SessionRepository(db).get_turns(session_id)

        actual = profiles_by_name.get(record.actual_profile)
        ledger = build_ledger(session_id, turns)
        report = render_report(ledger, actual)
        # The coach needs the profile standing at each rung, not just the drawn one:
        # "one rung too high" is a claim about two stages, and the numbers that
        # separate them are read off both.
        readings = coach(ledger, worksheet.as_ratings(), actual, profiles_by_rung) if actual else []
        return {
            "actual": {"name": record.actual_profile, "label": record.actual_label},
            "ratings": worksheet.as_record(),
            "coach": [
                {
                    "domain": reading.domain,
                    "kind": str(reading.kind),
                    "rated": reading.rated,
                    "actual": reading.actual,
                    "missed": reading.missed,
                    "lines": reading.lines,
                }
                for reading in readings
            ],
            "report": report,
        }

    @app.get("/api/session/{session_id}/review")
    def review(session_id: str) -> dict[str, Any]:
        """The finished interview with its trace panel unlocked.

        The cheapest high-value feature in the phase, and the one with the sharpest
        guard: the trace names every memory withheld and why, so before the rating
        is committed it *is* the answer key. Locked until then — and locked by the
        committed-at column rather than by the browser being polite about it, since
        the browser is exactly what a curious trainee would open the devtools on.

        Read from the session log, not the live store: the store's blind exchanges
        never carried a trace, and this is the record that always did.
        """
        with database.session() as db:
            record = AssessmentRepository(db).get(session_id)
            if record is None:
                raise HTTPException(404, "not an assessment session")
            if record.committed_at is None:
                raise HTTPException(
                    409, "the rating has not been committed — the trace is the answer key"
                )
            turns = SessionRepository(db).get_turns(session_id)

        return {
            "session_id": session_id,
            "actual": {"name": record.actual_profile, "label": record.actual_label},
            "turns": [
                {
                    "user": turn.user_message.content,
                    "persona": turn.persona_message.content,
                    "trace": turn.trace.model_dump(mode="json"),
                }
                for turn in turns
            ],
        }

    @app.get("/api/assessments")
    def assessments() -> list[dict[str, Any]]:
        """The history: every committed interview, newest first.

        A mirror, not a mark — date, actual, rated, hit or miss, and nothing that
        adds up to a score. A trainee who keeps calling healthy patients CDR 0.5
        should see that column themselves rather than be given a percentage.

        Only committed assessments appear. An abandoned draw leaves a row with no
        rating and no turns behind it, and listing those would pad the history with
        interviews that never happened.
        """
        with database.session() as db:
            records = AssessmentRepository(db).committed()

        return [
            {
                "session_id": record.session_id,
                "persona_id": record.persona_id,
                "at": record.drawn_at.isoformat(),
                "actual": {"name": record.actual_profile, "label": record.actual_label},
                "ratings": record.ratings,
                "hit": rung_of(record.actual_profile) == (record.ratings or {}).get("global"),
            }
            for record in records
        ]

    @app.get("/api/session/{session_id}/transcript")
    def transcript(session_id: str) -> JSONResponse:
        """This conversation, and only this one. Downloaded as JSON."""
        try:
            exchanges = sessions.transcript(session_id)
        except SessionError:
            raise HTTPException(404, "no such conversation") from None

        payload = {
            "session_id": session_id,
            "turns": [
                {
                    "role": exchange.role,
                    "content": exchange.content,
                    "at": exchange.at.isoformat(),
                    # The trace goes with it — a transcript that cannot say *why*
                    # she answered as she did is half a record. A blind session's
                    # exchanges never carried one, so its download stays blind too.
                    "trace": exchange.trace,
                    "formed": exchange.formed,
                }
                for exchange in exchanges
            ],
        }
        return JSONResponse(
            payload,
            headers={
                "Content-Disposition": f'attachment; filename="transcript-{session_id[:8]}.json"'
            },
        )

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app
