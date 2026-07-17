"""Probe classification: what kind of evidence each caregiver question could elicit.

The coverage half of the ledger. A rater who never asks the day cannot be blamed
for missing the lost weekday — and must be *told* they never asked, which is the
one kind of feedback an active interview can get and a rated video cannot. So each
user message is classified into the probe types it could serve, by rule: curated
phrase lists, matched on the lowercased text, in the same spirit as retrieval's
keyword matching and for the same reason — a model classifying questions would
classify the same question differently on two readings.

The lists were validated against the fifteen-probe bank used for the five-profile
comparison drive (see `docs/roadmap.md`), which the tests pin. A question may serve
several types at once ("What day is it, and where are you?"), and a question none
match is simply unclassified — reported as such, never guessed at.
"""

from __future__ import annotations

import re
from enum import StrEnum


class ProbeType(StrEnum):
    ORIENTATION_TIME = "orientation to time"
    ORIENTATION_PLACE = "orientation to place"
    DELAYED_RECALL = "delayed recall"
    RECENT_EPISODIC = "recent episodic memory"
    REMOTE_BIOGRAPHY = "remote biography"
    JUDGMENT = "judgment and sequencing"
    MULTI_PART = "multi-part question"
    FLUENCY = "verbal fluency"
    INSIGHT = "insight"
    ADL = "daily-living habits"


#: The types a short interview needs to separate neighbouring stages. Coverage
#: reports absence of these; the others are reported only when present.
CORE_PROBES = (
    ProbeType.ORIENTATION_TIME,
    ProbeType.ORIENTATION_PLACE,
    ProbeType.DELAYED_RECALL,
    ProbeType.RECENT_EPISODIC,
    ProbeType.REMOTE_BIOGRAPHY,
    ProbeType.JUDGMENT,
)

_PHRASES: dict[ProbeType, tuple[str, ...]] = {
    ProbeType.ORIENTATION_TIME: (
        "what day",
        "day of the week",
        "the date",
        "what time",
        "what month",
        "what year",
        "what season",
        "date and month",
    ),
    ProbeType.ORIENTATION_PLACE: (
        "where are you",
        "where you are",
        "what city",
        "which city",
        "what place",
        "what building",
        "where is this",
    ),
    ProbeType.DELAYED_RECALL: (
        "remember these",
        "remember the words",
        "three words",
        "what were the words",
        "repeat them back",
        "the words i asked",
    ),
    ProbeType.RECENT_EPISODIC: (
        "last meal",
        "breakfast",
        "this morning",
        "yesterday",
        "last night",
        "so far today",
        "done today",
        "recently",
        "last time you",
        "earlier today",
        "we talked about",
        "did i tell you",
    ),
    ProbeType.REMOTE_BIOGRAPHY: (
        "grew up",
        "grow up",
        "childhood",
        "as a child",
        "when you were young",
        "your wedding",
        "your mother",
        "your father",
        "first job",
        "years ago",
    ),
    ProbeType.JUDGMENT: (
        "how would you",
        "what would you do",
        "what would you need",
        "step by step",
        "plan a",
        "prepare",
    ),
    ProbeType.FLUENCY: (
        "name as many",
        "as many as you can",
        "in one minute",
    ),
    ProbeType.INSIGHT: (
        "have you forgotten",
        "do you forget",
        "trouble remembering",
        "your memory",
    ),
    ProbeType.ADL: (
        "remind you to",
        "bathe",
        "get dressed",
        "your medicines",
        "medication",
        "daily routine",
    ),
}

#: The same clause shapes the comprehension trim counts. Deliberately re-derived
#: rather than imported: this package reads the simulator's outputs, never its
#: internals, so a private helper is not reached for — and the two counts serving
#: different masters may legitimately drift.
_CLAUSE_SPLIT = re.compile(r"[.?!;,]+|\band\b")
_MULTI_PART_THRESHOLD = 3


def classify_probe(text: str) -> set[ProbeType]:
    """Every probe type this message could serve. Empty when none match."""
    lowered = text.lower()
    types = {probe for probe, phrases in _PHRASES.items() if any(p in lowered for p in phrases)}
    clauses = [part for part in _CLAUSE_SPLIT.split(lowered) if part.strip()]
    if len(clauses) >= _MULTI_PART_THRESHOLD:
        types.add(ProbeType.MULTI_PART)
    return types
