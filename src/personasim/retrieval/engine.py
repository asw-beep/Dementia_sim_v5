"""The retrieval engine.

    Question → Intent Detection → Entity Extraction → Retrieve → Rank → Context

Every call emits a `MemoryTrace` explaining what was retrieved and why. This is
the surface Phase 2 wraps: a cognitive-impairment layer decorates `retrieve`,
degrading its results, without reaching inside any of the steps below.
"""

from __future__ import annotations

from collections.abc import Sequence

from personasim.config import Settings
from personasim.models.memory import LinkRelation, Memory, MemoryId, SemanticMemory
from personasim.models.trace import (
    MemoryTrace,
    RetrievalIntent,
    RetrievedMemory,
    ScoreComponents,
)
from personasim.retrieval.entities import extract_keywords, find_person_mentions
from personasim.retrieval.intent import classify, types_for
from personasim.retrieval.ranking import RankWeights, ScoredMemory, rank
from personasim.retrieval.scope import Scope, scope_of
from personasim.retrieval.search import find_candidates
from personasim.retrieval.source import MemorySource

# Relations worth following out of a matched memory. `caused_by` and `led_to`
# supply the causal bridge the model would otherwise invent; `involves` and
# `concerns` bring in the person or fact the memory is about.
EXPANDABLE: frozenset[LinkRelation] = frozenset(
    {
        LinkRelation.CAUSED_BY,
        LinkRelation.LED_TO,
        LinkRelation.INVOLVES,
        LinkRelation.CONCERNS,
    }
)


class RetrievalEngine:
    """Turns a question into the memories that answer it, and says why."""

    def __init__(self, source: MemorySource, settings: Settings) -> None:
        self._source = source
        self._settings = settings
        self._weights = RankWeights(
            keyword=settings.rank_weight_keyword,
            importance=settings.rank_weight_importance,
            confidence=settings.rank_weight_confidence,
        )

    def retrieve(self, query: str) -> MemoryTrace:
        keywords = extract_keywords(query)
        mentions = find_person_mentions(query, self._source.person_names())
        intent = classify(query, mentions)
        types = types_for(intent)

        if not types:
            return MemoryTrace(
                query=query,
                intent=intent,
                entities=mentions,
                searched_types=[],
                retrieved=[],
                reason="small talk: no memory retrieval needed",
            )

        scope = scope_of(query)
        candidates = _in_scope(find_candidates(self._source, keywords, mentions, types), scope)
        ranked = rank(
            candidates,
            keywords,
            self._weights,
            top_k=self._settings.retrieval_top_k,
            min_score=self._settings.retrieval_min_score,
        )

        retrieved = [_to_retrieved(item) for item in ranked]
        expanded = self._expand(ranked)
        retrieved.extend(expanded)

        return MemoryTrace(
            query=query,
            intent=intent,
            entities=mentions,
            searched_types=list(types),
            retrieved=retrieved,
            reason=_explain(intent, keywords, mentions, ranked, expanded, scope),
        )

    def _expand(self, ranked: Sequence[ScoredMemory]) -> list[RetrievedMemory]:
        """Follow typed links out of the matched memories.

        A memory reached this way was not asked for; it explains one that was. It
        carries its own importance and confidence but no keyword credit, since the
        question never mentioned it.
        """
        if not self._settings.retrieval_expand_links or not ranked:
            return []

        already: set[MemoryId] = {item.memory.id for item in ranked}
        expansions: list[RetrievedMemory] = []

        for item in ranked:
            for link in item.memory.links:
                if len(expansions) >= self._settings.retrieval_max_expansions:
                    return expansions
                if link.relation not in EXPANDABLE or link.target in already:
                    continue

                target = self._source.get(link.target)
                if target is None:
                    continue

                already.add(target.id)
                # No keyword credit: the question never mentioned this memory. Its
                # score is still its components' total, so `total == score` holds
                # for every retrieved memory; `linked_from` is what marks it as
                # explanatory rather than asked-for.
                components = ScoreComponents(
                    keyword_overlap=0.0,
                    importance=target.importance * self._weights.importance,
                    confidence=target.confidence * self._weights.confidence,
                )
                expansions.append(
                    RetrievedMemory(
                        memory_id=target.id,
                        memory_type=target.type,
                        summary=target.summary,
                        score=components.total,
                        components=components,
                        matched_keywords=[],
                        linked_from=item.memory.id,
                        via_relation=link.relation,
                    )
                )

        return expansions


def _in_scope(candidates: Sequence[Memory], scope: Scope) -> list[Memory]:
    """Drop the memories the question was not asking for.

    The persona and the caregiver both have a city, a job, a family, and both are in
    memory. "Where do I live?" and "Where do you live?" retrieve on the same keyword
    and reach both — and it was the *model* deciding which to answer with. It got it
    wrong: it answered "What do I do for a living?" with "I am a cartographer".

    Filtering, not ranking. A question about the caregiver must not merely prefer
    the caregiver's memories; it must not be handed the persona's at all, or the
    model will reach for the one it finds more interesting.
    """
    if scope is not Scope.CAREGIVER:
        return list(candidates)

    # Everything the persona knows about the caregiver is a disclosed fact. She has
    # no episodes with them and no relationship memory of them, so a question about
    # them reaches nothing else.
    #
    # Only `caregiver` filters. The mirror rule — a question about *her* excludes
    # what she was told — is tempting and wrong: "what do you know about Chicago?"
    # asks what she *knows*, which includes what the caregiver told her, and
    # filtering it out made her forget a fact she had been given one turn earlier.
    # The failure this guards against runs one way, so the guard runs one way.
    return [memory for memory in candidates if _is_disclosed(memory)]


def _is_disclosed(memory: Memory) -> bool:
    """A semantic memory whose subject is not `self` was disclosed *to* her, about
    somebody else. Everything else is her own life."""
    return isinstance(memory, SemanticMemory) and memory.subject.casefold() != "self"


def _to_retrieved(item: ScoredMemory) -> RetrievedMemory:
    return RetrievedMemory(
        memory_id=item.memory.id,
        memory_type=item.memory.type,
        summary=item.memory.summary,
        score=item.score,
        components=item.components,
        matched_keywords=item.matched_keywords,
    )


def _explain(
    intent: RetrievalIntent,
    keywords: Sequence[str],
    mentions: Sequence[str],
    ranked: Sequence[ScoredMemory],
    expanded: Sequence[RetrievedMemory],
    scope: Scope,
) -> str:
    """A sentence a human can read, for the trace."""
    scoped = "" if scope is Scope.UNSCOPED else f" (asking about {scope.value})"

    if not ranked and not expanded:
        parts = [f"{intent.value}{scoped}: no memory matched"]
        if keywords:
            parts.append(f"keywords {list(keywords)}")
        return "; ".join(parts)

    parts = [f"{intent.value}{scoped}: {len(ranked)} memories matched"]

    if mentions:
        parts.append(f"named {list(mentions)}")

    matched = sorted({keyword for item in ranked for keyword in item.matched_keywords})
    if matched:
        parts.append(f"on keywords {matched}")

    if expanded:
        relations = sorted({e.via_relation.value for e in expanded if e.via_relation})
        parts.append(f"{len(expanded)} added by following {relations}")

    return "; ".join(parts)


def memories_of(trace: MemoryTrace, source: MemorySource) -> list[Memory]:
    """Rehydrate a trace's memories, in the order retrieval ranked them."""
    resolved = [source.get(memory_id) for memory_id in trace.memory_ids]
    return [memory for memory in resolved if memory is not None]
