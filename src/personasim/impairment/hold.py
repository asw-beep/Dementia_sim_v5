"""Working-memory fade: how the live conversation frays in RAM.

The delayed-recall probe — "remember these three words… now, what were they?" — is
the most diagnostic question in the CDR interview, and under a *hard* transcript
window it had only two answers. Wide enough and the three words sat verbatim in the
prompt, so she read them straight back: a perfect score, produced by a buffer rather
than by a mind. Narrow enough and the turn had scrolled out and she had nothing at
all — "I don't remember any words." Both are wrong for CDR 0.5, where immediate
registration is intact and it is *retention across a delay* that goes: the clinical
signature is *2 of 3, or 1 of 3 rescued by a cue*, not a blank.

So this fades the transcript instead of truncating it. The most recent
`crisp_turns` exchanges are handed to the prompt whole — registration, and the
thread of the current exchange, are preserved. Older exchanges lose words one at a
time, and lose more of them the further back they were, until at the window's edge
the exchange is gone. A three-word list a few turns old comes back in part; the
caregiver's cue is a fresh, unfaded turn that lets her land what the fade left.

**Hashed, not rolled.** `sha256(session:ordinal:role:index)` decides whether a given
word survives, so which words fade is fixed for a turn within a session and a
replayed session frays identically — the same discipline as `recall._encoding` and
`voice._fires`, and the same reason: a clinical validation cannot live with a
transcript that reads differently on two runs. The invariant test that bans `random`
from this package therefore still holds; there is no RNG here.

**Nothing is forgotten that was worth keeping.** The transcript is RAM, not the
store. A fact the caregiver disclosed reached long-term memory through formation the
moment it was said, and is gated — if at all — by the recall ladder, not by this. A
faded word is replaced by an ellipsis, never by another word: she loses the
particulars, she never acquires false ones, and formation never sees any of this. A
gap she can feel — the thing the trace note records — is exactly the deficit; a
confident wrong answer would be a different, later disease.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from personasim.impairment.profile import CognitiveProfile
from personasim.models.conversation import Message, Role, Turn

#: A faded word is never replaced by another word — only by a gap she can feel.
ELISION = "…"

#: However far back a turn is, a word may still linger: cued recall has something to
#: catch on, and total loss of an old exchange is a heavier deficit than CDR 0.5.
MAX_FADE = 0.85


def fade_transcript(
    turns: Sequence[Turn],
    turns_seen: int,
    profile: CognitiveProfile,
    session_id: str = "",
) -> tuple[list[Message], str | None]:
    """Fade the windowed transcript, returning it and a note for the trace.

    ``turns`` is the working-memory window, oldest first; ``turns_seen`` is how many
    turns the session has held in all, which fixes each turn's absolute ordinal and
    hence its age. A healthy hold (``fades`` false) returns the transcript unchanged
    and no note, so the prompt stays byte-for-byte Phase 1.
    """
    if not profile.hold.fades:
        return _flatten(turns), None

    oldest_ordinal = turns_seen - len(turns)
    messages: list[Message] = []
    faded_turns = 0
    faded_words = 0

    for offset, turn in enumerate(turns):
        ordinal = oldest_ordinal + offset
        # Age in turns from the most recent completed exchange: the newest turn in
        # the window is age 0, and older turns count up from there.
        age = (turns_seen - 1) - ordinal
        probability = _fade_probability(age, profile)

        turn_faded = 0
        for role, message in ((Role.USER, turn.user_message), (Role.PERSONA, turn.persona_message)):
            faded_text, dropped = _fade_message(
                message.content, probability, session_id, ordinal, role
            )
            turn_faded += dropped
            messages.append(Message(role=message.role, content=faded_text))

        if turn_faded:
            faded_turns += 1
            faded_words += turn_faded

    note = None
    if faded_words:
        note = (
            f"working memory: {faded_turns} earlier "
            f"exchange{'s' if faded_turns != 1 else ''} fading, "
            f"{faded_words} word{'s' if faded_words != 1 else ''} slipped"
        )
    return messages, note


def _fade_probability(age: int, profile: CognitiveProfile) -> float:
    """How likely any one word in a turn this old is to have slipped.

    Zero through the crisp span, then climbing turn by turn across the fade span —
    the further back, the more is lost — capped short of certainty so an old word can
    still linger for a cue to catch.
    """
    hold = profile.hold
    if age < hold.crisp_turns or hold.fade_turns <= 0:
        return 0.0
    distance = age - hold.crisp_turns + 1
    return min(MAX_FADE, distance / (hold.fade_turns + 1))


def _fade_message(
    content: str, probability: float, session_id: str, ordinal: int, role: Role
) -> tuple[str, int]:
    """Elide words independently at ``probability``, collapsing runs into one gap.

    Returns the faded text and how many words were dropped. The text is never empty:
    a wholly faded message becomes a single ellipsis, which is still something said.
    """
    if probability <= 0.0:
        return content, 0

    words = content.split()
    kept: list[str] = []
    dropped = 0
    for index, word in enumerate(words):
        if _slips(probability, session_id, ordinal, role, index):
            dropped += 1
            # Collapse a run of gaps into one, so faded prose reads as a single
            # lapse rather than a stutter of ellipses.
            if not kept or kept[-1] != ELISION:
                kept.append(ELISION)
        else:
            kept.append(word)

    if not dropped:
        return content, 0
    return " ".join(kept) if kept else ELISION, dropped


def _slips(probability: float, session_id: str, ordinal: int, role: Role, index: int) -> bool:
    """Whether one word has slipped. Hashed, not rolled — see the module docstring."""
    if probability >= 1.0:
        return True
    digest = hashlib.sha256(f"{session_id}:{ordinal}:{role.value}:{index}".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < probability


def _flatten(turns: Sequence[Turn]) -> list[Message]:
    """The transcript exactly as working memory hands it over — no fade applied."""
    return [message for turn in turns for message in (turn.user_message, turn.persona_message)]
