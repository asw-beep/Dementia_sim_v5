"""The one place the persona is allowed to make something up — and then keep it.

She has no clock and no episodic memory of today, so "what did you have for
breakfast?" has no true answer. Left to the model, she invented oatmeal with
raisins, then lentil soup for a dinner she ate before evening, then a reason for
that too — a fresh, contradictory life every single turn, invented anew each time
she was asked. Phase 1 must never do that.

The fix is not silence. It is **memory**. She may improvise a breakfast; what she
may not do is improvise a *different* breakfast tomorrow. So the first time she is
asked, a value is synthesised, written down as a proper structured memory, and from
then on she is answering from memory like anyone else. Consistency is not asked of
the model; it is taken away from it.

Two constraints make this safe, and they are the whole design:

**It only fires where memory is silent.** If retrieval found anything at all, this
does not run — so an improvised detail can never contradict, overwrite, or compete
with an authored one. Her life is not up for improvisation; her Tuesday is.

**It can only produce what is on the list.** `EVERYDAY` is exhaustive: meals, sleep,
what she is working on. There is no path from here to a person, a death, a job, a
place she lived, or a reason why she did something. Ask her about a sister she does
not have and she still says it does not come to mind — because `sister` is not an
everyday attribute, and never will be. The cast stays closed. She cannot manufacture
a relative and then believe in her for the rest of her life.

Note what is *not* happening here. The model is asked for a **value** — a short noun
phrase — which the system then stores. It is never asked for prose that is later
read back into memory. `memory/formation/` still cannot import the LLM, and an
invariant test still enforces it: what she *says* remains unable to become what she
knows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from personasim.llm.base import ChatMessage, ChatRole, LLMClient, LLMError
from personasim.models.identity import Identity
from personasim.models.memory import Memory, SemanticMemory
from personasim.retrieval.entities import extract_keywords


@dataclass(frozen=True)
class Everyday:
    """One thing she may improvise, and the words a question about it arrives in."""

    attribute: str
    #: What retrieval must match to reach the memory once it exists.
    keywords: tuple[str, ...]
    #: How the memory reads once written.
    phrasing: str
    #: What the model is asked to supply.
    asked_for: str
    #: Held for this conversation and never written down.
    #:
    #: What she ate is true tomorrow as well; what day it is, is not. A persisted
    #: "today is Tuesday" is a lie by Wednesday, and a persisted clock is a lie
    #: within the hour. So the date and the time are improvised into the live
    #: persona — retrieval reaches them, she answers from them, she stays consistent
    #: for the whole conversation — and then they go, exactly as working memory does.
    session_only: bool = False


# Exhaustive, and deliberately dull. Every entry is a fact about her *day*. None of
# them is a fact about her *life*, and nothing may be added here that is.
#
# Order matters: the first entry whose keywords the question touches wins. The meals
# lead, so "what foods did you have today?" is a question about eating rather than
# about the afternoon, and `date` trails them so "today" cannot drag a meal question
# off to the calendar.
EVERYDAY: tuple[Everyday, ...] = (
    Everyday(
        attribute="breakfast",
        # Not "today". It is a *time qualifier*, not a topic, and letting it in here
        # made "what day is it?" a question about porridge.
        keywords=("breakfast", "morning", "eat", "ate", "eaten", "food", "foods", "meal"),
        phrasing="For breakfast I had {value}",
        asked_for="what she had for breakfast this morning",
    ),
    Everyday(
        attribute="lunch",
        keywords=("lunch", "eat", "ate", "eaten", "food", "foods", "meal"),
        phrasing="For lunch I had {value}",
        asked_for="what she had for lunch today",
    ),
    Everyday(
        attribute="dinner",
        keywords=("dinner", "supper", "evening", "eat", "ate", "eaten", "food", "foods", "meal"),
        phrasing="For dinner I had {value}",
        asked_for="what she had for dinner",
    ),
    Everyday(
        attribute="sleep",
        keywords=("sleep", "slept", "sleeping", "night", "rest", "tired"),
        phrasing="Last night I slept {value}",
        asked_for="how she slept last night, in a few words",
    ),
    Everyday(
        attribute="activity",
        # No "today" and no "day": both belong to the calendar entry below, and
        # "what have you been doing today?" reaches this one on `doing` regardless.
        keywords=("doing", "working", "busy", "occupied"),
        phrasing="Today I have been {value}",
        asked_for="what she has been doing today, in a few words",
    ),
    # --- session-only, from here down -------------------------------------------
    Everyday(
        attribute="date",
        keywords=("day", "date", "today", "weekday", "week"),
        phrasing="Today is {value}",
        asked_for="what day of the week and date it is today",
        session_only=True,
    ),
    Everyday(
        attribute="time",
        keywords=("time", "clock", "hour", "late", "early"),
        phrasing="It is {value}",
        asked_for="roughly what time of day it is now",
        session_only=True,
    ),
)

# The question must actually be *about* the thing. `eat` reaches breakfast, lunch
# and dinner alike, so the more specific word wins — the tuple is ordered, and the
# first entry whose own name appears is preferred over one matched by a shared word.
_NAMED = {everyday.attribute: everyday for everyday in EVERYDAY}

# A value is a short noun phrase. Anything longer is the model writing prose, and
# prose is the thing this module exists to keep out of memory.
MAX_VALUE_WORDS = 8

# Improvised, and it says so. Lower than a memory she was told (0.9) and far below
# one she has lived (1.0). Phase 2 will want to know the difference; so does anyone
# reading a trace.
IMPROVISED_CONFIDENCE = 0.5
IMPROVISED_IMPORTANCE = 0.15

_ASK = (
    "You are {name}, {occupation}, {age}. In a few plain words, and nothing else, "
    "say {asked_for}. No sentence, no explanation, no punctuation at the end — just "
    "the words. For example: 'toast and black coffee'."
)


def is_improvised(memory: Memory) -> bool:
    """Whether a memory was made up rather than authored or disclosed."""
    return isinstance(memory, SemanticMemory) and memory.attribute in _NAMED


def everyday_for(question: str) -> Everyday | None:
    """Which everyday thing, if any, this question is asking about.

    Rule-based, like every other decision about what a question means. A model
    deciding this would decide differently on two hearings, and the whole point is
    that she stops answering differently on two hearings.
    """
    words = set(extract_keywords(question))
    if not words:
        return None

    # A question that names the thing outright wins over one that merely shares a
    # word with it: "what did you have for dinner?" is dinner, not breakfast, even
    # though both answer to `eat`.
    for everyday in EVERYDAY:
        if everyday.attribute in words:
            return everyday

    for everyday in EVERYDAY:
        if words & set(everyday.keywords):
            return everyday

    return None


def improvise(llm: LLMClient, identity: Identity, everyday: Everyday) -> SemanticMemory | None:
    """Synthesise a value, and return it as a memory. `None` if the model will not
    give a usable one — in which case she says it does not come to mind, which is
    what she did before this existed and is no worse than that."""
    asked = _ASK.format(
        name=identity.name,
        occupation=identity.occupation,
        age=identity.age,
        asked_for=everyday.asked_for,
    )

    try:
        value = _clean(llm.generate([ChatMessage(role=ChatRole.USER, content=asked)]))
    except LLMError:
        return None

    if value is None:
        return None

    return SemanticMemory(
        summary=everyday.phrasing.format(value=value),
        keywords=list(dict.fromkeys([*extract_keywords(value), *everyday.keywords])),
        subject="self",
        attribute=everyday.attribute,
        value=value,
        importance=IMPROVISED_IMPORTANCE,
        confidence=IMPROVISED_CONFIDENCE,
    )


def _clean(reply: str) -> str | None:
    """A noun phrase, or nothing.

    The model was asked for a few words and may still return a paragraph. A memory
    is structured, never free text — so if it will not answer in a phrase, it does
    not get to write a memory.
    """
    value = reply.strip().split("\n")[0]
    value = re.sub(r"^(?:i had|i ate|i slept|i have been|it was)\s+", "", value, flags=re.I)
    value = value.strip().strip(".,;:!?\"'").strip()

    if not value or len(value.split()) > MAX_VALUE_WORDS:
        return None
    return value
