"""The cognitive-impairment layer: Phase 2, wrapped around Phase 1.

Everything in this package is a wrapper or a pure function over surfaces Phase 1
already exposes — the memory trace, the retrieval engine's `retrieve()` seam, and
the prompt fragments. Nothing here touches storage, formation, or working memory,
and nothing here may ever call a model: impairment *withholds and hedges* what the
persona has; it never manufactures what she has not.

Severity is data, not code. A `CognitiveProfile` is loaded from YAML
(`data/profiles/`), and the healthy profile gates nothing by construction — with it
loaded, every module below is a no-op and the persona behaves exactly as Phase 1
built her.
"""

from personasim.impairment.engine import ImpairedRetrievalEngine
from personasim.impairment.profile import (
    HEALTHY,
    CognitiveProfile,
    ProfileError,
    load_profile,
)
from personasim.impairment.recall import apply_recall_gate

__all__ = [
    "HEALTHY",
    "CognitiveProfile",
    "ImpairedRetrievalEngine",
    "ProfileError",
    "apply_recall_gate",
    "load_profile",
]
