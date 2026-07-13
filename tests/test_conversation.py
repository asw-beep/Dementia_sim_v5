"""Stages 7 and 8: the conversation loop and memory formation.

There are only two people here: the persona, and the caregiver she is talking to.
The caregiver is a role, not an identity — they may say "I'm the nurse", never
"I'm Aswin" — so the persona never has to work out who is speaking, and everything
the caregiver discloses is a fact about the same subject.

The stage's reason for existing is the first test class below. The model will
invent biography under a leading question and nothing stops it reliably, so the
guarantee is not that it stays quiet — it is that what it invents is never
*remembered*. That is asserted before anything else.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from personasim.config import Settings
from personasim.conversation import Conversation, ConversationError
from personasim.llm.base import ChatMessage
from personasim.memory.formation import (
    CAREGIVER,
    consolidate,
    extract_disclosures,
    form_memories,
)
from personasim.models import MemoryType, Persona, SemanticMemory
from personasim.persona import build_persona, read_seed_file
from personasim.storage import (
    Database,
    MemoryRepository,
    PersonaRepository,
    SessionRepository,
)

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "personas" / "elena.yaml"


@pytest.fixture(scope="module")
def seeded() -> Persona:
    return build_persona(read_seed_file(SEED_FILE))


@pytest.fixture
def elena(seeded: Persona, database: Database) -> Persona:
    """A fresh copy per test, already in the database.

    The loop mutates the persona it is given, and writes what it forms — which the
    foreign keys will not allow against a persona that was never saved. That is
    how it works in earnest too: you seed a persona, then talk to it.
    """
    persona = seeded.model_copy(deep=True)
    with database.session() as db:
        PersonaRepository(db).save(persona)
    return persona


class ScriptedLLM:
    """Says what the script says, and records what it was asked.

    A fake, not a stub: the whole point of these tests is that what the model says
    has no bearing on what is remembered, and a fake lets us make it say the worst
    thing we can think of.
    """

    def __init__(self, *replies: str) -> None:
        self._replies = list(replies) or ["Mm."]
        self.prompts: list[list[ChatMessage]] = []

    @property
    def model(self) -> str:
        return "scripted"

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        self.prompts.append(list(messages))
        return self._replies[min(len(self.prompts), len(self._replies)) - 1]

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        yield self.generate(messages)

    def is_available(self) -> bool:
        return True


def conversation(persona: Persona, llm: ScriptedLLM, database: Database) -> Conversation:
    return Conversation(persona, llm, database, Settings())


def about_caregiver(persona: Persona) -> list[SemanticMemory]:
    return [
        memory
        for memory in persona.memories
        if isinstance(memory, SemanticMemory) and memory.subject == CAREGIVER
    ]


class TestAHallucinationIsNeverRemembered:
    """The exit criterion, and the reason the stage exists.

    Formation is handed the caregiver's words. The model's reply is not in scope
    for it — not filtered, not scored, not checked. Simply never offered.
    """

    def test_an_invented_biography_forms_nothing(self, elena: Persona, database: Database) -> None:
        before = len(elena.memories)
        liar = ScriptedLLM(
            "My mother took it badly. She stopped sleeping, and my sister Clara "
            "moved back from Paris to sit with her."
        )

        with conversation(elena, liar, database) as chat:
            reply = chat.send("How did your mother take it when he died?")

        assert "Clara" in reply.text
        assert reply.formed == []
        assert len(elena.memories) == before

    def test_the_invention_does_not_reach_the_database_either(
        self, elena: Persona, database: Database
    ) -> None:
        liar = ScriptedLLM("I have a sister called Clara. She lives in Paris.")

        with conversation(elena, liar, database) as chat:
            chat.send("Tell me about your sister.")

        with database.session() as db:
            stored = MemoryRepository(db).list_memories(elena.id)

        assert not any("Clara" in memory.summary for memory in stored)

    def test_the_model_cannot_talk_the_persona_into_a_memory(
        self, elena: Persona, database: Database
    ) -> None:
        """Not a filter that could be misconfigured — an input that does not exist.

        If the reply were ever fed back in, a persona could be talked into a memory
        by being told what it remembers. It cannot.
        """
        confessor = ScriptedLLM("You are right, I do live in Paris. I am a nurse.")

        with conversation(elena, confessor, database) as chat:
            reply = chat.send("You live in Paris, don't you?")

        assert reply.formed == []
        assert about_caregiver(elena) == []


class TestWhatTheCaregiverDisclosesIsRemembered:
    def test_a_scripted_conversation_forms_exactly_the_expected_memories(
        self, elena: Persona, database: Database
    ) -> None:
        llm = ScriptedLLM("Good to meet you.", "Boston, myself.", "That sounds like work.")

        with conversation(elena, llm, database) as chat:
            first = chat.send("Hello. I'm the nurse.")
            second = chat.send("I live in Chicago.")
            third = chat.send("I've got two kids.")

        assert [memory.summary for memory in first.formed] == ["my caregiver is a nurse"]
        assert [memory.summary for memory in second.formed] == ["my caregiver lives in Chicago"]
        assert [memory.summary for memory in third.formed] == ["my caregiver has two kids"]

    def test_the_caregiver_is_the_subject_whether_or_not_they_introduce_themselves(
        self, elena: Persona, database: Database
    ) -> None:
        """There is no anonymous phase to be stranded in.

        When the speaker was a name to be learned, a fact disclosed *before* the
        name was stranded on an anonymous subject forever: nothing re-attributed it,
        consolidation could not merge it, and it carried no keyword that could reach
        it. A fixed subject deletes that bug rather than fixing it.
        """
        with conversation(elena, ScriptedLLM(), database) as chat:
            [told_first] = chat.send("I live in Chicago.").formed
            [told_later] = chat.send("I'm the nurse.").formed

        assert isinstance(told_first, SemanticMemory)
        assert isinstance(told_later, SemanticMemory)
        assert told_first.subject == CAREGIVER
        assert told_later.subject == CAREGIVER

    def test_a_formed_memory_is_retrievable_on_the_very_next_turn(
        self, elena: Persona, database: Database
    ) -> None:
        """Formation appends to the live persona, so recall does not wait for a
        restart. This is what makes the loop a loop."""
        with conversation(elena, ScriptedLLM(), database) as chat:
            chat.send("I live in Chicago.")
            reply = chat.send("What do you know about Chicago?")

        assert any("Chicago" in item.summary for item in reply.trace.retrieved)

    def test_a_disclosed_fact_answers_the_question_that_would_ask_for_it(
        self, elena: Persona, database: Database
    ) -> None:
        """A memory keyworded only by its content is stored and unfindable.

        Keyworded `chicago, caregiver, city`, it does not answer "where do I live?"
        — which tokenizes to `live`. The fact would be remembered perfectly and
        never recalled, and a persona that cannot recall what it was told is the
        whole project failing quietly.
        """
        with conversation(elena, ScriptedLLM(), database) as chat:
            chat.send("I'm a nurse. I live in Chicago. I grew up in Vermont.")

            about_home = chat.send("Do you remember where I live?")
            about_work = chat.send("And what do I do for a living?")
            about_youth = chat.send("Where did I grow up?")

        assert any("Chicago" in item.summary for item in about_home.trace.retrieved)
        assert any("nurse" in item.summary for item in about_work.trace.retrieved)
        assert any("Vermont" in item.summary for item in about_youth.trace.retrieved)

    def test_a_question_about_a_job_does_not_drag_an_address_along(
        self, elena: Persona, database: Database
    ) -> None:
        """The Stage 5 lesson, still binding: a lazy keyword is a spurious memory
        waiting to fire. "For a living" belongs to a job, not to a city."""
        with conversation(elena, ScriptedLLM(), database) as chat:
            chat.send("I'm a nurse. I live in Chicago.")
            reply = chat.send("What do I do for a living?")

        assert not any("Chicago" in item.summary for item in reply.trace.retrieved)

    def test_a_formed_memory_survives_the_session(self, elena: Persona, database: Database) -> None:
        with conversation(elena, ScriptedLLM(), database) as chat:
            chat.send("I'm a nurse. I live in Chicago.")

        with database.session() as db:
            stored = MemoryRepository(db).list_memories(elena.id, types=[MemoryType.SEMANTIC])

        summaries = [memory.summary for memory in stored]
        assert "my caregiver is a nurse" in summaries
        assert "my caregiver lives in Chicago" in summaries

    def test_she_recalls_it_in_a_later_session(self, elena: Persona, database: Database) -> None:
        """The point of the whole stage."""
        with conversation(elena, ScriptedLLM(), database) as monday:
            monday.send("I'm a nurse. I live in Chicago.")

        with database.session() as db:
            tomorrow = PersonaRepository(db).load(elena.id)
        assert tomorrow is not None

        with conversation(tomorrow, ScriptedLLM(), database) as tuesday:
            reply = tuesday.send("Do you remember where I live?")

        assert any("Chicago" in item.summary for item in reply.trace.retrieved)

    def test_repeating_yourself_does_not_accumulate_duplicates(
        self, elena: Persona, database: Database
    ) -> None:
        with conversation(elena, ScriptedLLM(), database) as chat:
            first = chat.send("I live in Chicago.")
            again = chat.send("I live in Chicago.")

        assert len(first.formed) == 1
        assert again.formed == []

    def test_a_disclosed_fact_is_less_certain_than_an_authored_one(
        self, elena: Persona, database: Database
    ) -> None:
        """A seeded memory is the persona's own life. This is something said once,
        in passing, and people misspeak."""
        with conversation(elena, ScriptedLLM(), database) as chat:
            reply = chat.send("I live in Chicago.")

        assert reply.formed[0].confidence < 1.0


class TestSheActuallyListens:
    """Extraction recognised only the most formal way of saying each thing, and a
    live conversation showed the cost. Told "I'm a nurse", "I grew up in Vermont",
    "I've got two kids", she formed *nothing* — and ended the session remembering
    exactly what she started with.

    A persona who does not listen is a worse failure than one who over-hears,
    because it is the one the user notices. The guard against invention was never
    the formality of the phrasing; it is the disclosure anchor and the
    short-noun-phrase rule, and both survive.
    """

    @pytest.mark.parametrize(
        ("said", "attribute", "value"),
        [
            ("I'm the nurse.", "role", "nurse"),
            ("I'm your doctor.", "role", "doctor"),
            ("I'm a nurse.", "role", "nurse"),
            ("I work as a physiotherapist.", "role", "physiotherapist"),
            ("I live in Chicago.", "city", "Chicago"),
            ("I grew up in Vermont.", "hometown", "Vermont"),
            ("I was born in Rutland.", "hometown", "Rutland"),
            ("I've got two kids.", "family", "two kids"),
            ("I have three children.", "family", "three children"),
        ],
    )
    def test_an_ordinary_disclosure_is_heard(self, said: str, attribute: str, value: str) -> None:
        [disclosure] = extract_disclosures(said)

        assert disclosure.attribute == attribute
        assert disclosure.value == value

    @pytest.mark.parametrize(
        "said",
        [
            "I'm tired.",
            "I'm a bit worried about that.",
            "I'm so glad.",
            "Chicago is a fine city.",
            "Do you live in Boston?",
            "What do you do for a living?",
            "I live in the hope that one day I will be finished.",
        ],
    )
    def test_an_ordinary_remark_still_discloses_nothing(self, said: str) -> None:
        """Recall went up; precision did not go down. "I'm a nurse" and "I'm tired"
        begin the same way — the article is what tells a role from a mood."""
        assert extract_disclosures(said) == []


class TestAskingIsNotTelling:
    """The worst bug this project has produced.

    Asked "Do I have any kids?", the persona formed the memory "…has any kids". The
    question contains the words "I have … kids", and extraction took them at face
    value: someone asking whether they had children was recorded as having them.

    A question is the one kind of sentence that discloses nothing by definition, and
    every disclosure verb appears intact inside the question that asks about it. So
    questions are dropped *before* the patterns run.
    """

    @pytest.mark.parametrize(
        "asked",
        [
            "Do I have any kids?",
            "Do I have kids",  # people drop the mark constantly
            "Did I tell you I live in Chicago?",
            "What do I do for a living?",
            "Am I a nurse?",
            "Where did I grow up?",
            "Have I mentioned I'm from Vermont?",
        ],
    )
    def test_a_question_forms_no_memory(self, asked: str) -> None:
        assert extract_disclosures(asked) == []

    def test_asking_whether_you_have_children_does_not_give_you_children(
        self, elena: Persona, database: Database
    ) -> None:
        """The live failure, replayed."""
        with conversation(elena, ScriptedLLM(), database) as chat:
            reply = chat.send("Do I have any kids?")

        assert reply.formed == []
        assert not any("kids" in memory.summary for memory in elena.memories)

    def test_a_statement_after_a_question_is_still_heard(self) -> None:
        """Dropping questions must not deafen her to the rest of the message."""
        formed = form_memories("Do you like maps? I'm a nurse.")

        assert [memory.summary for memory in formed.memories] == ["my caregiver is a nurse"]


class TestExtractionPrefersSilenceToInvention:
    def test_a_disclosure_needs_a_disclosing_verb(self) -> None:
        assert extract_disclosures("Chicago is a fine city.") == []
        assert extract_disclosures("Do you live in Chicago?") == []

    def test_a_disclosure_ends_at_a_conjunction(self) -> None:
        [city] = extract_disclosures("I live in Chicago and I hate the wind")
        assert city.value == "Chicago"

    def test_a_time_qualifier_is_not_part_of_the_fact(self) -> None:
        """ "I live in Denver now" discloses a city of Denver. People say *when* as
        often as *what*, and the when is not part of the fact."""
        [city] = extract_disclosures("Actually I live in Denver now.")

        assert city.value == "Denver"

    def test_a_sentence_that_merely_starts_like_a_disclosure_is_ignored(self) -> None:
        assert extract_disclosures("I live in the hope that one day I will be finished") == []

    def test_formation_forms_nothing_from_an_ordinary_remark(self) -> None:
        assert form_memories("It's raining here.").is_empty


class TestConsolidation:
    def caregiver_fact(self, value: str) -> SemanticMemory:
        return SemanticMemory(
            summary=f"my caregiver lives in {value}",
            keywords=[value.lower()],
            subject=CAREGIVER,
            attribute="city",
            value=value,
        )

    def test_a_changed_fact_supersedes_the_old_one(self) -> None:
        old = self.caregiver_fact("Chicago")
        new = self.caregiver_fact("Denver")

        plan = consolidate([old, new])

        assert plan.superseded == [old.id]
        assert plan.survivors[0].id == new.id

    def test_the_survivor_answers_to_the_old_facts_keywords(self) -> None:
        """The persona should recall that a fact *changed*, not lose the thread of
        the conversation that changed it."""
        old = self.caregiver_fact("Chicago")
        new = self.caregiver_fact("Denver")

        [survivor] = consolidate([old, new]).survivors

        assert set(survivor.keywords) >= {"denver", "chicago"}

    def test_the_authored_life_is_never_consolidated(self, elena: Persona) -> None:
        """An authored memory is ground truth. Merging two would be editing a life,
        not tidying it — and could dangle a link. A seed may not state one fact
        twice, so consolidation can never find an authored duplicate."""
        assert consolidate(elena.memories).is_empty

    def test_distinct_facts_are_left_alone(self) -> None:
        city = self.caregiver_fact("Chicago")
        role = SemanticMemory(
            summary="my caregiver is a nurse",
            keywords=["nurse"],
            subject=CAREGIVER,
            attribute="role",
            value="nurse",
        )
        assert consolidate([city, role]).is_empty

    def test_a_session_consolidates_on_the_way_out(
        self, elena: Persona, database: Database
    ) -> None:
        chat = conversation(elena, ScriptedLLM(), database)
        chat.start()
        chat.send("I live in Chicago.")
        chat.send("Actually I live in Denver now.")

        assert len(about_caregiver(elena)) == 2

        plan = chat.end()

        assert len(plan.superseded) == 1
        assert [memory.value for memory in about_caregiver(elena)] == ["Denver"]

    def test_consolidation_reaches_the_database(self, elena: Persona, database: Database) -> None:
        with conversation(elena, ScriptedLLM(), database) as chat:
            chat.send("I live in Chicago.")
            chat.send("Actually I live in Denver now.")

        with database.session() as db:
            stored = MemoryRepository(db).list_memories(elena.id, types=[MemoryType.SEMANTIC])

        summaries = [memory.summary for memory in stored]
        assert "my caregiver lives in Denver" in summaries
        assert "my caregiver lives in Chicago" not in summaries


class TestTheLoopItself:
    def test_the_prompt_carries_the_conversation_so_far(
        self, elena: Persona, database: Database
    ) -> None:
        llm = ScriptedLLM("I do — Compass, a beagle.", "After my father died.")

        with conversation(elena, llm, database) as chat:
            chat.send("Do you have a dog?")
            chat.send("Why did you take him in?")

        roles = [message.role.value for message in llm.prompts[-1]]
        assert roles == ["system", "user", "assistant", "user"]

    def test_the_persona_is_told_who_she_is_talking_to(
        self, elena: Persona, database: Database
    ) -> None:
        llm = ScriptedLLM()

        with conversation(elena, llm, database) as chat:
            chat.send("What do I do for a living?")

        assert "always mean YOU, Elena Marsh" in llm.prompts[-1][0].content

    def test_she_still_denies_a_relative_she_does_not_have(
        self, elena: Persona, database: Database
    ) -> None:
        """Making room for the caregiver must not blunt the closed cast."""
        llm = ScriptedLLM()

        with conversation(elena, llm, database) as chat:
            chat.send("Do you have a sister?")

        cast = llm.prompts[-1][0].content
        assert "There is no one else" in cast
        assert "Do not invent the person" in cast

    def test_every_turn_is_recorded_with_the_trace_that_produced_it(
        self, elena: Persona, database: Database
    ) -> None:
        """A response the persona cannot account for is a bug; the session log is
        where the accounting is kept."""
        with conversation(elena, ScriptedLLM("Boston."), database) as chat:
            chat.send("Where do you live?")
            session_id = chat.session_id

        with database.session() as db:
            [turn] = SessionRepository(db).get_turns(session_id)

        assert turn.user_message.content == "Where do you live?"
        assert turn.persona_message.content == "Boston."
        assert turn.trace.reason

    def test_the_session_survives_a_turn_that_throws(
        self, elena: Persona, database: Database
    ) -> None:
        """Working memory can be *unable* to persist, but it cannot make a caller
        remember to tear it down. The context manager can."""

        class Exploding(ScriptedLLM):
            def generate(self, messages: Sequence[ChatMessage]) -> str:
                raise RuntimeError("the model fell over")

        chat = Conversation(elena, Exploding(), database, Settings())

        with pytest.raises(RuntimeError), chat:
            chat.send("Where do you live?")

        with database.session() as db:
            assert SessionRepository(db).get_turns(chat.session_id) == []

    def test_a_finished_conversation_still_knows_which_session_it_was(
        self, elena: Persona, database: Database
    ) -> None:
        """Teardown gives working memory a fresh session id — right for the RAM,
        wrong for the conversation. Read it back from there and the session just
        written to the log becomes unfindable the instant it closes."""
        chat = conversation(elena, ScriptedLLM(), database)
        with chat:
            chat.send("Where do you live?")
            during = chat.session_id

        assert chat.session_id == during

        with database.session() as db:
            assert len(SessionRepository(db).get_turns(chat.session_id)) == 1

    def test_a_conversation_cannot_be_used_after_it_ends(
        self, elena: Persona, database: Database
    ) -> None:
        with conversation(elena, ScriptedLLM(), database) as chat:
            chat.send("Hello.")

        with pytest.raises(ConversationError):
            chat.send("Are you still there?")

    def test_sending_before_starting_is_refused(self, elena: Persona, database: Database) -> None:
        chat = conversation(elena, ScriptedLLM(), database)

        with pytest.raises(ConversationError):
            chat.send("Hello?")

    def test_small_talk_leaves_the_session_without_a_topic(
        self, elena: Persona, database: Database
    ) -> None:
        with conversation(elena, ScriptedLLM("Well enough."), database) as chat:
            reply = chat.send("hello there")

        assert reply.trace.is_empty
        assert reply.formed == []


class TestMemoryUpdatesInStorage:
    def test_a_memory_can_be_revised_without_becoming_a_different_memory(
        self, database: Database, elena: Persona
    ) -> None:
        memory = SemanticMemory(
            summary="my caregiver lives in Chicago",
            keywords=["chicago"],
            subject=CAREGIVER,
            attribute="city",
            value="Chicago",
        )
        with database.session() as db:
            MemoryRepository(db).add(elena.id, memory)

        revised = memory.model_copy(update={"keywords": ["chicago", "denver"]})

        with database.session() as db:
            assert MemoryRepository(db).update(revised) is True

        with database.session() as db:
            stored = MemoryRepository(db).get(memory.id)

        assert stored is not None
        assert stored.id == memory.id
        assert set(stored.keywords) == {"chicago", "denver"}

    def test_updating_a_memory_that_does_not_exist_reports_so(self, database: Database) -> None:
        absent = SemanticMemory(
            summary="nobody lives nowhere",
            keywords=["nowhere"],
            subject=CAREGIVER,
            attribute="city",
            value="Nowhere",
        )
        with database.session() as db:
            assert MemoryRepository(db).update(absent) is False
