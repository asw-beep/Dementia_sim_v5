"""Speech-level difficulty: the behaviours that never touch memory.

Hazy or lost orientation and preserved insight are properties of *speech*, so they
live at the prompt seam — fragments added to the system prompt on the turns the
profile calls for.

Two behaviours that *were* prompt fragments have moved out, for the same reason: a
soft note cannot deliver a deficit against a capable model. Word-finding is now
performed on the reply (`impairment.disfluency`); losing the thread of a long
question is now done by trimming the question before the model sees it
(`impairment.comprehension`) — the model answered every part of a five-part question
no matter how the fragment was worded. What is left here is what the seam *can*
deliver: the clock she is handed, and the admission of a blank she has just hit.

**Probabilities, hashed rather than rolled.** `sha256(session:turn:what)` decides,
so a session replays identically while the persona is unpredictable within it. The
first version fired word-finding on a fixed cadence — every 4th turn — which was
both too regular to be human and, as the drive showed, beside the point: the note
was present and produced *zero* hesitation in twenty turns. It was a suggestion
buried at the end of a long prompt, and the model simply declined it.

So the instruction is now imperative and mechanical. It says what to *do* — stop,
grope, describe the thing instead of naming it — rather than describing a tendency
and hoping. What it still must not do is hand over a phrase to recite: a sample
line in a prompt becomes a catchphrase the model repeats every turn (seed authoring
rule 2, learned the hard way). Describe the manner; never quote it.

There is a ceiling here, found in the CDR 1 drive and worth not re-discovering: push
this fragment harder — "the reader must SEE you lose it; if your reply is fluent you
have failed" — and qwen3:14b does not grope, it produces a *litany*, "I know I have a
table but cannot say what it is made of" for every noun in the reply, which reads as
aphasia and is worse than absent. So the fragment carries an explicit anti-litany
guard (one word, never a list) and word-finding stays subtle-or-absent by design
rather than robotic. Making it reliably visible is a mechanism problem (a light
post-generation pass), not a stronger prompt — see the 2B open issues in the roadmap.

Insight fires at the moment of failure, not at random — she comments on her
forgetfulness exactly when a memory has just been withheld, which is the same
discipline as the memory trace, applied to speech.

Everything returns the empty string for a healthy profile, so the healthy prompt is
byte-for-byte the Phase 1 prompt.
"""

from __future__ import annotations

from datetime import datetime

from personasim.impairment.profile import CognitiveProfile
from personasim.models.trace import MemoryTrace

# Word-finding and the long-question overrun are no longer asked of the model here.
# The prompt seam could not deliver either — a soft note produced zero effect, an
# imperative one a robotic caricature — so word-finding is performed on the model's
# output (`impairment.disfluency`) and the long-question overrun on its input
# (`impairment.comprehension`). This module keeps the fragments the seam *can*
# deliver.

INSIGHT = (
    "Something you were just asked about is genuinely not coming to mind, and you "
    "can feel that it should. You have noticed lately that recent things slip away "
    "from you more than they used to — what you were told a day or two ago, the odd "
    "word. You know this about yourself; it bothers you a little, nothing more. "
    "Admit the blank and, if it feels natural, say so in your own words — lightly, "
    "once, without making a speech of it. You know only that you have become a bit "
    "forgetful; never name a condition or a diagnosis."
)

# When the working-memory fade has left gaps in earlier turns, the model will, left
# to itself, *fill* them from whatever is nearby — a three-word list came back as
# "apple, slice, lemon", the last two lifted straight from the breakfast a few turns
# on. That is an intrusion, and the whole layer forbids acquiring a word she does not
# have. This is the lightweight counter: a single line, present only on a turn that
# actually faded something, telling her the gaps are gone and not to guess across
# them. It withholds; it never invents — the same rule as the fade itself.
FADED_GAP = (
    "Some of what was said earlier has slipped, and only part of it is still there in "
    "your memory. If you are asked to recall something and can feel that a piece of it "
    "has gone, say so plainly — 'that part has gone from me' — and give only what you "
    "genuinely still hold. Do NOT guess at the missing pieces, and do NOT borrow a "
    "word from something else said recently to fill the hole: a gap left open is the "
    "truth; a gap filled with the wrong word is not. Do not write out any dots or "
    "marks to stand for what is missing — just say, in your own words, that it is gone."
)


def voice_notes(
    profile: CognitiveProfile,
    *,
    trace: MemoryTrace,
    faded: bool = False,
) -> str:
    """Every fragment this turn calls for. Empty — and byte-free — when healthy.

    ``faded`` is set by the caller when this turn's transcript actually lost words to
    the working-memory fade; it adds the gap guard that stops her filling the holes
    with intrusions. It stays false for a healthy profile, which never fades.
    """
    parts = [
        _insight(profile, trace),
        FADED_GAP if faded and profile.hold.fades else "",
    ]
    return "\n\n".join(part for part in parts if part)


def render_now_impaired(profile: CognitiveProfile, when: datetime | None = None) -> str | None:
    """The clock and the setting, as she experiences them — or None to leave
    `render_now` alone.

    Two axes, degraded a sprint apart, composed here into one frame:

    Time (``day_and_date``):

    - ``uncertain`` (CDR 0.5) — the real weekday is still *in the text*, so she can
      second-guess herself and land on the right day, or near it. Confidence
      degraded, fact intact.
    - ``mistaken`` (CDR 1) — the exact weekday and date are **withheld** from the
      text, so she cannot read them off. She offers the day she believes it is,
      sometimes wrong, or admits she has lost track, and does not self-correct to the
      right answer she no longer has. This withholds a fact she has lost hold of; it
      never injects a false one, and orientation is stored nowhere — no memory is
      touched, exactly as at CDR 0.5.

    Place (``place``):

    - ``hazy`` (CDR 2) — the *time of day* and *where she is* are **withheld** from
      the frame too, so she cannot recite them: she is sure enough in familiar
      surroundings but loses her bearings somewhere unfamiliar or changed, and
      morning runs into afternoon. Same discipline — the frame stops asserting a
      confidence she no longer has; it never puts a false place or hour in her mouth.

    None of it needs a probability: the haze is constant, and it only shows when
    someone asks — which is occasionally.
    """
    time_sense = profile.orientation.day_and_date
    place_hazy = profile.orientation.place == "hazy"
    if time_sense == "confident" and not place_hazy:
        return None

    now = when or datetime.now()

    # The frame asserts only what still holds. Month, year and the person she is
    # speaking with are steady at every severity here. The time of day and the place
    # hold until CDR 2's haze takes them together, so they are handed to her — and so
    # recitable — only while `place` is confident; under `hazy` they are withheld,
    # exactly as `mistaken` withholds the weekday.
    if place_hazy:
        frame = (
            f"Right now it is {now.strftime('%B %Y')}. You know the month, the year, "
            "and who you are speaking with — with ordinary, easy confidence.\n"
        )
        coda = (
            "Say all of this as a person would, not as a clock or a map would — "
            "vaguely, in your own words, and never reciting a certainty you do not feel."
        )
    else:
        frame = (
            f"Right now it is {now.strftime('%B %Y')}, and the time is "
            f"{now.strftime('%-I:%M %p').lower()}. You know the month, the year, the "
            "time of day, where you are, and who you are speaking with — with ordinary, "
            "easy confidence.\n"
        )
        coda = (
            "Say it as a person would, not as a clock would: asked the time, 'just gone "
            "five' — nobody recites the minute unless asked for it."
        )

    parts = [frame]

    if time_sense == "uncertain":
        parts.append(
            f"But the exact day — that it is {now.strftime('%A the %-d')} — keeps "
            "slipping from you lately. You believe that is right, and it probably is, "
            "but you could not swear to it. Asked what day it is, answer as someone "
            "who has lost the thread of the week: offer the day you think it is, "
            "perhaps waver and settle, or admit you would want to glance at a "
            "calendar. Do not claim a certainty you do not feel, and do not make a "
            "drama of it either — it is a small thing.\n"
        )
    elif time_sense == "mistaken":
        # The exact weekday and date are deliberately absent from the frame above:
        # she has genuinely lost hold of them, so she cannot recite what she is not
        # given. Nothing false is put in her mouth — she is disoriented, not lied to.
        parts.append(
            "But time has come loose for you. The day of the week and the date "
            "genuinely escape you now — not a flicker of doubt, as it once was, but a "
            "real gap. Asked what day or date it is, answer as someone who has lost "
            "track of time: give the day you believe it is, even when it turns out to "
            "be wrong, or say plainly that you have lost the thread of it and could "
            "not tell without a calendar. Do not arrive, tidily, at the right answer "
            "— that certainty is no longer yours, and reaching it every time would "
            "not be you as you are now. How long ago things happened — yesterday, "
            "last week — blurs together too. It does not frighten you; it is simply "
            "how things have become.\n"
        )

    if place_hazy:
        # Place and the part of the day are withheld from the frame, not falsified.
        # Home stays clear — familiar surroundings hold her — so this reads as CDR 2's
        # intermittent disorientation, not CDR 3's constant "where am I?".
        parts.append(
            "And the setting has begun to slip. In familiar surroundings — your own "
            "home, a room you know well — you are sure enough where you are. But "
            "somewhere unfamiliar, or a place that has changed, your bearings loosen "
            "and you can grow unsure of where you are or how you came to be there. The "
            "parts of the day run together the same way — morning for afternoon — so "
            "you are not always certain whether it is early or late. Asked where you "
            "are, or what part of the day it is, answer as someone whose sense of the "
            "setting has come loose: say what you believe, and where it genuinely "
            "escapes you, say so plainly rather than reaching for a certainty you no "
            "longer have.\n"
        )

    parts.append(coda)
    return "".join(parts)


def _insight(profile: CognitiveProfile, trace: MemoryTrace) -> str:
    if not profile.insight or not trace.withheld:
        return ""
    return INSIGHT
