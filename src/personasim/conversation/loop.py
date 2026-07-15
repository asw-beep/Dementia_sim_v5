"""The conversation loop.

    User Message → Working Memory → Retrieve → Context → LLM → Response
                 → Memory Formation → Long-Term Memory (optional)

Every module it drives was built and tested alone. This one only sequences them,
and owns the two things that could not exist until they were joined: the session,
and the decision about what a conversation is allowed to leave behind.

Note what does *not* appear below. The LLM's reply is put into working memory, sent
to the session log, and handed back to the caller. It is never passed to formation.
The persona can therefore say something unfounded — Stage 6 showed it will — and
still be structurally incapable of remembering it.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

import structlog

from personasim.config import Settings
from personasim.conversation.improvise import everyday_for, improvise
from personasim.impairment import HEALTHY, CognitiveProfile, ImpairedRetrievalEngine
from personasim.impairment.hold import fade_transcript
from personasim.impairment.voice import render_now_impaired, voice_notes
from personasim.llm.base import LLMClient
from personasim.llm.context_builder import build_messages
from personasim.memory.formation import ConsolidationPlan, consolidate, form_memories
from personasim.memory.working import WorkingMemory
from personasim.models.conversation import Message, Role, SessionId, Turn
from personasim.models.memory import Memory, SemanticMemory
from personasim.models.persona import Persona
from personasim.models.trace import MemoryTrace, RetrievalIntent
from personasim.retrieval.engine import RetrievalEngine
from personasim.retrieval.scope import Scope, scope_of
from personasim.retrieval.source import PersonaMemorySource
from personasim.storage.database import Database
from personasim.storage.repositories.memory import MemoryRepository
from personasim.storage.repositories.session import SessionRepository

log = structlog.get_logger(__name__)


class ConversationError(Exception):
    """The loop was driven out of order."""


class Reply:
    """One turn's outcome, and the evidence for it.

    The trace and the formed memories are exposed rather than logged away: a
    response the persona cannot account for is a bug, and this is where the
    accounting lives.
    """

    __slots__ = ("formed", "text", "trace")

    def __init__(self, text: str, trace: MemoryTrace, formed: list[Memory]) -> None:
        self.text = text
        self.trace = trace
        self.formed = formed

    def __repr__(self) -> str:
        return (
            f"Reply(text={self.text!r}, "
            f"retrieved={len(self.trace.retrieved)}, formed={len(self.formed)})"
        )


class Conversation:
    """One session with one persona.

    Use it as a context manager. The session is then ended and working memory
    discarded even if a turn raises, which is the one guarantee working memory
    could not make for itself: it can be *unable* to persist, but it cannot make a
    caller remember to tear it down.
    """

    def __init__(
        self,
        persona: Persona,
        llm: LLMClient,
        database: Database,
        settings: Settings,
        profile: CognitiveProfile | None = None,
    ) -> None:
        self._persona = persona
        self._llm = llm
        self._database = database
        self._settings = settings
        self._profile = profile or HEALTHY

        # Retrieval runs against the persona held in memory, and formation appends
        # to it. A fact disclosed on turn two is therefore retrievable on turn
        # three, without a database round trip and without a second source of truth.
        self._source = PersonaMemorySource(persona)

        # How much of the live conversation she can hold. The healthy window is a
        # plain capacity bound; an impaired profile widens it to make room for the
        # fade (`impairment.hold`) that frays older turns word by word, which is
        # what turns a delayed-recall probe from free — three words read verbatim
        # out of the prompt — into the graded, partial thing a clinician looks for.
        capacity = self._profile.hold.capacity or settings.working_memory_turns
        self._working = WorkingMemory(persona.id, capacity=capacity)
        self._turn_number = 0

        # Held here, not read back from working memory. `discard()` starts a fresh
        # session — which is right for the RAM and wrong for us: a conversation
        # that has ended must still be able to say which session it *was*, or the
        # session it wrote to the log becomes unfindable the moment it closes.
        self._session_id = self._working.session_id

        # The impairment layer wraps retrieval; it never replaces it. Under the
        # healthy profile the engine is the bare Phase 1 engine — not a wrapper
        # configured to do nothing, but no wrapper at all.
        engine = RetrievalEngine(self._source, settings)
        self._engine: RetrievalEngine | ImpairedRetrievalEngine = (
            ImpairedRetrievalEngine(engine, self._profile, self._source, self._session_id)
            if self._profile.gates_recall
            else engine
        )

        self._started = False
        self._ended = False

    # --- lifecycle ---------------------------------------------------------

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.end()

    @property
    def session_id(self) -> SessionId:
        return self._session_id

    @property
    def persona(self) -> Persona:
        return self._persona

    def start(self) -> None:
        if self._started:
            raise ConversationError("this conversation has already started")

        with self._database.session() as db:
            SessionRepository(db).create(self.session_id, self._persona.id)

        self._started = True
        log.debug("conversation.start", session=self.session_id, persona=self._persona.id)

    def end(self) -> ConsolidationPlan:
        """Close the session: consolidate what was learned, then throw away the RAM."""
        if not self._started:
            raise ConversationError("this conversation was never started")
        if self._ended:
            return ConsolidationPlan()

        plan = self._consolidate()

        with self._database.session() as db:
            SessionRepository(db).end(self.session_id)

        self._working.discard()
        self._ended = True
        log.debug("conversation.end", session=self.session_id, superseded=len(plan.superseded))
        return plan

    # --- the turn ----------------------------------------------------------

    def send(self, text: str) -> Reply:
        """One exchange, in the order the architecture prescribes."""
        if not self._started:
            raise ConversationError("start the conversation before sending to it")
        if self._ended:
            raise ConversationError("this conversation has ended")

        self._turn_number += 1
        user_message = Message(role=Role.USER, content=text)
        self._working.observe_user_message(user_message)

        trace = self._engine.retrieve(text)

        # She has no clock and no memory of today, so "what did you have for
        # breakfast?" has no true answer — and left to the model she invented a
        # different one every turn. Now a value is synthesised *once*, written down,
        # and answered from ever after. Note the order: the memory is made **before**
        # the reply, so she is reading it out rather than making it up. Consistency
        # is not asked of the model; it is taken away from it.
        improvised = self._improvise(text, trace)
        if improvised is not None:
            trace = self._engine.retrieve(text)

        self._working.set_topic(_topic_of(trace))

        # The windowed transcript, which excludes the message being answered — it
        # is the last thing in the prompt, not part of the history. Under an
        # impaired hold, older turns are faded word by word before they reach the
        # prompt; the note explains, in the trace, a delayed-recall failure that
        # otherwise has no retrieved memory to point at. Under the healthy profile
        # the fade is a no-op and every hook resolves to None/"", so the prompt is
        # byte-for-byte the Phase 1 prompt.
        history, fade_note = fade_transcript(
            self._working.recent_turns(),
            self._working.turns_seen,
            self._profile,
            self._session_id,
        )
        if fade_note is not None:
            trace = trace.model_copy(update={"reason": f"{trace.reason}; {fade_note}"})

        reply_text = self._llm.generate(
            build_messages(
                self._persona.identity,
                trace,
                self._source,
                text,
                history=history,
                now_text=render_now_impaired(self._profile),
                voice_notes=voice_notes(
                    self._profile,
                    turn=self._turn_number,
                    user_message=text,
                    trace=trace,
                    session_id=self._session_id,
                    faded=fade_note is not None,
                ),
            )
        )

        persona_message = Message(role=Role.PERSONA, content=reply_text)
        turn = self._working.complete_turn(persona_message, trace)

        # Formation is handed `text` — the user's words. `reply_text` is not in
        # scope for it, and must never be.
        formed = self._form(text)
        if improvised is not None:
            formed = [improvised, *formed]

        self._record(turn, formed)
        return Reply(text=reply_text, trace=trace, formed=formed)

    def _improvise(self, text: str, trace: MemoryTrace) -> SemanticMemory | None:
        """Make something up, but only where memory is silent and only about her day.

        Two guards, and they are the whole safety argument:

        `trace.memory_is_silent` — if retrieval found *anything*, this does not run,
        so an improvised detail can never contradict or overwrite an authored one.
        Silent, not merely empty: a memory a recall gate withheld still *exists*,
        and a turn that failed to reach it must produce "it doesn't come to mind" —
        never a permanent invention written over the top of a real fact. That would
        be manufacturing a memory she actually has, which is the one thing the
        impairment layer must never cause.

        `everyday_for` — the whitelist is exhaustive. There is no path from here to a
        person, a death, a job, or a life event. Asked about a sister she does not
        have, she still says it does not come to mind, because `sister` is not an
        everyday attribute and never will be.
        """
        if not self._settings.improvise_everyday or not trace.memory_is_silent:
            return None
        if trace.intent is RetrievalIntent.SMALL_TALK or scope_of(text) is Scope.CAREGIVER:
            return None

        everyday = everyday_for(text)
        if everyday is None:
            return None

        memory = improvise(self._llm, self._persona.identity, everyday)
        if memory is None:
            return None

        self._remember([memory])
        log.debug("conversation.improvised", session=self.session_id, memory=memory.summary)
        return memory

    # --- formation ---------------------------------------------------------

    def _form(self, text: str) -> list[Memory]:
        result = form_memories(text, existing=self._persona.memories)

        for disclosure in result.disclosures:
            # Everything disclosed is noted in working memory, including what
            # formation declined to keep. The session should know what was said
            # even where long-term memory does not.
            self._working.note_fact(disclosure.matched, Role.USER)

        if result.memories:
            self._remember(result.memories)
            log.debug(
                "conversation.formed",
                session=self.session_id,
                memories=[memory.summary for memory in result.memories],
            )

        return result.memories

    def _remember(self, memories: list[Memory]) -> None:
        """Append to the live persona. Reassigned, not mutated: `Persona`
        revalidates its memory graph on assignment, so an unsound memory cannot
        be slipped in through the back."""
        self._persona.memories = [*self._persona.memories, *memories]

    def _consolidate(self) -> ConsolidationPlan:
        plan = consolidate(self._persona.memories)
        if plan.is_empty:
            return plan

        superseded = set(plan.superseded)
        survivors = {memory.id: memory for memory in plan.survivors}

        kept: list[Memory] = [
            survivors.get(memory.id, memory)
            for memory in self._persona.memories
            if memory.id not in superseded
        ]
        self._persona.memories = kept

        with self._database.session() as db:
            memories = MemoryRepository(db)
            for memory_id in plan.superseded:
                memories.delete(memory_id)
            for survivor in plan.survivors:
                memories.update(survivor)

        return plan

    # --- persistence -------------------------------------------------------

    def _record(self, turn: Turn, formed: list[Memory]) -> None:
        """One unit of work per turn: the turn and what it taught, together.

        If the write fails, neither lands — the session log cannot claim a turn
        whose memory was lost, nor hold a memory for a turn it never recorded.
        """
        with self._database.session() as db:
            SessionRepository(db).append_turn(self.session_id, turn)
            memories = MemoryRepository(db)
            for memory in formed:
                memories.add(self._persona.id, memory)


def _topic_of(trace: MemoryTrace) -> str | None:
    """What the session is currently about: the best-scoring memory's subject
    matter, taken from what actually matched. Small talk is about nothing, and
    says so."""
    for retrieved in trace.retrieved:
        if retrieved.matched_keywords:
            return retrieved.matched_keywords[0]
    return None
