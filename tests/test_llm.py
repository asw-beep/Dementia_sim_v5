"""Stage 6: the LLM layer.

The model is the last thing to arrive and the least trusted thing in the system.
These tests pin down what it is handed (identity, memories, and the *typed
relations between them*), what it may never be asked for, and that no module
outside `llm/` knows which provider is in use.

Everything here runs without a model, except the two tests marked `live_llm`,
which skip when Ollama is not running.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from pathlib import Path

import pytest

from personasim.config import Settings
from personasim.llm import (
    ChatMessage,
    ChatRole,
    LLMClient,
    LLMError,
    LLMUnavailableError,
    build_client,
    build_memory_context,
    build_messages,
    build_system_prompt,
    to_chat_messages,
)
from personasim.llm.context_builder import (
    NO_MEMORY,
    NO_RECALL_NEEDED,
    render_cast,
    render_now,
    render_speaker,
)
from personasim.llm.ollama import OllamaClient, strip_thinking
from personasim.models import (
    Identity,
    Memory,
    MemoryId,
    MemoryTrace,
    MemoryType,
    Message,
    Persona,
    RetrievalIntent,
    Role,
    SemanticMemory,
)
from personasim.persona import build_persona, memory_id_for, read_seed_file
from personasim.retrieval import MemorySource, PersonaMemorySource, RetrievalEngine

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "personas" / "elena.yaml"


@pytest.fixture(scope="module")
def elena() -> Persona:
    return build_persona(read_seed_file(SEED_FILE))


@pytest.fixture(scope="module")
def source(elena: Persona) -> PersonaMemorySource:
    return PersonaMemorySource(elena)


@pytest.fixture(scope="module")
def engine(source: PersonaMemorySource) -> RetrievalEngine:
    return RetrievalEngine(source, Settings())


def mid(key: str) -> str:
    return memory_id_for("elena-marsh", key)


class FakeLLM:
    """A model that says what it is told to, and records what it was asked.

    Satisfies `LLMClient` structurally — it inherits nothing, which is the point
    of the protocol: a test double needs no provider and no base class.
    """

    def __init__(self, reply: str = "Something plausible.") -> None:
        self.reply = reply
        self.calls: list[list[ChatMessage]] = []

    @property
    def model(self) -> str:
        return "fake"

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        return self.reply

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        self.calls.append(list(messages))
        yield self.reply

    def is_available(self) -> bool:
        return True

    @property
    def last_system_prompt(self) -> str:
        return self.calls[-1][0].content


class ForgetfulSource:
    """A source that has every memory except one — used to prove nothing is dropped."""

    def __init__(self, inner: MemorySource, missing: MemoryId) -> None:
        self._inner = inner
        self._missing = missing

    def get(self, memory_id: MemoryId) -> Memory | None:
        return None if memory_id == self._missing else self._inner.get(memory_id)

    def find_by_keywords(
        self, keywords: Sequence[str], types: Sequence[MemoryType] | None = None
    ) -> list[Memory]:
        return self._inner.find_by_keywords(keywords, types)

    def find_by_person(self, person_name: str) -> list[Memory]:
        return self._inner.find_by_person(person_name)

    def person_names(self) -> list[str]:
        return self._inner.person_names()


class TestTheInterface:
    def test_a_fake_satisfies_the_client_protocol(self) -> None:
        """No provider, no base class, no network — and it type-checks as a client."""
        client: LLMClient = FakeLLM()
        assert client.generate([ChatMessage(role=ChatRole.USER, content="hello")])

    def test_the_real_adapter_satisfies_the_client_protocol(self) -> None:
        client: LLMClient = build_client(Settings())
        assert client.model == Settings().llm_model

    def test_a_message_cannot_be_empty(self) -> None:
        with pytest.raises(ValueError):
            ChatMessage(role=ChatRole.USER, content="")

    def test_chat_roles_are_the_providers_vocabulary_not_the_domains(self) -> None:
        """`persona` is a domain role; a chat model only knows `assistant`."""
        assert {role.value for role in ChatRole} == {"system", "user", "assistant"}


class TestIdentityInThePrompt:
    def test_identity_is_injected_never_generated(self, elena: Persona) -> None:
        prompt = build_system_prompt(elena.identity, NO_MEMORY)

        assert "Elena Marsh" in prompt
        assert str(elena.identity.age) in prompt
        assert elena.identity.occupation in prompt
        assert elena.identity.speech_style in prompt
        for trait in elena.identity.personality:
            assert trait in prompt

    def test_the_model_is_forbidden_from_inventing_biography(self, identity: Identity) -> None:
        prompt = build_system_prompt(identity, NO_MEMORY).lower()

        assert "never state anything about your life that is not written above" in prompt
        assert "say what you remember, and then stop" in prompt
        assert "how you felt" in prompt
        assert "first person" in prompt

    def test_the_model_is_told_the_memories_are_all_there_is(self, identity: Identity) -> None:
        """Read as *notes*, a memory list invites the model to fill the gaps.

        It is given as a boundary instead: this is the whole of what comes to mind.
        """
        prompt = build_system_prompt(identity, NO_MEMORY).lower()

        assert "the whole of what comes to mind" in prompt
        assert "add nothing of your own" in prompt

    def test_the_model_is_told_to_refuse_a_questions_premise(self, identity: Identity) -> None:
        """A question can smuggle in a person who does not exist.

        Asked how her mother took her father's death, the persona invented a
        mother — her silence, her sleeplessness, all of it. The premise alone was
        enough. This rule, and the closed cast, are what stand against that.
        """
        prompt = build_system_prompt(identity, NO_MEMORY).lower()

        assert "never accept a premise you have no memory of" in prompt

    def test_a_true_premise_is_not_refused(self, identity: Identity) -> None:
        """The anti-premise rule turned on her own life.

        Told "your mother is dead, right?" — while *holding the memory of her
        mother dying, retrieved at the top of her context* — she answered "No. My
        mother is alive." She refused a premise she had every memory of, because the
        question sounded like a trap. Denying something true is as much a lie as
        inventing something false, and it is the worse one: it is her own life she
        is denying.
        """
        prompt = build_system_prompt(identity, NO_MEMORY)

        assert "never overrides a memory" in prompt
        assert "Refuse the premise only when" in prompt

    def test_her_day_is_her_life(self, identity: Identity) -> None:
        """Asked what she ate, she produced oatmeal with raisins — then, challenged
        on having dined before evening, produced a reason for that too. The escape
        hatch for "anything outside your own life" was letting autobiography through
        as small talk."""
        prompt = build_system_prompt(identity, NO_MEMORY)

        assert "your day is your life" in prompt.lower()
        assert "do not produce a breakfast" in prompt

    def test_a_blank_covers_today(self, identity: Identity) -> None:
        """ "If you are being asked about your own life" was too soft a hedge — the
        model did not count breakfast as her life. The blank is now stated as a fact
        about her, not a condition for her to evaluate."""
        assert "You do not know the answer" in NO_MEMORY
        assert "what you ate" in NO_MEMORY
        assert "a blank *is* the" in NO_MEMORY

    def test_she_is_a_person_not_an_encyclopedia(self, identity: Identity) -> None:
        """Asked to define electrostatic force she gave a textbook answer; asked for
        gradient descent she produced the LaTeX. A woman who draws maps for a living
        does not have the mathematics of machine learning at her fingertips, and
        pretending otherwise is the moment she stops being her."""
        prompt = build_system_prompt(identity, NO_MEMORY)

        assert "not an encyclopedia" in prompt
        assert "never produce a definition, a formula" in prompt

    def test_she_does_not_know_her_own_ancestry(self, identity: Identity) -> None:
        """Ancestry, religion, politics, health: they *feel* like things a person
        simply knows about herself, which is exactly why the model fills them in. She
        invented an English and Scottish descent, and a Nigerian one for her wife."""
        prompt = build_system_prompt(identity, NO_MEMORY)

        # the rule wraps across lines in the prompt, so match on its content
        assert "ancestry, your religion, your politics, or your health" in " ".join(prompt.split())
        assert "You do not know them unless they are written above" in prompt

    def test_the_rules_come_last(self, identity: Identity) -> None:
        """The model weights the end of a prompt most heavily, and the rules are
        what stand between a question's premise and an invented life."""
        prompt = build_system_prompt(identity, NO_MEMORY, cast="The people in your life are: X.")

        assert prompt.index(NO_MEMORY) < prompt.index("Two rules override")
        assert prompt.index("The people in your life are: X.") < prompt.index(NO_MEMORY)


class TestMemoryContext:
    def test_a_retrieved_fact_reaches_the_prompt(
        self, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        trace = engine.retrieve("Where do you live?")
        context = build_memory_context(trace, source)

        assert "Boston" in context
        assert "Things you know about yourself:" in context

    def test_nothing_retrieved_tells_the_model_a_blank_is_the_right_answer(
        self, source: MemorySource
    ) -> None:
        empty = MemoryTrace(
            query="what is your sister's name?",
            intent=RetrievalIntent.RELATIONSHIP_QUERY,
            reason="no memory matched",
        )
        context = build_memory_context(empty, source)

        assert NO_MEMORY in context
        assert "Do not invent" in context

    def test_small_talk_is_not_treated_as_a_memory_failure(
        self, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        """A greeting must not make the persona protest that she cannot remember."""
        trace = engine.retrieve("hello there")

        assert trace.intent is RetrievalIntent.SMALL_TALK
        assert build_memory_context(trace, source) == NO_RECALL_NEEDED

    def test_sections_lead_with_the_type_retrieval_ranked_highest(
        self, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        """Section order follows relevance, not a fixed hierarchy of memory types."""
        about_a_person = build_memory_context(engine.retrieve("Who is Maya?"), source)
        about_an_event = build_memory_context(engine.retrieve("Why did you adopt Compass?"), source)

        assert about_a_person.index("People in your life:") < about_a_person.index(
            "Things you have lived through:"
        )
        assert about_an_event.index("Things you have lived through:") < about_an_event.index(
            "Things you know about yourself:"
        )

    def test_an_episode_carries_its_date_place_and_people(
        self, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        context = build_memory_context(engine.retrieve("Tell me about your wedding."), source)

        assert "2014-09-06" in context
        assert "Maya" in context

    def test_a_fact_about_someone_else_is_not_filed_as_a_fact_about_herself(
        self, elena: Persona, engine: RetrievalEngine
    ) -> None:
        """Formation stores what the *user* disclosed, so not every semantic memory
        is autobiography. Filed under "things you know about yourself", "Sam lives
        in Chicago" invites the persona to move to Chicago."""
        about_sam = SemanticMemory(
            summary="my caregiver lives in Chicago",
            keywords=["chicago", "caregiver", "live"],
            subject="my caregiver",
            attribute="city",
            value="Chicago",
        )
        persona = elena.model_copy(deep=True)
        persona.memories = [*persona.memories, about_sam]
        source = PersonaMemorySource(persona)

        context = build_memory_context(
            RetrievalEngine(source, Settings()).retrieve("Where does my caregiver live?"), source
        )

        assert "Things the person you are speaking with has told you about themselves:" in context
        sam_line = next(
            line for line in context.splitlines() if "my caregiver lives in Chicago" in line
        )
        heading = next(
            line
            for line in reversed(context[: context.index(sam_line)].splitlines())
            if line.endswith(":")
        )
        assert heading != "Things you know about yourself:"

    def test_a_person_carries_the_shape_of_the_relationship(
        self, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        context = build_memory_context(engine.retrieve("Who is Maya?"), source)

        assert "your wife" in context or "your spouse" in context
        assert "you are very close" in context


class TestTheCausalBridgeIsHandedOver:
    """The reason typed links exist: the model verbalizes the relation, never invents it."""

    def test_an_explaining_memory_arrives_with_its_relation(
        self, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        trace = engine.retrieve("Why did you adopt Compass?")
        context = build_memory_context(trace, source)

        assert "came about because of this" in context
        assert "died of a stroke" in context

    def test_the_relation_is_glossed_in_english_not_as_a_field_name(
        self, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        context = build_memory_context(engine.retrieve("Why did you adopt Compass?"), source)

        assert "caused_by" not in context

    def test_an_explaining_memory_is_stated_as_a_separate_occasion(
        self, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        """It used to be nested beneath the memory it explained, which is how it
        read: as part of it. Asked about her wedding in 2014, she recounted an
        argument from a birthday in 2011 as though it had happened at the altar —
        both memories true, the juxtaposition a lie. No wording of the label fixed
        it, because the *indentation* was making the claim."""
        trace = engine.retrieve("Why did you adopt Compass?")
        context = build_memory_context(trace, source)

        death = next(item for item in trace.retrieved if item.memory_id == mid("fathers_death"))
        assert death.was_expanded

        assert "do not describe one as part of another" in context
        assert context.index("Things you have lived through:") < context.index(
            "These are connected to what you recalled above"
        )

    def test_a_memory_is_never_silently_dropped(
        self, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        """If the memory it explains cannot be read back, it still gets rendered."""
        trace = engine.retrieve("Why did you adopt Compass?")
        forgetful = ForgetfulSource(source, missing=mid("compass_adoption"))

        context = build_memory_context(trace, forgetful)

        assert "died of a stroke" in context
        assert "·" not in context


class TestTheCastIsClosed:
    """Who is in your life is identity-level: you need no reminder that you have a
    brother in order to deny having a sister."""

    def test_everyone_the_persona_knows_is_named_every_turn(self, source: MemorySource) -> None:
        cast = render_cast(source)

        for name in ("Maya Okonkwo", "Robert Marsh", "Tom Marsh", "Priya Raman", "Dan Hollis"):
            assert name in cast

    def test_the_cast_says_who_each_person_is(self, source: MemorySource) -> None:
        """Handed her father's memory beside her wife's family home, the model made
        Robert into Maya's father. The roster fixes each person in place."""
        assert "Robert Marsh (father)" in render_cast(source)
        assert "Maya Okonkwo (wife)" in render_cast(source)

    def test_the_cast_is_asserted_to_be_complete(self, source: MemorySource) -> None:
        """Relationship memory is exhaustive by construction, so this is true —
        and it is what refuses a mother the persona does not have."""
        cast = render_cast(source)

        assert "There is no one else" in cast
        assert "Do not invent the person" in cast

    def test_the_caregiver_is_not_denied_by_the_closed_cast(self, source: MemorySource) -> None:
        """They are not *in* her life; they are *in the room*. Left unqualified,
        "there is no one else" made her deny the person she was speaking to."""
        assert "besides the person you are speaking with" in render_cast(source)

    def test_the_cast_reaches_the_prompt(
        self, elena: Persona, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        messages = build_messages(
            elena.identity, engine.retrieve("Who is Maya?"), source, "Who is Maya?"
        )

        assert "There is no one else" in messages[0].content

    def test_a_persona_with_no_relationships_gets_no_roster(self, identity: Identity) -> None:
        """An empty list must not become the claim that she knows nobody at all."""
        alone = PersonaMemorySource(Persona(identity=identity, memories=[]))

        assert render_cast(alone) == ""


class TestSheKnowsWhatDayItIs:
    """Told, not invented. "What did you have for breakfast?" has no true answer;
    "what day is it?" does, and the system has known it all along."""

    def test_the_clock_is_a_fact_she_is_handed(self) -> None:
        told = render_now(datetime(2026, 7, 13, 17, 19))

        assert "Monday, 13 July 2026" in told
        assert "5:19 pm" in told

    def test_she_is_told_she_knows_it_rather_than_to_guess(self) -> None:
        told = render_now(datetime(2026, 7, 13, 17, 19))

        assert "do not guess" in told
        assert "does not come to mind" in told  # ...and is told NOT to say that

    def test_it_reaches_every_prompt(
        self, elena: Persona, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        """Injected like identity — present whether or not the question is about it."""
        messages = build_messages(
            elena.identity, engine.retrieve("Where do you live?"), source, "Where do you live?"
        )

        assert "Right now it is" in messages[0].content


class TestWhoIIs:
    """Asked "what do I do for a living?", she answered "I'm a cartographer".

    She read the caregiver's "I" as her own — while holding the caregiver's job in
    the very context she had been handed. Her memories speak of the caregiver in the
    third person, the question says "I", and nothing joined the two.
    """

    def test_each_person_owns_their_own_pronouns(self) -> None:
        said = render_speaker("Elena Marsh")

        assert "'I', 'me' and 'my' always mean THEM" in said
        assert "always mean YOU, Elena Marsh" in said

    def test_the_persona_is_not_told_she_is_looked_after(self) -> None:
        """Told she was speaking to "your caregiver, the person who looks after
        you", she inverted the roles outright: announced "I am your caregiver", gave
        away her own home as theirs, and claimed their city as hers. A healthy woman
        of thirty-eight has no one who looks after her, and handed that
        contradiction the model resolved it by swapping the two of them."""
        said = render_speaker("Elena Marsh")

        assert "looks after you" not in said
        assert "never speak as if you were them" in said

    def test_a_question_about_the_caregiver_is_answered_in_the_second_person(
        self, elena: Persona, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        """Told whose question it was but not how to answer it, she answered "what do
        I do for a living?" with "I am a nurse" — she retrieved the caregiver's job
        correctly and then spoke *as* them. Knowing whose fact it is and knowing whose
        mouth it comes out of are two different things."""
        messages = build_messages(
            elena.identity,
            engine.retrieve("What do I do for a living?"),
            source,
            "What do I do for a living?",
        )
        system = messages[0].content

        assert "NOT about you" in system
        assert '"You are a nurse", never "I am a nurse"' in system

    def test_the_bridge_reaches_the_prompt(
        self, elena: Persona, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        messages = build_messages(
            elena.identity,
            engine.retrieve("What do I do for a living?"),
            source,
            "What do I do for a living?",
        )

        assert "always mean YOU, Elena Marsh" in messages[0].content


class TestPromptAssembly:
    def test_a_turn_is_system_then_history_then_the_new_message(
        self, elena: Persona, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        history = [
            Message(role=Role.USER, content="Do you have a dog?"),
            Message(role=Role.PERSONA, content="I do — Compass, a beagle."),
        ]
        trace = engine.retrieve("Why did you adopt him?")

        messages = build_messages(
            elena.identity, trace, source, "Why did you adopt him?", history=history
        )

        assert [message.role for message in messages] == [
            ChatRole.SYSTEM,
            ChatRole.USER,
            ChatRole.ASSISTANT,
            ChatRole.USER,
        ]
        assert messages[-1].content == "Why did you adopt him?"

    def test_the_persona_speaks_in_the_assistant_slot(self) -> None:
        chat = to_chat_messages([Message(role=Role.PERSONA, content="I do.")])

        assert chat[0].role is ChatRole.ASSISTANT

    def test_the_model_receives_identity_and_memory_in_one_system_message(
        self, elena: Persona, engine: RetrievalEngine, source: MemorySource
    ) -> None:
        fake = FakeLLM("I took him in after my father died.")
        trace = engine.retrieve("Why did you adopt Compass?")

        fake.generate(build_messages(elena.identity, trace, source, "Why did you adopt Compass?"))

        assert "Elena Marsh" in fake.last_system_prompt
        assert "came about because of this" in fake.last_system_prompt


class TestReasoningNeverReachesTheUser:
    """A reasoning model's scratchpad is not the persona's voice."""

    def test_an_inline_thinking_block_is_stripped(self) -> None:
        assert strip_thinking("<think>She lives in Boston.</think>I live in Boston.") == (
            "I live in Boston."
        )

    def test_text_without_thinking_is_untouched(self) -> None:
        assert strip_thinking("I live in Boston.") == "I live in Boston."

    def test_a_tag_split_across_stream_chunks_is_still_caught(self) -> None:
        from personasim.llm.ollama import _ThinkingFilter

        thinking = _ThinkingFilter()
        chunks = ["I live", " in <thi", "nk>hmm</thi", "nk>Boston."]
        visible = "".join(thinking.feed(chunk) for chunk in chunks) + thinking.flush()

        assert visible == "I live in Boston."

    def test_an_unclosed_thought_is_discarded_not_spoken(self) -> None:
        assert strip_thinking("<think>I am not sure what to say") == ""


class TestTheProviderBoundary:
    def test_no_provider_exception_escapes_the_adapter(self) -> None:
        """Callers handle a model failure without importing the thing that failed."""
        unreachable = Settings(llm_host="http://localhost:1", llm_timeout_seconds=2.0)
        client = OllamaClient(unreachable)

        with pytest.raises(LLMUnavailableError):
            client.generate([ChatMessage(role=ChatRole.USER, content="hello")])

    def test_an_unreachable_model_reports_itself_unavailable(self) -> None:
        client = OllamaClient(Settings(llm_host="http://localhost:1", llm_timeout_seconds=2.0))

        assert client.is_available() is False

    def test_an_empty_prompt_is_refused_before_the_network(self) -> None:
        with pytest.raises(LLMError):
            OllamaClient(Settings()).generate([])

    def test_unavailability_is_a_kind_of_llm_error(self) -> None:
        """Callers may catch the general case without enumerating the specific ones."""
        assert issubclass(LLMUnavailableError, LLMError)


@pytest.fixture(scope="module")
def live_client() -> OllamaClient:
    client = OllamaClient(Settings())
    if not client.is_available():
        pytest.skip(f"Ollama is not running, or {client.model} is not pulled")
    return client


@pytest.mark.live_llm
class TestAgainstARealModel:
    """The only tests that run a model. Skipped when Ollama is not there, so the
    suite stays hermetic."""

    def test_the_persona_speaks_the_causal_bridge_it_was_handed(
        self,
        live_client: OllamaClient,
        elena: Persona,
        engine: RetrievalEngine,
        source: MemorySource,
    ) -> None:
        question = "Why did you adopt Compass?"
        trace = engine.retrieve(question)

        reply = live_client.generate(build_messages(elena.identity, trace, source, question))

        assert reply
        assert "<think>" not in reply
        # The link said the adoption was caused by her father's death. She should
        # say so — that connection is data, not something the model came up with.
        assert "father" in reply.lower() or "dad" in reply.lower()

    def test_streaming_yields_the_same_kind_of_answer(
        self,
        live_client: OllamaClient,
        elena: Persona,
        engine: RetrievalEngine,
        source: MemorySource,
    ) -> None:
        question = "Where do you live?"
        trace = engine.retrieve(question)

        chunks = list(live_client.stream(build_messages(elena.identity, trace, source, question)))
        reply = "".join(chunks)

        assert reply.strip()
        assert "<think>" not in reply
        # The memory reads "I live in Boston, in a third-floor walk-up in Jamaica
        # Plain". Either half is an answer from memory; insisting on one word would
        # be testing the model's phrasing rather than its grounding.
        assert "boston" in reply.lower() or "jamaica plain" in reply.lower()
