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

**Assessment mode** (Sprint 3B): constructed with a profile *pool* instead of a
profile, the store draws a hidden severity per session — genuinely at random, on
purpose: the hash-not-roll invariant exists so an impaired session replays
identically, and that reasoning protects `impairment/`; the draw's one job is to
be unguessable. Its one constraint is that it never repeats the previous session's
stage --- see `_draw`. The drawn profile is written to the assessments table (the reveal
has to read it from somewhere that is not the UI) and appears nowhere else — not
in a log line, not in an `Exchange`. A blind session's exchanges carry **no
trace**: the trace names withheld memories and their reasons, which is the answer
key. The session log still records every trace server-side, which is what the
post-reveal review (Sprint 3C) reads.
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence
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
from personasim.storage.repositories.assessment import AssessmentRepository


class SessionError(Exception):
    """No such live session."""


@dataclass
class Exchange:
    """One turn, as the browser needs it. The trace is the *why* — and is absent,
    deliberately, for a blind assessment session."""

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
        assessment_pool: Sequence[CognitiveProfile] | None = None,
    ) -> None:
        if profile is not None and assessment_pool is not None:
            raise ValueError("a fixed profile and an assessment pool are mutually exclusive")
        self._database = database
        self._llm = llm
        self._settings = settings
        self._profile = profile or HEALTHY
        self._pool = list(assessment_pool) if assessment_pool else None
        self._live: dict[SessionId, Conversation] = {}
        self._transcripts: dict[SessionId, list[Exchange]] = {}
        self._blind: set[SessionId] = set()
        self._last_draw: str | None = None

    @property
    def profile(self) -> CognitiveProfile:
        return self._profile

    @property
    def assessing(self) -> bool:
        return self._pool is not None

    def is_blind(self, session_id: SessionId) -> bool:
        return session_id in self._blind

    def _draw(self, pool: Sequence[CognitiveProfile]) -> CognitiveProfile:
        """The hidden severity for one session.

        `secrets.choice`, not a hash: unpredictability is the point. The stage
        drawn for the *previous* session is held out of the pool, so the same one
        can never come up twice running. That rule is not statistical tidiness —
        a run of identical draws reads as a broken simulator long before it reads
        as a coincidence, and a trainee who stops believing the severity is real
        is no longer being trained.

        The cost is stated plainly because it is real: a trainee who has just been
        shown one answer can rule that stage out of the next draw, so the session
        after a reveal is a choice of four rather than five. The draw is still
        unguessable; it is one bit less unguessable. That is the trade, and it is
        the right way round — a streak costs the instrument its credibility, which
        is worth more than the bit.

        A single-profile pool has nothing to hold out, and keeps its one profile.
        """
        candidates = [p for p in pool if p.name != self._last_draw] or list(pool)
        drawn = secrets.choice(candidates)
        self._last_draw = drawn.name
        return drawn

    def open(self, persona: Persona) -> SessionId:
        profile = self._profile
        if self._pool is not None:
            profile = self._draw(self._pool)

        chat = Conversation(persona, self._llm, self._database, self._settings, profile=profile)
        chat.start()
        self._live[chat.session_id] = chat
        self._transcripts[chat.session_id] = []

        if self._pool is not None:
            self._blind.add(chat.session_id)
            # The answer key goes to storage, where only the reveal reads it. It is
            # never logged and never returned from this method.
            with self._database.session() as db:
                AssessmentRepository(db).record_draw(
                    chat.session_id, persona.id, profile.name, profile.label or profile.name
                )
        return chat.session_id

    def send(self, session_id: SessionId, text: str) -> Exchange:
        chat = self._require(session_id)
        blind = self.is_blind(session_id)

        transcript = self._transcripts[session_id]
        transcript.append(Exchange(role="user", content=text, at=utc_now()))

        reply = chat.send(text)
        exchange = Exchange(
            role="persona",
            content=reply.text,
            at=utc_now(),
            # Blind sessions carry no trace and no formed-memory notes: both name
            # what the profile did, and the trainee has not committed yet.
            trace=None if blind else _trace_of(reply.trace.model_dump(mode="json")),
            formed=[] if blind else [memory.summary for memory in reply.formed],
        )
        transcript.append(exchange)
        return exchange

    def end(self, session_id: SessionId) -> int:
        """Close the session and consolidate. Returns memories superseded."""
        chat = self._require(session_id)
        plan = chat.end()
        del self._live[session_id]
        return len(plan.superseded)

    def end_if_live(self, session_id: SessionId) -> None:
        """Commit-time closer: ending the conversation is part of committing, and
        a session already ended is not an error."""
        if session_id in self._live:
            self.end(session_id)

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
