"""The place-orientation gate: degrading *where she is*, at the retrieval seam.

The recall gate (`impairment.recall`) degrades recent memory by age. It deliberately
never touches her authored life — and her home address is authored (`subject: self`,
`attribute: city`), ageless, so "where do you live?" always works. That is right for
CDR 0.5 and CDR 1, where orientation to place is intact.

But from CDR 2 place orientation frays, and CDR 3 loses it. The clock frame in
`impairment.voice` stops *asserting* where she is — yet the drive showed that is not
enough: asked "where are you right now?", the model retrieves the residence memory and
recites it as fact ("a third-floor walk-up in Jamaica Plain"), the address standing in
for a present orientation she no longer has. A prompt cannot talk the model out of a
memory it has been handed — the same lesson `disfluency` and `comprehension` already
learned. So the deficit is delivered where the memory lives: this gate degrades the
*self-location* memory in the trace, exactly as the recall gate degrades a recent one.

- ``hazy`` (CDR 2) — the residence is **hedged**: she still believes she is home but
  cannot be sure ("I believe I'm at home"). The content stands; the certainty does not.
- ``lost`` (CDR 3) — the residence is **withheld**: she cannot place herself at all,
  and says so ("I don't know where I am"). Withheld, not falsified — it moves to
  `trace.withheld` with its reason, so the failure is explained and never silent, and
  `memory_is_silent` stays false so no improvisation fills the gap.

Bounded like every mechanism here. It touches only the *current* residence
(`_LOCATION_ATTRS`), never the childhood *hometown* — remote memory is preserved, so
"where did you grow up?" still surfaces its fragment. It withholds and hedges; it never
manufactures a false place. It rolls no die: the degradation is a property of the
profile, constant for the turn. Healthy, CDR 0.5 and CDR 1 (`place: confident`) are a
no-op by construction.
"""

from __future__ import annotations

from personasim.impairment.profile import CognitiveProfile
from personasim.models.memory import SemanticMemory
from personasim.models.trace import MemoryTrace, RetrievedMemory, WithheldMemory
from personasim.retrieval.source import MemorySource

#: Semantic-memory attributes that name *where she is now* — her current home or
#: whereabouts. A curated set, like `disfluency._SKIP`: it must catch the residence
#: and must NOT catch `hometown` (her childhood home is remote memory, preserved at
#: every stage) or any other biographical fact.
_LOCATION_ATTRS = frozenset(
    {"city", "residence", "home", "address", "location", "lives_in", "whereabouts"}
)


def apply_place_gate(
    trace: MemoryTrace, profile: CognitiveProfile, source: MemorySource
) -> MemoryTrace:
    """Degrade the self-location memory to match orientation to place.

    `confident` (healthy through CDR 1) returns the trace untouched.
    """
    place = profile.orientation.place
    if place == "confident" or not trace.retrieved:
        return trace

    kept: list[RetrievedMemory] = []
    withheld: list[WithheldMemory] = list(trace.withheld)
    hedged_ids: set[str] = set()
    withheld_ids: set[str] = set()

    # Direct matches first, then expansions — an expansion's fate is its parent's.
    # A memory pulled in to *explain* where she lives (the dated "I moved to Jamaica
    # Plain") names the place just as squarely, so if the residence it hangs off is
    # gone or hedged, so is it. This is the recall gate's two-pass shape, reused.
    for item in trace.retrieved:
        if item.was_expanded:
            continue
        if not _is_self_location(item, source):
            kept.append(item)
            continue
        if place == "hazy":
            # Keep it, but strip her certainty: "I believe I'm home", not a recital.
            kept.append(item.model_copy(update={"hedged": True}))
            hedged_ids.add(item.memory_id)
        else:  # lost
            withheld.append(_withhold(item))
            withheld_ids.add(item.memory_id)

    for item in trace.retrieved:
        if not item.was_expanded:
            continue
        if item.linked_from in withheld_ids:
            withheld.append(_withhold(item))
        elif item.linked_from in hedged_ids:
            kept.append(item.model_copy(update={"hedged": True}))
        else:
            kept.append(item)

    if not hedged_ids and not withheld_ids:
        return trace

    note = (
        "orientation: where-she-is "
        + ("hedged" if place == "hazy" else "withheld")
        + " — disoriented to place"
    )
    return trace.model_copy(
        update={"retrieved": kept, "withheld": withheld, "reason": f"{trace.reason}; {note}"}
    )


def _is_self_location(item: RetrievedMemory, source: MemorySource) -> bool:
    memory = source.get(item.memory_id)
    return (
        isinstance(memory, SemanticMemory)
        and memory.subject == "self"
        and memory.attribute in _LOCATION_ATTRS
    )


def _withhold(item: RetrievedMemory) -> WithheldMemory:
    return WithheldMemory(
        memory_id=item.memory_id,
        memory_type=item.memory_type,
        summary=item.summary,
        cue_strength=item.components.keyword_overlap,
        age_days=0,
        reason="disoriented to place: cannot say where she is",
    )
