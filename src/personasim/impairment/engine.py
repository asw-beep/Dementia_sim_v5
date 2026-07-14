"""The wrapper the retrieval engine's docstring promised.

`retrieval/engine.py` says: "This is the surface Phase 2 wraps: a
cognitive-impairment layer decorates `retrieve`, degrading its results, without
reaching inside any of the steps below." This class is that sentence, made code.
It holds a `RetrievalEngine`, calls it, and gates what comes back — same method,
same signature, so a `Conversation` never knows which one it is holding.
"""

from __future__ import annotations

from personasim.impairment.profile import CognitiveProfile
from personasim.impairment.recall import apply_recall_gate
from personasim.models.trace import MemoryTrace
from personasim.retrieval.engine import RetrievalEngine
from personasim.retrieval.source import MemorySource


class ImpairedRetrievalEngine:
    """A `RetrievalEngine` whose recall of recent memory is gated by a profile."""

    def __init__(
        self, inner: RetrievalEngine, profile: CognitiveProfile, source: MemorySource
    ) -> None:
        self._inner = inner
        self._profile = profile
        self._source = source

    def retrieve(self, query: str) -> MemoryTrace:
        return apply_recall_gate(self._inner.retrieve(query), self._profile, self._source)
