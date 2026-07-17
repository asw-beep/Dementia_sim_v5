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

# CDR 3: speech has grown simple. This is a *register*, not a deficit, which is why
# the seam may carry it — the word-finding lesson (a prompt cannot make a capable
# model fail at something it can do) does not apply to an instruction the model
# follows willingly, like the speech manner the seed already delivers this way. Two
# guards, both learned elsewhere: describe the manner, quote nothing (a sample phrase
# becomes a catchphrase); and forbid the caricature in both directions — no babbling
# or performed confusion, and no decorated fluency. If a drive shows the model
# declines the register, the fallback is mechanical, and must be earned by that
# transcript — see docs/design/sprint4_cdr3.md.
SIMPLE_SPEECH = (
    "Your speech has grown simple. Short sentences, plain everyday words, one "
    "thought at a time — the long, fluent sentences you once made do not come any "
    "more. Answer in a few short sentences at most, often fewer, and it is natural "
    "for you to trail off or leave a thought unfinished. Do not perform confusion "
    "and do not babble: the words you do say are ordinary, clear, and your own — "
    "there are simply fewer of them, said more plainly."
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
        SIMPLE_SPEECH if profile.speech.simplified_language else "",
    ]
    return "\n\n".join(part for part in parts if part)


def render_now_impaired(profile: CognitiveProfile, when: datetime | None = None) -> str | None:
    """The clock and the setting, as she experiences them — or None to leave
    `render_now` alone.

    Three axes, degraded a sprint apart, composed here into one frame:

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
    - ``lost`` (CDR 3) — the month, the year and the season go too. The frame asserts
      the one thing that still holds — who she herself is — and nothing about when or
      where. Orientation to person only, and familiar surroundings no longer hold her.

    Person (``person``):

    - ``unfamiliar`` (CDR 3) — *who she is speaking with* is withheld from the frame:
      recognition does not reliably come. What is never withheld is the I/you split —
      she always knows the speaker is someone else — and what is expressly forbidden
      is resolving a blank by inventing an identity. Unfamiliarity is honest;
      misidentification would manufacture a false fact about a closed cast.

    None of it needs a probability: the haze is constant, and it only shows when
    someone asks — which is occasionally.
    """
    time_sense = profile.orientation.day_and_date
    place_sense = profile.orientation.place
    person_known = profile.orientation.person == "confident"
    if time_sense == "confident" and place_sense == "confident" and person_known:
        return None

    now = when or datetime.now()

    # The frame asserts only what still holds. The time of day and the place hold
    # until CDR 2's haze takes them together; the month and year hold until CDR 3's
    # `lost` takes them; recognising the speaker holds until CDR 3's `unfamiliar`.
    # Whatever is degraded is *withheld* from the frame — and so not recitable —
    # exactly as `mistaken` withholds the weekday. What outlasts every stage is
    # orientation to her own person.
    speaker = ", and who you are speaking with" if person_known else ""
    if place_sense == "lost":
        # No date string at all: month, year and season are genuinely gone, so the
        # frame cannot hand them to her. Only her own person is asserted.
        frame = (
            f"You know who you are — your name, your own life{speaker} — with "
            "ordinary, easy confidence. That much is steady.\n"
        )
        coda = (
            "Say all of this as a person would, not as a clock or a map would — "
            "vaguely, in your own words, and never reciting a certainty you do not feel."
        )
    elif place_sense == "hazy":
        frame = (
            f"Right now it is {now.strftime('%B %Y')}. You know the month, the year"
            f"{speaker} — with ordinary, easy confidence.\n"
        )
        coda = (
            "Say all of this as a person would, not as a clock or a map would — "
            "vaguely, in your own words, and never reciting a certainty you do not feel."
        )
    else:
        frame = (
            f"Right now it is {now.strftime('%B %Y')}, and the time is "
            f"{now.strftime('%-I:%M %p').lower()}. You know the month, the year, the "
            f"time of day, where you are{speaker} — with ordinary, "
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

    if place_sense == "hazy":
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
    elif place_sense == "lost":
        # Place is gone, familiar surroundings included — the CDR 2 haze deepened past
        # its anchor. Still withheld, never falsified: she says she does not know, or
        # offers a guess she marks as one; she is never told she is somewhere she is not.
        parts.append(
            "And you no longer know where you are. Even a room that should be familiar "
            "does not tell you where you are or how you came to be in it, and the time "
            "of day — morning, evening — is gone with it; you could not say whether it "
            "is early or late. You may still know your own address as a fact — the "
            "street, the town you have lived in for years — but knowing where you live "
            "is not the same as knowing where you are now, and mostly you are not sure "
            "that you are there. So asked where you are at this moment, do NOT simply "
            "recite your address as though it answered the question; say instead that "
            "you are not certain where you are — you might name the home you know and "
            "add that you cannot be sure this is it, or simply say it has gone from you. "
            "Asked the time, the month, the season, answer the same way: say plainly "
            "that you do not know, or offer a guess and let it be a guess, rather than "
            "reaching for a certainty you no longer have. Sometimes the gap unsettles "
            "you and you may say so; sometimes it does not — either is honest. What you "
            "never do is state a place or an hour as fact when you do not truly have it.\n"
        )

    if not person_known:
        # The last axis. Who the speaker is is withheld, never the fact that someone is
        # speaking and never the I/you split — she always knows the speaker is not her.
        # And a blank is answered with honest unfamiliarity, never a manufactured
        # identity: not knowing who someone is, is the truth; deciding who they are is
        # the confabulation the whole layer forbids.
        parts.append(
            "And who you are speaking with does not always come to you. This person is "
            "here and talking with you, and you answer them warmly — but you may not "
            "know who they are, or whether you have met them before, and often you do "
            "not. When their name or how you know them will not come, say so plainly — "
            "'I'm sorry, I don't quite know who you are' — rather than pretending to "
            "place them; it may unsettle you a little, or it may not, and either is "
            "honest. Never decide they are someone in particular — a daughter, a "
            "friend, someone from your past — when you do not truly know; a wrong name "
            "would be worse than an honest 'I don't know'. Whoever they are, when they "
            "say 'I' they mean themselves and when they say 'you' they mean you: they "
            "are not you, and you never speak as though you were them.\n"
        )

    parts.append(coda)
    return "".join(parts)


def _insight(profile: CognitiveProfile, trace: MemoryTrace) -> str:
    if not profile.insight or not trace.withheld:
        return ""
    return INSIGHT
