"""Losing the thread of a long question, delivered by trimming what she heard.

The input-side twin of `impairment.disfluency`. Word-finding could not be asked of
the model — it declined the note, or overdid it — so it is performed on the output.
Losing the thread of a multi-part question is the same story from the other end: a
prompt fragment told her *"you did not keep all of it, answer the part you are surest
of"*, and qwen3:14b read all five parts and answered every one, fluently, exactly
what the deficit says she can no longer do. A soft instruction cannot deliver a
comprehension deficit against a capable model.

So it is not asked. A long question overruns her working memory, and only the tail
of it registers: this trims the message to its last `long_question_clauses` parts
**before the model sees it**, so she cannot answer the earlier parts — there is
nothing there to answer. The same structural guarantee as formation never seeing the
reply: not a filter the model can talk its way past, a fact about what reached it.

The recency of it is the point. Working memory holds the *last* things said, so the
parts that survive are the ones at the end — which, in a real multi-part question,
are usually the actual questions ("…did the city change, and did you think of
leaving?"), the earlier clauses being the scene-setting she has already lost.

Bounded like every mechanism here:

- It **withholds, never invents.** It drops parts of the question; it never adds a
  word, and formation still reads the *full* user message, so nothing the caregiver
  disclosed in a dropped clause is lost from memory — she simply does not *answer* it
  this turn. The closed cast is untouched.
- It **rolls no die.** Whether a long question overruns is `sha256`-hashed from
  (session, turn), so a session replays identically — the same discipline as
  `disfluency` and `recall._encoding`, and the reason the invariant banning `random`
  from this package still holds.
- **Healthy is a no-op by construction:** `long_question_clauses` 0 trims nothing,
  and a question with no more parts than she can hold is returned whole.
"""

from __future__ import annotations

import hashlib
import re

from personasim.impairment.profile import CognitiveProfile

#: Clause punctuation, or a coordinating "and". The same split that decides whether a
#: message has "more parts than she can hold" also decides where the parts begin, so
#: the count and the trim can never disagree.
_SPLIT = re.compile(r"[.?!;,]+|\band\b")

#: Trailing discourse tags — the little courtesies that hang off the end of a question
#: without being part of it ("do you have a dog, *by the way*?"). They are not clauses
#: she has to hold, so they must not count toward the part total, and — crucially — the
#: trim must not keep one *instead* of the real question. When `long_question_clauses`
#: is 1, keeping the last raw clause kept "by the way" and dropped "do you have a dog",
#: and she answered a non-sequitur. A curated set, like `disfluency._SKIP`: precise
#: beats a stopword heuristic, which would read "way" in "by the way" as content.
_TAGS = frozenset(
    {
        "by the way",
        "do you know",
        "you know",
        "would you say",
        "wouldnt you say",
        "please",
        "if you dont mind",
        "if you recall",
        "if you remember",
        "come to think of it",
        "for that matter",
        "i wonder",
        "i was wondering",
        "just wondering",
        "tell me",
        "i mean",
        "may i ask",
        "if i may ask",
    }
)

#: Bare anaphors — pronouns whose referent lives in an earlier clause. The trim's
#: whole premise is that the dropped clauses were scene-setting she has already
#: lost; a kept tail that leans on one of these proves the premise wrong, because
#: the dropped clause held the referent. "Describe the home where you grew up. What
#: do you remember most about *it*?" trimmed to its tail is not a question she
#: answers partially — it is a question about nothing, and the Sprint 2C/2D
#: comparison drive showed the model resolving the orphaned "it" against the
#: transcript instead (her maps) or denying the memory outright, which read as a
#: remote-memory failure CDR 2 must not have. When the tail is anaphoric, one more
#: clause is kept so the referent survives. "That"/"this" also appear as harmless
#: complementizers; the false positive merely keeps one extra clause.
_ANAPHORS = frozenset(
    {"it", "its", "them", "they", "that", "those", "this", "these", "he", "she", "him", "her"}
)


def retain_question(
    user_message: str,
    profile: CognitiveProfile,
    *,
    session_id: str = "",
    turn: int = 0,
) -> tuple[str, str | None]:
    """What of a multi-part question actually registered, and a trace note when the
    rest of it overran.

    Returns the message untouched — and no note — for a healthy profile, for a
    question with no more *substantive* parts than she can hold, or on a turn that does
    not overrun. Otherwise returns just the last `long_question_clauses` substantive
    parts — trailing discourse tags dropped — and a note saying so.
    """
    limit = profile.speech.long_question_clauses
    if limit <= 0:
        return user_message, None

    spans = _clause_spans(user_message)
    # The parts she has to hold are the substantive ones; a trailing "by the way" is
    # not a second question. Counting and trimming both work off these, so a tacked-on
    # tag neither inflates the total nor survives as the sole kept clause.
    substantive = [
        i for i, (s, e) in enumerate(spans) if _normalise(user_message[s:e]) not in _TAGS
    ]
    if len(substantive) <= limit:
        return user_message, None

    # A long question does not *always* defeat her — at this severity she usually
    # copes. The overrun is a chance, and the length is what gives it one.
    if not _fires(profile.speech.long_question_probability, session_id, turn):
        return user_message, None

    last = substantive[-1]
    # Keep to end of string when the last substantive clause *is* the last clause (so a
    # closing "?" survives); otherwise cut at its end, dropping the trailing tag(s).
    end = len(user_message) if last == len(spans) - 1 else spans[last][1]

    keep = limit
    start = spans[substantive[-keep]][0]
    # A tail that leans on a bare anaphor cannot stand alone — its referent was in
    # the clause just dropped, and a question about an orphaned "it" is a question
    # about nothing (see `_ANAPHORS`). Keep one more clause so the referent survives:
    # the deficit stays (a 3-part question still loses its head), the wreckage goes.
    if keep < len(substantive) and _anaphoric(user_message[start:end]):
        keep += 1
        start = spans[substantive[-keep]][0]
        if keep == len(substantive):
            return user_message, None

    kept = user_message[start:end].strip()
    note = f"working memory: a {len(substantive)}-part question overran; kept only the last {keep}"
    return kept, note


def _clause_spans(text: str) -> list[tuple[int, int]]:
    """The (start, end) span of every non-empty part of `text`, split on clause
    punctuation and coordinating 'and's, in order."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for match in _SPLIT.finditer(text):
        if text[pos : match.start()].strip():
            spans.append((pos, match.start()))
        pos = match.end()
    if text[pos:].strip():
        spans.append((pos, len(text)))
    return spans


def _anaphoric(text: str) -> bool:
    """Whether `text` leans on a bare anaphor — a pronoun whose referent must live in
    an earlier clause. Matched on whole words, lowercased, punctuation stripped."""
    words = set(re.sub(r"[^a-z' ]", " ", text.lower()).split())
    return bool(words & _ANAPHORS)


def _normalise(clause: str) -> str:
    """A clause reduced to lowercase words, punctuation and apostrophes stripped, for
    matching against `_TAGS`. "By the way?" and "by the way" both become "by the way"."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", clause.lower()).split())


def _fires(probability: float, session_id: str, turn: int) -> bool:
    """Whether the overrun happens this turn. Hashed, not rolled: unpredictable across
    turns, identical on replay. See `impairment.disfluency._fires`."""
    if probability <= 0.0:
        return False
    if probability >= 1.0:
        return True
    digest = hashlib.sha256(f"{session_id}:{turn}:long".encode()).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < probability
