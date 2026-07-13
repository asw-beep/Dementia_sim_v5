"""Keyword and entity extraction.

Deterministic and rule-based. No LLM touches this: if the model decided what a
question was about, the persona's recall would vary between identical questions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

# Words that carry no retrieval signal. Kept small on purpose — an over-eager stop
# list silently deletes the subject of a question.
STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "about",
        "all",
        "am",
        "an",
        "and",
        "any",
        "are",
        "as",
        "at",
        "be",
        "been",
        "but",
        "by",
        "can",
        "did",
        "do",
        "does",
        "for",
        # "from" is NOT a stopword. It is the entire subject of "where are you
        # from?" — drop it and the question tokenizes to nothing, and a persona who
        # knows exactly where she grew up cannot answer it. This is what the docstring
        # above warns about: an over-eager stop list silently deletes the question.
        "had",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "just",
        "me",
        "my",
        "of",
        "on",
        "or",
        "so",
        "some",
        "still",
        "than",
        "that",
        "the",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "too",
        "us",
        "very",
        "was",
        "we",
        "were",
        "what",
        "when",
        "where",
        "which",
        "who",
        "whom",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "ever",
        "tell",
        "think",
        "know",
        "like",
        "get",
        "got",
    }
)

MIN_KEYWORD_LENGTH = 3

_TOKEN = re.compile(r"[a-z0-9']+")


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, with possessives reduced to the noun.

    Without this, "your father's soup" yields `father's`, which matches no
    memory's keywords, and the question silently recalls nothing.
    """
    tokens = []
    for raw in _TOKEN.findall(text.lower()):
        token = raw.removesuffix("'s").strip("'")
        if token:
            tokens.append(token)
    return tokens


def extract_keywords(text: str) -> list[str]:
    """Content words, lowercased, de-duplicated, in order of first appearance.

    Short tokens survive the length filter when they are not stopwords, so "dog"
    is kept while "do" is not.
    """
    keywords: dict[str, None] = {}
    for token in tokenize(text):
        if token in STOPWORDS or len(token) < MIN_KEYWORD_LENGTH:
            continue
        keywords[token] = None
    return list(keywords)


def find_person_mentions(text: str, known_names: Sequence[str]) -> list[str]:
    """People the persona knows who are named in the text.

    Matching against known names rather than guessing at proper nouns keeps this
    deterministic and stops "Boston" from being mistaken for a person. A first
    name alone counts: "how is Maya?" should find Maya Okonkwo.
    """
    tokens = set(tokenize(text))
    mentions: dict[str, None] = {}

    for name in known_names:
        parts = tokenize(name)
        if not parts:
            continue
        full_name_present = all(part in tokens for part in parts)
        first_name_present = parts[0] in tokens
        if full_name_present or first_name_present:
            mentions[name] = None

    return list(mentions)
