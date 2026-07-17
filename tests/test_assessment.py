"""Sprint 3A — the evidence ledger.

Design: docs/design/phase3_assessment.md. Three things are pinned here. The note
vocabulary, from *both sides* — the impairment mechanisms are invoked for real and
their notes must parse, so a reworded note breaks loudly rather than silently
orphaning the ledger. The probe classifier, against the fifteen-probe bank the
comparison drive validated. And the ledger's classification rules — remote versus
recent by id shape, the place gate's hedges landing under orientation, coverage
recording what was asked and what never was.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from personasim.assessment.ledger import build_ledger
from personasim.assessment.probes import CORE_PROBES, ProbeType, classify_probe
from personasim.assessment.report import render_report
from personasim.assessment.vocabulary import (
    NoteKind,
    WithheldKind,
    notes_of,
    withheld_kind,
)
from personasim.impairment import (
    HEALTHY,
    CognitiveProfile,
    apply_place_gate,
    apply_recall_gate,
    fade_transcript,
    inject_word_finding,
    load_profile,
    retain_question,
)
from personasim.impairment.profile import RecallGate, Speech, WorkingMemoryHold
from personasim.models import EpisodicMemory, Memory, SemanticMemory
from personasim.models.conversation import Message, Role, Turn
from personasim.models.trace import (
    MemoryTrace,
    RetrievalIntent,
    RetrievedMemory,
)
from personasim.persona.seed import memory_id_for
from tests.test_impairment import PROFILES, _Source, retrieved, session_encoding

NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def trace_of(*items: RetrievedMemory, reason: str = "test") -> MemoryTrace:
    return MemoryTrace(
        query="test",
        intent=RetrievalIntent.FACTUAL_RECALL,
        retrieved=list(items),
        reason=reason,
    )


def turn_of(question: str, trace: MemoryTrace) -> Turn:
    return Turn(
        user_message=Message(role=Role.USER, content=question),
        persona_message=Message(role=Role.PERSONA, content="Mm."),
        trace=trace,
    )


def authored_fact(key: str, summary: str, attribute: str) -> SemanticMemory:
    return SemanticMemory(
        summary=summary,
        keywords=[attribute],
        subject="self",
        attribute=attribute,
        value=summary,
    ).model_copy(update={"id": memory_id_for("elena-marsh", key)})


def acquired_fact(summary: str) -> SemanticMemory:
    """A conversation-acquired memory: random uuid4, recent by construction."""
    return SemanticMemory(
        summary=summary,
        keywords=["recent"],
        subject="self",
        attribute="breakfast",
        value=summary,
        created_at=NOW - timedelta(hours=3),
    )


class TestVocabularyBothSides:
    """The emitters are invoked for real; their notes must parse. This is the
    contract that lets trace notes stay strings instead of a Phase 1 model change."""

    def test_the_fade_note_parses(self) -> None:
        profile = CognitiveProfile(name="fade", hold=WorkingMemoryHold(crisp_turns=1, fade_turns=2))
        turns = [
            turn_of("remember apple train blue please for me now", trace_of()),
            turn_of("and how are you keeping today then", trace_of()),
            turn_of("lovely weather we are having", trace_of()),
        ]
        note = None
        for i in range(50):
            _, note = fade_transcript(turns, len(turns), profile, session_id=f"s{i}")
            if note is not None:
                break
        assert note is not None
        parsed = notes_of(f"base reason; on keywords ['x']; {note}")
        assert [n.kind for n in parsed] == [NoteKind.FADE]
        assert "slipped" in parsed[0].text

    def test_the_overrun_note_parses_across_its_own_semicolon(self) -> None:
        profile = CognitiveProfile(
            name="overrun",
            speech=Speech(long_question_clauses=1, long_question_probability=1.0),
        )
        message = "You slept well, you ate at noon, and what is your dog called?"
        _, note = retain_question(message, profile, session_id="s", turn=1)
        assert note is not None
        parsed = notes_of(f"factual_recall: 1 memories matched; {note}")
        assert [n.kind for n in parsed] == [NoteKind.OVERRUN]
        assert "kept only the last 1" in parsed[0].text

    def test_the_word_finding_note_parses(self) -> None:
        profile = CognitiveProfile(name="words", speech=Speech(word_finding_probability=1.0))
        _, note = inject_word_finding(
            "I walked to the harbour today.", profile, session_id="s", turn=1
        )
        assert note is not None
        parsed = notes_of(f"base; {note}")
        assert [n.kind for n in parsed] == [NoteKind.WORD_FINDING]
        assert "groped" in parsed[0].text

    def test_the_place_gate_note_and_reason_parse(self) -> None:
        home = authored_fact("city", "I live in Boston", "city")
        profile = load_profile(PROFILES / "cdr3.yaml")
        gated = apply_place_gate(trace_of(retrieved(home, cue=1.0)), profile, _Source(home))

        parsed = notes_of(gated.reason)
        assert NoteKind.ORIENTATION in [n.kind for n in parsed]
        assert withheld_kind(gated.withheld[0].reason) is WithheldKind.PLACE

    def test_the_recall_gate_reason_and_summary_parse(self) -> None:
        lunch = EpisodicMemory(
            summary="Had lunch at the market",
            keywords=["lunch"],
            occurred_on=(NOW - timedelta(days=3)).date(),
        )
        profile = CognitiveProfile(
            name="recall",
            recall=RecallGate(
                recent_window_days=90, withhold_below=0.45, gist_below=0.85, cue_weight=0.55
            ),
        )
        session = session_encoding(lunch.id, 0.0, 0.1)
        gated = apply_recall_gate(
            trace_of(retrieved(lunch, cue=0.0)),
            profile,
            _Source(lunch),
            session_id=session,
            now=NOW,
        )

        assert withheld_kind(gated.withheld[0].reason) is WithheldKind.RECENT_RECALL
        assert NoteKind.RECALL_SUMMARY in [n.kind for n in notes_of(gated.reason)]

    def test_the_expansion_reason_parses(self) -> None:
        assert (
            withheld_kind("connected to a memory that did not come to mind")
            is WithheldKind.EXPANSION
        )

    def test_an_unimpaired_reason_yields_no_notes(self) -> None:
        reason = "experiential_recall (asking about self): 2 memories matched; on keywords ['x']"
        assert notes_of(reason) == []


# The fifteen-probe bank from the comparison drive, with the core types each
# question must classify into. A question may carry more types than asserted.
PROBE_BANK = [
    ("What did you have for your last meal today?", {ProbeType.RECENT_EPISODIC}),
    ("Can you tell me everything you've done so far today, in order?", {ProbeType.RECENT_EPISODIC}),
    (
        "What day of the week is it today? What is today's date and month?",
        {ProbeType.ORIENTATION_TIME},
    ),
    (
        "Can you tell me where you are right now (city, place, or building)?",
        {ProbeType.ORIENTATION_PLACE},
    ),
    (
        "If you needed to pay your electricity bill online, how would you do it?",
        {ProbeType.JUDGMENT},
    ),
    (
        "Imagine you're planning a trip to another city tomorrow. "
        "What would you need to prepare before leaving?",
        {ProbeType.JUDGMENT},
    ),
    (
        "Can you explain, step by step, how you would make a cup of tea "
        "(or another simple dish you know well)?",
        {ProbeType.JUDGMENT},
    ),
    (
        "Have you watched a movie or TV show recently? Tell me what it was about.",
        {ProbeType.RECENT_EPISODIC},
    ),
    ("What hobbies or activities do you enjoy these days? How often do you do them?", set()),
    (
        "When was the last time you went shopping by yourself? What did you buy?",
        {ProbeType.RECENT_EPISODIC},
    ),
    (
        "Have you forgotten any appointments, birthdays, or important events recently? "
        "Can you tell me about one?",
        {ProbeType.INSIGHT, ProbeType.RECENT_EPISODIC},
    ),
    (
        "Can you describe the home where you grew up? What do you remember most about it?",
        {ProbeType.REMOTE_BIOGRAPHY},
    ),
    ("Please name as many animals as you can think of in one minute.", {ProbeType.FLUENCY}),
    (
        "If your mobile phone suddenly stopped working and you needed to call "
        "a family member, what would you do?",
        {ProbeType.JUDGMENT},
    ),
    (
        "Do you usually need someone to remind you to take your medicines, bathe, "
        "get dressed, or complete your daily routine?",
        {ProbeType.ADL},
    ),
]


class TestProbeClassification:
    @pytest.mark.parametrize(("question", "expected"), PROBE_BANK)
    def test_the_probe_bank_classifies(self, question: str, expected: set[ProbeType]) -> None:
        assert expected <= classify_probe(question)

    def test_a_delayed_recall_probe_classifies(self) -> None:
        assert ProbeType.DELAYED_RECALL in classify_probe(
            "I'd like you to remember these three words: apple, train, blue."
        )
        assert ProbeType.DELAYED_RECALL in classify_probe("Now — what were the words?")

    def test_a_compound_question_serves_several_types(self) -> None:
        types = classify_probe("What day is it, and can you tell me where you are?")
        assert {ProbeType.ORIENTATION_TIME, ProbeType.ORIENTATION_PLACE} <= types


class TestLedger:
    def test_a_clean_session_shows_nothing(self) -> None:
        home = authored_fact("hometown", "I grew up in Rutland, Vermont", "hometown")
        turns = [turn_of("Where did you grow up?", trace_of(retrieved(home, cue=1.0)))]
        ledger = build_ledger("s1", turns)

        assert not ledger.shows_impairment
        assert [line.text for line in ledger.remote_intact] == ["I grew up in Rutland, Vermont"]

    def test_remote_recalls_are_deduplicated_recent_ones_are_not(self) -> None:
        home = authored_fact("hometown", "I grew up in Rutland, Vermont", "hometown")
        turns = [
            turn_of("Where did you grow up?", trace_of(retrieved(home, cue=1.0))),
            turn_of("Tell me about your childhood.", trace_of(retrieved(home, cue=0.5))),
        ]
        ledger = build_ledger("s1", turns)
        assert len(ledger.remote_intact) == 1

    def test_degraded_acquired_memories_are_memory_evidence(self) -> None:
        breakfast = acquired_fact("For breakfast I had porridge")
        hedged = retrieved(breakfast, cue=1.0, hedged=True)
        gist = retrieved(breakfast, cue=1.0, hedged=True, detail_withheld=True)
        turns = [
            turn_of("What did you have for your last meal today?", trace_of(hedged)),
            turn_of("What did you eat this morning?", trace_of(gist)),
        ]
        ledger = build_ledger("s1", turns)

        assert [line.turn for line in ledger.recent_hedged] == [1]
        assert [line.turn for line in ledger.recent_gist] == [2]
        assert not ledger.orientation

    def test_a_hedged_authored_memory_is_orientation_evidence(self) -> None:
        # Only the place gate hedges an authored memory — her residence, believed
        # rather than known. It must land under orientation, not memory.
        home = authored_fact("city", "I live in Boston", "city")
        turns = [
            turn_of(
                "Can you tell me where you are right now?",
                trace_of(retrieved(home, cue=1.0, hedged=True)),
            )
        ]
        ledger = build_ledger("s1", turns)

        assert ledger.orientation and ledger.orientation[0].turn == 1
        assert not ledger.recent_hedged

    def test_withheld_memories_split_by_gate(self) -> None:
        breakfast = acquired_fact("For breakfast I had porridge")
        home = authored_fact("city", "I live in Boston", "city")
        trace = MemoryTrace(
            query="q",
            intent=RetrievalIntent.FACTUAL_RECALL,
            retrieved=[],
            withheld=[
                _withheld(
                    breakfast, "recent (0d) and poorly laid down: reach 0.30 < 0.80 (cue 1.00)"
                ),
                _withheld(home, "disoriented to place: cannot say where she is"),
            ],
            reason="base",
        )
        ledger = build_ledger("s1", [turn_of("Where are you, and what did you eat?", trace)])

        assert len(ledger.recent_withheld) == 1
        assert len(ledger.orientation) == 1

    def test_notes_land_in_their_domains(self) -> None:
        reason = (
            "base; working memory: 2 earlier exchanges fading, 9 words slipped; "
            "working memory: a 4-part question overran; kept only the last 1; "
            "word-finding: groped for 'kettle'"
        )
        ledger = build_ledger("s1", [turn_of("A question?", trace_of(reason=reason))])

        assert len(ledger.fades) == 1
        assert len(ledger.overruns) == 1
        assert len(ledger.word_finding) == 1
        assert ledger.shows_impairment

    def test_coverage_records_what_was_asked_and_what_never_was(self) -> None:
        turns = [
            turn_of("What day of the week is it?", trace_of()),
            turn_of("Hmm.", trace_of()),
        ]
        ledger = build_ledger("s1", turns)

        assert ledger.coverage[ProbeType.ORIENTATION_TIME] == [1]
        assert ledger.unclassified_turns == [2]
        assert ProbeType.DELAYED_RECALL not in ledger.coverage


class TestReport:
    def test_a_clean_session_reads_clean(self) -> None:
        report = render_report(build_ledger("s1", []), HEALTHY)
        assert "Nothing impaired was observed" in report
        assert "never probed: delayed recall" in report
        assert "intended: nothing gated (healthy)" in report

    def test_every_evidence_line_names_its_turn(self) -> None:
        reason = "base; word-finding: groped for 'kettle'"
        ledger = build_ledger("s1", [turn_of("What day is it?", trace_of(reason=reason))])
        report = render_report(ledger)

        assert "turn 1" in report
        assert "groped for 'kettle'" in report

    def test_the_profile_puts_intended_beside_observed(self) -> None:
        profile = load_profile(PROFILES / "cdr2.yaml")
        report = render_report(build_ledger("s1", []), profile)

        assert "intended: recent window 365d" in report
        assert "time mistaken; place hazy; person confident" in report
        assert "overruns 85% of longer questions" in report
        assert "word-finding on 45% of turns" in report

    def test_the_unobservable_domains_are_named_not_padded(self) -> None:
        report = render_report(build_ledger("s1", []))
        assert "Community affairs, home and hobbies, and personal care" in report
        assert "does not score them" in report

    def test_core_coverage_lists_all_absent_probes_for_an_empty_session(self) -> None:
        report = render_report(build_ledger("s1", []))
        for probe in CORE_PROBES:
            assert f"never probed: {probe}" in report


def _withheld(memory: Memory, reason: str) -> object:
    from personasim.models.trace import WithheldMemory

    return WithheldMemory(
        memory_id=memory.id,
        memory_type=memory.type,
        summary=memory.summary,
        cue_strength=1.0,
        age_days=0,
        reason=reason,
    )
