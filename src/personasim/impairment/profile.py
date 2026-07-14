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

    `cue_threshold` and `detail_threshold` are compared against the trace's
    `keyword_overlap` score component — the fraction of the question's keywords the
    memory carries, times the keyword rank weight (1.0 by default). A recent memory
    below the cue threshold is withheld; between the thresholds its gist survives
    but its specifics do not; at or above the detail threshold it is recalled in
    full. A window of zero days makes nothing recent, which is what healthy means.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    recent_window_days: int = Field(default=0, ge=0)
    cue_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    detail_threshold: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _thresholds_are_ordered(self) -> Self:
        if self.detail_threshold < self.cue_threshold:
            raise ValueError(
                f"detail_threshold ({self.detail_threshold}) must be at least "
                f"cue_threshold ({self.cue_threshold}): a memory cued too weakly to "
                "recall cannot be cued strongly enough to recall in full"
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

    Deterministic on purpose: word-finding fires every Nth turn, and the
    long-question note fires when the caregiver's message has more parts than she
    can hold. Zero disables either, which is what healthy means.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    word_finding_every_n_turns: int = Field(default=0, ge=0)
    long_question_clauses: int = Field(default=0, ge=0)


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

    @property
    def gates_recall(self) -> bool:
        return self.recall.recent_window_days > 0


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
