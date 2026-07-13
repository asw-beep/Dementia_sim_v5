"""Intent detection.

Rule-based, ordered, and deterministic. The same question always yields the same
intent, so the same memories are searched every time it is asked.
"""

from __future__ import annotations

from collections.abc import Sequence

from personasim.models.memory import MemoryType
from personasim.models.trace import RetrievalIntent
from personasim.retrieval.entities import STOPWORDS, tokenize

# Greetings and pleasantries, which need no memory at all.
_SMALL_TALK = frozenset(
    {
        "hi",
        "hello",
        "hey",
        "good",
        "morning",
        "afternoon",
        "evening",
        "night",
        "thanks",
        "thank",
        "cheers",
        "bye",
        "goodbye",
        "please",
        "sorry",
        "ok",
        "okay",
        "fine",
    }
)

# Asking after an experience: something that happened, at a time, to the persona.
_EXPERIENTIAL = frozenset(
    {
        "remember",
        "happened",
        "did",
        "when",
        "time",
        "ever",
        "story",
        "day",
        "year",
        "childhood",
        "then",
        "ago",
        "once",
        "felt",
        "feel",
        "was",
        "were",
    }
)

# Asking after a fact: a stable property of the persona.
_FACTUAL = frozenset(
    {
        "what",
        "where",
        "which",
        "favourite",
        "favorite",
        "live",
        "lives",
        "do",
        "does",
        "like",
        "have",
        "own",
        "work",
        "many",
        "old",
    }
)

# Asking after a person, without necessarily naming one.
_RELATIONAL = frozenset(
    {
        "who",
        "family",
        "friend",
        "friends",
        "wife",
        "husband",
        "spouse",
        "married",
        "mother",
        "father",
        "brother",
        "sister",
        "parents",
        "boss",
        "partner",
        "anyone",
        "someone",
    }
)

# Cues made entirely of stopwords, invisible to the token sets above.
_EXPERIENTIAL_PHRASES: tuple[str, ...] = (
    "tell me about",
    "what was it like",
    "what happened",
    "do you recall",
    "back then",
)

_TYPES_BY_INTENT: dict[RetrievalIntent, tuple[MemoryType, ...]] = {
    RetrievalIntent.FACTUAL_RECALL: (MemoryType.SEMANTIC, MemoryType.EPISODIC),
    RetrievalIntent.EXPERIENTIAL_RECALL: (MemoryType.EPISODIC, MemoryType.SEMANTIC),
    RetrievalIntent.RELATIONSHIP_QUERY: (
        MemoryType.RELATIONSHIP,
        MemoryType.EPISODIC,
        MemoryType.SEMANTIC,
    ),
    RetrievalIntent.SMALL_TALK: (),
}


def classify(text: str, person_mentions: Sequence[str] = ()) -> RetrievalIntent:
    """Classify a message. Rules are checked in order; the first match wins.

    Naming a person the persona knows is the strongest signal available, so it is
    checked before the keyword cues — "what did Maya say?" is about Maya, whatever
    else the sentence contains.
    """
    tokens = set(tokenize(text))
    if not tokens:
        return RetrievalIntent.SMALL_TALK

    if person_mentions:
        return RetrievalIntent.RELATIONSHIP_QUERY

    # A pure pleasantry carries no content words. Comparing raw tokens would let a
    # single filler word — "hello there" — masquerade as a question.
    content = tokens - STOPWORDS
    if not content or content <= _SMALL_TALK:
        return RetrievalIntent.SMALL_TALK

    # Naming a relation beats a phrase cue: "tell me about your family" is a
    # question about people, not about an episode.
    if tokens & _RELATIONAL:
        return RetrievalIntent.RELATIONSHIP_QUERY

    # Some experiential cues are phrases whose words are individually stopwords,
    # so they survive neither the token sets below nor keyword extraction.
    lowered = text.lower()
    if any(phrase in lowered for phrase in _EXPERIENTIAL_PHRASES):
        return RetrievalIntent.EXPERIENTIAL_RECALL

    if tokens & _EXPERIENTIAL:
        return RetrievalIntent.EXPERIENTIAL_RECALL

    if tokens & _FACTUAL:
        return RetrievalIntent.FACTUAL_RECALL

    # A content-bearing statement with no interrogative cue: treat it as a factual
    # prompt rather than small talk, so "your dog" still recalls the dog.
    return RetrievalIntent.FACTUAL_RECALL


def types_for(intent: RetrievalIntent) -> tuple[MemoryType, ...]:
    """Which memory types an intent should search. Small talk searches none."""
    return _TYPES_BY_INTENT[intent]
