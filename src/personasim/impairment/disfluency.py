"""Word-finding, delivered after the fact.

The prompt seam could not make the model grope for a word. A soft note produced
*zero* hesitation across twenty turns; an imperative one, pushed hard enough to
fire, turned into a robotic litany — "I know I had a napkin but I cannot say what
it was made of" for every noun — which reads as aphasia, not the single anomic
pause of CDR 1. This is the honest limit the roadmap recorded: the behaviour the
model would not perform, performed on its output instead. One hesitation, on one
word, in a reply that is otherwise as fluent as she has always been.

This edits the text the model already produced. It never asks the model for
anything (no `llm` import), touches no store, and rolls no die: *which* word and
*whether* a turn stumbles are `sha256`-hashed from (session, turn), so a session
replays identically — the same discipline as `recall._encoding` and `voice._fires`,
and the reason the invariant test banning `random` from this package still holds.

It adds a **disfluency, not a fact**. Nothing here reaches memory — formation is
handed the user's words, never this reply — so the closed cast is untouched: she
gropes for a word she has, she never acquires one she has not. She stumbles only on
a plain lowercase noun, never a name or a capitalised word, which is where anomia
falls and which keeps "Maya" and "Vermont" safe.

Healthy is a no-op by construction: `word_finding_probability` 0 never fires.
"""

from __future__ import annotations

import hashlib
import re

from personasim.impairment.profile import CognitiveProfile

#: A plain, lowercase word of four letters or more. Lowercase is the point: it skips
#: sentence-initial words and proper nouns (names, places), which anomia spares.
_WORD = re.compile(r"(?<![A-Za-z'])[a-z]{4,}(?![A-Za-z'])")

#: Common non-nouns that clear the length bar. Anomia lands on content nouns, so
#: these are filtered out to keep the stumble on "the kettle", not "the would".
_SKIP = frozenset(
    {
        "that",
        "this",
        "then",
        "than",
        "them",
        "they",
        "their",
        "there",
        "these",
        "those",
        "with",
        "from",
        "have",
        "been",
        "were",
        "what",
        "when",
        "where",
        "which",
        "would",
        "could",
        "should",
        "about",
        "really",
        "think",
        "because",
        "just",
        "only",
        "very",
        "much",
        "more",
        "most",
        "some",
        "such",
        "also",
        "into",
        "over",
        "your",
        "here",
        "well",
        "like",
        "know",
        "dont",
        "cant",
        "wont",
        "didnt",
        "remember",
        "recall",
        "suppose",
        "perhaps",
        "maybe",
        "quite",
        "rather",
        "still",
        "being",
        "doing",
        "going",
        "said",
        "says",
        "tell",
        "told",
        "want",
        "need",
        "make",
        "made",
        "come",
        "came",
        "went",
        "does",
        "done",
        "hardly",
        "always",
        "never",
        "again",
        "myself",
        "yourself",
        # Prepositions and conjunctions that clear the length bar — anomia is a
        # trouble finding *nouns*, so a stumble reads wrong on these.
        "before",
        "after",
        "while",
        "around",
        "through",
        "along",
        "beside",
        "between",
        "within",
        "toward",
        "towards",
        "against",
        "across",
        "behind",
        "below",
        "above",
        "under",
        "upon",
        "onto",
        "without",
        "during",
        "since",
        "until",
        "unless",
        "though",
        "although",
        "whether",
        "either",
        "neither",
        "however",
        "instead",
    }
)

#: A small rotation, chosen by hash — a fixed line every time would read as a tic.
#: These are groping *interjections*, not apologies; she breaks off and reaches.
_FILLERS = (
    "oh, what's the word",
    "what do you call it",
    "it's on the tip of my tongue",
    "you know the one",
    "what is it now",
)


def inject_word_finding(
    text: str,
    profile: CognitiveProfile,
    *,
    session_id: str = "",
    turn: int = 0,
) -> tuple[str, str | None]:
    """Grope for one word in `text`, or leave it whole. Returns the (possibly
    stumbled) text and a trace note when it fired.

    Fires at `word_finding_probability`, hashed per (session, turn). Returns the text
    untouched — and no note — for a healthy profile, on a turn that does not fire, or
    when the reply has no plain noun to lose.
    """
    probability = profile.speech.word_finding_probability
    if probability <= 0.0 or not text.strip():
        return text, None
    if not _fires(probability, session_id, turn):
        return text, None

    # Only words that begin past the first character, so the reply never *opens*
    # with a stumble — anomia interrupts a sentence, it does not preface one.
    candidates = [m for m in _WORD.finditer(text) if m.start() > 0 and m.group(0) not in _SKIP]
    if not candidates:
        return text, None

    match = candidates[_index(session_id, turn, "which", len(candidates))]
    filler = _FILLERS[_index(session_id, turn, "filler", len(_FILLERS))]
    stumbled = f"{text[: match.start()]}— {filler} — {text[match.start() :]}"
    return stumbled, f"word-finding: groped for '{match.group(0)}'"


def _digest01(seed: str) -> float:
    """A value in [0, 1), hashed from `seed`. See the module docstring."""
    return int.from_bytes(hashlib.sha256(seed.encode()).digest()[:8], "big") / 2**64


def _fires(probability: float, session_id: str, turn: int) -> bool:
    if probability >= 1.0:
        return True
    return _digest01(f"{session_id}:{turn}:wordfind") < probability


def _index(session_id: str, turn: int, what: str, count: int) -> int:
    """A stable choice among `count` options, hashed so it varies turn to turn."""
    return int(_digest01(f"{session_id}:{turn}:{what}") * count) % count
