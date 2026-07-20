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

from personasim.assessment import build_ledger, render_report
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

    def as_record(self) -> dict[str, object]:
        return {
            "memory": self.memory,
            "orientation": self.orientation,
            "judgment": self.judgment,
            "language": self.language,
            "global": self.overall,
        }


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
        and the evidence ledger over the logged turns — rendered with the actual
        profile's intended numbers, exactly as `persona assess --profile` would.
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
        report = render_report(build_ledger(session_id, turns), actual)
        return {
            "actual": {"name": record.actual_profile, "label": record.actual_label},
            "ratings": worksheet.as_record(),
            "report": report,
        }

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
