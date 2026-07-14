"""Sprint 2A — the CDR 0.5 impairment layer.

Clinical ground truth: docs/disease_profiles/CDR05.md. Design:
docs/design/sprint1_cdr05.md. The gate's whole thesis is tested here: a recent
memory is reached only when the question cues it strongly enough, a remote memory
is always reached, and nothing — under any profile — is ever invented.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from personasim.config import Settings
from personasim.conversation import Conversation
from personasim.conversation.render import render_trace
from personasim.impairment import (
    HEALTHY,
    CognitiveProfile,
    ProfileError,
    apply_recall_gate,
    load_profile,
)
from personasim.impairment.profile import RecallGate
from personasim.impairment.voice import render_now_uncertain, voice_notes
from personasim.llm.base import ChatMessage
from personasim.llm.context_builder import build_memory_context
from personasim.models import (
    EpisodicMemory,
    Memory,
    Persona,
    RelationshipMemory,
    SemanticMemory,
)
from personasim.models.trace import (
    MemoryTrace,
    RetrievalIntent,
    RetrievedMemory,
    ScoreComponents,
)
from personasim.retrieval.source import PersonaMemorySource
from personasim.storage import Database, MemoryRepository, PersonaRepository

PROFILES = Path(__file__).resolve().parents[1] / "data" / "profiles"

CDR05 = CognitiveProfile(
    name="cdr05-test",
    recall=RecallGate(recent_window_days=90, cue_threshold=0.55, detail_threshold=0.80),
    insight=True,
)

NOW = datetime(2026, 7, 14, 17, 0, tzinfo=UTC)


class _Source:
    """The one method the gate uses, and nothing else."""

    def __init__(self, *memories: Memory) -> None:
        self._memories = {memory.id: memory for memory in memories}

    def get(self, memory_id: str) -> Memory | None:
        return self._memories.get(memory_id)


def retrieved(memory: Memory, cue: float, **overrides: object) -> RetrievedMemory:
    components = ScoreComponents(keyword_overlap=cue, importance=0.0, confidence=0.0)
    return RetrievedMemory(
        memory_id=memory.id,
        memory_type=memory.type,
        summary=memory.summary,
        score=components.total,
        components=components,
        matched_keywords=[],
        **overrides,  # type: ignore[arg-type]
    )


def trace_of(*items: RetrievedMemory) -> MemoryTrace:
    return MemoryTrace(
        query="test",
        intent=RetrievalIntent.FACTUAL_RECALL,
        retrieved=list(items),
        reason="test",
    )


def recent_episode(days_ago: int = 3) -> EpisodicMemory:
    return EpisodicMemory(
        summary="Had lunch at the harbour market",
        keywords=["lunch", "eat", "market"],
        occurred_on=(NOW - timedelta(days=days_ago)).date(),
        importance=0.4,
    )


class TestProfiles:
    def test_the_shipped_profiles_load(self) -> None:
        healthy = load_profile(PROFILES / "healthy.yaml")
        cdr05 = load_profile(PROFILES / "cdr05.yaml")

        assert not healthy.gates_recall
        assert not healthy.insight
        assert cdr05.gates_recall
        assert cdr05.insight
        assert cdr05.orientation.day_and_date == "uncertain"
        assert cdr05.speech.word_finding_every_n_turns > 0

    def test_thresholds_must_be_ordered(self) -> None:
        with pytest.raises(ValueError, match="detail_threshold"):
            RecallGate(recent_window_days=90, cue_threshold=0.8, detail_threshold=0.5)

    def test_a_missing_file_is_a_profile_error(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileError, match="cannot read"):
            load_profile(tmp_path / "nope.yaml")

    def test_a_non_mapping_file_is_a_profile_error(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- just\n- a\n- list\n")
        with pytest.raises(ProfileError, match="mapping"):
            load_profile(path)

    def test_an_unknown_field_is_a_profile_error(self, tmp_path: Path) -> None:
        path = tmp_path / "typo.yaml"
        path.write_text("name: typo\nrecal:\n  recent_window_days: 90\n")
        with pytest.raises(ProfileError, match="not a possible profile"):
            load_profile(path)


class TestRecallGate:
    """The rule, one branch at a time."""

    def test_healthy_returns_the_very_same_trace(self) -> None:
        memory = recent_episode()
        trace = trace_of(retrieved(memory, cue=0.0))

        assert apply_recall_gate(trace, HEALTHY, _Source(memory), now=NOW) is trace

    def test_a_remote_memory_survives_any_cue(self) -> None:
        wedding = EpisodicMemory(
            summary="Married Maya on a rainy afternoon in Vermont",
            keywords=["wedding", "maya"],
            occurred_on=date(2014, 9, 6),
        )
        trace = trace_of(retrieved(wedding, cue=0.0))

        gated = apply_recall_gate(trace, CDR05, _Source(wedding), now=NOW)

        assert gated.retrieved == trace.retrieved
        assert not gated.withheld

    def test_a_recent_weakly_cued_memory_is_withheld_with_its_arithmetic(self) -> None:
        memory = recent_episode(days_ago=3)
        trace = trace_of(retrieved(memory, cue=0.25))

        gated = apply_recall_gate(trace, CDR05, _Source(memory), now=NOW)

        assert gated.retrieved == []
        assert len(gated.withheld) == 1
        gone = gated.withheld[0]
        assert gone.memory_id == memory.id
        assert gone.cue_strength == 0.25
        assert gone.age_days == 3
        assert "weakly cued" in gone.reason
        assert "kept out of reach" in gated.reason

    def test_a_stronger_cue_brings_the_same_memory_back(self) -> None:
        """Gentle cueing is not simulated; it is what the mechanism does."""
        memory = recent_episode()

        weak = apply_recall_gate(
            trace_of(retrieved(memory, cue=0.25)), CDR05, _Source(memory), now=NOW
        )
        strong = apply_recall_gate(
            trace_of(retrieved(memory, cue=0.85)), CDR05, _Source(memory), now=NOW
        )

        assert weak.retrieved == []
        assert [item.memory_id for item in strong.retrieved] == [memory.id]
        assert not strong.retrieved[0].detail_withheld

    def test_the_middle_band_keeps_the_gist_and_loses_the_specifics(self) -> None:
        memory = recent_episode()
        trace = trace_of(retrieved(memory, cue=0.65))

        gated = apply_recall_gate(trace, CDR05, _Source(memory), now=NOW)

        assert len(gated.retrieved) == 1
        assert gated.retrieved[0].detail_withheld
        assert not gated.withheld

    def test_an_authored_self_fact_is_never_recent_whatever_its_created_at(self) -> None:
        """The freshly-seeded-database case: `created_at` is the seed time, and a
        persona seeded five minutes ago must not forget where she lives."""
        city = SemanticMemory(
            summary="Lives in Boston",
            keywords=["boston", "home"],
            subject="self",
            attribute="city",
            value="Boston",
            created_at=NOW - timedelta(minutes=5),
        )
        trace = trace_of(retrieved(city, cue=0.0))

        gated = apply_recall_gate(trace, CDR05, _Source(city), now=NOW)

        assert gated.retrieved == trace.retrieved
        assert not gated.withheld

    def test_a_relationship_is_never_gated(self) -> None:
        """Failure to recognise close family is a later severity, and it is not a
        parameter here — it is structurally out of the gate's reach."""
        spouse = RelationshipMemory(
            summary="Maya is my spouse",
            keywords=["maya", "spouse"],
            person_name="Maya",
            relation="spouse",
            created_at=NOW - timedelta(days=1),
        )
        trace = trace_of(retrieved(spouse, cue=0.0))

        gated = apply_recall_gate(trace, CDR05, _Source(spouse), now=NOW)

        assert gated.retrieved == trace.retrieved

    def test_a_disclosed_fact_is_gateable_by_when_it_was_heard(self) -> None:
        chicago = SemanticMemory(
            summary="My caregiver lives in Chicago",
            keywords=["live", "city", "chicago"],
            subject="my caregiver",
            attribute="city",
            value="Chicago",
            created_at=NOW - timedelta(days=2),
        )
        trace = trace_of(retrieved(chicago, cue=0.3))

        gated = apply_recall_gate(trace, CDR05, _Source(chicago), now=NOW)

        assert gated.retrieved == []
        assert [gone.memory_id for gone in gated.withheld] == [chicago.id]

    def test_an_expansion_follows_its_parent_out_of_reach(self) -> None:
        """A link-expanded memory exists to explain the one it hangs from. Its
        parent withheld, rendering it alone would speak a memory she failed to
        recall — the orphan-expansion leak, closed."""
        parent = recent_episode()
        explanation = EpisodicMemory(
            summary="Father died of a stroke that spring",
            keywords=["father", "stroke"],
            occurred_on=date(2018, 4, 2),
        )
        trace = trace_of(
            retrieved(parent, cue=0.25),
            retrieved(explanation, cue=0.0, linked_from=parent.id),
        )

        gated = apply_recall_gate(trace, CDR05, _Source(parent, explanation), now=NOW)

        assert gated.retrieved == []
        assert len(gated.withheld) == 2
        assert "connected to a memory" in gated.withheld[1].reason

    def test_an_expansion_of_a_recalled_parent_is_kept(self) -> None:
        parent = recent_episode()
        explanation = EpisodicMemory(
            summary="Father died of a stroke that spring",
            keywords=["father", "stroke"],
            occurred_on=date(2018, 4, 2),
        )
        trace = trace_of(
            retrieved(parent, cue=0.9),
            retrieved(explanation, cue=0.0, linked_from=parent.id),
        )

        gated = apply_recall_gate(trace, CDR05, _Source(parent, explanation), now=NOW)

        assert [item.memory_id for item in gated.retrieved] == [parent.id, explanation.id]

    def test_the_same_question_fails_the_same_way_twice(self) -> None:
        """Deterministic, not stochastic: reliably bad at the same things."""
        memory = recent_episode()
        trace = trace_of(retrieved(memory, cue=0.25))
        source = _Source(memory)

        first = apply_recall_gate(trace, CDR05, source, now=NOW)
        second = apply_recall_gate(trace, CDR05, source, now=NOW)

        assert first == second


class TestVoice:
    def test_healthy_says_nothing_at_all(self) -> None:
        gone = trace_of()
        assert voice_notes(HEALTHY, turn=4, user_message="a, b, c, d, and e?", trace=gone) == ""
        assert render_now_uncertain(HEALTHY) is None

    def test_word_finding_fires_on_the_profiles_cadence_and_only_then(self) -> None:
        profile = load_profile(PROFILES / "cdr05.yaml")
        cadence = profile.speech.word_finding_every_n_turns
        empty = trace_of()

        on = voice_notes(profile, turn=cadence, user_message="hello", trace=empty)
        off = voice_notes(profile, turn=cadence + 1, user_message="hello", trace=empty)

        assert "refuses to come" in on
        assert "refuses to come" not in off

    def test_a_long_question_triggers_the_attention_note(self) -> None:
        profile = load_profile(PROFILES / "cdr05.yaml")
        empty = trace_of()
        long_message = (
            "Tell me about your wedding, who was there, what the weather was like, "
            "and whether your father made a speech?"
        )

        fired = voice_notes(profile, turn=1, user_message=long_message, trace=empty)
        quiet = voice_notes(profile, turn=1, user_message="How are you?", trace=empty)

        assert "several parts" in fired
        assert quiet == ""

    def test_insight_fires_exactly_when_a_memory_was_withheld(self) -> None:
        memory = recent_episode()
        withheld = apply_recall_gate(
            trace_of(retrieved(memory, cue=0.25)), CDR05, _Source(memory), now=NOW
        )

        spoken = voice_notes(CDR05, turn=1, user_message="hello", trace=withheld)
        silent = voice_notes(CDR05, turn=1, user_message="hello", trace=trace_of())

        assert "slip away" in spoken
        assert silent == ""

    def test_the_uncertain_clock_still_tells_the_truth(self) -> None:
        profile = load_profile(PROFILES / "cdr05.yaml")
        text = render_now_uncertain(profile, when=datetime(2026, 7, 14, 17, 5))

        assert text is not None
        assert "July 2026" in text
        assert "Tuesday" in text  # the real day is in the text; her hold on it is not
        assert "could not swear" in text


class TestContextRendering:
    def test_gist_only_renders_no_date_place_or_participants(self, persona: Persona) -> None:
        source = PersonaMemorySource(persona)
        wedding = persona.memories[0]
        assert isinstance(wedding, EpisodicMemory)

        full = trace_of(retrieved(wedding, cue=0.9))
        gist = trace_of(retrieved(wedding, cue=0.9, detail_withheld=True))

        full_context = build_memory_context(full, source)
        gist_context = build_memory_context(gist, source)

        assert "2014-09-06" in full_context and "Vermont" in full_context
        assert "2014-09-06" not in gist_context
        assert "Vermont" not in gist_context.replace(wedding.summary, "")
        assert wedding.summary in gist_context
        assert "hazy" in gist_context

    def test_the_trace_renderer_shows_what_was_withheld(self) -> None:
        memory = recent_episode()
        gated = apply_recall_gate(
            trace_of(retrieved(memory, cue=0.25)), CDR05, _Source(memory), now=NOW
        )

        rendered = render_trace(gated)

        assert "[withheld]" in rendered
        assert memory.summary in rendered

    def test_a_trace_round_trips_with_its_withheld_memories(self) -> None:
        memory = recent_episode()
        gated = apply_recall_gate(
            trace_of(retrieved(memory, cue=0.25)), CDR05, _Source(memory), now=NOW
        )

        revived = MemoryTrace.model_validate(gated.model_dump(mode="json"))

        assert revived.withheld == gated.withheld

    def test_a_phase_1_trace_without_the_field_still_loads(self) -> None:
        dumped = trace_of().model_dump(mode="json")
        del dumped["withheld"]

        assert MemoryTrace.model_validate(dumped).withheld == []


class ScriptedLLM:
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


@pytest.fixture
def saved(persona: Persona, database: Database) -> Persona:
    with database.session() as db:
        PersonaRepository(db).save(persona)
    return persona


def impaired(persona: Persona, llm: ScriptedLLM, database: Database) -> Conversation:
    return Conversation(persona, llm, database, Settings(), profile=CDR05)


class TestImpairedConversation:
    """The gate in the loop, end to end — including the landmine."""

    def test_a_withheld_memory_never_becomes_an_improvised_one(
        self, saved: Persona, database: Database
    ) -> None:
        """THE landmine. She has eaten; the gate keeps it out of reach; the trace
        goes empty — and under the Phase 1 guard improvisation would have written
        a fabricated meal over a real one, permanently. `memory_is_silent` is the
        difference: found-and-withheld is not silence, so nothing may be invented.
        """
        lunch = EpisodicMemory(
            summary="Had lunch at the harbour market",
            keywords=["lunch", "eat", "market"],
            occurred_on=(datetime.now(UTC) - timedelta(days=2)).date(),
            importance=0.4,
        )
        saved.memories = [*saved.memories, lunch]
        with database.session() as db:
            MemoryRepository(db).add(saved.id, lunch)
        before = len(saved.memories)

        llm = ScriptedLLM("It's slipped my mind, I'm afraid.")
        with impaired(saved, llm, database) as chat:
            reply = chat.send("did you eat anything nice yesterday?")

        assert [gone.memory_id for gone in reply.trace.withheld] == [lunch.id]
        assert reply.trace.is_empty  # the Phase 1 guard would have improvised here
        assert not reply.trace.memory_is_silent  # the new guard is why it does not
        assert reply.formed == []
        assert len(saved.memories) == before

    def test_a_withheld_memory_is_not_spoken_but_insight_is(
        self, saved: Persona, database: Database
    ) -> None:
        lunch = EpisodicMemory(
            summary="Had lunch at the harbour market",
            keywords=["lunch", "eat", "market"],
            occurred_on=(datetime.now(UTC) - timedelta(days=2)).date(),
        )
        saved.memories = [*saved.memories, lunch]
        with database.session() as db:
            MemoryRepository(db).add(saved.id, lunch)

        llm = ScriptedLLM("It's gone, I'm afraid.")
        with impaired(saved, llm, database) as chat:
            chat.send("did you eat anything nice yesterday?")

        system = llm.prompts[0][0].content
        assert lunch.summary not in system  # withheld means withheld
        assert "slip away" in system  # and she may say she has noticed

    def test_disclose_forget_then_recall_under_a_stronger_cue(
        self, saved: Persona, database: Database
    ) -> None:
        """The whole clinical thesis in one flow: a fact disclosed is formed even
        under impairment, fails to come to mind on a vague cue, and comes back
        when the question reaches for it by name."""
        llm = ScriptedLLM("How lovely.", "Home? I couldn't say.", "You live in Chicago.")

        with impaired(saved, llm, database) as chat:
            first = chat.send("I live in Chicago.")
            assert len(first.formed) == 1  # formation is not impaired

            vague = chat.send("how are things at home these days?")
            # Her own authored "Lives in Boston" may surface — it is never gated.
            # The recently heard fact is the one that fails to come to mind.
            assert not any("Chicago" in item.summary for item in vague.trace.retrieved)
            assert any("Chicago" in gone.summary for gone in vague.trace.withheld)

            specific = chat.send("where do I live?")
            assert any("Chicago" in item.summary for item in specific.trace.retrieved)
            assert not specific.trace.withheld

        with database.session() as db:
            stored = MemoryRepository(db).list_memories(saved.id)
        assert any("Chicago" in memory.summary for memory in stored)

    def test_her_own_life_is_reachable_under_the_profile(
        self, saved: Persona, database: Database
    ) -> None:
        """Remote autobiography and authored facts survive: the same questions a
        healthy persona answers from memory, she answers from memory."""
        llm = ScriptedLLM("We married in Vermont, in the rain.")
        with impaired(saved, llm, database) as chat:
            reply = chat.send("tell me about your wedding")

        assert any("Maya" in item.summary for item in reply.trace.retrieved)
        assert not reply.trace.withheld

    def test_the_healthy_profile_is_the_phase_1_conversation(
        self, saved: Persona, database: Database
    ) -> None:
        """No wrapper is even constructed: default and explicit-healthy behave
        identically, and nothing is ever withheld."""
        llm = ScriptedLLM("Boston.")
        with Conversation(saved, llm, database, Settings(), profile=HEALTHY) as chat:
            reply = chat.send("tell me about your home")

        assert reply.trace.withheld == []
        assert any("Boston" in item.summary for item in reply.trace.retrieved)
