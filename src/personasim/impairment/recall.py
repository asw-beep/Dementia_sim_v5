"""The recall gate: a recent memory is reached only when the question cues it
strongly enough. A remote memory is always reached.

This is the whole of very-mild memory impairment in this architecture — not a new
kind of memory, but a threshold in front of the existing one, using two signals
Phase 1 already computes: how strongly the question cued each memory
(`keyword_overlap`, on the trace) and how old the memory is (on the memory itself).

Deterministic, emphatically. A coin-flip would answer the same question differently
each time it is asked — which is fluctuating confusion, a later severity, and the
wrong disease. Real very-mild impairment is *reliably* bad at the same things: the
memory that would not come on Monday will not come on Tuesday either, and a more
specific question — a stronger cue — brings it back both days. "Occasionally" is
not produced here at all; it emerges from the conversation, because most questions
are about the remote past where the gate never fires.

What "recent" means is the load-bearing decision. It is NOT `now - created_at`:
an authored memory's `created_at` is the *seed time*, and in a freshly seeded
database "Lives in Boston" is five minutes old — a naive age check would gate her
own address and make her forget where she lives. Only **conversation-shaped**
memories are gateable:

- an episodic memory, anchored on when it *happened* (`occurred_on`, falling back
  to `created_at` for episodes formed without a date);
- a semantic memory whose subject is not `self` — a disclosed fact, whose
  `created_at` genuinely is the moment of hearing it. This is the same reading
  the retrieval engine's own `_is_disclosed` commits to.

Authored self-facts and relationship memories are her *life*: never recent, never
gated, at any age. "Identity and remote memory preserved" is structural here, not
probabilistic.

Nothing is forgotten. The memory stays in the database and stays in the persona;
what this gate degrades is *reach*, this turn, for this question. A withheld memory
moves to `trace.withheld` with its arithmetic — never silently dropped, because a
recall failure the trace cannot explain is indistinguishable from a bug.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from enum import Enum, auto

from personasim.impairment.profile import CognitiveProfile
from personasim.models.memory import EpisodicMemory, Memory, MemoryId, SemanticMemory
from personasim.models.trace import MemoryTrace, RetrievedMemory, WithheldMemory
from personasim.retrieval.source import MemorySource

SELF = "self"


class _Fate(Enum):
    FULL = auto()
    GIST = auto()
    WITHHELD = auto()


def apply_recall_gate(
    trace: MemoryTrace,
    profile: CognitiveProfile,
    source: MemorySource,
    *,
    now: datetime | None = None,
) -> MemoryTrace:
    """Gate one retrieval pass. Healthy profiles return the trace untouched."""
    if not profile.gates_recall or not trace.retrieved:
        return trace

    moment = now or datetime.now(UTC)
    fates: dict[MemoryId, _Fate] = {}
    kept: list[RetrievedMemory] = []
    withheld: list[WithheldMemory] = list(trace.withheld)

    # Directly-matched memories first: their fate is their own. Expansions follow
    # in a second pass, because an expansion's fate is its *parent's* — it was never
    # asked for, only pulled in to explain a memory that was, and rendering it after
    # its parent was withheld would speak a memory she failed to recall.
    for item in trace.retrieved:
        if item.was_expanded:
            continue
        fate, age_days = _judge(item, profile, source, moment)
        fates[item.memory_id] = fate

        if fate is _Fate.FULL:
            kept.append(item)
        elif fate is _Fate.GIST:
            kept.append(item.model_copy(update={"detail_withheld": True}))
        else:
            withheld.append(_withhold(item, profile, age_days))

    for item in trace.retrieved:
        if not item.was_expanded:
            continue
        parent_fate = fates.get(item.linked_from) if item.linked_from else None
        if parent_fate is _Fate.FULL or parent_fate is None:
            kept.append(item)
        else:
            withheld.append(
                WithheldMemory(
                    memory_id=item.memory_id,
                    memory_type=item.memory_type,
                    summary=item.summary,
                    cue_strength=item.components.keyword_overlap,
                    age_days=0,
                    reason="connected to a memory that did not come to mind",
                )
            )

    gist = sum(1 for item in kept if item.detail_withheld)
    gated = len(withheld) - len(trace.withheld)
    if not gist and not gated:
        return trace

    notes = []
    if gated:
        notes.append(f"{gated} recent and weakly cued, kept out of reach")
    if gist:
        notes.append(f"{gist} recalled as gist only")
    return trace.model_copy(
        update={
            "retrieved": kept,
            "withheld": withheld,
            "reason": f"{trace.reason}; {'; '.join(notes)}",
        }
    )


def _judge(
    item: RetrievedMemory,
    profile: CognitiveProfile,
    source: MemorySource,
    moment: datetime,
) -> tuple[_Fate, int]:
    memory = source.get(item.memory_id)
    age_days = _age_days(memory, moment)
    if age_days is None or age_days >= profile.recall.recent_window_days:
        return _Fate.FULL, age_days or 0

    cue = item.components.keyword_overlap
    if cue >= profile.recall.detail_threshold:
        return _Fate.FULL, age_days
    if cue >= profile.recall.cue_threshold:
        return _Fate.GIST, age_days
    return _Fate.WITHHELD, age_days


def _age_days(memory: Memory | None, moment: datetime) -> int | None:
    """How old the memory is — or None for the kinds the gate must never touch."""
    if memory is None:
        return None

    if isinstance(memory, EpisodicMemory):
        anchor = (
            datetime.combine(memory.occurred_on, time(), tzinfo=UTC)
            if memory.occurred_on is not None
            else memory.created_at
        )
    elif isinstance(memory, SemanticMemory) and memory.subject.casefold() != SELF:
        anchor = memory.created_at
    else:
        # Authored self-facts, improvised everyday details, relationships: her
        # life, not a recent event. Ageless as far as this gate is concerned.
        return None

    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    return max(0, (moment - anchor).days)


def _withhold(item: RetrievedMemory, profile: CognitiveProfile, age_days: int) -> WithheldMemory:
    cue = item.components.keyword_overlap
    return WithheldMemory(
        memory_id=item.memory_id,
        memory_type=item.memory_type,
        summary=item.summary,
        cue_strength=cue,
        age_days=age_days,
        reason=(
            f"recent ({age_days}d old) and only weakly cued "
            f"({cue:.2f} < {profile.recall.cue_threshold:.2f})"
        ),
    )
