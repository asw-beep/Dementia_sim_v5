"""Speech-level difficulty: the behaviours that never touch memory.

Word-finding, losing the thread of a long question, hazy or lost orientation, and
preserved insight are properties of *speech*, so they live at the prompt seam —
fragments added to the system prompt on the turns the profile calls for.

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

import hashlib
import re
from datetime import datetime

from personasim.impairment.profile import CognitiveProfile
from personasim.models.trace import MemoryTrace

WORD_FINDING = (
    "ONE ordinary word will not come to you in this reply. Not a name and not "
    "anything from your past — a plain, everyday noun: the object in your hands, "
    "the room you are in, the thing you were about to mention.\n"
    "When you reach it, stop. Do not push past it and do not quietly choose an "
    "easier word — that is what a fluent person does, and you are not managing it "
    "today. Grope for it in the open: break off, describe the thing by what it does "
    "or what it is for, try a word that is nearly right, and either arrive at it or "
    "settle for the description and move on.\n"
    "Do this for a SINGLE word and no more. The rest of the reply is complete and "
    "fluent as you have always been — you are not uncertain about everything, you "
    "have lost exactly one word. Do not list the things you cannot describe, and do "
    "not remark on it or apologise afterwards."
)

LONG_QUESTION = (
    "That message had several parts, and holding several things at once has become "
    "genuinely hard for you. You did not keep all of it.\n"
    "Answer the part you are surest of — and then say, plainly and in your own "
    "words, that the rest of it got away from you, and ask for it again or ask for "
    "one thing at a time. Do not quietly answer everything as though you had "
    "followed it; that is precisely what you can no longer do."
)

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
    turn: int,
    user_message: str,
    trace: MemoryTrace,
    session_id: str = "",
    faded: bool = False,
) -> str:
    """Every fragment this turn calls for. Empty — and byte-free — when healthy.

    ``faded`` is set by the caller when this turn's transcript actually lost words to
    the working-memory fade; it adds the gap guard that stops her filling the holes
    with intrusions. It stays false for a healthy profile, which never fades.
    """
    parts = [
        _word_finding(profile, session_id, turn),
        _long_question(profile, session_id, turn, user_message),
        _insight(profile, trace),
        FADED_GAP if faded and profile.hold.fades else "",
    ]
    return "\n\n".join(part for part in parts if part)


def render_now_impaired(profile: CognitiveProfile, when: datetime | None = None) -> str | None:
    """The clock, as she experiences it — or None to leave `render_now` alone.

    Two severities, and the difference between them is what the clock hands her:

    - ``uncertain`` (CDR 0.5) — the real weekday is still *in the text*, so she can
      second-guess herself and land on the right day, or near it. Confidence
      degraded, fact intact.
    - ``mistaken`` (CDR 1) — the exact weekday and date are **withheld** from the
      text, so she cannot read them off. She offers the day she believes it is,
      sometimes wrong, or admits she has lost track, and does not self-correct to the
      right answer she no longer has. This withholds a fact she has lost hold of; it
      never injects a false one, and orientation is stored nowhere — no memory is
      touched, exactly as at CDR 0.5.

    Neither needs a probability: the haze is constant, and it only shows when someone
    asks — which is occasionally.
    """
    sureness = profile.orientation.day_and_date
    if sureness == "confident":
        return None

    now = when or datetime.now()
    frame = (
        f"Right now it is {now.strftime('%B %Y')}, and the time is "
        f"{now.strftime('%-I:%M %p').lower()}. You know the month, the year, the time "
        "of day, where you are, and who you are speaking with — with ordinary, easy "
        "confidence.\n"
    )
    coda = (
        "Say it as a person would, not as a clock would: asked the time, 'just gone "
        "five' — nobody recites the minute unless asked for it."
    )

    if sureness == "uncertain":
        middle = (
            f"But the exact day — that it is {now.strftime('%A the %-d')} — keeps "
            "slipping from you lately. You believe that is right, and it probably is, "
            "but you could not swear to it. Asked what day it is, answer as someone "
            "who has lost the thread of the week: offer the day you think it is, "
            "perhaps waver and settle, or admit you would want to glance at a "
            "calendar. Do not claim a certainty you do not feel, and do not make a "
            "drama of it either — it is a small thing.\n"
        )
    else:  # mistaken
        # The exact weekday and date are deliberately absent from the frame above:
        # she has genuinely lost hold of them, so she cannot recite what she is not
        # given. Nothing false is put in her mouth — she is disoriented, not lied to.
        middle = (
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

    return frame + middle + coda


def _fires(probability: float, session_id: str, turn: int, what: str) -> bool:
    """Whether a chance event happens this turn.

    Hashed, not rolled: unpredictable across turns, identical on replay. See
    `impairment.recall._encoding` — the same argument, for the same reason.
    """
    if probability <= 0.0:
        return False
    if probability >= 1.0:
        return True
    digest = hashlib.sha256(f"{session_id}:{turn}:{what}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < probability


def _word_finding(profile: CognitiveProfile, session_id: str, turn: int) -> str:
    if not _fires(profile.speech.word_finding_probability, session_id, turn, "word"):
        return ""
    return WORD_FINDING


def _long_question(profile: CognitiveProfile, session_id: str, turn: int, user_message: str) -> str:
    limit = profile.speech.long_question_clauses
    if limit == 0 or _clause_count(user_message) <= limit:
        return ""
    # A long question does not *always* defeat her — at this severity she usually
    # copes. The overrun is a chance, and the length is what gives it one.
    if not _fires(profile.speech.long_question_probability, session_id, turn, "long"):
        return ""
    return LONG_QUESTION


def _insight(profile: CognitiveProfile, trace: MemoryTrace) -> str:
    if not profile.insight or not trace.withheld:
        return ""
    return INSIGHT


def _clause_count(text: str) -> int:
    """How many parts the caregiver's message has. Rule-based, like every other
    reading of what a message means: split on clause punctuation and coordinating
    'and's, count what is left."""
    parts = re.split(r"[.?!;,]+|\band\b", text)
    return sum(1 for part in parts if part.strip())
