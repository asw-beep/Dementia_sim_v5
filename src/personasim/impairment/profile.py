"""Cognitive profiles: severity as data, not code.

A profile is a set of parameters, loaded from YAML exactly as personas are loaded
from seed files. No symptom is hardcoded and none is branched on by name — a later
stage is a different file, not a different code path, and a random patient is
nothing more than *load persona + load profile*.

The healthy profile is a no-op **by construction**, not by special case: a recall
window of zero days gates nothing, a word-finding cadence of zero never fires, and
`day_and_date: confident` leaves the clock exactly as `render_now` tells it. The
regression argument for the whole layer rests on this — impairment that can be
switched off to *nothing* is a wrapper; anything else is an edit.

Every field here has a consumer. A profile parameter nothing reads is a lie in a
config file, so domains without a mechanism yet (judgement, home and hobbies,
personal care) are deliberately absent until the sprint that gives them one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

Sureness = Literal["confident", "uncertain"]


class ProfileError(Exception):
    """The profile file is missing, unreadable, or not a possible profile."""


class RecallGate(BaseModel):
    """How recent memory is gated. Consumed by `impairment.recall`.

    A recent memory's *reach* is `encoding + cue_weight * cue`:

    - **encoding** — how well this memory was laid down, in [0, 1). Not a die roll:
      a hash of (session, memory), so it is fixed for a given memory within a
      session, varies between memories, and varies across visits. Reproducible by
      construction — replay a session and it fails identically — which is what a
      clinical validation needs and what a `random.random()` could never give.
    - **cue** — `keyword_overlap`: how squarely the question reached for it.

    Reach then falls on a ladder, and the top rung matters as much as the bottom:

        reach < withhold_below   → not recalled at all
        reach < gist_below       → the gist, without its specifics
        otherwise                → recalled, but **hedged** — never crisp

    A recent memory is *never* recalled with full confidence, however hard it is
    cued. That is the correction the first CDR 0.5 drive forced: with a crisp top
    rung, a direct question ("what did you have for breakfast?") cues at 1.0 and
    was answered perfectly every time, and a clinical interview asks nothing but
    direct questions. The impairment was aimed squarely at the questions a
    clinician never asks.

    A window of zero days makes nothing recent, which is what healthy means.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    recent_window_days: int = Field(default=0, ge=0)
    #: Below this reach, the memory does not come to mind at all.
    withhold_below: float = Field(default=0.0, ge=0.0, le=2.0)
    #: Below this reach, the gist survives but the specifics do not.
    gist_below: float = Field(default=0.0, ge=0.0, le=2.0)
    #: How much a squarely-aimed question helps. This is gentle cueing, and it is
    #: the mechanism itself rather than a simulation of one: a more specific
    #: question raises `cue`, which raises reach, which climbs the ladder.
    cue_weight: float = Field(default=0.0, ge=0.0, le=2.0)

    @model_validator(mode="after")
    def _thresholds_are_ordered(self) -> Self:
        if self.gist_below < self.withhold_below:
            raise ValueError(
                f"gist_below ({self.gist_below}) must be at least withhold_below "
                f"({self.withhold_below}): a memory too far out of reach to recall "
                "cannot be within reach of recalling as gist"
            )
        return self


class Orientation(BaseModel):
    """What she is sure of about time and place. Consumed by `impairment.voice`.

    Only the weekday and exact date can be uncertain at this severity — month,
    year, place, and the person she is speaking with stay confident, and gain
    fields only in the sprint that degrades them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    day_and_date: Sureness = "confident"


class Speech(BaseModel):
    """The cadence of speech-level difficulty. Consumed by `impairment.voice`.

    Probabilities, not a fixed cadence — but hashed, not rolled, so a session
    replays identically. "Every 4th turn" was the first attempt and it was both
    too regular to be human and, as the first drive showed, too weak to be obeyed:
    a soft note buried in a long prompt produced *zero* word-finding in twenty
    turns. Frequency is now a probability and the instruction is imperative.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Chance, per reply, that one word will not come. Clinically 5-10%.
    word_finding_probability: float = Field(default=0.0, ge=0.0, le=1.0)
    #: A message with more parts than this may overrun what she can hold at once.
    long_question_clauses: int = Field(default=0, ge=0)
    #: Chance she actually loses the thread of such a message, rather than coping.
    long_question_probability: float = Field(default=0.0, ge=0.0, le=1.0)


class CognitiveProfile(BaseModel):
    """One severity, complete: everything the impairment layer may do, as data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    label: str = ""
    recall: RecallGate = RecallGate()
    orientation: Orientation = Orientation()
    speech: Speech = Speech()
    #: Preserved insight: she knows recent things have been slipping, and may say
    #: so at the moment a memory fails her. A clinical feature, not a leak.
    insight: bool = False

    #: How many turns of the live conversation she can hold. `None` leaves the
    #: healthy window (`settings.working_memory_turns`) alone.
    #:
    #: This is what makes a delayed-recall probe mean anything. Three words given
    #: at turn three and asked for at turn nine were sitting *verbatim in the
    #: prompt*, so she read them straight back — a perfect score on the single most
    #: diagnostic question in the CDR interview, produced by a transcript window
    #: rather than by memory. Shortening the window is what turns that probe from
    #: free into real.
    working_memory_turns: int | None = Field(default=None, gt=0)

    @property
    def gates_recall(self) -> bool:
        return self.recall.recent_window_days > 0

    @property
    def is_impaired(self) -> bool:
        """Whether this profile changes anything at all."""
        return (
            self.gates_recall
            or self.insight
            or self.working_memory_turns is not None
            or self.orientation.day_and_date != "confident"
            or self.speech.word_finding_probability > 0
        )


#: The profile that changes nothing. `Conversation` defaults to it, so every
#: Phase 1 call site keeps its exact behaviour without being touched.
HEALTHY = CognitiveProfile(name="healthy", label="Healthy — nothing is gated")


def load_profile(path: Path) -> CognitiveProfile:
    """Read a profile from YAML, or say precisely why it cannot be one."""
    try:
        raw = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ProfileError(f"cannot read profile {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ProfileError(f"{path} is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ProfileError(f"{path} must be a mapping of profile fields")

    try:
        return CognitiveProfile.model_validate(raw)
    except ValueError as exc:
        raise ProfileError(f"{path} is not a possible profile: {exc}") from exc
