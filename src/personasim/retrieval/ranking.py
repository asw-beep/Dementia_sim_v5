"""Ranking.

The score is a weighted sum of three signals, and each weighted contribution is
recorded separately on the trace. A human — or a Phase 2 wrapper — can therefore
see which signal actually surfaced a memory, not merely that it scored well.

`ScoreComponents.total` equals the score, by construction: the components hold
the already-weighted contributions rather than the raw values.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from personasim.models.memory import Memory
from personasim.models.trace import ScoreComponents


@dataclass(frozen=True)
class RankWeights:
    keyword: float
    importance: float
    confidence: float


@dataclass(frozen=True)
class ScoredMemory:
    memory: Memory
    score: float
    components: ScoreComponents
    matched_keywords: list[str]


def keyword_overlap(memory: Memory, query_keywords: Sequence[str]) -> list[str]:
    """Query keywords the memory carries, in the order the question asked them."""
    carried = set(memory.keywords)
    return [keyword for keyword in query_keywords if keyword in carried]


def score_memory(
    memory: Memory,
    query_keywords: Sequence[str],
    weights: RankWeights,
) -> ScoredMemory:
    matched = keyword_overlap(memory, query_keywords)

    # Fraction of the question the memory answers, not raw count: a memory
    # matching two of two keywords beats one matching two of six.
    overlap = len(matched) / len(query_keywords) if query_keywords else 0.0

    components = ScoreComponents(
        keyword_overlap=overlap * weights.keyword,
        importance=memory.importance * weights.importance,
        confidence=memory.confidence * weights.confidence,
    )
    return ScoredMemory(
        memory=memory,
        score=components.total,
        components=components,
        matched_keywords=matched,
    )


def rank(
    memories: Sequence[Memory],
    query_keywords: Sequence[str],
    weights: RankWeights,
    *,
    top_k: int,
    min_score: float = 0.0,
) -> list[ScoredMemory]:
    """Best first.

    Ties break on importance, then on id, so an unchanged persona answers an
    unchanged question with an unchanged memory set every time.
    """
    scored = [score_memory(memory, query_keywords, weights) for memory in memories]
    surviving = [item for item in scored if item.score >= min_score]
    surviving.sort(key=lambda item: (-item.score, -item.memory.importance, item.memory.id))
    return surviving[:top_k]
