"""The cognitive-impairment layer: Phase 2, wrapped around Phase 1.

Everything in this package is a wrapper or a pure function over surfaces Phase 1
already exposes — the memory trace, the retrieval engine's `retrieve()` seam, the
prompt fragments, and the windowed transcript working memory hands to the prompt.
It reads those surfaces; it never reaches into storage, formation, or the working-
memory store itself, and nothing here may ever call a model: impairment *withholds,
hedges and lets fade* what the persona has; it never manufactures what she has not.

Severity is data, not code. A `CognitiveProfile` is loaded from YAML
(`data/profiles/`), and the healthy profile gates nothing by construction — with it
loaded, every module below is a no-op and the persona behaves exactly as Phase 1
built her.
"""

from personasim.impairment.engine import ImpairedRetrievalEngine
from personasim.impairment.hold import fade_transcript
from personasim.impairment.profile import (
    HEALTHY,
    CognitiveProfile,
    ProfileError,
    WorkingMemoryHold,
    load_profile,
)
from personasim.impairment.recall import apply_recall_gate

__all__ = [
    "HEALTHY",
    "CognitiveProfile",
    "ImpairedRetrievalEngine",
    "ProfileError",
    "WorkingMemoryHold",
    "apply_recall_gate",
    "fade_transcript",
    "load_profile",
]
