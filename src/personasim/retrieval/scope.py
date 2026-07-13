"""Who a question is about: the persona, or the caregiver asking it.

Both of them have a city, a job, a family. Both are in memory. "Where do I live?"
and "Where do you live?" retrieve on the same keyword — `live` — and reach both
memories, and until this existed it was the *model* that decided which one to
answer with. It decided wrongly, and differently on different phrasings: it
answered "Where do I live?" correctly, then answered "Do you remember where I
live?" with "I don't have a memory of where you live", and "What do I do for a
living?" with "I am a cartographer".

That is not a decision a model may make. Retrieval is deterministic so that recall
does not vary between two askings of the same question, and *whose fact is being
asked for* is exactly a retrieval decision. Pronouns settle it, and pronouns are
rules.

The rule: look at what comes after the question word. "Where do **I** live" asks
about the caregiver; "Where do **you** live" asks about the persona. In "Do you
remember where **I** live", the "you" is only the address — the question word is
`where`, and after it comes `I`. That is why the pronouns before it are ignored.
"""

from __future__ import annotations

import re
from enum import StrEnum

# The persona never speaks in the caregiver's message, so a first-person subject
# there is always the caregiver. `me` is deliberately absent: "tell me about your
# mother" is first-person in form and about the persona in fact.
FIRST_PERSON = re.compile(r"\b(?:i|my)\b", re.IGNORECASE)
SECOND_PERSON = re.compile(r"\b(?:you|your|yours)\b", re.IGNORECASE)

# Everything after the question word is the question; everything before it is
# throat-clearing. "Do you remember where I live?" is about `I`, not about `you`.
QUESTION_WORD = re.compile(r"\b(?:who|what|where|when|why|how|which)\b", re.IGNORECASE)


class Scope(StrEnum):
    """Whose memories a question is reaching for."""

    SELF = "self"
    CAREGIVER = "caregiver"
    UNSCOPED = "unscoped"


def scope_of(question: str) -> Scope:
    """Decide from pronouns alone. No model, no guessing."""
    match = QUESTION_WORD.search(question)
    asked = question[match.end() :] if match else question

    first = FIRST_PERSON.search(asked) is not None
    second = SECOND_PERSON.search(asked) is not None

    if first and not second:
        return Scope.CAREGIVER
    if second and not first:
        return Scope.SELF

    # "I heard you have a dog?" names both, and means neither exclusively. An
    # unscoped question searches everything, which is what retrieval did before this
    # module existed — the old behaviour, kept for the case it was right for.
    return Scope.UNSCOPED
