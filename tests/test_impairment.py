"""The CDR impairment layer — Sprint 2A (CDR 0.5) and Sprint 2B (CDR 1).

Clinical ground truth: docs/disease_profiles/CDR05.md and CDR1.md. Design:
docs/design/sprint1_cdr05.md and sprint2_cdr1.md. The gate's whole thesis is tested
here: a recent memory is reached only when the question cues it strongly enough, a
remote memory is always reached, and nothing — under any profile — is ever invented.
CDR 1 is the same mechanisms turned up a rung, plus one new orientation level
(time "mistaken", not merely "uncertain"); the tests assert that relationship.
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
from personasim.impairment.comprehension import retain_question
from personasim.impairment.disfluency import inject_word_finding
from personasim.impairment.hold import ELISION, fade_transcript
from personasim.impairment.orientation import apply_place_gate
from personasim.impairment.profile import Orientation, RecallGate, WorkingMemoryHold
from personasim.impairment.recall import _encoding
from personasim.impairment.voice import render_now_impaired, voice_notes
from personasim.llm.base import ChatMessage
from personasim.llm.context_builder import build_memory_context
from personasim.models import (
    EpisodicMemory,
    Memory,
    Persona,
    RelationshipMemory,
    SemanticMemory,
)
from personasim.models.conversation import Message, Role, Turn
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
    hold=WorkingMemoryHold(crisp_turns=2, fade_turns=8),
)

CDR1 = CognitiveProfile(
    name="cdr1-test",
    recall=RecallGate(
        recent_window_days=180, withhold_below=0.65, gist_below=1.10, cue_weight=0.45
    ),
    insight=True,
    hold=WorkingMemoryHold(crisp_turns=1, fade_turns=5),
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
        assert cdr05.hold.fades
        assert not healthy.hold.fades
        assert healthy.hold.capacity is None
        # Place orientation is confident until CDR 2, at every earlier severity.
        assert healthy.orientation.place == "confident"
        assert cdr05.orientation.place == "confident"

    def test_cdr1_is_a_rung_past_cdr05(self) -> None:
        # Severity is data: CDR 1 is the same mechanisms turned up. Every knob that
        # governs how impaired she is moves in the more-impaired direction, and the
        # one qualitative jump — time orientation from "uncertain" to "mistaken" —
        # is a new level, not a new code path.
        cdr05 = load_profile(PROFILES / "cdr05.yaml")
        cdr1 = load_profile(PROFILES / "cdr1.yaml")

        assert cdr1.gates_recall
        assert cdr1.is_impaired
        assert cdr1.orientation.day_and_date == "mistaken"
        # Recent memory: a wider window catches more, and the ladder sits higher.
        assert cdr1.recall.recent_window_days > cdr05.recall.recent_window_days
        assert cdr1.recall.withhold_below > cdr05.recall.withhold_below
        assert cdr1.recall.gist_below > cdr05.recall.gist_below
        # Word-finding is "often" now, not "occasionally".
        assert cdr1.speech.word_finding_probability > cdr05.speech.word_finding_probability
        # Working memory frays sooner: the crisp span narrows, the whole window shrinks.
        assert cdr1.hold.crisp_turns < cdr05.hold.crisp_turns
        assert (cdr1.hold.capacity or 0) < (cdr05.hold.capacity or 0)

    def test_cdr2_is_a_rung_past_cdr1(self) -> None:
        # The same discipline again: CDR 2 is CDR 1's mechanisms turned up, plus the
        # one qualitative jump — orientation to *place* (a new axis, not a new code
        # path). Every knob moves in the more-impaired direction.
        cdr1 = load_profile(PROFILES / "cdr1.yaml")
        cdr2 = load_profile(PROFILES / "cdr2.yaml")

        assert cdr2.gates_recall
        assert cdr2.is_impaired
        # The CDR 2 jump: place orientation degrades, time was already mistaken.
        assert cdr2.orientation.place == "hazy"
        assert cdr1.orientation.place == "confident"
        assert cdr2.orientation.day_and_date == "mistaken"
        # Recent memory: wider window, higher ladder, weaker cueing.
        assert cdr2.recall.recent_window_days > cdr1.recall.recent_window_days
        assert cdr2.recall.withhold_below > cdr1.recall.withhold_below
        assert cdr2.recall.gist_below > cdr1.recall.gist_below
        assert cdr2.recall.cue_weight < cdr1.recall.cue_weight
        # No recent memory ever comes back crisp: gist_below sits above the reach
        # ceiling (encoding < 1.0 plus cue_weight times cue, cue <= 1.0).
        assert cdr2.recall.gist_below > 1.0 + cdr2.recall.cue_weight
        # Word-finding more frequent; the working-memory window collapses further.
        assert cdr2.speech.word_finding_probability > cdr1.speech.word_finding_probability
        assert cdr2.speech.long_question_probability > cdr1.speech.long_question_probability
        assert cdr2.speech.long_question_clauses < cdr1.speech.long_question_clauses
        assert (cdr2.hold.capacity or 0) < (cdr1.hold.capacity or 0)
        # Insight is largely lost at CDR 2, where CDR 1 preserved it.
        assert cdr1.insight
        assert not cdr2.insight

    def test_cdr3_is_a_rung_past_cdr2(self) -> None:
        # The last rung, same discipline: CDR 2's mechanisms turned up, plus the
        # qualitative jumps — place from "hazy" to "lost", person from "confident"
        # to "unfamiliar" (a new axis, not a new code path), and simplified speech.
        cdr2 = load_profile(PROFILES / "cdr2.yaml")
        cdr3 = load_profile(PROFILES / "cdr3.yaml")

        assert cdr3.gates_recall
        assert cdr3.is_impaired
        # The CDR 3 jumps: place is lost, person no longer recognised, speech simple.
        assert cdr3.orientation.place == "lost"
        assert cdr2.orientation.place == "hazy"
        assert cdr3.orientation.person == "unfamiliar"
        assert cdr2.orientation.person == "confident"
        assert cdr3.speech.simplified_language
        assert not cdr2.speech.simplified_language
        assert cdr3.orientation.day_and_date == "mistaken"
        # Recent memory: wider window, higher ladder, weaker cueing still.
        assert cdr3.recall.recent_window_days > cdr2.recall.recent_window_days
        assert cdr3.recall.withhold_below > cdr2.recall.withhold_below
        assert cdr3.recall.gist_below > cdr2.recall.gist_below
        assert cdr3.recall.cue_weight < cdr2.recall.cue_weight
        # Only fragments remain: withhold_below sits above the encoding ceiling
        # (encoding < 1.0), so an uncued recent memory is *always* withheld.
        assert cdr3.recall.withhold_below > 1.0
        # Word-finding more frequent; overrun more certain; the window collapses to
        # its floor — even the current exchange now fades (crisp_turns 0).
        assert cdr3.speech.word_finding_probability > cdr2.speech.word_finding_probability
        assert cdr3.speech.long_question_probability > cdr2.speech.long_question_probability
        assert cdr3.hold.crisp_turns == 0
        assert (cdr3.hold.capacity or 0) < (cdr2.hold.capacity or 0)
        # Insight was already lost at CDR 2 and stays lost.
        assert not cdr3.insight

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
            # A *deterministic* id per sample, not a fresh uuid4: encoding is hashed
            # from (session, memory id), so a random id makes the measured rate drift
            # run to run and flake against the band. Reproducible-by-construction is
            # the whole point of the gate; the rate test must honour it too.
            memory = recent_episode().model_copy(
                update={"id": memory_id_for("rate", f"{cue}-{index}")}
            )
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

    def test_cdr1_blocks_recent_recall_harder_than_cdr05(self) -> None:
        """The roadmap's 2B line, measured: at CDR 1 a recent memory is withheld or
        reduced to gist more often than at CDR 0.5, across the same questions. Same
        gate, higher rungs — retrieval more often blocked, without a new branch."""

        def blocked_rate(profile: CognitiveProfile, cue: float, count: int = 400) -> float:
            reduced = 0
            for index in range(count):
                memory = recent_episode()
                gated = apply_recall_gate(
                    trace_of(retrieved(memory, cue=cue)),
                    profile,
                    _Source(memory),
                    session_id=f"s{index}",
                    now=NOW,
                )
                # "Blocked" = did not come back whole: withheld outright, or gist-only.
                if gated.withheld or (gated.retrieved and gated.retrieved[0].detail_withheld):
                    reduced += 1
            return reduced / count

        # A vague question, and a direct one: CDR 1 is worse on both.
        assert blocked_rate(CDR1, cue=0.0) > blocked_rate(CDR05, cue=0.0)
        assert blocked_rate(CDR1, cue=1.0) > blocked_rate(CDR05, cue=1.0)

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
        assert voice_notes(HEALTHY, trace=trace_of()) == ""
        assert render_now_impaired(HEALTHY) is None

    def test_word_finding_is_no_longer_a_prompt_fragment(self) -> None:
        """It moved out of the seam entirely. The model would not perform it, so the
        prompt no longer asks — `impairment.disfluency` performs it on the output."""
        profile = load_profile(PROFILES / "cdr05.yaml")
        assert "will not come to you" not in voice_notes(profile, trace=trace_of())

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

        spoken = voice_notes(CDR05, trace=withheld)
        silent = voice_notes(CDR05, trace=trace_of())

        assert "slip away" in spoken
        assert silent == ""

    def test_a_faded_turn_warns_her_not_to_fill_the_gaps(self) -> None:
        # The lightweight intrusion guard: only when the transcript actually faded is
        # she told the '…' gaps are gone and not to guess across them. This is the
        # counter to "apple, slice, lemon" — the second two lifted from a later turn.
        empty = trace_of()
        with_fade = voice_notes(CDR1, trace=empty, faded=True)
        without = voice_notes(CDR1, trace=empty, faded=False)

        assert "gone from me" in with_fade
        assert "gone from me" not in without
        # Healthy never fades, so the guard cannot appear even if `faded` is forced.
        assert "gone from me" not in voice_notes(HEALTHY, trace=empty, faded=True)

    def test_the_uncertain_clock_still_tells_the_truth(self) -> None:
        profile = load_profile(PROFILES / "cdr05.yaml")
        text = render_now_impaired(profile, when=datetime(2026, 7, 14, 17, 5))

        assert text is not None
        assert "July 2026" in text
        assert "Tuesday" in text  # the real day is in the text; her hold on it is not
        assert "could not swear" in text

    def test_the_mistaken_clock_withholds_the_weekday_it_can_no_longer_hold(self) -> None:
        # CDR 1: the exact day is *not* handed to her, so she cannot read it off — she
        # is disoriented in time, not fed a false fact. The frame she is given is real.
        profile = load_profile(PROFILES / "cdr1.yaml")
        text = render_now_impaired(profile, when=datetime(2026, 7, 14, 17, 5))

        assert text is not None
        assert "July 2026" in text  # the frame is still true
        assert "Tuesday" not in text  # but the weekday is withheld — she has lost it
        assert "come loose" in text

    def test_the_hazy_place_withholds_where_she_is_and_the_hour(self) -> None:
        # CDR 2: the new axis. Place and the time of day are withheld from the frame
        # too, so she cannot recite them — she is disoriented in space and the part of
        # the day, not fed a false location. Month, year and person stay confident.
        profile = load_profile(PROFILES / "cdr2.yaml")
        text = render_now_impaired(profile, when=datetime(2026, 7, 14, 17, 5))

        assert text is not None
        assert "July 2026" in text  # month and year still hold
        assert "5:05" not in text  # the exact time is withheld — she cannot read it off
        assert "Tuesday" not in text  # weekday still withheld (time is still mistaken)
        assert "setting has begun to slip" in text  # the place haze is present
        assert "morning for afternoon" in text  # and the part of the day runs together

    def test_a_hazy_place_alone_still_renders_a_frame(self) -> None:
        # Composable: place degrades independently of time. A profile with a hazy
        # place but a confident clock still produces a frame (it is not None), and the
        # place haze appears without any time-degradation prose.
        profile = CognitiveProfile(name="place-only", orientation=Orientation(place="hazy"))
        text = render_now_impaired(profile, when=datetime(2026, 7, 14, 17, 5))

        assert text is not None
        assert "setting has begun to slip" in text
        assert "time has come loose" not in text  # no mistaken-time middle
        assert "could not swear" not in text  # no uncertain-time middle

    def test_the_lost_place_withholds_month_year_and_where_she_is(self) -> None:
        # CDR 3: orientation to her own person only. The month, year and place are all
        # withheld from the frame — she is never handed them — so nothing false is put
        # in her mouth. What the frame still asserts is who she herself is.
        profile = load_profile(PROFILES / "cdr3.yaml")
        text = render_now_impaired(profile, when=datetime(2026, 7, 14, 17, 5))

        assert text is not None
        assert "July 2026" not in text  # month and year are gone now
        assert "5:05" not in text  # the time is withheld
        assert "Tuesday" not in text  # weekday still withheld
        assert "no longer know where you are" in text  # place is lost
        assert "who you are — your name" in text  # her own person still holds

    def test_the_unfamiliar_person_withholds_who_is_speaking_but_keeps_the_split(
        self,
    ) -> None:
        # The last axis. Who the speaker is is withheld, but two lines are not: she
        # always knows the speaker is someone else (the I/you split), and she must
        # never invent an identity for them — unfamiliarity, never misidentification.
        profile = load_profile(PROFILES / "cdr3.yaml")
        text = render_now_impaired(profile, when=datetime(2026, 7, 14, 17, 5))

        assert text is not None
        assert "who you are speaking with does not always come to you" in text
        assert "they are not you" in text  # the I/you split is preserved
        assert "Never decide they are someone in particular" in text  # no misID

    def test_an_unfamiliar_person_alone_still_recognises_the_frame(self) -> None:
        # Composable: person degrades independently. A confident clock and place with
        # only person unfamiliar still renders a frame, with the recognition fragment
        # and none of the time/place-degradation prose.
        profile = CognitiveProfile(name="person-only", orientation=Orientation(person="unfamiliar"))
        text = render_now_impaired(profile, when=datetime(2026, 7, 14, 17, 5))

        assert text is not None
        assert "does not always come to you" in text
        assert "no longer know where you are" not in text  # place still confident
        assert "time has come loose" not in text  # time still confident
        # The full frame no longer claims she knows who she is speaking with.
        assert "who you are speaking with — with ordinary" not in text

    def test_simplified_speech_is_a_voice_note_only_at_cdr3(self) -> None:
        # The register lives in `voice_notes`, not the clock, and fires every turn
        # (it is a manner, not a moment). It is absent at every earlier severity.
        cdr3 = load_profile(PROFILES / "cdr3.yaml")
        assert "Short sentences" in voice_notes(cdr3, trace=trace_of())
        assert "Short sentences" not in voice_notes(CDR1, trace=trace_of())
        assert "Short sentences" not in voice_notes(HEALTHY, trace=trace_of())


def _residence() -> SemanticMemory:
    """Her current home — the memory the drive showed CDR 3 reciting as its present
    location. Authored (uuid5), so the recall gate never touches it."""
    return authored(
        SemanticMemory(
            summary="I live in Boston, in a third-floor walk-up in Jamaica Plain",
            keywords=["boston", "home", "jamaica plain", "live", "city"],
            subject="self",
            attribute="city",
            value="Boston",
        )
    )


def _hometown() -> SemanticMemory:
    """Her childhood home — remote memory, preserved at every stage. The place gate
    must never touch it, or 'where did you grow up?' would fail at CDR 3."""
    return authored(
        SemanticMemory(
            summary="I grew up in Rutland, Vermont",
            keywords=["rutland", "vermont", "hometown", "grew"],
            subject="self",
            attribute="hometown",
            value="Rutland, Vermont",
        )
    )


class TestPlaceGate:
    """Orientation to place, degraded at the retrieval seam — the fix for the CDR 3
    drive, where the residence memory was recited as a present location."""

    def test_confident_place_leaves_the_residence_untouched(self) -> None:
        # Healthy through CDR 1: place is confident, so the gate is a no-op and
        # "where do you live?" answers exactly as Phase 1 did.
        home = _residence()
        for profile in (HEALTHY, CDR1, load_profile(PROFILES / "cdr1.yaml")):
            gated = apply_place_gate(trace_of(retrieved(home, cue=1.0)), profile, _Source(home))
            assert gated.retrieved and not gated.retrieved[0].hedged
            assert not gated.withheld

    def test_hazy_place_hedges_the_residence(self) -> None:
        # CDR 2: she still believes she is home, but cannot be sure — hedged, not gone.
        home = _residence()
        profile = load_profile(PROFILES / "cdr2.yaml")
        gated = apply_place_gate(trace_of(retrieved(home, cue=1.0)), profile, _Source(home))

        assert gated.retrieved and gated.retrieved[0].hedged
        assert not gated.withheld
        assert "hedged" in gated.reason

    def test_lost_place_withholds_the_residence(self) -> None:
        # CDR 3: she cannot place herself at all. The residence is withheld — moved to
        # the trace, explained, never silently dropped — so she says she does not know
        # rather than reciting her address as her present location.
        home = _residence()
        profile = load_profile(PROFILES / "cdr3.yaml")
        gated = apply_place_gate(trace_of(retrieved(home, cue=1.0)), profile, _Source(home))

        assert gated.retrieved == []
        assert [w.memory_id for w in gated.withheld] == [home.id]
        assert "disoriented to place" in gated.withheld[0].reason
        # Withheld, not silent: no path to improvisation filling the gap.
        assert not gated.memory_is_silent

    def test_an_expansion_that_names_the_place_goes_with_its_parent(self) -> None:
        # The CDR 3 drive's actual leak: retrieval pulled in the dated "I moved to a
        # third-floor walk-up in Jamaica Plain" as an expansion of the residence, and
        # it named the place just as squarely. When the residence is withheld, its
        # expansions must go too — the recall gate's rule, reused.
        home = _residence()
        moved = EpisodicMemory(
            summary="I moved to a third-floor walk-up in Jamaica Plain with two boxes of maps",
            keywords=["moved", "jamaica plain"],
            occurred_on=date(1986, 9, 1),
        ).model_copy(update={"id": memory_id_for("elena-marsh", "moved_in")})
        profile = load_profile(PROFILES / "cdr3.yaml")
        trace = trace_of(
            retrieved(home, cue=1.0),
            retrieved(moved, cue=0.0, linked_from=home.id),
        )
        gated = apply_place_gate(trace, profile, _Source(home, moved))

        assert gated.retrieved == []  # both the residence and its place-naming expansion
        assert {w.memory_id for w in gated.withheld} == {home.id, moved.id}

    def test_the_childhood_hometown_is_never_touched(self) -> None:
        # Remote memory is preserved at every stage: "where did you grow up?" must
        # still surface Rutland even at CDR 3, where the *current* residence is gone.
        town = _hometown()
        profile = load_profile(PROFILES / "cdr3.yaml")
        gated = apply_place_gate(trace_of(retrieved(town, cue=1.0)), profile, _Source(town))

        assert gated.retrieved and not gated.retrieved[0].hedged
        assert not gated.withheld


class TestComprehension:
    # A five-part question: three scene-setting clauses, then the two actual
    # questions at the end — exactly where working memory keeps them.
    LONG = (
        "When you moved to Boston, and you were at the survey firm, and Henry was "
        "with you, did the city change much, and did you ever think of leaving?"
    )
    # `long_question_clauses` is 2 in cdr1.yaml, so the tail she keeps is the last two.
    TAIL = "did the city change much, and did you ever think of leaving?"

    def test_healthy_hears_the_whole_question(self) -> None:
        heard, note = retain_question(self.LONG, HEALTHY, session_id="s", turn=1)
        assert heard == self.LONG
        assert note is None

    def test_a_short_question_is_never_trimmed(self) -> None:
        profile = load_profile(PROFILES / "cdr1.yaml")
        for turn in range(40):
            heard, note = retain_question("How are you today?", profile, session_id="s", turn=turn)
            assert heard == "How are you today?"
            assert note is None

    def test_a_long_question_sometimes_overruns_and_keeps_only_its_tail(self) -> None:
        profile = load_profile(PROFILES / "cdr1.yaml")
        results = [retain_question(self.LONG, profile, session_id="s", turn=t) for t in range(40)]
        trimmed = [(h, n) for (h, n) in results if n is not None]
        coped = [(h, n) for (h, n) in results if n is None]

        assert trimmed  # sometimes she loses the thread
        assert coped  # usually she copes — this is CDR 1, not a total collapse

        heard, note = trimmed[0]
        assert heard == self.TAIL  # only the last two parts survive…
        assert heard in self.LONG  # …verbatim — a suffix of what was asked, never invented
        assert note is not None and "kept only the last 2" in note

    def test_the_overrun_is_deterministic_per_session_and_turn(self) -> None:
        profile = load_profile(PROFILES / "cdr1.yaml")
        first = retain_question(self.LONG, profile, session_id="v1", turn=7)
        again = retain_question(self.LONG, profile, session_id="v1", turn=7)
        assert first == again

    def test_a_trailing_tag_is_not_a_second_part(self) -> None:
        # "Do you have a dog, by the way?" is one question with a courtesy tacked on,
        # not two parts. The tag must not tip a simple question into an overrun — the
        # CDR 2 drive had it trim to "by the way" and answer a non-sequitur.
        profile = load_profile(PROFILES / "cdr2.yaml")  # long_question_clauses == 1
        for turn in range(40):
            heard, note = retain_question(
                "Do you have a dog, by the way?", profile, session_id="s", turn=turn
            )
            assert heard == "Do you have a dog, by the way?"
            assert note is None

    def test_an_overrun_drops_a_trailing_tag_and_keeps_the_real_question(self) -> None:
        # A genuine multi-part question with a tag on the end: the tag is dropped, and
        # what survives is the last *substantive* clause, not the courtesy.
        profile = load_profile(PROFILES / "cdr2.yaml")  # keeps the last 1
        message = "You've been getting a lot of rest, and do you have a dog, by the way?"
        results = [retain_question(message, profile, session_id="s", turn=t) for t in range(40)]
        trimmed = [(h, n) for (h, n) in results if n is not None]

        assert trimmed  # a real two-part question overruns at CDR 2
        heard, note = trimmed[0]
        assert heard == "do you have a dog"  # the tag is gone, the question is kept
        assert "by the way" not in heard
        assert note is not None and "2-part question overran" in note


def _exchange(user: str, persona: str = "Mm, yes.") -> Turn:
    return Turn(
        user_message=Message(role=Role.USER, content=user),
        persona_message=Message(role=Role.PERSONA, content=persona),
        trace=trace_of(),
    )


def _survivors(text: str, words: Sequence[str]) -> int:
    """How many of `words` are still standing in a possibly-faded message."""
    tokens = {token.strip(",.;:!?").lower() for token in text.split()}
    return sum(1 for word in words if word.lower() in tokens)


WORDS = ("apple", "train", "blue")


def _window_with_old(first: str, age: int) -> list[Turn]:
    """A window whose oldest exchange is `first`, with `age` newer exchanges in
    front of it — so `first` sits at exactly `age` turns back."""
    return [_exchange(first), *(_exchange("we talked of other things") for _ in range(age))]


def _fade_old(first: str, age: int, session_id: str) -> tuple[str, str | None]:
    """Fade a window whose oldest turn is `first`, `age` turns back. Return that
    turn's (faded user text, trace note)."""
    turns = _window_with_old(first, age)
    messages, note = fade_transcript(turns, len(turns), profile=CDR05, session_id=session_id)
    return messages[0].content, note


def _recall_at_age(age: int, session_id: str) -> int:
    """Register the three words, ask for them `age` turns later, count survivors."""
    faded, _ = _fade_old(" ".join(WORDS), age, session_id)
    return _survivors(faded, WORDS)


class TestWorkingMemoryHold:
    """The delayed-recall probe: 2 of 3, or 1 of 3 with a cue — never a blank.

    A hard window could only ever read the words back verbatim or lose them whole.
    The fade is what puts CDR 0.5 in between: registration intact, retention frayed,
    partially. Which words go is hashed, so these assertions are reproducible.
    """

    def test_healthy_hands_the_transcript_back_untouched(self) -> None:
        turns = [_exchange("remember apple train blue"), _exchange("lovely weather")]
        messages, note = fade_transcript(turns, turns_seen=2, profile=HEALTHY, session_id="s")

        assert note is None
        assert [m.content for m in messages] == [
            "remember apple train blue",
            "Mm, yes.",
            "lovely weather",
            "Mm, yes.",
        ]

    def test_the_most_recent_exchanges_are_held_whole(self) -> None:
        """Immediate registration is intact at CDR 0.5: the crisp span never fades,
        so a word asked for straight back always comes back."""
        # Age 0 (the only completed turn) and age 1 (older than a filler) both sit
        # inside the two crisp turns and are handed over verbatim.
        assert _recall_at_age(0, "s") == 3
        assert _recall_at_age(1, "s") == 3

        turns = [_exchange(" ".join(WORDS)), _exchange("and how are you keeping?")]
        messages, note = fade_transcript(turns, turns_seen=2, profile=CDR05, session_id="s")
        assert messages[0].content == " ".join(WORDS)  # age 1: still crisp
        assert note is None

    def test_an_old_three_word_list_comes_back_in_part(self) -> None:
        """The clinical signature, across many sessions: partial recall is the norm,
        a total blank is the minority, and a perfect score after the delay is too."""
        counts = [_recall_at_age(6, f"s{i}") for i in range(300)]

        partial = sum(1 for c in counts if c in (1, 2))
        blank = sum(1 for c in counts if c == 0)
        perfect = sum(1 for c in counts if c == 3)

        assert partial > blank and partial > perfect  # 2-of-3 / 1-of-3 dominates
        assert 0 < blank < len(counts) * 0.45  # she can lose them all — but rarely
        assert 0 < perfect < len(counts) * 0.45  # and can hold them all — rarely

    def test_the_further_back_it_was_the_more_is_lost(self) -> None:
        """More delay, more forgotten: survival averaged over many sessions falls as
        the list recedes. This is the gradient a hard window could not produce."""
        near = sum(_recall_at_age(3, f"s{i}") for i in range(300))
        far = sum(_recall_at_age(9, f"s{i}") for i in range(300))
        assert near > far

    def test_the_fade_is_hashed_not_rolled(self) -> None:
        """A replayed session frays identically — the reproducibility a validation
        cannot do without, and the reason `random` is banned from this package."""
        turns = _window_with_old("the quick brown fox jumped clean over the lazy dog", age=7)
        first = fade_transcript(turns, len(turns), profile=CDR05, session_id="sess")
        again = fade_transcript(turns, len(turns), profile=CDR05, session_id="sess")

        assert [m.content for m in first[0]] == [m.content for m in again[0]]
        assert first[1] == again[1]

    def test_a_fade_leaves_a_note_that_explains_the_lapse(self) -> None:
        """A delayed-recall failure has no retrieved memory to point at, so the note
        is what keeps it from being an unexplained gap in the trace."""
        _, note = _fade_old(
            "the quick brown fox jumped clean over the lazy dog", age=8, session_id="s"
        )

        assert note is not None
        assert "slipped" in note

    def test_cdr3_fades_even_the_current_exchange(self) -> None:
        """crisp_turns 0: registration itself is failing, so the exchange just
        completed (age 0) can already lose words — a delayed-recall probe that is
        cue-proof because the list is gone before the cue can arrive. At CDR 0.5 the
        crisp span held age 0 whole; here nothing is held."""
        cdr3 = load_profile(PROFILES / "cdr3.yaml")

        faded = 0
        for i in range(300):
            turns = [_exchange(" ".join(WORDS))]
            messages, _ = fade_transcript(turns, turns_seen=1, profile=cdr3, session_id=f"s{i}")
            if _survivors(messages[0].content, WORDS) < 3:
                faded += 1
        assert faded > 0  # the current exchange is no longer safe

    def test_a_faded_word_becomes_a_gap_never_another_word(self) -> None:
        """She loses the particulars; she never acquires false ones. A wholly faded
        message is still something said — a single gap, never nothing."""
        allowed = {ELISION, "gone", "we", "talked", "of", "other", "things", "Mm,", "yes."}
        seen_gap = False
        for i in range(80):
            turns = _window_with_old("gone", age=9)
            messages, _ = fade_transcript(turns, len(turns), profile=CDR05, session_id=f"x{i}")
            for message in messages:
                assert message.content  # never empty (a gap is still content)
                for token in message.content.split():
                    # Every token is either an original word or the gap marker —
                    # nothing invented has been slipped in.
                    assert token in allowed
                if ELISION in message.content:
                    seen_gap = True
        assert seen_gap  # the fade does bite at this depth


class TestWordFinding:
    """One groping pause, injected into the reply the model already wrote — the
    behaviour the prompt seam could not deliver, done to the output instead.
    """

    #: The real CDR 1 profile: the in-test `CDR1` fixture leaves speech at its
    #: healthy default, and word-finding is a speech parameter.
    PROFILE = load_profile(PROFILES / "cdr1.yaml")
    REPLY = "I put the kettle on and set the teapot beside the window to warm."

    def test_healthy_never_stumbles(self) -> None:
        text, note = inject_word_finding(self.REPLY, HEALTHY, session_id="s", turn=1)
        assert text == self.REPLY
        assert note is None

    def test_it_fires_on_some_turns_and_not_others(self) -> None:
        """Intermittent, never a metronome and never every sentence."""
        outcomes = [
            inject_word_finding(self.REPLY, self.PROFILE, session_id="s", turn=turn)[1] is not None
            for turn in range(60)
        ]
        assert any(outcomes)
        assert not all(outcomes)
        rate = sum(outcomes) / len(outcomes)
        assert 0.1 < rate < 0.6  # near the profile's word_finding_probability

    def test_when_it_fires_it_inserts_exactly_one_grope(self) -> None:
        # A turn known to fire for this session (searched, not assumed).
        turn = next(
            t
            for t in range(200)
            if inject_word_finding(self.REPLY, self.PROFILE, session_id="s", turn=t)[1] is not None
        )
        text, note = inject_word_finding(self.REPLY, self.PROFILE, session_id="s", turn=turn)

        assert note is not None and note.startswith("word-finding: groped for ")
        assert text.count("—") == 2  # one interjection, bracketed by two dashes
        assert note.split("'")[1] in text  # the groped word is named and still there
        # Nothing was deleted: excise the injected interjection and the reply is whole.
        before, _, rest = text.partition("— ")
        _, _, after = rest.partition(" — ")
        assert before + after == self.REPLY

    def test_it_never_stumbles_on_a_name_or_the_first_word(self) -> None:
        """Anomia spares proper nouns and does not preface a sentence. Every word it
        ever gropes for is a plain lowercase noun that began past the first letter."""
        reply = "Maya and I drove to Vermont for the wedding that autumn."
        groped = {
            inject_word_finding(reply, self.PROFILE, session_id=f"s{i}", turn=t)[1]
            for i in range(30)
            for t in range(30)
        }
        words = {n.split("'")[1] for n in groped if n is not None}
        assert "Maya" not in words and "Vermont" not in words  # names are safe
        assert all(reply.index(w) > 0 for w in words)  # never the opening word

    def test_a_reply_with_no_plain_noun_is_left_whole(self) -> None:
        text, note = inject_word_finding("Yes. No. I did.", self.PROFILE, session_id="s", turn=3)
        assert text == "Yes. No. I did."
        assert note is None

    def test_it_replays_identically(self) -> None:
        first = inject_word_finding(self.REPLY, self.PROFILE, session_id="sess", turn=9)
        again = inject_word_finding(self.REPLY, self.PROFILE, session_id="sess", turn=9)
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

    def test_delayed_recall_frays_partially_rather_than_to_a_blank(
        self, saved: Persona, database: Database
    ) -> None:
        """Three words, then several turns of other conversation — the correction a
        clinical review forced.

        A hard short window had only two answers to "what were the three words?":
        read them back verbatim, or — once the turn had scrolled clean out of the
        prompt — a flat blank, "I don't remember any words". A blank is a heavier
        deficit than CDR 0.5, where registration is intact and it is *retention* that
        frays, partially: 2 of 3, or 1 of 3. The transcript now fades instead of
        truncating, so the probe lands in that middle.

        Which words go is hashed per session, and the session id is fresh each
        conversation, so this asks across many and checks the shape of the outcome —
        the same way the clinical-rate tests do.
        """
        fillers = (
            "Lovely weather today.",
            "Have you been outside at all?",
            "The garden is looking well.",
            "Did you sleep alright?",
            "Anything worth hearing on the wireless?",
            "Shall I put the kettle on?",
        )
        counts = []
        for _ in range(40):
            llm = ScriptedLLM("I'll remember them.")
            with impaired(saved, llm, database) as chat:
                chat.send("Remember these three words: apple, train, blue.")
                for filler in fillers:
                    chat.send(filler)
                probe = chat.send("What were those three words?")

            assert probe.formed == []  # nothing is ever invented to fill the gap
            # The oldest turn in the last prompt is the registration line, now faded.
            registration = llm.prompts[-1][1].content
            counts.append(_survivors(registration, WORDS))

        partial = sum(1 for c in counts if c in (1, 2))
        blank = sum(1 for c in counts if c == 0)
        perfect = sum(1 for c in counts if c == 3)

        assert partial > blank  # the middle is where CDR 0.5 lives
        assert partial > perfect  # not read straight off a card either
        assert blank < len(counts) * 0.5  # a clean blank is the exception, not the rule

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
