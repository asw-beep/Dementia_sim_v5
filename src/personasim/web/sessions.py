"""Live conversations, held in the process that is serving them.

A `Conversation` is stateful: it owns working memory, the persona it is mutating,
and an open session in the log. HTTP is not, so something has to hold it between
one request and the next. This does.

It is a dict. That is not a shortcut — it is the correct data structure for a
handful of kilobytes of process-local state with exactly one reader. A cache would
make the volatility of working memory a *promise* (a TTL somebody has to set
correctly, forever) where today it is a fact: there is no code path from working
memory to durable storage, and an invariant test fails if anyone adds one.

The moment this runs behind more than one worker process, that stops being true and
a shared store starts earning its place. It does not earn it before then.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from personasim.config import Settings
from personasim.conversation import Conversation
from personasim.impairment import HEALTHY, CognitiveProfile
from personasim.llm.base import LLMClient
from personasim.models.conversation import SessionId
from personasim.models.memory import utc_now
from personasim.models.persona import Persona, PersonaId
from personasim.storage.database import Database


class SessionError(Exception):
    """No such live session."""


@dataclass
class Exchange:
    """One turn, as the browser needs it. The trace is the *why*."""

    role: str
    content: str
    at: datetime
    trace: dict[str, object] | None = None
    formed: list[str] = field(default_factory=list)


class SessionStore:
    """Every conversation currently open in this process."""

    def __init__(
        self,
        database: Database,
        llm: LLMClient,
        settings: Settings,
        profile: CognitiveProfile | None = None,
    ) -> None:
        self._database = database
        self._llm = llm
        self._settings = settings
        self._profile = profile or HEALTHY
        self._live: dict[SessionId, Conversation] = {}
        self._transcripts: dict[SessionId, list[Exchange]] = {}

    @property
    def profile(self) -> CognitiveProfile:
        return self._profile

    def open(self, persona: Persona) -> SessionId:
        chat = Conversation(
            persona, self._llm, self._database, self._settings, profile=self._profile
        )
        chat.start()
        self._live[chat.session_id] = chat
        self._transcripts[chat.session_id] = []
        return chat.session_id

    def send(self, session_id: SessionId, text: str) -> Exchange:
        chat = self._require(session_id)

        transcript = self._transcripts[session_id]
        transcript.append(Exchange(role="user", content=text, at=utc_now()))

        reply = chat.send(text)
        exchange = Exchange(
            role="persona",
            content=reply.text,
            at=utc_now(),
            trace=_trace_of(reply.trace.model_dump(mode="json")),
            formed=[memory.summary for memory in reply.formed],
        )
        transcript.append(exchange)
        return exchange

    def end(self, session_id: SessionId) -> int:
        """Close the session and consolidate. Returns memories superseded."""
        chat = self._require(session_id)
        plan = chat.end()
        del self._live[session_id]
        return len(plan.superseded)

    def transcript(self, session_id: SessionId) -> list[Exchange]:
        """The current conversation, and only it. A session that has ended is still
        downloadable until the process forgets it — you may well want the transcript
        *because* you just ended it."""
        if session_id not in self._transcripts:
            raise SessionError(session_id)
        return self._transcripts[session_id]

    def persona_of(self, session_id: SessionId) -> PersonaId:
        return self._require(session_id).persona.id

    def _require(self, session_id: SessionId) -> Conversation:
        chat = self._live.get(session_id)
        if chat is None:
            raise SessionError(session_id)
        return chat


def _trace_of(dumped: dict[str, object]) -> dict[str, object]:
    """The trace, as the panel shows it: why she said that.

    Sequenced after `persona trace` on purpose — the CLI forced the trace into a
    readable shape first, so this renders an honest data structure rather than one
    bent around a UI component.
    """
    return {
        "reason": dumped["reason"],
        "intent": dumped["intent"],
        "retrieved": dumped["retrieved"],
        # Present under a cognitive profile; [] when healthy. A memory that was
        # found and kept out of reach is the most important line the panel can
        # show — it is what the user just experienced as a symptom.
        "withheld": dumped.get("withheld", []),
    }
