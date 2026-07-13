"""Working memory: the persona's RAM.

Holds the current conversation, the active topic, and facts disclosed mid-session.
It is created when a session starts and destroyed when it ends. Nothing here
reaches long-term memory except by passing through memory formation.

This module touches no database. That is the point: working memory is volatile
by construction, not by policy.
"""

from __future__ import annotations

from personasim.models.conversation import (
    ConversationState,
    Message,
    Role,
    SessionId,
    TemporaryFact,
    Turn,
)
from personasim.models.persona import PersonaId
from personasim.models.trace import MemoryTrace


class WorkingMemoryError(Exception):
    """Working memory was driven out of order."""


class WorkingMemory:
    """A bounded, session-scoped view of the conversation in progress.

    The turn window is a capacity bound, not a forgetting model. A turn that falls
    out of the window has already been persisted to the session log; it leaves RAM,
    not existence. Long-term memory is entirely unaffected by the window, so a
    memory formed from an early turn remains retrievable for the rest of the
    session and every session after.
    """

    def __init__(
        self,
        persona_id: PersonaId,
        *,
        capacity: int,
        session_id: SessionId | None = None,
    ) -> None:
        if capacity <= 0:
            raise ValueError("working memory capacity must be positive")

        self._capacity = capacity
        self._state = (
            ConversationState(persona_id=persona_id, session_id=session_id)
            if session_id
            else ConversationState(persona_id=persona_id)
        )
        self._pending: Message | None = None
        self._turns_seen = 0

    # --- inspection --------------------------------------------------------

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def session_id(self) -> SessionId:
        return self._state.session_id

    @property
    def persona_id(self) -> PersonaId:
        return self._state.persona_id

    @property
    def state(self) -> ConversationState:
        return self._state

    @property
    def active_topic(self) -> str | None:
        return self._state.active_topic

    @property
    def turns_seen(self) -> int:
        """Every turn this session has held, including those outside the window."""
        return self._turns_seen

    @property
    def is_empty(self) -> bool:
        return not self._state.turns and not self._state.temporary_facts

    def recent_turns(self, limit: int | None = None) -> list[Turn]:
        """The most recent turns, oldest first."""
        turns = self._state.turns
        return turns[-limit:] if limit is not None else list(turns)

    def transcript(self) -> list[Message]:
        """The windowed conversation, flattened in the order it was spoken."""
        return [
            message
            for turn in self._state.turns
            for message in (turn.user_message, turn.persona_message)
        ]

    def temporary_facts(self) -> list[TemporaryFact]:
        return list(self._state.temporary_facts)

    # --- the update hook ---------------------------------------------------

    def observe_user_message(self, message: Message) -> None:
        """Called on every inbound user message, before retrieval runs."""
        if message.role is not Role.USER:
            raise WorkingMemoryError("expected a user message")
        if self._pending is not None:
            raise WorkingMemoryError("the previous turn was never completed")
        self._pending = message

    def complete_turn(self, persona_message: Message, trace: MemoryTrace) -> Turn:
        """Pair the pending user message with the persona's reply and window it."""
        if persona_message.role is not Role.PERSONA:
            raise WorkingMemoryError("expected a persona message")
        if self._pending is None:
            raise WorkingMemoryError("no user message is awaiting a reply")

        turn = Turn(user_message=self._pending, persona_message=persona_message, trace=trace)
        self._pending = None
        self._turns_seen += 1

        # Reassign rather than mutate: ConversationState revalidates on assignment.
        self._state.turns = [*self._state.turns, turn][-self._capacity :]
        return turn

    # --- session-scoped scratch space --------------------------------------

    def set_topic(self, topic: str | None) -> None:
        self._state.active_topic = topic

    def note_fact(self, content: str, stated_by: Role) -> TemporaryFact:
        """Record something learned mid-conversation.

        This does not persist. Only memory formation may promote a temporary fact
        into long-term memory, and only after validating it.
        """
        fact = TemporaryFact(content=content, stated_by=stated_by)
        self._state.temporary_facts = [*self._state.temporary_facts, fact]
        return fact

    # --- teardown ----------------------------------------------------------

    def discard(self) -> None:
        """End the session. Working memory does not survive it."""
        self._state = ConversationState(persona_id=self._state.persona_id)
        self._pending = None
        self._turns_seen = 0
