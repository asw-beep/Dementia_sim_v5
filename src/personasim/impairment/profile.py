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

Sureness = Literal["confident", "uncertain", "mistaken"]

#: Orientation to *place*, degraded a sprint later than time. Its own short ladder,
#: not `Sureness`: place has no "uncertain-but-corrects" rung — she either knows
#: where she is or she does not reliably. ``hazy`` is CDR 2's intermittent
#: disorientation (unsure in unfamiliar or changed surroundings, fine at home);
#: ``lost`` is CDR 3's — where she is, and when it is beyond her own person, have
#: gone, familiar surroundings included. The rung `sprint3_cdr2.md` promised.
PlaceSense = Literal["confident", "hazy", "lost"]

#: Recognition of the person she is speaking with — the last orientation axis to
#: fray, at CDR 3. Two rungs only: she either places the speaker easily or does not
#: reliably. ``unfamiliar`` withholds *who this person is*, never the fact that
#: someone is speaking or the I/you split — and failed recognition is honest
#: unfamiliarity, never a manufactured identity (see `impairment.voice`).
PersonSense = Literal["confident", "unfamiliar"]


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
    """What she is sure of about time, place, and person. Consumed by
    `impairment.voice`.

    Three axes, degraded a sprint apart. **Time** (`day_and_date`) frays first, at
    CDR 0.5; **place** frays at CDR 2 and goes at CDR 3; **person** — recognition of
    who she is speaking with — frays last, at CDR 3. What never degrades is
    orientation to her *own* person: knowing who she herself is outlasts every stage
    on the scale.

    Time — `day_and_date`:

    - ``confident`` — healthy. The clock is exactly what `render_now` tells it.
    - ``uncertain`` — CDR 0.5. She knows the weekday is slippery and second-guesses
      herself, but the truth is still handed to her and she lands on the right day,
      or near it. Confidence degraded, fact intact.
    - ``mistaken`` — CDR 1. Time has come loose. The exact weekday and date are
      *withheld* from the clock she is handed, so she cannot read them off: she
      offers the day she believes it is — sometimes wrong — or admits she has lost
      track, and does **not** perform the tidy self-correction that arrives at the
      right answer. This is disorientation, not a fabricated fact: nothing false is
      injected, and orientation is stored nowhere, so no memory is touched.

    Place — `place`:

    - ``confident`` — healthy through CDR 1. She knows where she is, easily.
    - ``hazy`` — CDR 2. She is oriented in familiar surroundings but grows unsure
      when they are unfamiliar or have changed — and the same haze runs the parts of
      the day together (morning for afternoon). Like the clock, this *withholds* the
      easy confidence the frame otherwise asserts; it never puts a false place in her
      mouth, and stores nothing. A constant "where am I?" is CDR 3, not this.
    - ``lost`` — CDR 3. Orientation to her own person only: where she is, how she
      came to be there, the part of day, the month and the season are withheld from
      the frame even in familiar surroundings. Same discipline — withheld, never
      falsified, stored nowhere.

    Person — `person`:

    - ``confident`` — healthy through CDR 2. She knows who she is speaking with.
    - ``unfamiliar`` — CDR 3. *Who* the speaker is does not reliably come to her.
      The frame withholds the easy recognition, keeps the I/you split intact (she
      always knows the speaker is not herself), and forbids resolving the blank by
      inventing an identity — unfamiliarity is honest; misidentification would
      manufacture a false fact about a closed cast, at any severity.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    day_and_date: Sureness = "confident"
    place: PlaceSense = "confident"
    person: PersonSense = "confident"


class WorkingMemoryHold(BaseModel):
    """How the live conversation fades in RAM. Consumed by `impairment.hold`.

    This is what makes a *delayed*-recall probe mean anything — "remember these
    three words… now, what were they?", the single most diagnostic question in the
    CDR interview. A hard window could only ever answer it two ways: the three
    words sat *verbatim in the prompt* and she read them straight back, or the turn
    had scrolled out and she had **nothing** — "I don't remember any words". Both
    are wrong for CDR 0.5, where immediate registration is intact and it is
    *retention across a delay* that frays. A clinician looks for the pattern in
    between: *2 of 3, or 1 of 3 with a nudge from a cue* — early Alzheimer's, drawn
    to the life.

    So retention is graded, not a cliff. The last `crisp_turns` exchanges are held
    whole — immediate registration, and the thread of what is being said right now,
    are preserved. Older exchanges fade *word by word*, more of them lost the
    further back they were, until at `crisp_turns + fade_turns` the exchange is gone
    from RAM entirely. A three-word list given a few turns ago comes back in part;
    a cue ("it was a colour") is a fresh, unfaded turn that helps her land the rest.

    Which words fade is hashed, never rolled (see `impairment.hold`), so a session
    replays identically. Nothing here touches long-term memory: a fact worth keeping
    left the transcript through memory formation long ago, and is gated — if at all —
    by the recall ladder, not by this.

    Both zero (the healthy default) is a no-op: no fade, and the window is left at
    `settings.working_memory_turns` exactly as Phase 1 set it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The most recent exchanges, held verbatim. Immediate registration is intact
    #: at CDR 0.5; this is the span over which it stays that way.
    crisp_turns: int = Field(default=0, ge=0)
    #: Exchanges older than the crisp span fade progressively over this many turns —
    #: more lost the further back — and beyond it are gone from RAM.
    fade_turns: int = Field(default=0, ge=0)

    @property
    def fades(self) -> bool:
        return self.crisp_turns > 0 or self.fade_turns > 0

    @property
    def capacity(self) -> int | None:
        """Turns to keep in RAM, or None to leave the healthy window alone."""
        return self.crisp_turns + self.fade_turns if self.fades else None


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
    #: CDR 3: speech has grown simple — short sentences, plain words, one thought at
    #: a time. A register, not a deficit, which is why the prompt seam may carry it
    #: (see `impairment.voice.SIMPLE_SPEECH` and `sprint4_cdr3.md`).
    simplified_language: bool = False


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

    #: How the live conversation fades in RAM. The healthy default holds nothing
    #: back; a profile that sets it turns the delayed-recall probe from free (the
    #: words sit verbatim in the prompt) into real (they fade, and come back in
    #: part). See `WorkingMemoryHold`.
    hold: WorkingMemoryHold = WorkingMemoryHold()

    @property
    def gates_recall(self) -> bool:
        return self.recall.recent_window_days > 0

    @property
    def degrades_place(self) -> bool:
        """Whether orientation to place is degraded — the place gate has work to do."""
        return self.orientation.place != "confident"

    @property
    def is_impaired(self) -> bool:
        """Whether this profile changes anything at all."""
        return (
            self.gates_recall
            or self.insight
            or self.hold.fades
            or self.orientation.day_and_date != "confident"
            or self.orientation.place != "confident"
            or self.orientation.person != "confident"
            or self.speech.word_finding_probability > 0
            or self.speech.simplified_language
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
