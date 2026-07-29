"""The recall gate: how far out of reach a recent memory is.

A recent memory's *reach* is `encoding + cue_weight * cue`, and reach decides
whether it comes back whole, in outline, or not at all. A remote memory is always
reached. This is the whole of very-mild memory impairment in this architecture —
not a new kind of memory, but a gate in front of the existing one.

Two corrections, both forced by the first clinical drive, and both structural
rather than a matter of tuning:

**Her breakfast is a recent memory.** The gate originally exempted every semantic
memory whose subject was `self`, to protect her authored life — and improvised
everyday facts (breakfast, sleep, what she has been doing today) are *also*
subject `self`. So the single most-probed domain in a CDR interview was
structurally immune, and she recalled her morning perfectly every time. What
distinguishes her life from her Tuesday is not the subject but the **provenance**:
an authored memory's id is `uuid5(persona_id:key)`, derived from the seed file,
while anything acquired in conversation carries a random `uuid4`. That is the same
structural marker `persona seed --force` already relies on to tell an authored
memory from a learned one, and it is exactly the line the gate needs. Authored is
her life and is never gated; acquired is her recent past and is.

**A crisp top rung made the gate useless in a clinic.** Reach used to end at
"recalled in full", and a direct question — "what did you have for breakfast?" —
cues at 1.0 and sailed over every threshold. But a clinical interview asks nothing
*but* direct questions, so the impairment was aimed squarely at the questions
nobody asks. A recent memory is now never recalled crisply: the best it does is
`HEDGED` — the content intact, the confidence not.

**Encoding is hashed, not rolled.** `sha256(session:memory)` gives a value in
[0, 1) that is fixed for a memory within a session, differs between memories, and
differs across visits. So she is unreliable the way a person is — some things come,
some do not, and a cue helps — while a replayed session fails *identically*. A
`random.random()` would have bought the same clinical texture and thrown away
reproducibility, which is the one thing a validation cannot do without. (The
invariant test forbidding `random` in this package therefore still stands, and is
not being worked around: there is no RNG here.)

Nothing is forgotten. The memory stays in the database and stays in the persona;
what this gate degrades is *reach*, this turn, for this question. A withheld memory
moves to `trace.withheld` with its arithmetic — never silently dropped, because a
recall failure the trace cannot explain is indistinguishable from a bug.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, time
from enum import Enum, auto

from personasim.impairment.profile import CognitiveProfile
from personasim.models.memory import EpisodicMemory, Memory, MemoryId, SemanticMemory
from personasim.models.trace import MemoryTrace, RetrievedMemory, WithheldMemory
from personasim.retrieval.source import MemorySource

#: A seed file's memories are `uuid5`; anything learned or improvised in
#: conversation is `uuid4`. Authored life versus acquired past, told apart by
#: construction rather than by a column that could drift out of step.
AUTHORED_UUID_VERSION = 5


class _Fate(Enum):
    FULL = auto()
    HEDGED = auto()
    GIST = auto()
    WITHHELD = auto()


def apply_recall_gate(
    trace: MemoryTrace,
    profile: CognitiveProfile,
    source: MemorySource,
    *,
    session_id: str = "",
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
        fate, age_days, reach = _judge(item, profile, source, session_id, moment)
        fates[item.memory_id] = fate

        if fate is _Fate.FULL:
            kept.append(item)
        elif fate is _Fate.HEDGED:
            kept.append(item.model_copy(update={"hedged": True}))
        elif fate is _Fate.GIST:
            kept.append(item.model_copy(update={"detail_withheld": True, "hedged": True}))
        else:
            withheld.append(_withhold(item, profile, age_days, reach))

    for item in trace.retrieved:
        if not item.was_expanded:
            continue
        parent_fate = fates.get(item.linked_from) if item.linked_from else None
        if parent_fate is None or parent_fate is _Fate.FULL or parent_fate is _Fate.HEDGED:
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

    return _rebuilt(trace, kept, withheld)


def _rebuilt(
    trace: MemoryTrace, kept: list[RetrievedMemory], withheld: list[WithheldMemory]
) -> MemoryTrace:
    gated = len(withheld) - len(trace.withheld)
    gist = sum(1 for item in kept if item.detail_withheld)
    hedged = sum(1 for item in kept if item.hedged and not item.detail_withheld)
    if not gated and not gist and not hedged:
        return trace

    notes = []
    if gated:
        notes.append(f"{gated} out of reach")
    if gist:
        notes.append(f"{gist} in outline only")
    if hedged:
        notes.append(f"{hedged} recalled but unsure")

    return trace.model_copy(
        update={
            "retrieved": kept,
            "withheld": withheld,
            "reason": f"{trace.reason}; {', '.join(notes)}",
        }
    )


def _judge(
    item: RetrievedMemory,
    profile: CognitiveProfile,
    source: MemorySource,
    session_id: str,
    moment: datetime,
) -> tuple[_Fate, int, float]:
    memory = source.get(item.memory_id)
    age_days = _age_days(memory, moment)
    if age_days is None or age_days >= profile.recall.recent_window_days:
        return _Fate.FULL, age_days or 0, 1.0

    cue = item.components.keyword_overlap
    reach = _encoding(session_id, item.memory_id) + profile.recall.cue_weight * cue

    if reach < profile.recall.withhold_below:
        return _Fate.WITHHELD, age_days, reach
    if reach < profile.recall.gist_below:
        return _Fate.GIST, age_days, reach
    # Never FULL. A recent memory is reached at best unsurely, however squarely the
    # question aimed at it — which is what a clinician's direct question tests.
    return _Fate.HEDGED, age_days, reach


def _encoding(session_id: str, memory_id: MemoryId) -> float:
    """How well this memory was laid down, in [0, 1).

    A hash, not a die roll. Fixed for a memory within a session, different between
    memories, different across visits — and reproducible, so a replayed session
    fails exactly as it failed the first time.
    """
    digest = hashlib.sha256(f"{session_id}:{memory_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


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
    elif isinstance(memory, SemanticMemory) and _was_acquired(memory.id):
        # Learned in conversation, not authored: a fact the caregiver disclosed, or
        # an everyday detail she improvised. Both are her recent past — and the
        # improvised ones (breakfast, sleep, what she did today) are precisely what
        # a CDR interview probes. Anchored on `created_at`, which for these *is* the
        # moment she acquired them.
        anchor = memory.created_at
    else:
        # Her authored life: who she is, where she lives, the people in it. Ageless
        # as far as this gate is concerned, at any `created_at` — a persona seeded
        # five minutes ago must not have forgotten where she lives.
        return None

    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=UTC)
    return max(0, (moment - anchor).days)


def _was_acquired(memory_id: MemoryId) -> bool:
    """True for a memory learned in conversation, false for one the seed authored.

    Authored ids are `uuid5(persona_id:key)` and derive from the seed file itself;
    a formed or improvised memory carries a random `uuid4`. Provenance is therefore
    a property of the id's *shape*, needing no column that could fall out of step
    with the truth — the same guarantee `persona seed --force` already leans on.
    """
    try:
        return uuid.UUID(memory_id).version != AUTHORED_UUID_VERSION
    except ValueError:
        return False


def _withhold(
    item: RetrievedMemory, profile: CognitiveProfile, age_days: int, reach: float
) -> WithheldMemory:
    cue = item.components.keyword_overlap
    return WithheldMemory(
        memory_id=item.memory_id,
        memory_type=item.memory_type,
        summary=item.summary,
        cue_strength=cue,
        age_days=age_days,
        reason=(
            f"recent ({age_days}d) and poorly laid down: reach {reach:.2f} "
            f"< {profile.recall.withhold_below:.2f} (cue {cue:.2f})"
        ),
    )
