"""The web adapter.

A second front end over the Stage 7 orchestrator, alongside the CLI. It adds no
memory, no retrieval, no persona logic — it calls `Conversation` exactly as
`persona chat` does, and would be a bug if it did anything else.

The API is deliberately thin. Everything interesting already happened downstairs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from personasim.config import Settings, get_settings
from personasim.llm import LLMError, build_client
from personasim.storage.database import Database
from personasim.storage.repositories.persona import PersonaRepository
from personasim.web.sessions import SessionError, SessionStore

STATIC = Path(__file__).parent / "static"


class PersonaCard(BaseModel):
    """A persona as the gallery introduces her, before anyone has spoken to her."""

    id: str
    name: str
    age: int
    occupation: str
    description: str | None = None


class Said(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def create_app(settings: Settings | None = None, database: Database | None = None) -> FastAPI:
    settings = settings or get_settings()
    database = database or Database.from_path(settings.database_path)
    database.create_schema()

    sessions = SessionStore(database, build_client(settings), settings)
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
                    # The trace goes with it. A transcript that cannot say *why* she
                    # answered as she did is half a record.
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
