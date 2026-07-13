"""Memory formation: the only door from a conversation into long-term memory.

It reads what the caregiver disclosed. It does not read what the model said.
Nothing the LLM improvises about the persona can pass through here, because it is
never offered to it.
"""

from personasim.memory.formation.consolidate import ConsolidationPlan, consolidate
from personasim.memory.formation.extract import (
    CAREGIVER,
    Disclosure,
    Formed,
    extract_disclosures,
    form_memories,
)

__all__ = [
    "CAREGIVER",
    "ConsolidationPlan",
    "Disclosure",
    "Formed",
    "consolidate",
    "extract_disclosures",
    "form_memories",
]
