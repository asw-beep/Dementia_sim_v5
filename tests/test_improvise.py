"""She may improvise her Tuesday. She may not improvise her life.

She has no clock and no memory of today, so "what did you have for breakfast?" has
no true answer — and left to the model she invented oatmeal with raisins, then a
dinner she ate before evening, then a reason for that too. A fresh, contradictory
life every turn.

The fix is not silence, it is *memory*: synthesise a value once, write it down, and
answer from it ever after. Consistency is not asked of the model; it is taken away
from it.

What makes that safe is the subject of most of this file.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path

import pytest

from personasim.config import Settings
from personasim.conversation import EVERYDAY, Conversation, everyday_for, is_improvised
from personasim.conversation.improvise import improvise
from personasim.llm import render_now
from personasim.llm.base import ChatMessage
from personasim.models import Identity, Persona, RelationshipMemory, SemanticMemory
from personasim.persona import build_persona, read_seed_file
from personasim.storage import Database, MemoryRepository, PersonaRepository

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "personas" / "elena.yaml"


class Fixed:
    """Says the same thing every time — like a model at temperature zero, and unlike
    the one that gave her a different breakfast each turn."""

    def __init__(self, value: str = "toast and black coffee") -> None:
        self.value = value
        self.asked: list[str] = []
        self.prompts: list[list[ChatMessage]] = []

    @property
    def model(self) -> str:
        return "fixed"

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        self.prompts.append(list(messages))
        self.asked.append(messages[-1].content)
        return self.value

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        yield self.generate(messages)

    def is_available(self) -> bool:
        return True


@pytest.fixture
def elena(database: Database) -> Persona:
    persona = build_persona(read_seed_file(SEED_FILE))
    with database.session() as db:
        PersonaRepository(db).save(persona)
    return persona


def reload(database: Database) -> Persona:
    with database.session() as db:
        persona = PersonaRepository(db).load("elena-marsh")
    assert persona is not None
    return persona


class TestSheKeepsWhatSheMadeUp:
    def test_the_first_answer_becomes_a_memory(self, elena: Persona, database: Database) -> None:
        with Conversation(elena, Fixed(), database, Settings()) as chat:
            reply = chat.send("What did you have for breakfast?")

        [breakfast] = [memory for memory in reply.formed if is_improvised(memory)]
        assert breakfast.summary == "For breakfast I had toast and black coffee"
        assert isinstance(breakfast, SemanticMemory)
        assert breakfast.attribute == "breakfast"

    def test_asked_again_she_answers_from_memory_not_from_the_model(
        self, elena: Persona, database: Database
    ) -> None:
        """The point of the whole module. The second answer must come from *memory* —
        so the model is never asked a second time, and cannot give a second
        breakfast."""
        llm = Fixed()

        with Conversation(elena, llm, database, Settings()) as chat:
            chat.send("What did you have for breakfast?")
            asked_after_first = len([q for q in llm.asked if "breakfast this morning" in q])

            again = chat.send("Remind me what you ate this morning?")

        assert asked_after_first == 1
        # never improvised twice
        assert len([q for q in llm.asked if "breakfast this morning" in q]) == 1
        # and the memory is what answered the second time
        assert any("toast and black coffee" in item.summary for item in again.trace.retrieved)
        assert not [memory for memory in again.formed if is_improvised(memory)]

    def test_it_survives_the_session(self, elena: Persona, database: Database) -> None:
        with Conversation(elena, Fixed(), database, Settings()) as chat:
            chat.send("What did you have for breakfast?")

        with database.session() as db:
            stored = MemoryRepository(db).list_memories("elena-marsh")

        assert any("toast and black coffee" in memory.summary for memory in stored)

    def test_a_later_session_gives_the_same_answer(
        self, elena: Persona, database: Database
    ) -> None:
        """Not "she is consistent because the model is". She is consistent because
        the second model never gets asked."""
        with Conversation(elena, Fixed("toast and black coffee"), database, Settings()) as monday:
            monday.send("What did you have for breakfast?")

        # a model that would happily say something else, if it were consulted
        contrarian = Fixed("a completely different breakfast")

        with Conversation(reload(database), contrarian, database, Settings()) as tuesday:
            reply = tuesday.send("What did you have for breakfast?")

        assert any("toast and black coffee" in item.summary for item in reply.trace.retrieved)
        assert not [q for q in contrarian.asked if "breakfast this morning" in q]

    def test_it_is_marked_as_improvised(self, elena: Persona, database: Database) -> None:
        """Confidence 0.5 — below a memory she was told (0.9), far below one she has
        lived (1.0). Phase 2 will want to know the difference; so does anyone reading
        a trace."""
        with Conversation(elena, Fixed(), database, Settings()) as chat:
            [breakfast] = [m for m in chat.send("What did you eat?").formed if is_improvised(m)]

        assert breakfast.confidence == 0.5
        assert breakfast.importance < 0.5


class TestTheClockIsToldNotInvented:
    """The date and the time were improvised for a while, and that was a mistake.

    "What did you have for breakfast?" has no true answer — she did not really eat,
    so something has to be made up. "What day is it?" *does* have a true answer, and
    the system has known it all along. Making her invent a fact that was sitting in
    `datetime.now()` was inventing for the sake of it.

    So it is injected, exactly as identity is: a fact she is handed, not a memory she
    holds. It needs no storage, because a clock is right by construction and a stored
    one is wrong within the hour.
    """

    @pytest.mark.parametrize(
        "question",
        [
            "What day is it today?",
            "What time is it now?",
            "What is the date?",
        ],
    )
    def test_the_clock_is_never_improvised(
        self, elena: Persona, database: Database, question: str
    ) -> None:
        llm = Fixed()

        with Conversation(elena, llm, database, Settings()) as chat:
            reply = chat.send(question)

        assert not [memory for memory in reply.formed if is_improvised(memory)]
        assert not [q for q in llm.asked if "what day of the week" in q]

    def test_the_clock_is_never_written_down(self, elena: Persona, database: Database) -> None:
        """A stored clock is wrong within the hour."""
        with Conversation(elena, Fixed(), database, Settings()) as chat:
            chat.send("What day is it today?")
            chat.send("What time is it now?")

        with database.session() as db:
            stored = MemoryRepository(db).list_memories("elena-marsh")

        assert not [
            memory
            for memory in stored
            if isinstance(memory, SemanticMemory) and memory.attribute in ("date", "time")
        ]

    def test_the_real_time_reaches_the_prompt(self, elena: Persona, database: Database) -> None:
        llm = Fixed()

        with Conversation(elena, llm, database, Settings()) as chat:
            chat.send("What day is it today?")

        now = datetime.now()
        system = llm.prompts[-1][0].content

        assert now.strftime("%A") in system
        assert now.strftime("%-I:%M").lstrip("0") in system

    def test_she_is_told_she_knows_it(self, elena: Persona, database: Database) -> None:
        """Not "it does not come to mind". A healthy person knows what day it is —
        losing that is a *symptom*, which is Phase 2's business, not Phase 1's."""
        assert "you know them" in render_now().lower() or "you know this" in render_now().lower()


class TestSheMayNotImproviseHerLife:
    """The safety argument, and the reason this was allowed at all."""

    @pytest.mark.parametrize(
        "question",
        [
            "Do you have a sister?",
            "Tell me about your sister Clara.",
            "Who was your first boyfriend?",
            "What was your mother's maiden name?",
            "Where did you go to school?",
            "Why did you leave your last job?",
            "What happened in 1994?",
        ],
    )
    def test_biography_is_never_improvised(self, question: str) -> None:
        """There is no path from here to a person, a death, a job, or a life event.
        `EVERYDAY` is exhaustive, and nothing may be added to it that is not a fact
        about her *day*."""
        assert everyday_for(question) is None

    def test_a_question_she_has_a_memory_for_is_never_improvised(
        self, elena: Persona, database: Database
    ) -> None:
        """It only fires where memory is *silent*, so an improvised detail can never
        contradict or overwrite an authored one."""
        llm = Fixed()

        with Conversation(elena, llm, database, Settings()) as chat:
            reply = chat.send("What is your favourite food?")

        assert not [memory for memory in reply.formed if is_improvised(memory)]
        assert llm.asked and "breakfast" not in llm.asked[0]

    def test_it_can_only_ever_produce_a_semantic_memory_about_herself(
        self, elena: Persona, database: Database
    ) -> None:
        """It cannot manufacture a relative. The type system says so: `improvise`
        returns a `SemanticMemory` with `subject='self'`, and a person is a
        `RelationshipMemory`."""
        with Conversation(elena, Fixed(), database, Settings()) as chat:
            chat.send("What did you have for breakfast?")

        improvised = [m for m in reload(database).memories if is_improvised(m)]

        assert improvised
        for memory in improvised:
            assert isinstance(memory, SemanticMemory)
            assert not isinstance(memory, RelationshipMemory)
            assert memory.subject == "self"

    def test_the_cast_does_not_grow(self, elena: Persona, database: Database) -> None:
        before = {m.person_name for m in elena.memories if isinstance(m, RelationshipMemory)}

        with Conversation(elena, Fixed("my sister Clara"), database, Settings()) as chat:
            chat.send("What did you have for breakfast?")
            chat.send("Do you have a sister?")

        after = {
            m.person_name for m in reload(database).memories if isinstance(m, RelationshipMemory)
        }
        assert after == before

    def test_improvisation_can_be_turned_off(self, elena: Persona, database: Database) -> None:
        settings = Settings(improvise_everyday=False)

        with Conversation(elena, Fixed(), database, settings) as chat:
            reply = chat.send("What did you have for breakfast?")

        assert not [memory for memory in reply.formed if is_improvised(memory)]


class TestTheQuestionIsMatchedByRule:
    """Rule-based, like every other decision about what a question means. A model
    deciding this would decide differently on two hearings — and the whole point is
    that she stops answering differently on two hearings."""

    @pytest.mark.parametrize(
        ("question", "attribute"),
        [
            ("What did you have for breakfast?", "breakfast"),
            ("What did you have for dinner?", "dinner"),
            ("Did you eat anything today?", "breakfast"),
            ("How did you sleep last night?", "sleep"),
            ("What have you been doing today?", "activity"),
        ],
    )
    def test_the_named_meal_wins_over_a_shared_word(self, question: str, attribute: str) -> None:
        """ "Eat" reaches breakfast, lunch and dinner alike, so the question that
        names one outright must get that one."""
        everyday = everyday_for(question)

        assert everyday is not None
        assert everyday.attribute == attribute

    def test_every_everyday_thing_is_a_fact_about_her_day(self) -> None:
        """A standing guard on the list itself. If someone ever adds `sister` or
        `job` here, this fails — and it should."""
        forbidden = {
            "sister",
            "brother",
            "mother",
            "father",
            "wife",
            "friend",
            "job",
            "occupation",
            "city",
            "hometown",
            "school",
            "education",
        }
        assert not {everyday.attribute for everyday in EVERYDAY} & forbidden


class TestTheModelStillDoesNotWriteProse:
    """A memory is structured, never free text. The model is asked for a *value*; it
    is never asked for prose that is later read back into memory."""

    def test_a_paragraph_is_refused(self) -> None:
        identity = Identity(
            name="Elena Marsh",
            age=38,
            occupation="Cartographer",
            personality=["precise"],
            values=["honesty"],
            speech_style="Measured.",
        )
        rambler = Fixed(
            "Well, I suppose I had a little of this and a little of that, and I "
            "remember thinking about the coastline while I ate it, which is the kind "
            "of thing that happens when you make maps for a living."
        )

        assert improvise(rambler, identity, EVERYDAY[0]) is None

    def test_a_short_phrase_is_kept(self) -> None:
        identity = Identity(
            name="Elena Marsh",
            age=38,
            occupation="Cartographer",
            personality=["precise"],
            values=["honesty"],
            speech_style="Measured.",
        )

        memory = improvise(Fixed("I had toast and coffee."), identity, EVERYDAY[0])

        assert memory is not None
        # the lead-in and the full stop are stripped: what is stored is the value
        assert memory.value == "toast and coffee"
