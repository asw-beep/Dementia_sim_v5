"""Stage 4: working memory behaves like RAM."""

from __future__ import annotations

import pytest

from personasim.memory import WorkingMemory, WorkingMemoryError
from personasim.models import MemoryTrace, Message, RetrievalIntent, Role


def trace(query: str = "hello") -> MemoryTrace:
    return MemoryTrace(query=query, intent=RetrievalIntent.SMALL_TALK, reason="no memory needed")


def user(content: str) -> Message:
    return Message(role=Role.USER, content=content)


def persona(content: str) -> Message:
    return Message(role=Role.PERSONA, content=content)


@pytest.fixture
def working() -> WorkingMemory:
    return WorkingMemory("elena-marsh", capacity=3)


def exchange(memory: WorkingMemory, n: int) -> None:
    memory.observe_user_message(user(f"question {n}"))
    memory.complete_turn(persona(f"answer {n}"), trace(f"question {n}"))


class TestConstruction:
    def test_starts_empty(self, working: WorkingMemory) -> None:
        assert working.is_empty
        assert working.recent_turns() == []
        assert working.active_topic is None
        assert working.session_id

    def test_capacity_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            WorkingMemory("p", capacity=0)

    def test_session_id_may_be_supplied(self) -> None:
        assert WorkingMemory("p", capacity=2, session_id="s1").session_id == "s1"


class TestTurnCycle:
    def test_a_completed_turn_pairs_the_messages(self, working: WorkingMemory) -> None:
        working.observe_user_message(user("where do you live?"))
        turn = working.complete_turn(persona("Boston."), trace())

        assert turn.user_message.content == "where do you live?"
        assert turn.persona_message.content == "Boston."
        assert working.recent_turns() == [turn]

    def test_persona_message_before_user_message_is_rejected(self, working: WorkingMemory) -> None:
        with pytest.raises(WorkingMemoryError, match="no user message"):
            working.complete_turn(persona("Boston."), trace())

    def test_two_user_messages_without_a_reply_is_rejected(self, working: WorkingMemory) -> None:
        working.observe_user_message(user("first"))
        with pytest.raises(WorkingMemoryError, match="never completed"):
            working.observe_user_message(user("second"))

    def test_roles_are_enforced(self, working: WorkingMemory) -> None:
        with pytest.raises(WorkingMemoryError, match="expected a user message"):
            working.observe_user_message(persona("wrong role"))

        working.observe_user_message(user("hi"))
        with pytest.raises(WorkingMemoryError, match="expected a persona message"):
            working.complete_turn(user("wrong role"), trace())

    def test_transcript_is_in_spoken_order(self, working: WorkingMemory) -> None:
        exchange(working, 1)
        exchange(working, 2)
        assert [m.content for m in working.transcript()] == [
            "question 1",
            "answer 1",
            "question 2",
            "answer 2",
        ]


class TestCapacityWindow:
    def test_the_window_is_bounded(self, working: WorkingMemory) -> None:
        for n in range(10):
            exchange(working, n)
        assert len(working.recent_turns()) == working.capacity

    def test_the_window_keeps_the_most_recent_turns(self, working: WorkingMemory) -> None:
        for n in range(5):
            exchange(working, n)
        assert [t.user_message.content for t in working.recent_turns()] == [
            "question 2",
            "question 3",
            "question 4",
        ]

    def test_turns_seen_counts_beyond_the_window(self, working: WorkingMemory) -> None:
        """A turn leaving the window is a capacity bound, not a forgetting event."""
        for n in range(5):
            exchange(working, n)
        assert working.turns_seen == 5
        assert len(working.recent_turns()) == 3

    def test_recent_turns_honours_an_explicit_limit(self, working: WorkingMemory) -> None:
        for n in range(3):
            exchange(working, n)
        assert [t.user_message.content for t in working.recent_turns(1)] == ["question 2"]

    def test_a_capacity_of_one_keeps_only_the_last_turn(self) -> None:
        memory = WorkingMemory("p", capacity=1)
        exchange(memory, 1)
        exchange(memory, 2)
        assert [t.user_message.content for t in memory.recent_turns()] == ["question 2"]


class TestScratchSpace:
    def test_topic_is_settable_and_clearable(self, working: WorkingMemory) -> None:
        working.set_topic("maps")
        assert working.active_topic == "maps"
        working.set_topic(None)
        assert working.active_topic is None

    def test_facts_accumulate_in_order(self, working: WorkingMemory) -> None:
        working.note_fact("the user's name is Sam", Role.USER)
        working.note_fact("the user lives in Lisbon", Role.USER)

        facts = working.temporary_facts()
        assert [f.content for f in facts] == [
            "the user's name is Sam",
            "the user lives in Lisbon",
        ]
        assert all(f.stated_by is Role.USER for f in facts)

    def test_noting_a_fact_makes_working_memory_non_empty(self, working: WorkingMemory) -> None:
        working.note_fact("something", Role.USER)
        assert not working.is_empty

    def test_facts_are_not_bounded_by_the_turn_window(self, working: WorkingMemory) -> None:
        """The window bounds conversation, not what was learned during it."""
        for n in range(10):
            working.note_fact(f"fact {n}", Role.USER)
            exchange(working, n)

        assert len(working.recent_turns()) == 3
        assert len(working.temporary_facts()) == 10

    def test_returned_collections_are_copies(self, working: WorkingMemory) -> None:
        working.note_fact("a", Role.USER)
        working.temporary_facts().clear()
        assert len(working.temporary_facts()) == 1


class TestTeardown:
    def test_discard_erases_everything(self, working: WorkingMemory) -> None:
        exchange(working, 1)
        working.note_fact("a fact", Role.USER)
        working.set_topic("maps")

        working.discard()

        assert working.is_empty
        assert working.recent_turns() == []
        assert working.temporary_facts() == []
        assert working.active_topic is None
        assert working.turns_seen == 0

    def test_discard_clears_a_pending_message(self, working: WorkingMemory) -> None:
        working.observe_user_message(user("unanswered"))
        working.discard()
        working.observe_user_message(user("a new session"))

    def test_discard_starts_a_new_session(self, working: WorkingMemory) -> None:
        original = working.session_id
        working.discard()
        assert working.session_id != original

    def test_persona_survives_teardown(self, working: WorkingMemory) -> None:
        working.discard()
        assert working.persona_id == "elena-marsh"
