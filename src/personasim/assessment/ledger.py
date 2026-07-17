"""The evidence ledger: one session's traces, sorted into clinical domains.

Aggregation by rule over the session log — nothing here is inferred. Each line of
evidence names the turn it came from, so `persona trace` is always the drill-down,
and the classification rules are few and mechanical:

- A retrieved memory is *authored* (part of her life, remote by construction) when
  its id is a uuid5 — the same provenance-by-id-shape the seeder and the recall
  gate already rely on — and *acquired* (her recent past) when it is not.
- The recall gate only degrades acquired memories, and the place gate only
  degrades authored self-location ones. So a hedged or gist *acquired* memory is
  recent-memory evidence, and a hedged *authored* one is orientation evidence —
  the two gates cannot produce the other's combination.
- Withheld memories carry their gate's reason, classified by `withheld_kind`.
- Mechanism notes (the fade, the overrun, word-finding, the place frame) are read
  from `trace.reason` under the pinned vocabulary.
- Each user message is classified into the probe types it could serve, so the
  report can also say what was *never asked*.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from personasim.assessment.probes import ProbeType, classify_probe
from personasim.assessment.vocabulary import NoteKind, WithheldKind, notes_of, withheld_kind
from personasim.models.conversation import Turn

#: A seed file's memories are uuid5; anything learned or improvised is uuid4.
_AUTHORED_UUID_VERSION = 5


@dataclass(frozen=True)
class EvidenceLine:
    """One observed fact, anchored to the turn that produced it."""

    turn: int
    text: str


@dataclass
class Ledger:
    """Everything one session showed, sorted by domain. Built, never stored —
    rerunning is free and always current."""

    session_id: str
    turn_count: int = 0

    # Memory
    remote_intact: list[EvidenceLine] = field(default_factory=list)
    recent_hedged: list[EvidenceLine] = field(default_factory=list)
    recent_gist: list[EvidenceLine] = field(default_factory=list)
    recent_withheld: list[EvidenceLine] = field(default_factory=list)
    fades: list[EvidenceLine] = field(default_factory=list)

    # Orientation
    orientation: list[EvidenceLine] = field(default_factory=list)

    # Judgment, as far as conversation expresses it
    overruns: list[EvidenceLine] = field(default_factory=list)

    # Language, as supporting observation
    word_finding: list[EvidenceLine] = field(default_factory=list)

    # Coverage: which probe types the interview contained, and where
    coverage: dict[ProbeType, list[int]] = field(default_factory=dict)
    unclassified_turns: list[int] = field(default_factory=list)

    @property
    def shows_impairment(self) -> bool:
        """Whether any mechanism left evidence at all."""
        return bool(
            self.recent_hedged
            or self.recent_gist
            or self.recent_withheld
            or self.fades
            or self.orientation
            or self.overruns
            or self.word_finding
        )


def build_ledger(session_id: str, turns: Sequence[Turn]) -> Ledger:
    ledger = Ledger(session_id=session_id, turn_count=len(turns))
    seen_remote: set[str] = set()

    for number, turn in enumerate(turns, start=1):
        _classify_question(ledger, number, turn.user_message.content)
        _read_retrieved(ledger, number, turn, seen_remote)
        _read_withheld(ledger, number, turn)
        _read_notes(ledger, number, turn)

    return ledger


def _classify_question(ledger: Ledger, number: int, text: str) -> None:
    types = classify_probe(text)
    if not types:
        ledger.unclassified_turns.append(number)
        return
    for probe in types:
        ledger.coverage.setdefault(probe, []).append(number)


def _read_retrieved(ledger: Ledger, number: int, turn: Turn, seen_remote: set[str]) -> None:
    for item in turn.trace.retrieved:
        if item.was_expanded:
            continue  # an expansion's fate is its parent's; counting both double-counts
        line = EvidenceLine(number, _clip(item.summary))
        if _is_authored(item.memory_id):
            if item.hedged:
                # Only the place gate hedges an authored memory: her residence,
                # believed rather than known. Orientation evidence, not memory.
                hedged = EvidenceLine(number, f"where-she-is hedged: {_clip(item.summary)}")
                ledger.orientation.append(hedged)
            elif item.memory_id not in seen_remote:
                seen_remote.add(item.memory_id)
                ledger.remote_intact.append(line)
        elif item.detail_withheld:
            ledger.recent_gist.append(line)
        elif item.hedged:
            ledger.recent_hedged.append(line)


def _read_withheld(ledger: Ledger, number: int, turn: Turn) -> None:
    for gone in turn.trace.withheld:
        kind = withheld_kind(gone.reason)
        line = EvidenceLine(number, f"{_clip(gone.summary)} — {gone.reason}")
        if kind is WithheldKind.PLACE:
            ledger.orientation.append(line)
        else:
            ledger.recent_withheld.append(line)


def _read_notes(ledger: Ledger, number: int, turn: Turn) -> None:
    for note in notes_of(turn.trace.reason):
        line = EvidenceLine(number, note.text)
        if note.kind is NoteKind.FADE:
            ledger.fades.append(line)
        elif note.kind is NoteKind.OVERRUN:
            ledger.overruns.append(line)
        elif note.kind is NoteKind.WORD_FINDING:
            ledger.word_finding.append(line)
        elif note.kind is NoteKind.ORIENTATION:
            ledger.orientation.append(line)
        # RECALL_SUMMARY duplicates the per-memory evidence above; not double-counted.


def _is_authored(memory_id: str) -> bool:
    try:
        return uuid.UUID(memory_id).version == _AUTHORED_UUID_VERSION
    except ValueError:
        return False


def _clip(text: str, limit: int = 70) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}…"
