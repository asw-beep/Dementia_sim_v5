"""Speech-level difficulty: the behaviours that never touch memory.

Word-finding, losing the thread of a long question, hazy orientation, and
preserved insight are properties of *speech*, so they live at the prompt seam —
fragments added to the system prompt on the turns the profile says, and only
those turns. The gating is deterministic and testable without a model (assert the
fragment's presence, not the model's prose); *how* she gropes for a word is left
to the model, which is what the model is for.

Two Phase 1 lessons are law here:

- **Describe the manner; never quote it.** A sample phrase in a prompt becomes a
  catchphrase the model repeats every turn (seed authoring rule 2). Every fragment
  below says *that* something happens, never the words it happens in.
- **Insight fires at the moment of failure, not at random.** She comments on her
  forgetfulness exactly when a memory has just been withheld — the same discipline
  as the memory trace, applied to speech.

Everything returns the empty string for a healthy profile, so the healthy prompt
is byte-for-byte the Phase 1 prompt.
"""

from __future__ import annotations

import re
from datetime import datetime

from personasim.impairment.profile import CognitiveProfile
from personasim.models.trace import MemoryTrace

WORD_FINDING = (
    "At one natural moment in this reply — one, no more — a specific everyday word "
    "refuses to come to you. Reach for it the way anyone does: hesitate, talk around "
    "the thing until the word arrives or a plainer one has to do, and move on. Do not "
    "remark on it, and keep everything else as fluent as you always are."
)

LONG_QUESTION = (
    "That last message had several parts, and holding that many things at once has "
    "become genuinely hard for you. Answer the part you are surest of, and ask — in "
    "your own words, simply — for the rest again, or for one thing at a time. Do not "
    "pretend to have followed all of it."
)

INSIGHT = (
    "Something you were just asked about is genuinely not coming to mind, and you "
    "can feel that it should. You have noticed lately that recent things slip away "
    "from you more than they used to — things you were told a day or two ago, the "
    "odd word. You know this about yourself; it bothers you a little, nothing more. "
    "If it feels natural, admit the blank and say so in your own words — lightly, "
    "once, without making a speech of it. You know only that you have become a bit "
    "forgetful; never name a condition or a diagnosis."
)


def voice_notes(
    profile: CognitiveProfile, *, turn: int, user_message: str, trace: MemoryTrace
) -> str:
    """Every fragment this turn calls for. Empty — and byte-free — when healthy."""
    parts = [
        _word_finding(profile, turn),
        _long_question(profile, user_message),
        _insight(profile, trace),
    ]
    return "\n\n".join(part for part in parts if part)


def render_now_uncertain(profile: CognitiveProfile, when: datetime | None = None) -> str | None:
    """The clock, as she experiences it — or None to leave `render_now` alone.

    The truth is still told: the real weekday is in the text, which is what lets
    her second-guess herself and *land on the right day*, or near it. What is
    degraded is her confidence in it, not the fact itself — the clock stays right
    by construction, and her access to it is what wavers. No memory is touched.

    "Occasionally uncertain" needs no randomness: the haze is constant, and it
    only shows when someone asks — which is occasionally.
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


def _word_finding(profile: CognitiveProfile, turn: int) -> str:
    cadence = profile.speech.word_finding_every_n_turns
    if cadence == 0 or turn % cadence != 0:
        return ""
    return WORD_FINDING


def _long_question(profile: CognitiveProfile, user_message: str) -> str:
    limit = profile.speech.long_question_clauses
    if limit == 0 or _clause_count(user_message) <= limit:
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
