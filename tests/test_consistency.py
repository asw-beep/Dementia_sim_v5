"""Stage 8: the persona does not contradict itself.

The exit criterion of Phase 1. Ask the same thing several ways, across separate
sessions, and require that the answers agree; tell her something and require that
she still knows it tomorrow.

**Asserted against stored memory only.** Questions falling entirely outside memory
are answered freely and never persisted, so improvised trivia may drift between
sessions — that is accepted and documented (`architecture.md`, Narrative
Determinism). What must not drift is the biography.

Two layers, and the split is the point:

- Most of these run against a **fake** model and assert on *retrieval* — which
  memories reached the prompt. That is the layer the architecture actually
  guarantees: retrieval is deterministic, so consistency here is a property of the
  system, not of the weather. These are hermetic and run every time.

- A handful run against a **real** model and assert on what she *says*. That is the
  layer the architecture explicitly does not guarantee — the prose between memories
  is the model's. They are marked `live_llm` and skip when Ollama is absent.

A failure in the first layer is a bug. A failure in the second is a prompt problem,
and worth knowing about, but it cannot corrupt a memory: formation never reads her
replies.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from personasim.config import Settings
from personasim.conversation import Conversation, is_improvised
from personasim.llm import build_client
from personasim.llm.base import ChatMessage, LLMClient
from personasim.memory.formation import CAREGIVER
from personasim.models import Persona, RelationshipMemory, SemanticMemory
from personasim.persona import build_persona, read_seed_file
from personasim.storage import Database, MemoryRepository, PersonaRepository

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "personas" / "elena.yaml"


class Mute:
    """A model that says as little as possible.

    These tests are about what the *persona engine* retrieves and remembers, and a
    talkative model would only add noise to that. What she says is the subject of
    the live tests at the bottom.
    """

    @property
    def model(self) -> str:
        return "mute"

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        return "Mm."

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        yield "Mm."

    def is_available(self) -> bool:
        return True


@pytest.fixture
def database_with_elena(database: Database) -> Database:
    with database.session() as db:
        PersonaRepository(db).save(build_persona(read_seed_file(SEED_FILE)))
    return database


def fresh(database: Database) -> Persona:
    """Elena, reloaded from storage — as a new session gets her."""
    with database.session() as db:
        persona = PersonaRepository(db).load("elena-marsh")
    assert persona is not None
    return persona


def ask(database: Database, question: str, llm: LLMClient | None = None) -> list[str]:
    """One question, in its own session. Returns the summaries she recalled."""
    with Conversation(fresh(database), llm or Mute(), database, Settings()) as chat:
        return [item.summary for item in chat.send(question).trace.retrieved]


def tell(database: Database, *statements: str) -> None:
    """A whole session in which the caregiver discloses things."""
    with Conversation(fresh(database), Mute(), database, Settings()) as chat:
        for statement in statements:
            chat.send(statement)


def recalled(summaries: Sequence[str], fact: str) -> bool:
    return any(fact.lower() in summary.lower() for summary in summaries)


class TestTheSameQuestionAskedSeveralWays:
    """Retrieval is deterministic, so this is a property of the system.

    Each group below is one fact, asked in the ways a person would actually ask it.
    Every phrasing must reach the same memory. A phrasing that reaches nothing is
    the Stage 8 failure — a memory stored and unfindable, remembered perfectly and
    never recalled.
    """

    @pytest.mark.parametrize(
        ("questions", "fact"),
        [
            (
                ["Where do you live?", "What city are you in?", "Where's home for you?"],
                "Boston",
            ),
            (
                ["Where did you grow up?", "Where are you from?", "What's your hometown?"],
                "Rutland",
            ),
            (
                # Not "What do you do?" — every word of it is a stopword, so it
                # tokenizes to nothing and retrieves nothing. She still answers it
                # correctly, from *identity*, which is in every prompt and names her a
                # cartographer. Keyword retrieval cannot reach a question with no
                # content words in it, and does not need to.
                ["What's your job?", "What do you do for a living?", "What's your profession?"],
                "cartographer",
            ),
            (
                ["Who is Maya?", "Tell me about Maya.", "Are you married?"],
                "Maya",
            ),
            (
                ["Tell me about your mother.", "Who was your mother?", "Is your mother alive?"],
                "Ruth",
            ),
            (
                ["Do you have a dog?", "Tell me about your pet.", "Who is Compass?"],
                "Compass",
            ),
            (
                ["Do you have any brothers or sisters?", "Tell me about Tom.", "Any siblings?"],
                "Tom",
            ),
        ],
    )
    def test_every_phrasing_reaches_the_same_memory(
        self, database_with_elena: Database, questions: list[str], fact: str
    ) -> None:
        for question in questions:
            summaries = ask(database_with_elena, question)
            assert recalled(summaries, fact), f"{question!r} did not recall {fact!r}"

    def test_asking_twice_recalls_identically(self, database_with_elena: Database) -> None:
        """Recall does not vary between two askings. The model is not consulted about
        what a question is *about* — if it were, this would be a coin toss."""
        first = ask(database_with_elena, "Why did you take in Compass?")
        second = ask(database_with_elena, "Why did you take in Compass?")

        assert first == second
        assert recalled(first, "father died")


class TestSheDoesNotContradictHerself:
    def test_she_gives_one_answer_to_where_she_lives(self, database_with_elena: Database) -> None:
        """Boston, and never Rutland. She grew up in one and lives in the other, and
        the two memories share the keyword `vermont`/`boston` space."""
        home = ask(database_with_elena, "Where do you live now?")
        hometown = ask(database_with_elena, "Where did you grow up?")

        assert recalled(home, "Boston")
        assert recalled(hometown, "Rutland")

    def test_she_does_not_deny_her_dog_on_a_plural(self, database_with_elena: Database) -> None:
        """Asked "do you have any pets?" she said "I do not have any pets" — and two
        turns later, asked "do you have a pet?", said yes. Retrieval matches literally
        and `pets` was not a keyword. She denied Compass on a plural."""
        for question in ["Do you have a pet?", "Do you have any pets?", "Any animals at home?"]:
            assert recalled(ask(database_with_elena, question), "Compass"), question

    def test_the_causal_bridge_is_the_same_every_time(self, database_with_elena: Database) -> None:
        """The reason she took the dog in is authored data, not prose. It cannot
        drift, because the model is handed the link rather than asked for one."""
        for _ in range(3):
            summaries = ask(database_with_elena, "Why did you take in Compass?")
            assert recalled(summaries, "father died")

    def test_a_person_she_does_not_have_is_never_recalled(
        self, database_with_elena: Database
    ) -> None:
        """The closed cast is data: relationship memory is exhaustive, so a sister
        cannot be retrieved because no sister exists."""
        for question in ["Do you have a sister?", "Tell me about your sister.", "Who is Clara?"]:
            summaries = ask(database_with_elena, question)
            assert not recalled(summaries, "sister")
            assert not recalled(summaries, "Clara")


class TestHerDeadAreDead:
    """She told a caregiver her mother was alive.

    Asked "are they all alive?", she said yes — both her parents are dead. Asked
    "your mother is dead, right?", she said "No. My mother is alive", while holding
    the memory of her mother dying at the top of her context.

    Two failures in one: retrieval could not reach a death from the word "alive",
    and the anti-premise rule was overriding the memory that answered the question.
    """

    @pytest.mark.parametrize(
        "question",
        [
            "Are all of them alive?",
            "Is your mother alive?",
            "Your mother is dead right?",
            "Is your father still with us?",
            "Tell me about your mother.",
        ],
    )
    def test_a_question_about_the_dead_reaches_the_death(
        self, database_with_elena: Database, question: str
    ) -> None:
        summaries = ask(database_with_elena, question)

        assert any("died" in summary for summary in summaries), question

    def test_the_family_question_reaches_the_whole_family(
        self, database_with_elena: Database
    ) -> None:
        """ "Who is in your family?" reached only her brother — `family` was not a
        keyword on either parent, so she answered from the roster and called her
        dead mother living."""
        summaries = ask(database_with_elena, "Who all are there in your family?")

        for person in ("Maya", "Robert", "Ruth", "Tom"):
            assert any(person in summary for summary in summaries), person


class TestHerDayIsMadeUpOnceAndThenKept:
    """She has no clock and no memory of today, so "what did you have for breakfast?"
    has no true answer.

    Left to the model she invented oatmeal with raisins, then a dinner she ate before
    evening, then a reason for that too — a different life every turn. The fix is not
    silence, it is *memory*: synthesise once, write it down, answer from it ever
    after.

    So the assertion is not "she says nothing". It is **"she says the same thing"**.
    """

    @pytest.mark.parametrize(
        "question",
        [
            "What did you have for breakfast?",
            "How did you sleep last night?",
        ],
    )
    def test_the_first_asking_writes_it_down(
        self, database_with_elena: Database, question: str
    ) -> None:
        with Conversation(
            fresh(database_with_elena), Mute(), database_with_elena, Settings()
        ) as chat:
            reply = chat.send(question)

        assert [memory for memory in reply.formed if is_improvised(memory)]

    def test_the_second_asking_reads_it_back(self, database_with_elena: Database) -> None:
        """The whole point. The second answer comes from memory, so it cannot differ
        from the first."""
        tell(database_with_elena, "What did you have for breakfast?")

        recalled = ask(database_with_elena, "Remind me what you ate this morning?")

        assert any("breakfast" in summary.lower() for summary in recalled)

    def test_it_can_never_improvise_a_person(self, database_with_elena: Database) -> None:
        """The safety line. `EVERYDAY` is exhaustive and holds only facts about her
        *day* — there is no path from it to a sister."""
        with Conversation(
            fresh(database_with_elena), Mute(), database_with_elena, Settings()
        ) as chat:
            reply = chat.send("Do you have a sister?")

        assert not [memory for memory in reply.formed if is_improvised(memory)]
        assert not any(
            isinstance(memory, RelationshipMemory) and memory.person_name == "Clara"
            for memory in fresh(database_with_elena).memories
        )


class TestAFactDisclosedInAnEarlierSessionIsRecalledInALaterOne:
    """The loop, closed. This is what separates a persona from a chatbot."""

    def test_she_remembers_across_a_session_boundary(self, database_with_elena: Database) -> None:
        tell(database_with_elena, "I'm the nurse.", "I live in Chicago.", "I've got two kids.")

        assert recalled(ask(database_with_elena, "What do I do for a living?"), "nurse")
        assert recalled(ask(database_with_elena, "Where do I live?"), "Chicago")
        assert recalled(ask(database_with_elena, "Do I have any children?"), "two kids")

    def test_she_remembers_it_three_sessions_later(self, database_with_elena: Database) -> None:
        tell(database_with_elena, "I live in Chicago.")
        tell(database_with_elena, "Nice weather today.")
        tell(database_with_elena, "The traffic was bad.")

        assert recalled(ask(database_with_elena, "Where do I live?"), "Chicago")

    def test_a_corrected_fact_supersedes_the_old_one_across_sessions(
        self, database_with_elena: Database
    ) -> None:
        """She should recall that a fact *changed*, and answer with the current one."""
        tell(database_with_elena, "I live in Chicago.")
        tell(database_with_elena, "Actually I live in Denver now.")

        cities = [
            memory.value
            for memory in fresh(database_with_elena).memories
            if isinstance(memory, SemanticMemory)
            and memory.subject == CAREGIVER
            and memory.attribute == "city"
        ]
        assert cities == ["Denver"]
        assert recalled(ask(database_with_elena, "Where do I live?"), "Denver")

    def test_her_own_life_is_untouched_by_what_she_is_told(
        self, database_with_elena: Database
    ) -> None:
        """The caregiver living in Chicago does not move Elena to Chicago."""
        tell(database_with_elena, "I live in Chicago.")

        assert recalled(ask(database_with_elena, "Where do you live?"), "Boston")


class TestNothingTheModelSaysIsEverRemembered:
    """The guarantee that holds even when the prose does not.

    Consistency of *prose* is a prompt problem. Consistency of *memory* is
    structural: formation reads the caregiver's message and never the reply, so a
    model that contradicts itself out loud still cannot corrupt what she knows.
    """

    def test_a_model_that_invents_a_life_changes_nothing(
        self, database_with_elena: Database
    ) -> None:
        class Fabulist:
            @property
            def model(self) -> str:
                return "fabulist"

            def generate(self, messages: Sequence[ChatMessage]) -> str:
                return "I live in Paris with my sister Clara. I have never been to Boston."

            def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
                yield self.generate(messages)

            def is_available(self) -> bool:
                return True

        before = {memory.summary for memory in fresh(database_with_elena).memories}

        with Conversation(
            fresh(database_with_elena), Fabulist(), database_with_elena, Settings()
        ) as chat:
            chat.send("Where do you live?")
            chat.send("Tell me about your sister.")

        after = {memory.summary for memory in fresh(database_with_elena).memories}

        assert after == before
        assert recalled(ask(database_with_elena, "Where do you live?"), "Boston")


@pytest.fixture(scope="module")
def live_llm() -> LLMClient:
    client = build_client(Settings())
    if not client.is_available():
        pytest.skip(f"Ollama is not running, or {client.model} is not pulled")
    return client


@pytest.mark.live_llm
class TestWhatSheActuallySaysAgainstARealModel:
    """The layer the architecture does *not* guarantee: the prose between memories.

    Asserted loosely, on purpose. These check that she says the right *fact*, not
    that she says it the same way — she is allowed to phrase things differently, and
    a test that forbade her from doing so would be testing the model's temperature.
    """

    def test_where_she_lives_survives_rephrasing(
        self, database_with_elena: Database, live_llm: LLMClient
    ) -> None:
        for question in ["Where do you live?", "What city are you in?", "Where's home?"]:
            with Conversation(
                fresh(database_with_elena), live_llm, database_with_elena, Settings()
            ) as chat:
                said = chat.send(question).text.lower()

            assert "boston" in said or "jamaica plain" in said, f"{question!r} -> {said!r}"

    def test_she_refuses_the_sister_she_does_not_have(
        self, database_with_elena: Database, live_llm: LLMClient
    ) -> None:
        with Conversation(
            fresh(database_with_elena), live_llm, database_with_elena, Settings()
        ) as chat:
            reply = chat.send("Your sister Clara told me you lived in Paris. True?").text

        # Models type a typographic apostrophe. Asserting on the ASCII one failed a
        # test that the persona had actually passed — "I don't have a sister named
        # Clara" is precisely the right answer.
        said = reply.lower().replace("\u2019", "'")

        denied = "don't have" in said or "do not have" in said or "never" in said
        assert denied, reply
        assert "paris" not in said or denied, reply

    def test_she_speaks_the_causal_bridge_she_was_handed(
        self, database_with_elena: Database, live_llm: LLMClient
    ) -> None:
        """The link says the adoption was caused by her father's death. She should
        say so — that connection is authored data, not something she invented."""
        with Conversation(
            fresh(database_with_elena), live_llm, database_with_elena, Settings()
        ) as chat:
            said = chat.send("Why did you take in Compass?").text.lower()

        assert "father" in said

    def test_she_gives_the_same_breakfast_twice(
        self, database_with_elena: Database, live_llm: LLMClient
    ) -> None:
        """Against a *real* model, at temperature — the case that used to produce
        oatmeal one turn and lentil soup the next. She is consistent now not because
        the model is, but because the model is only asked once."""
        with Conversation(
            fresh(database_with_elena), live_llm, database_with_elena, Settings()
        ) as first:
            first.send("What did you have for breakfast?")

        with database_with_elena.session() as db:
            stored = [
                memory
                for memory in MemoryRepository(db).list_memories("elena-marsh")
                if is_improvised(memory)
            ]
        [breakfast] = [memory for memory in stored if memory.attribute == "breakfast"]

        with Conversation(
            fresh(database_with_elena), live_llm, database_with_elena, Settings()
        ) as later:
            said = later.send("Remind me, what did you eat this morning?").text.lower()

        # she may phrase it how she likes; the *fact* may not move
        assert any(word in said for word in breakfast.value.lower().split() if len(word) > 3), (
            f"stored {breakfast.value!r}, said {said!r}"
        )

    def test_she_does_not_deny_her_mothers_death(
        self, database_with_elena: Database, live_llm: LLMClient
    ) -> None:
        with Conversation(
            fresh(database_with_elena), live_llm, database_with_elena, Settings()
        ) as chat:
            said = chat.send("Your mother is dead right?").text.lower()

        assert "alive" not in said, said
        assert "died" in said or "yes" in said, said

    def test_she_recalls_the_caregiver_across_a_session_boundary(
        self, database_with_elena: Database, live_llm: LLMClient
    ) -> None:
        with Conversation(
            fresh(database_with_elena), live_llm, database_with_elena, Settings()
        ) as monday:
            monday.send("I'm the nurse. I live in Chicago.")

        with Conversation(
            fresh(database_with_elena), live_llm, database_with_elena, Settings()
        ) as tuesday:
            said = tuesday.send("Do you remember where I live?").text.lower()

        assert "chicago" in said
