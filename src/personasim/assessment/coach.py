"""Sprint 3C — the coach: why the rating was right, or what was misread.

The ledger says what the session showed. The coach says what that *meant for the
rating the trainee gave*, which is a different question and the one training turns
on. Three kinds of feedback, all computed by rule and none by a model — the same
invariant as the ledger, for the same reason: an explanation that varies between
readings cannot be studied, and a wrong one is worse than none.

- **Discriminating evidence**, where rated ≠ actual. The turns whose recorded
  behaviour separates the two stages, with both anchors quoted so the trainee can
  see what they were choosing between. Every claim carries its turn.
- **Coverage**, where the domain was never probed. *"Nothing in this transcript
  could separate 0.5 from 1 on orientation — the day was never asked."* This is the
  feedback only an active interview can give, and the one a rated video cannot:
  missed diagnoses are more often failures of elicitation than of reading.
- **Confirming evidence**, where rated = actual. The turns that carried the signal,
  so a right answer consolidates rather than merely passing.

**Absence of evidence is evidence, but only once you asked.** The three cases are
kept apart deliberately. A domain with evidence discriminates by what it showed; a
domain that was *probed and stayed clean* discriminates the other way — being asked
the day and answering it rules a stage out — and a domain never probed discriminates
nothing at all, however confident the rating was. Collapsing the last two would tell
a trainee they read something correctly when they never looked.

Nothing here scores. There is no total, no percentage and no pass mark: the record
is a mirror, not a mark (`docs/design/phase3_assessment.md`).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from personasim.assessment.anchors import CDR_RUNGS, anchor, rung_of
from personasim.assessment.ledger import EvidenceLine, Ledger
from personasim.assessment.probes import ProbeType
from personasim.impairment import CognitiveProfile


class FeedbackKind(StrEnum):
    DISCRIMINATING = "discriminating"
    COVERAGE = "coverage"
    CONFIRMING = "confirming"


@dataclass(frozen=True)
class Feedback:
    """One domain's verdict, and the evidence for it."""

    domain: str
    kind: FeedbackKind
    rated: float | None
    actual: float
    #: The reading, in order. Each line stands alone and names its turns.
    lines: list[str] = field(default_factory=list)

    @property
    def missed(self) -> bool:
        return self.rated is not None and self.rated != self.actual


#: Which ledger evidence belongs to which domain, and how a line of it reads. The
#: ledger sorts by mechanism; the worksheet rates by domain; this is the join.
_EVIDENCE: dict[str, tuple[tuple[str, str], ...]] = {
    "memory": (
        ("recent_withheld", "did not come to mind at all"),
        ("recent_gist", "came back in outline only"),
        ("recent_hedged", "was recalled, but hedged"),
        ("fades", "slipped out of the live conversation"),
        # The counterpoint, and half the diagnosis: remote memory standing while
        # recent memory fails is the dissociation a rater is looking for. Reading
        # only the failures would teach half the picture.
        ("remote_intact", "came back intact — remote memory holding"),
    ),
    "orientation": (("orientation", "orientation was degraded"),),
    "judgment": (("overruns", "a multi-part question overran"),),
    "language": (("word_finding", "a word would not come"),),
}

#: The probes that could elicit each domain. Language is absent on purpose: it is
#: observed from whatever she happens to say, so there is no question that "fails to
#: ask" it and no coverage feedback to give.
_PROBES: dict[str, tuple[ProbeType, ...]] = {
    "memory": (
        ProbeType.DELAYED_RECALL,
        ProbeType.RECENT_EPISODIC,
        ProbeType.REMOTE_BIOGRAPHY,
    ),
    "orientation": (ProbeType.ORIENTATION_TIME, ProbeType.ORIENTATION_PLACE),
    "judgment": (ProbeType.JUDGMENT, ProbeType.MULTI_PART),
    "language": (),
}

#: What to say was never asked, per domain — in the trainee's words, not the
#: classifier's enum.
_NEVER_ASKED: dict[str, str] = {
    "memory": "she was never asked about a recent event, a remote one, or a word list",
    "orientation": "the day was never asked, nor where she was",
    "judgment": "no multi-part or planning question was ever put to her",
}


def coach(
    ledger: Ledger,
    ratings: dict[str, float | None],
    actual: CognitiveProfile,
    rated_profiles: dict[float, CognitiveProfile] | None = None,
) -> list[Feedback]:
    """Read one committed assessment back to the trainee, domain by domain.

    `rated_profiles` maps a rung to the profile standing there, so the coach can name
    the mechanical difference between what was rated and what was drawn. It is
    optional: without it the anchors still carry the reading, which is what a trainee
    is actually being taught to see.
    """
    actual_rung = rung_of(actual.name)
    if actual_rung is None:
        return []

    feedback: list[Feedback] = []
    for domain in ("memory", "orientation", "judgment", "language"):
        rated = ratings.get(domain)
        found = _evidence_for(ledger, domain)
        probed = _probed_turns(ledger, domain)

        if rated is None:
            # Not rated, and that is allowed — a blank is honest. But it is still a
            # chance to learn, so say either what was there to be read or that
            # nothing could have been: silence would teach neither.
            if found:
                feedback.append(
                    Feedback(
                        domain,
                        FeedbackKind.CONFIRMING,
                        None,
                        actual_rung,
                        [
                            f"You left {domain} unrated. It was there to be read — "
                            f"she was {_cdr(actual_rung)}:",
                            *found,
                        ],
                    )
                )
            elif probed:
                # Asked, answered cleanly, and left blank anyway. The evidence was
                # there and it was rateable — a clean answer to a real probe is a
                # finding, not a gap.
                feedback.append(
                    Feedback(
                        domain,
                        FeedbackKind.CONFIRMING,
                        None,
                        actual_rung,
                        [
                            f"You left {domain} unrated, but you did probe it — "
                            f"{_turns(probed)} — and nothing impaired showed.",
                            f"That was rateable. She was {_cdr(actual_rung)}: "
                            f"{anchor(domain, actual_rung)}",
                        ],
                    )
                )
            elif domain in _NEVER_ASKED:
                feedback.append(
                    Feedback(
                        domain,
                        FeedbackKind.COVERAGE,
                        None,
                        actual_rung,
                        [
                            f"You left {domain} unrated, and nothing probed it — "
                            f"{_NEVER_ASKED[domain]}.",
                            f"Leaving it blank was right. She was {_cdr(actual_rung)}: "
                            f"{anchor(domain, actual_rung)}",
                        ],
                    )
                )
            continue

        if rated == actual_rung:
            feedback.append(_confirming(domain, rated, actual_rung, found, probed))
        elif not found and not probed and domain in _NEVER_ASKED:
            feedback.append(_coverage(domain, rated, actual_rung))
        else:
            feedback.append(
                _discriminating(
                    domain,
                    rated,
                    actual_rung,
                    found,
                    probed,
                    actual,
                    rated_profiles,
                    _cadence(domain, ledger, actual, (rated_profiles or {}).get(rated)),
                )
            )

    overall = ratings.get("global")
    if overall is not None:
        feedback.append(_global(overall, actual_rung, feedback))
    return feedback


def _confirming(
    domain: str, rated: float, actual_rung: float, found: list[str], probed: list[int]
) -> Feedback:
    lines = [f"You read {domain} correctly: {_cdr(rated)} — {anchor(domain, rated)}"]
    if found:
        lines.append("The turns that carried it:")
        lines += found
    elif probed:
        # Right for the right reason, and worth saying so: nothing showed *because*
        # nothing was there, and she was asked.
        lines.append(
            f"Nothing impaired showed, and you did ask — {_turns(probed)}. "
            "A clean answer to a real probe is evidence, not an absence of it."
        )
    else:
        lines.append(
            f"Nothing in the transcript bore on {domain}, and it was never probed — "
            "so this one was right without being shown to be."
        )
    return Feedback(domain, FeedbackKind.CONFIRMING, rated, actual_rung, lines)


def _coverage(domain: str, rated: float, actual_rung: float) -> Feedback:
    return Feedback(
        domain,
        FeedbackKind.COVERAGE,
        rated,
        actual_rung,
        [
            f"You rated {domain} {_cdr(rated)}; she was {_cdr(actual_rung)}.",
            f"But nothing in this transcript could separate them — {_NEVER_ASKED[domain]}.",
            f"At {_cdr(actual_rung)} you would expect: {anchor(domain, actual_rung)}",
            "Ask it next time; a rating no probe could have supported is a guess "
            "however well it lands.",
        ],
    )


def _discriminating(
    domain: str,
    rated: float,
    actual_rung: float,
    found: list[str],
    probed: list[int],
    actual: CognitiveProfile,
    rated_profiles: dict[float, CognitiveProfile] | None,
    cadence: str | None = None,
) -> Feedback:
    lines = [
        f"You rated {domain} {_cdr(rated)} — {_distance(rated, actual_rung)}. "
        f"She was {_cdr(actual_rung)}.",
        f"You chose: {anchor(domain, rated)}",
        f"She was:   {anchor(domain, actual_rung)}",
    ]

    if found:
        lines.append("What the transcript actually showed:")
        lines += found
    elif probed:
        lines.append(
            f"Nothing impaired showed in {domain}, though you did ask — {_turns(probed)}. "
            f"That absence is the evidence: at {_cdr(rated)} you would have seen "
            f"{_lowered(anchor(domain, rated))}"
        )
    else:
        # No evidence and no probe. Not a misreading — a rating with nothing under
        # it, which is worth saying plainly rather than dressing as a diagnosis.
        lines.append(
            f"Nothing bore on {domain} and nothing probed it, so this rating rested "
            "on no evidence either way."
        )

    difference = _difference(domain, actual, (rated_profiles or {}).get(rated))
    if difference is not None:
        lines.append(f"What separates them: {difference}")
    if cadence is not None:
        lines.append(cadence)
    return Feedback(domain, FeedbackKind.DISCRIMINATING, rated, actual_rung, lines)


def _global(overall: float, actual_rung: float, domains: Sequence[Feedback]) -> Feedback:
    if overall == actual_rung:
        return Feedback(
            "global",
            FeedbackKind.CONFIRMING,
            overall,
            actual_rung,
            [
                f"Your global rating was right: {_cdr(actual_rung)} — "
                f"{anchor('global', actual_rung)}"
            ],
        )

    missed = [f.domain for f in domains if f.missed]
    read_right = [f.domain for f in domains if f.rated is not None and not f.missed]
    lines = [
        f"You rated globally {_cdr(overall)}; she was {_cdr(actual_rung)} — "
        f"{anchor('global', actual_rung)}",
    ]
    if missed:
        lines.append(f"The domains that moved you off it: {', '.join(missed)}.")
    if read_right:
        lines.append(f"You read these correctly: {', '.join(read_right)}.")
    if not missed and read_right:
        # Every box right and the global still wrong — worth naming, because the
        # global is a holistic judgment and not an average of the boxes.
        lines.append(
            "Every domain you rated was right, so this was the holistic step, not "
            "the reading — the global is a judgment about the whole person."
        )
    return Feedback("global", FeedbackKind.DISCRIMINATING, overall, actual_rung, lines)


def _cadence(
    domain: str,
    ledger: Ledger,
    actual: CognitiveProfile,
    rated: CognitiveProfile | None,
) -> str | None:
    """For language, what the interview could and could not have shown.

    Word-finding is a *rate*, and a short interview samples it badly: one groping
    pause in six turns reads as 17%, which sits between two stages and belongs to
    neither. Told flatly that they were "one rung too low", a trainee would learn to
    distrust a reading that was in fact perfectly defensible. So the observed
    cadence is stated beside both intended rates, and the sampling problem is named.

    This is the honest consequence of the anti-goal: the actual stage is the drawn
    profile, never inferred from the transcript, so a domain *can* be "wrong" while
    the transcript supported the answer given. Where that is likely, say so.
    """
    if domain != "language" or rated is None or ledger.turn_count == 0:
        return None

    observed = len({line.turn for line in ledger.word_finding})
    rate = observed / ledger.turn_count
    return (
        f"On the sample: word-finding showed on {observed} of {ledger.turn_count} turns "
        f"({rate:.0%}), against {actual.speech.word_finding_probability:.0%} intended at "
        f"her stage and {rated.speech.word_finding_probability:.0%} at yours. A short "
        "interview samples a rate poorly — this one may not have been readable."
    )


def _difference(
    domain: str, actual: CognitiveProfile, rated: CognitiveProfile | None
) -> str | None:
    """The mechanical difference between the two stages, in one line.

    Read off the profiles rather than written down anywhere, so it cannot drift from
    what the engine actually did. Returns None when the profile for the rated stage
    was not supplied, or when the two do not differ in this domain's parameters —
    which happens, and saying nothing is better than inventing a distinction.
    """
    if rated is None:
        return None

    if domain == "memory":
        parts = []
        if actual.recall.withhold_below != rated.recall.withhold_below:
            parts.append(
                f"a recent memory is withheld below reach {actual.recall.withhold_below:.2f} "
                f"at her stage, {rated.recall.withhold_below:.2f} at yours"
            )
        if actual.hold.capacity != rated.hold.capacity:
            parts.append(
                f"the live conversation holds {_span(actual)} at her stage, {_span(rated)} at yours"
            )
        return "; ".join(parts) or None

    if domain == "orientation":
        parts = [
            f"{axis} {getattr(actual.orientation, field_name)} at her stage, "
            f"{getattr(rated.orientation, field_name)} at yours"
            for axis, field_name in (
                ("time", "day_and_date"),
                ("place", "place"),
                ("person", "person"),
            )
            if getattr(actual.orientation, field_name) != getattr(rated.orientation, field_name)
        ]
        return "; ".join(parts) or None

    if domain == "judgment":
        if actual.speech.long_question_clauses != rated.speech.long_question_clauses:
            return f"a long question: {_holds(actual)} at her stage, {_holds(rated)} at yours"
        return None

    if actual.speech.word_finding_probability != rated.speech.word_finding_probability:
        return (
            f"word-finding on {actual.speech.word_finding_probability:.0%} of turns at "
            f"her stage, {rated.speech.word_finding_probability:.0%} at yours"
        )
    return None


def _evidence_for(ledger: Ledger, domain: str) -> list[str]:
    """This domain's ledger lines, one per distinct observation, naming its turns.

    Collapsed the way the report's orientation section is, and for the reason the
    drive showed: a standing condition reports itself every turn, and six identical
    sentences under "the turns that carried it" bury the turns that differ.
    """
    grouped: dict[tuple[str, str], list[int]] = {}
    for attribute, reading in _EVIDENCE[domain]:
        entries: list[EvidenceLine] = getattr(ledger, attribute)
        for entry in entries:
            grouped.setdefault((entry.text, reading), []).append(entry.turn)
    return [f"  {_turns(turns)}: {text} ({reading})" for (text, reading), turns in grouped.items()]


def _probed_turns(ledger: Ledger, domain: str) -> list[int]:
    turns = {turn for probe in _PROBES[domain] for turn in ledger.coverage.get(probe, [])}
    return sorted(turns)


def _holds(profile: CognitiveProfile) -> str:
    """How much of a multi-part question survives, in words.

    Zero clauses does not mean "holds nothing" — it means the overrun mechanism is
    off, which is what healthy is. Printing the raw number said "holds 0 parts at
    yours" of a healthy rating, i.e. exactly the opposite of the truth, and a drive
    caught it reading back as though healthy were the worse stage.
    """
    clauses = profile.speech.long_question_clauses
    return "never overruns" if clauses == 0 else f"she holds {clauses} part(s)"


def _span(profile: CognitiveProfile) -> str:
    capacity = profile.hold.capacity
    return "everything said" if capacity is None else f"{capacity} exchange(s)"


def _distance(rated: float, actual_rung: float) -> str:
    """How far off, in rungs — not in CDR points.

    The scale is not linear: 2 to 3 is one step, and so is 0.5 to 1. Saying "one
    rung too high" is the reading a rater is being trained in; saying "0.5 too high"
    would invite arithmetic on a scale that has none.
    """
    gap = abs(CDR_RUNGS.index(rated) - CDR_RUNGS.index(actual_rung))
    direction = "too high" if rated > actual_rung else "too low"
    return f"one rung {direction}" if gap == 1 else f"{gap} rungs {direction}"


def _turns(turns: Sequence[int]) -> str:
    label = "turn" if len(turns) == 1 else "turns"
    return f"{label} {', '.join(str(turn) for turn in turns)}"


def _lowered(text: str) -> str:
    return text[0].lower() + text[1:] if text else text


def _cdr(rung: float) -> str:
    return "CDR 0 (healthy)" if rung == 0.0 else f"CDR {rung:g}"
