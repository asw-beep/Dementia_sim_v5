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
from personasim.impairment.recall import _encoding
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
from personasim.persona.seed import memory_id_for
from personasim.retrieval.source import PersonaMemorySource
from personasim.storage import Database, MemoryRepository, PersonaRepository

PROFILES = Path(__file__).resolve().parents[1] / "data" / "profiles"

CDR05 = CognitiveProfile(
    name="cdr05-test",
    recall=RecallGate(recent_window_days=90, withhold_below=0.45, gist_below=0.85, cue_weight=0.55),
    insight=True,
    working_memory_turns=5,
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


def session_encoding(memory_id: str, low: float, high: float) -> str:
    """A session in which this memory was laid down that well.

    Encoding is a hash of (session, memory) rather than a die roll, so a test that
    wants a poorly-encoded memory *searches for the session* instead of seeding an
    RNG. That the search always succeeds is itself the point: across visits, the
    same memory is sometimes reachable and sometimes not.
    """
    for index in range(100_000):
        session = f"session-{index}"
        if low <= _encoding(session, memory_id) < high:
            return session
    raise AssertionError("no session produced that encoding")


def improvised_breakfast() -> SemanticMemory:
    """What `conversation/improvise.py` writes: subject `self`, a random uuid4.

    The memory that broke the first CDR 0.5 drive. Subject `self` made it look like
    her authored life; it is nothing of the kind, and a clinical interview asks
    about it constantly.
    """
    return SemanticMemory(
        summary="For breakfast I had porridge, a boiled egg, black tea",
        keywords=["breakfast", "morning", "eat", "ate", "food", "meal"],
        subject="self",
        attribute="breakfast",
        value="porridge, a boiled egg, black tea",
        importance=0.15,
        confidence=0.5,
        created_at=NOW - timedelta(hours=4),
    )


def authored(memory: Memory) -> Memory:
    """The same memory, as the seed file would have authored it: a uuid5 id."""
    return memory.model_copy(update={"id": memory_id_for("elena-marsh", "some_key")})


class TestProfiles:
    def test_the_shipped_profiles_load(self) -> None:
        healthy = load_profile(PROFILES / "healthy.yaml")
        cdr05 = load_profile(PROFILES / "cdr05.yaml")

        assert not healthy.gates_recall
        assert not healthy.insight
        assert cdr05.gates_recall
        assert cdr05.insight
        assert cdr05.orientation.day_and_date == "uncertain"
        assert cdr05.speech.word_finding_probability > 0
        assert cdr05.working_memory_turns is not None

    def test_thresholds_must_be_ordered(self) -> None:
        with pytest.raises(ValueError, match="gist_below"):
            RecallGate(recent_window_days=90, withhold_below=0.8, gist_below=0.5)

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
    """The rule, one branch at a time.

    Encoding is a hash of (session, memory), so a test that wants a poorly-laid-down
    memory picks the *session* that laid it down poorly, via `session_encoding`.
    Nothing here seeds an RNG, because there is no RNG.
    """

    def test_healthy_returns_the_very_same_trace(self) -> None:
        memory = recent_episode()
        trace = trace_of(retrieved(memory, cue=0.0))

        assert apply_recall_gate(trace, HEALTHY, _Source(memory), now=NOW) is trace

    def test_a_remote_memory_survives_any_cue_and_any_encoding(self) -> None:
        wedding = EpisodicMemory(
            summary="Married Maya on a rainy afternoon in Vermont",
            keywords=["wedding", "maya"],
            occurred_on=date(2014, 9, 6),
        )
        trace = trace_of(retrieved(wedding, cue=0.0))
        worst = session_encoding(wedding.id, 0.0, 0.05)

        gated = apply_recall_gate(trace, CDR05, _Source(wedding), session_id=worst, now=NOW)

        assert gated.retrieved == trace.retrieved
        assert not gated.withheld

    def test_a_recent_poorly_encoded_memory_is_withheld_with_its_arithmetic(self) -> None:
        memory = recent_episode(days_ago=3)
        session = session_encoding(memory.id, 0.0, 0.1)
        trace = trace_of(retrieved(memory, cue=0.25))

        gated = apply_recall_gate(trace, CDR05, _Source(memory), session_id=session, now=NOW)

        assert gated.retrieved == []
        assert len(gated.withheld) == 1
        gone = gated.withheld[0]
        assert gone.memory_id == memory.id
        assert gone.age_days == 3
        assert "poorly laid down" in gone.reason
        assert "out of reach" in gated.reason

    def test_a_stronger_cue_brings_the_same_memory_back(self) -> None:
        """Gentle cueing is not simulated; it is what the mechanism does. Same
        memory, same session, same encoding — only the question got sharper."""
        memory = recent_episode()
        session = session_encoding(memory.id, 0.35, 0.42)

        vague = apply_recall_gate(
            trace_of(retrieved(memory, cue=0.0)),
            CDR05,
            _Source(memory),
            session_id=session,
            now=NOW,
        )
        squarely = apply_recall_gate(
            trace_of(retrieved(memory, cue=1.0)),
            CDR05,
            _Source(memory),
            session_id=session,
            now=NOW,
        )

        assert vague.retrieved == []
        assert [item.memory_id for item in squarely.retrieved] == [memory.id]

    def test_a_recent_memory_is_never_recalled_crisply_however_hard_it_is_cued(self) -> None:
        """The correction the first clinical review forced.

        A direct question — "what did you have for breakfast?" — cues at 1.0, and
        with a crisp top rung it sailed over every threshold and was answered
        perfectly, every time. A clinical interview asks nothing *but* direct
        questions, so the impairment was aimed at exactly the questions nobody asks.
        The best a recent memory now does is hedged.
        """
        memory = recent_episode()
        best = session_encoding(memory.id, 0.95, 1.0)

        gated = apply_recall_gate(
            trace_of(retrieved(memory, cue=1.0)),
            CDR05,
            _Source(memory),
            session_id=best,
            now=NOW,
        )

        [item] = gated.retrieved
        assert item.hedged
        assert not item.detail_withheld

    def test_the_middle_band_keeps_the_gist_and_loses_the_specifics(self) -> None:
        memory = recent_episode()
        session = session_encoding(memory.id, 0.5, 0.55)

        gated = apply_recall_gate(
            trace_of(retrieved(memory, cue=0.3)),
            CDR05,
            _Source(memory),
            session_id=session,
            now=NOW,
        )

        [item] = gated.retrieved
        assert item.detail_withheld
        assert item.hedged
        assert not gated.withheld

    def test_her_improvised_breakfast_is_a_recent_memory(self) -> None:
        """The bug the first drive found, pinned.

        `subject: self` made an improvised everyday detail look like her authored
        life, so the gate exempted it — and breakfast, sleep and "what have you been
        doing today?" are the most-probed recent memories in a CDR interview. She
        recalled her morning perfectly every single time. Provenance, not subject,
        is what separates her life from her Tuesday.
        """
        breakfast = improvised_breakfast()
        session = session_encoding(breakfast.id, 0.0, 0.1)

        gated = apply_recall_gate(
            trace_of(retrieved(breakfast, cue=0.4)),
            CDR05,
            _Source(breakfast),
            session_id=session,
            now=NOW,
        )

        assert gated.retrieved == []
        assert [gone.memory_id for gone in gated.withheld] == [breakfast.id]

    def test_an_authored_self_fact_is_never_gated_whatever_its_created_at(self) -> None:
        """The other side of that coin, and the freshly-seeded-database case: a
        seed's `created_at` is the seed time, and a persona seeded five minutes ago
        must not have forgotten where she lives."""
        city = authored(
            SemanticMemory(
                summary="Lives in Boston",
                keywords=["boston", "home"],
                subject="self",
                attribute="city",
                value="Boston",
                created_at=NOW - timedelta(minutes=5),
            )
        )
        worst = session_encoding(city.id, 0.0, 0.05)

        gated = apply_recall_gate(
            trace_of(retrieved(city, cue=0.0)),
            CDR05,
            _Source(city),
            session_id=worst,
            now=NOW,
        )

        assert gated.retrieved and not gated.withheld

    def test_a_relationship_is_never_gated(self) -> None:
        """Failure to recognise close family is a later severity, and it is not a
        parameter here — it is structurally out of the gate's reach."""
        spouse = authored(
            RelationshipMemory(
                summary="Maya is my spouse",
                keywords=["maya", "spouse"],
                person_name="Maya",
                relation="spouse",
                created_at=NOW - timedelta(days=1),
            )
        )
        worst = session_encoding(spouse.id, 0.0, 0.05)

        gated = apply_recall_gate(
            trace_of(retrieved(spouse, cue=0.0)),
            CDR05,
            _Source(spouse),
            session_id=worst,
            now=NOW,
        )

        assert gated.retrieved and not gated.withheld

    def test_a_disclosed_fact_is_gateable_by_when_it_was_heard(self) -> None:
        chicago = SemanticMemory(
            summary="My caregiver lives in Chicago",
            keywords=["live", "city", "chicago"],
            subject="my caregiver",
            attribute="city",
            value="Chicago",
            created_at=NOW - timedelta(days=2),
        )
        session = session_encoding(chicago.id, 0.0, 0.1)

        gated = apply_recall_gate(
            trace_of(retrieved(chicago, cue=0.3)),
            CDR05,
            _Source(chicago),
            session_id=session,
            now=NOW,
        )

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
        session = session_encoding(parent.id, 0.0, 0.1)
        trace = trace_of(
            retrieved(parent, cue=0.25),
            retrieved(explanation, cue=0.0, linked_from=parent.id),
        )

        gated = apply_recall_gate(
            trace, CDR05, _Source(parent, explanation), session_id=session, now=NOW
        )

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
        session = session_encoding(parent.id, 0.9, 1.0)
        trace = trace_of(
            retrieved(parent, cue=1.0),
            retrieved(explanation, cue=0.0, linked_from=parent.id),
        )

        gated = apply_recall_gate(
            trace, CDR05, _Source(parent, explanation), session_id=session, now=NOW
        )

        assert [item.memory_id for item in gated.retrieved] == [parent.id, explanation.id]

    def test_a_session_replays_identically(self) -> None:
        """Hashed, not rolled. She is unreliable the way a person is — but a
        replayed session fails exactly as it failed the first time, which is what a
        clinical validation needs and a `random.random()` could never give."""
        memory = recent_episode()
        trace = trace_of(retrieved(memory, cue=0.25))
        source = _Source(memory)

        first = apply_recall_gate(trace, CDR05, source, session_id="visit-1", now=NOW)
        again = apply_recall_gate(trace, CDR05, source, session_id="visit-1", now=NOW)

        assert first == again

    def test_but_a_later_visit_may_go_differently(self) -> None:
        """Which is the whole clinical texture: some days it comes, some days it
        does not, and a cue helps."""
        memory = recent_episode()
        trace = trace_of(retrieved(memory, cue=0.3))
        source = _Source(memory)

        fates = {
            bool(apply_recall_gate(trace, CDR05, source, session_id=f"visit-{n}", now=NOW).withheld)
            for n in range(40)
        }

        assert fates == {True, False}


class TestClinicalRates:
    """The behaviour a reviewer measures, rather than the branch a coder reads.

    Rates are asserted over many memories in one session — which is exactly how a
    clinician sees them: not "will *this* memory fail" but "how often does she".
    """

    def _fates(self, cue: float, count: int = 400) -> dict[str, int]:
        tally = {"withheld": 0, "gist": 0, "hedged": 0}
        for index in range(count):
            memory = recent_episode()
            gated = apply_recall_gate(
                trace_of(retrieved(memory, cue=cue)),
                CDR05,
                _Source(memory),
                session_id=f"s{index}",
                now=NOW,
            )
            if gated.withheld:
                tally["withheld"] += 1
            elif gated.retrieved[0].detail_withheld:
                tally["gist"] += 1
            else:
                tally["hedged"] += 1
        return tally

    def test_a_direct_question_loses_a_detail_about_a_quarter_of_the_time(self) -> None:
        """The reviewer's target: 20-30% of recent events lose a detail, and none
        is answered crisply."""
        tally = self._fates(cue=1.0)

        assert tally["withheld"] == 0  # a direct question is always *answered*
        assert 0.20 <= tally["gist"] / 400 <= 0.35
        assert tally["hedged"] > 0

    def test_a_vague_question_often_draws_a_blank(self) -> None:
        tally = self._fates(cue=0.0)

        assert 0.35 <= tally["withheld"] / 400 <= 0.55
        assert tally["gist"] > 0

    def test_remote_memory_stays_above_95_percent(self) -> None:
        """>95% accuracy on autobiography, per the acceptance criteria. It is 100%,
        because remote memory is not gated at all — a structural guarantee, not a
        rate that could drift."""
        intact = 0
        for index in range(200):
            wedding = EpisodicMemory(
                summary="Married Maya in Vermont",
                keywords=["wedding"],
                occurred_on=date(2014, 9, 6),
            )
            gated = apply_recall_gate(
                trace_of(retrieved(wedding, cue=0.0)),
                CDR05,
                _Source(wedding),
                session_id=f"s{index}",
                now=NOW,
            )
            if gated.retrieved and not gated.retrieved[0].hedged and not gated.withheld:
                intact += 1

        assert intact == 200


class TestVoice:
    def test_healthy_says_nothing_at_all(self) -> None:
        gone = trace_of()
        assert voice_notes(HEALTHY, turn=4, user_message="a, b, c, d, and e?", trace=gone) == ""
        assert render_now_uncertain(HEALTHY) is None

    def test_word_finding_fires_on_some_turns_and_not_others(self) -> None:
        """Not a metronome. Every 4th turn read as one, and — worse — the old soft
        note produced *zero* hesitation in twenty turns of real conversation, which
        is why the fragment is now imperative rather than suggestive."""
        profile = load_profile(PROFILES / "cdr05.yaml")
        empty = trace_of()

        fired = [
            "will not come to you"
            in voice_notes(
                profile, turn=turn, user_message="how are you?", trace=empty, session_id="s"
            )
            for turn in range(60)
        ]

        assert any(fired)
        assert not all(fired)
        assert sum(fired) / len(fired) < 0.35  # intermittent, never aphasic

    def test_a_long_question_can_overrun_her_but_a_short_one_never_does(self) -> None:
        profile = load_profile(PROFILES / "cdr05.yaml")
        empty = trace_of()
        long_message = (
            "Tell me about your wedding, who was there, what the weather was like, "
            "and whether your father made a speech?"
        )

        overrun = [
            "got away from you"
            in voice_notes(
                profile, turn=turn, user_message=long_message, trace=empty, session_id="s"
            )
            for turn in range(40)
        ]
        short = [
            voice_notes(
                profile, turn=turn, user_message="How are you?", trace=empty, session_id="s"
            )
            for turn in range(40)
        ]

        assert any(overrun)  # sometimes she loses the thread
        assert not all(overrun)  # usually she copes — this is CDR 0.5, not CDR 2
        assert all("got away from you" not in note for note in short)

    def test_insight_fires_exactly_when_a_memory_was_withheld(self) -> None:
        memory = recent_episode()
        session = session_encoding(memory.id, 0.0, 0.1)
        withheld = apply_recall_gate(
            trace_of(retrieved(memory, cue=0.0)),
            CDR05,
            _Source(memory),
            session_id=session,
            now=NOW,
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

    def test_a_session_replays_its_speech_identically(self) -> None:
        profile = load_profile(PROFILES / "cdr05.yaml")
        empty = trace_of()

        first = voice_notes(
            profile, turn=7, user_message="and how have you been?", trace=empty, session_id="v1"
        )
        again = voice_notes(
            profile, turn=7, user_message="and how have you been?", trace=empty, session_id="v1"
        )

        assert first == again


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
        assert "will not come" in gist_context

    def test_a_hedged_memory_keeps_its_content_but_loses_its_confidence(
        self, persona: Persona
    ) -> None:
        """The rung the first review was missing. She says the right thing; she
        just does not say it like a woman reading off a card."""
        source = PersonaMemorySource(persona)
        wedding = persona.memories[0]

        hedged = build_memory_context(trace_of(retrieved(wedding, cue=0.9, hedged=True)), source)

        assert "Vermont" in hedged  # the content is all there
        assert "half-sure" in hedged  # the certainty is not

    def test_the_trace_renderer_shows_what_was_withheld(self) -> None:
        memory = recent_episode()
        session = session_encoding(memory.id, 0.0, 0.1)
        gated = apply_recall_gate(
            trace_of(retrieved(memory, cue=0.0)),
            CDR05,
            _Source(memory),
            session_id=session,
            now=NOW,
        )

        rendered = render_trace(gated)

        assert "[withheld]" in rendered
        assert memory.summary in rendered

    def test_a_trace_round_trips_with_its_withheld_memories(self) -> None:
        memory = recent_episode()
        session = session_encoding(memory.id, 0.0, 0.1)
        gated = apply_recall_gate(
            trace_of(retrieved(memory, cue=0.0)),
            CDR05,
            _Source(memory),
            session_id=session,
            now=NOW,
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

        # Each session lays the memory down differently, so the question is asked
        # across many of them: in every session where the gate takes her lunch out
        # of reach, nothing may be invented in its place.
        blanked = 0
        for _ in range(25):
            llm = ScriptedLLM("It's slipped my mind, I'm afraid.")
            with impaired(saved, llm, database) as chat:
                reply = chat.send("did you eat anything nice yesterday?")

            assert reply.formed == []  # never, in any session
            assert len(saved.memories) == before

            if reply.trace.withheld:
                assert [g.memory_id for g in reply.trace.withheld] == [lunch.id]
                if reply.trace.is_empty:
                    # The Phase 1 guard would have improvised here — the trace *is*
                    # empty. `memory_is_silent` is why it does not: found-and-withheld
                    # is not silence, and a fabricated lunch would have been written
                    # over a real one, permanently.
                    assert not reply.trace.memory_is_silent
                    blanked += 1

        assert blanked, "the gate never withheld the lunch — the landmine went untested"

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

        # Which sessions withhold it depends on how well it was laid down in each,
        # so this asks across several and checks the ones that did.
        checked = 0
        for _ in range(25):
            llm = ScriptedLLM("It's gone, I'm afraid.")
            with impaired(saved, llm, database) as chat:
                reply = chat.send("did you eat anything nice yesterday?")

            system = llm.prompts[0][0].content
            if reply.trace.withheld:
                assert lunch.summary not in system  # withheld means withheld
                assert "slip away" in system  # and she says she has noticed
                checked += 1

        assert checked, "the gate never withheld the lunch"

    def test_a_squarely_cued_disclosure_always_comes_back_but_never_crisply(
        self, saved: Persona, database: Database
    ) -> None:
        """Two guarantees that hold whatever the encoding, and they are the shape of
        very mild impairment.

        A question that aims straight at a memory always reaches it — `cue_weight`
        alone clears `withhold_below`, so gentle cueing is not a coin toss. And a
        recent memory is *never* recalled crisply, however squarely it was asked
        for: that is the rung whose absence made the first drive read as healthy.
        """
        llm = ScriptedLLM("How lovely.", "Chicago, I think.")

        with impaired(saved, llm, database) as chat:
            told = chat.send("I live in Chicago.")
            assert len(told.formed) == 1  # formation is not impaired

            asked = chat.send("where do I live?")

        [chicago] = [m for m in asked.trace.retrieved if "Chicago" in m.summary]
        assert not asked.trace.withheld  # a square cue always reaches it
        assert chicago.hedged  # but she does not trust it the way she trusts her own name

        with database.session() as db:
            stored = MemoryRepository(db).list_memories(saved.id)
        assert any("Chicago" in memory.summary for memory in stored)

    def test_her_improvised_breakfast_is_gateable_end_to_end(
        self, saved: Persona, database: Database
    ) -> None:
        """The bug the review found, at the level it was found: she is asked about
        her morning, and her morning is a recent memory like any other — hedged at
        best, sometimes only an outline. Never recited."""
        llm = ScriptedLLM("Porridge, I think. And tea.", "Porridge... and tea, I believe.")

        with impaired(saved, llm, database) as chat:
            first = chat.send("What did you have for breakfast this morning?")
            assert len(first.formed) == 1  # improvised once, written down

            again = chat.send("What did you have for breakfast this morning?")

        # Formed as an improvised memory, and gateable from the very next turn: it
        # is either hedged, in outline, or out of reach — never crisply recited.
        recalled = [m for m in again.trace.retrieved if m.memory_id == first.formed[0].id]
        if recalled:
            assert recalled[0].hedged
        else:
            assert any(g.memory_id == first.formed[0].id for g in again.trace.withheld)

    def test_a_short_working_memory_makes_delayed_recall_mean_something(
        self, saved: Persona, database: Database
    ) -> None:
        """Three words, then ten minutes of other conversation.

        Under the healthy 12-turn window the words sat *verbatim in the prompt* six
        turns later and she read them straight back — a perfect score on the most
        diagnostic question in the CDR interview, produced by a transcript rather
        than by memory. The window is what makes the probe real.
        """
        llm = ScriptedLLM("I'll remember them.")
        with impaired(saved, llm, database) as chat:
            chat.send("Remember these three words: apple, train, blue.")
            for filler in (
                "Tell me about your wedding.",
                "And your father?",
                "Your brother?",
                "What do you make of the weather?",
                "Do you still draw maps?",
            ):
                chat.send(filler)

            probe = chat.send("What were those three words?")

        prompt = llm.prompts[-1]
        transcript = " ".join(message.content for message in prompt)
        assert "apple" not in transcript.lower()  # genuinely gone, not merely hedged
        assert probe.formed == []  # and nothing was invented to fill the gap

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
