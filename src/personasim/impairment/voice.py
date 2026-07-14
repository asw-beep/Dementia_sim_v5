"""Speech-level difficulty: the behaviours that never touch memory.

Word-finding, losing the thread of a long question, hazy orientation, and
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
    "Once, in one reply. Everything else you say stays as fluent as you have always "
    "been. Do not remark on it afterwards and do not apologise for it."
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


def voice_notes(
    profile: CognitiveProfile,
    *,
    turn: int,
    user_message: str,
    trace: MemoryTrace,
    session_id: str = "",
) -> str:
    """Every fragment this turn calls for. Empty — and byte-free — when healthy."""
    parts = [
        _word_finding(profile, session_id, turn),
        _long_question(profile, session_id, turn, user_message),
        _insight(profile, trace),
    ]
    return "\n\n".join(part for part in parts if part)


def render_now_uncertain(profile: CognitiveProfile, when: datetime | None = None) -> str | None:
    """The clock, as she experiences it — or None to leave `render_now` alone.

    The truth is still told: the real weekday is in the text, which is what lets her
    second-guess herself and *land on the right day*, or near it. What is degraded is
    her confidence in it, not the fact itself — the clock stays right by
    construction, and her access to it is what wavers. No memory is touched.

    "Occasionally uncertain" needs no probability: the haze is constant, and it only
    shows when someone asks — which is occasionally.
    """
    if profile.orientation.day_and_date == "confident":
        return None

    now = when or datetime.now()
    return (
        f"Right now it is {now.strftime('%B %Y')}, and the time is "
        f"{now.strftime('%-I:%M %p').lower()}. You know the month, the year, the time "
        "of day, where you are, and who you are speaking with — with ordinary, easy "
        "confidence.\n"
        f"But the exact day — that it is {now.strftime('%A the %-d')} — keeps slipping "
        "from you lately. You believe that is right, and it probably is, but you could "
        "not swear to it. Asked what day it is, answer as someone who has lost the "
        "thread of the week: offer the day you think it is, perhaps waver and settle, "
        "or admit you would want to glance at a calendar. Do not claim a certainty you "
        "do not feel, and do not make a drama of it either — it is a small thing.\n"
        "Say it as a person would, not as a clock would: asked the time, 'just gone "
        "five' — nobody recites the minute unless asked for it."
    )


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
