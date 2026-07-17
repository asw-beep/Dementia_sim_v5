"""Rendering the ledger: the report a trainer would hand back.

Plain text for the CLI, in the order a clinical reader expects: memory first
(remote against recent — the dissociation that separates the middle stages),
orientation, judgment as far as conversation expresses it, language as supporting
observation, then coverage — what the interview asked and what it never did — and
the fixed statement of what a conversation cannot show at all.

Given a profile, each section also states what that profile *intended*, straight
from its numbers, so intended and observed sit side by side. Given none, the
report is observations only. Either way every line names its turn: the claim is
checkable against `persona trace`, or it is not made.
"""

from __future__ import annotations

from personasim.assessment.ledger import EvidenceLine, Ledger
from personasim.assessment.probes import CORE_PROBES
from personasim.impairment import CognitiveProfile

_UNOBSERVABLE = (
    "Community affairs, home and hobbies, and personal care are rated from an\n"
    "informant interview in clinical practice. A conversation cannot show them,\n"
    "and this report does not score them."
)


def render_report(ledger: Ledger, profile: CognitiveProfile | None = None) -> str:
    sections = [
        _header(ledger, profile),
        _memory(ledger, profile),
        _orientation(ledger, profile),
        _judgment(ledger, profile),
        _language(ledger, profile),
        _coverage(ledger),
        f"NOT OBSERVABLE IN CONVERSATION\n{_UNOBSERVABLE}",
    ]
    return "\n\n".join(sections)


def _header(ledger: Ledger, profile: CognitiveProfile | None) -> str:
    lines = [f"Assessment ledger — session {ledger.session_id}  ({ledger.turn_count} turns)"]
    if profile is not None:
        lines.append(f"Profile: {profile.label or profile.name}")
    if not ledger.shows_impairment:
        lines.append("Nothing impaired was observed in this session.")
    return "\n".join(lines)


def _memory(ledger: Ledger, profile: CognitiveProfile | None) -> str:
    lines = ["MEMORY"]
    lines += _block("remote (authored) memory recalled intact", ledger.remote_intact)
    lines += _block("recent memory, recalled but unsure", ledger.recent_hedged)
    lines += _block("recent memory, gist only", ledger.recent_gist)
    lines += _block("recent memory, did not come to mind", ledger.recent_withheld)
    lines += _block("in-conversation retention", ledger.fades)
    if len(lines) == 1:
        lines.append("  no memory degradation observed")
    if profile is not None:
        recall, hold = profile.recall, profile.hold
        if profile.gates_recall:
            lines.append(
                f"  intended: recent window {recall.recent_window_days}d; withhold below "
                f"{recall.withhold_below:.2f}; gist below {recall.gist_below:.2f}; "
                f"cue weight {recall.cue_weight:.2f}"
            )
        if hold.fades:
            lines.append(
                f"  intended: transcript held {hold.crisp_turns} turn(s) crisp, "
                f"fading over {hold.fade_turns}"
            )
        if not profile.gates_recall and not hold.fades:
            lines.append("  intended: nothing gated (healthy)")
    return "\n".join(lines)


def _orientation(ledger: Ledger, profile: CognitiveProfile | None) -> str:
    lines = ["ORIENTATION"]
    lines += _lines(ledger.orientation) or ["  no disorientation observed"]
    if profile is not None:
        orient = profile.orientation
        lines.append(
            f"  intended: time {orient.day_and_date}; place {orient.place}; person {orient.person}"
        )
    return "\n".join(lines)


def _judgment(ledger: Ledger, profile: CognitiveProfile | None) -> str:
    lines = ["JUDGMENT (as far as conversation shows it)"]
    lines += _lines(ledger.overruns) or ["  no overrun observed"]
    if profile is not None:
        speech = profile.speech
        if speech.long_question_clauses > 0:
            lines.append(
                f"  intended: holds {speech.long_question_clauses} part(s); "
                f"overruns {speech.long_question_probability:.0%} of longer questions"
            )
        else:
            lines.append("  intended: no limit (healthy)")
    return "\n".join(lines)


def _language(ledger: Ledger, profile: CognitiveProfile | None) -> str:
    lines = ["LANGUAGE (supporting observation)"]
    lines += _lines(ledger.word_finding) or ["  no word-finding difficulty observed"]
    if profile is not None:
        speech = profile.speech
        parts = [f"word-finding on {speech.word_finding_probability:.0%} of turns"]
        if speech.simplified_language:
            parts.append("speech simplified")
        lines.append(f"  intended: {'; '.join(parts)}")
    return "\n".join(lines)


def _coverage(ledger: Ledger) -> str:
    lines = ["PROBE COVERAGE"]
    for probe in CORE_PROBES:
        turns = ledger.coverage.get(probe)
        if turns:
            lines.append(f"  probed: {probe} ({_turn_refs(turns)})")
    for probe in CORE_PROBES:
        if probe not in ledger.coverage:
            lines.append(f"  never probed: {probe}")
    extras = [p for p in ledger.coverage if p not in CORE_PROBES]
    for probe in sorted(extras):
        lines.append(f"  also probed: {probe} ({_turn_refs(ledger.coverage[probe])})")
    if ledger.unclassified_turns:
        lines.append(f"  unclassified questions: {_turn_refs(ledger.unclassified_turns)}")
    return "\n".join(lines)


def _block(title: str, lines: list[EvidenceLine]) -> list[str]:
    if not lines:
        return []
    return [f"  {title}:"] + [f"    - turn {line.turn}: {line.text}" for line in lines]


def _lines(lines: list[EvidenceLine]) -> list[str]:
    return [f"  - turn {line.turn}: {line.text}" for line in lines]


def _turn_refs(turns: list[int]) -> str:
    label = "turn" if len(turns) == 1 else "turns"
    return f"{label} {', '.join(str(t) for t in turns)}"
