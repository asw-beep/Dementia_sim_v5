"""What the *caregiver* told us. Deterministic, and deliberately hard of hearing.

There are only ever two people here: the persona, and the caregiver she is talking
to. The caregiver is a **role, not an identity** — they may say "I'm the nurse" or
"I'm your doctor", never "I'm Aswin". So formation does not track who it is
speaking to; it already knows. Everything the caregiver discloses is a fact about
`CAREGIVER`, always, whether or not they have said anything about themselves.

That single decision deletes a whole class of bug rather than fixing it. When the
speaker was a name to be learned, a fact disclosed *before* the name was stranded
on an anonymous subject forever — nothing re-attributed it, consolidation could not
merge it, and it carried no keyword that could reach it. With a fixed subject there
is no anonymous phase, so nothing can be stranded in it.

Formation reads the caregiver's message. It never reads the persona's reply. That
is the whole design: a model asked about a mother the persona does not have will
produce one — her silence, her sleeplessness, all of it — and no prompt reliably
stops it. So the model's output is not an input here. A hallucinated biography
cannot become a memory because there is no code path by which it could, which is a
stronger guarantee than any instruction.

Extraction is rule-based, not model-based, for the same reason retrieval is: a
model deciding what was disclosed would decide differently on two hearings of the
same sentence, and a memory formed by a coin toss is worse than no memory.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from personasim.models.memory import Memory, SemanticMemory
from personasim.retrieval.entities import extract_keywords

# The other person in the room, and the subject of everything they disclose. A
# role, not a name: this system has exactly two people in it, and the persona
# never needs to work out which one is speaking.
CAREGIVER = "my caregiver"

# How each disclosure reads once it is a memory. Written in the persona's own
# voice — the seed authoring rules apply to memories formed at runtime exactly as
# they apply to authored ones.
PHRASING: dict[str, str] = {
    "role": "{subject} is a {value}",
    "city": "{subject} lives in {value}",
    # "grew up in", not "is from". Told "I grew up in Vermont" and asked "where did
    # I grow up?", the persona refused: she had the memory, but it said the speaker
    # *was from* Vermont, and she is under orders to add nothing, so she would not
    # equate the two. Being pedantic is the correct behaviour; throwing away what
    # was actually said is the bug.
    "hometown": "{subject} grew up in {value}",
    "family": "{subject} has {value}",
}

# The words a question about this attribute will actually arrive as. Without them a
# memory is stored and unfindable: keyworded `chicago, caregiver, city`, it cannot
# answer "where do I live?", which tokenizes to `live`. The fact is remembered
# perfectly and can never be recalled.
#
# Chosen narrowly, per the Stage 5 lesson that a lazy keyword is a spurious memory
# waiting to fire. And with every form a question might use, per the Stage 8 lesson
# that retrieval matches literally: a memory keyworded `grew` cannot answer "where
# did I *grow* up?". An unused keyword costs a string; a missing one costs a memory.
ATTRIBUTE_KEYWORDS: dict[str, list[str]] = {
    "role": ["role", "job", "work", "works", "occupation", "profession", "living"],
    # Not "living": "for a living" asks about a job, and a city keyworded with it
    # would drag the caregiver's address into every question about their work.
    "city": ["live", "lives", "city", "home"],
    "hometown": ["hometown", "grew", "grow", "raised", "born", "childhood", "originally"],
    "family": ["family", "children", "child", "kids", "kid", "son", "daughter"],
}

# Every pattern is anchored to an explicit disclosure — "I'm a", "I live in" — so a
# passing remark cannot become a fact.
#
# The first version recognised only the most formal phrasing of each thing ("my
# name is", "I work as", "I'm from"), and a live conversation showed what that
# costs: told "I'm a nurse", "I grew up in Vermont", "I've got two kids", the
# persona formed *nothing*. A persona who does not listen is a worse failure than
# one who over-hears, because it is the one the user notices. The guard against
# invention was never the *formality* of the phrasing — it is the anchor and the
# short-noun-phrase rule, and both survive hearing the ordinary way of saying a
# thing.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # "I'm your nurse", "I'm the doctor", "I'm a nurse". The article is what tells a
    # role from a mood: "I'm tired" has none, and discloses nothing.
    (
        "role",
        re.compile(
            r"\bi(?:'m| am)\s+(?:your|the|an|a)\s+(?P<value>[^.,;!?]+)",
            re.IGNORECASE,
        ),
    ),
    (
        "role",
        re.compile(
            r"\b(?:i work as|my job is|i(?:'m| am) employed as)\s+(?:an?\s+)?"
            r"(?P<value>[^.,;!?]+)",
            re.IGNORECASE,
        ),
    ),
    ("city", re.compile(r"\bi live in\s+(?P<value>[^.,;!?]+)", re.IGNORECASE)),
    (
        "hometown",
        re.compile(
            r"\bi(?:(?:'m| am) from|(?: grew up| was raised| was born) in)\s+"
            r"(?P<value>[^.,;!?]+)",
            re.IGNORECASE,
        ),
    ),
    (
        "family",
        re.compile(
            r"\bi\s*(?:'ve got|'ve|have got|have|got)\s+(?P<value>[^.,;!?]*?\b"
            r"(?:kids?|children|child|sons?|daughters?)\b)",
            re.IGNORECASE,
        ),
    ),
]

# Split *behind* the terminator, so a sentence keeps the mark that says what kind
# of sentence it was. Splitting on `[.!?]` would throw away the only evidence that
# "Do I have any kids?" was a question.
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# A question, with or without the mark — people drop it constantly in chat.
INTERROGATIVE = re.compile(
    r"^(?:who|what|where|when|why|how|which|"
    r"do|does|did|have|has|had|am|are|is|was|were|can|could|will|would|should)\b"
    r"|\?\s*$",
    re.IGNORECASE,
)

# "I'm a bit tired" is not a role. `_clean` rejects anything that is not a short
# noun phrase, but these slip through it *because* they are short. A value
# beginning with one of them is a turn of phrase, not a disclosure.
NOT_A_NOUN = frozenset(
    {"bit", "little", "lot", "kind", "sort", "so", "very", "real", "big", "good", "great"}
)

# A disclosure ends at a conjunction as surely as at a full stop: "I live in Chicago
# and I work as a nurse" discloses a city of "Chicago", not of "Chicago and I work
# as a nurse".
CLAUSE_END = re.compile(r"\b(?:and|but|though|although|while|so|because)\b", re.IGNORECASE)

# "I live in Denver now" discloses a city of Denver, not of "Denver now". People say
# *when* as often as *what*, and the when is not part of the fact.
TRAILING_FILLER = re.compile(
    r"\s+(?:now|currently|nowadays|anymore|today|these days|at the moment)$",
    re.IGNORECASE,
)

# A disclosed value is a short noun phrase. Anything longer is a sentence that
# merely began like a disclosure — "I live in the hope that one day..." — and
# guessing at it is exactly the invention this module exists to prevent.
MAX_VALUE_WORDS = 5

# Confidence, not importance, is where the difference from an authored memory shows.
# A seeded memory is the persona's own life, certain by construction; this is
# something said once, in passing, and people misspeak.
DISCLOSED_IMPORTANCE = 0.5
DISCLOSED_CONFIDENCE = 0.9


@dataclass(frozen=True)
class Disclosure:
    """One fact the caregiver stated about themselves, and the words that stated it."""

    attribute: str
    value: str
    matched: str


@dataclass(frozen=True)
class Formed:
    """The outcome of one message passing through formation."""

    memories: list[Memory]
    disclosures: list[Disclosure]

    @property
    def is_empty(self) -> bool:
        return not self.memories


def extract_disclosures(text: str) -> list[Disclosure]:
    """Every self-disclosure in the caregiver's message.

    Questions are read past. "Do I have any kids?" contains the words "I have …
    kids", and the first version of this took them at face value: asked whether they
    had children, the persona recorded that they *did*. A question is the one kind
    of sentence that discloses nothing by definition, and every disclosure verb
    appears intact inside the question that asks about it — so questions are dropped
    before the patterns run. Asking is not telling.
    """
    statements = _statements(text)
    found: list[Disclosure] = []
    claimed: set[str] = set()

    for attribute, pattern in PATTERNS:
        if attribute in claimed:
            # One value per attribute per message. Two patterns can both fire on
            # "I'm the nurse, I work as a nurse"; the first is enough.
            continue

        for statement in statements:
            match = pattern.search(statement)
            if match is None:
                continue

            value = _clean(match.group("value"))
            if value is None:
                continue

            claimed.add(attribute)
            found.append(
                Disclosure(attribute=attribute, value=value, matched=match.group(0).strip())
            )
            break

    return found


def form_memories(text: str, existing: Sequence[Memory] | None = None) -> Formed:
    """Turn what the caregiver said into memories the persona will hold.

    Nothing already known is formed again: re-stating a fact the persona holds is a
    no-op, so a caregiver who repeats themselves does not accumulate duplicates.
    """
    disclosures = extract_disclosures(text)
    known = list(existing or [])
    memories: list[Memory] = []

    for disclosure in disclosures:
        if not _already_known([*known, *memories], disclosure):
            memories.append(_to_memory(disclosure))

    return Formed(memories=memories, disclosures=disclosures)


def _to_memory(disclosure: Disclosure) -> SemanticMemory:
    return SemanticMemory(
        summary=PHRASING[disclosure.attribute].format(subject=CAREGIVER, value=disclosure.value),
        keywords=_keywords(disclosure),
        subject=CAREGIVER,
        attribute=disclosure.attribute,
        value=disclosure.value,
        importance=DISCLOSED_IMPORTANCE,
        confidence=DISCLOSED_CONFIDENCE,
    )


def _keywords(disclosure: Disclosure) -> list[str]:
    """What the memory is about, and what a question about it will sound like.

    Keyed with the same tokenizer retrieval searches with, so the two cannot drift
    apart. This is the Stage 5 lesson from its other end: there, a lazy keyword
    surfaced a memory nobody asked for; here, a missing one buried a memory somebody
    did.
    """
    return list(
        dict.fromkeys(
            [
                *extract_keywords(disclosure.value),
                *extract_keywords(CAREGIVER),
                disclosure.attribute,
                *ATTRIBUTE_KEYWORDS[disclosure.attribute],
            ]
        )
    )


def _already_known(existing: Sequence[Memory], disclosure: Disclosure) -> bool:
    return any(
        isinstance(memory, SemanticMemory)
        and memory.subject == CAREGIVER
        and memory.attribute == disclosure.attribute
        and memory.value.casefold() == disclosure.value.casefold()
        for memory in existing
    )


def _statements(text: str) -> list[str]:
    """The sentences that assert something. Questions are dropped."""
    return [
        sentence
        for raw in SENTENCE_END.split(text)
        if (sentence := raw.strip()) and not INTERROGATIVE.match(sentence)
    ]


def _clean(raw: str) -> str | None:
    """The noun phrase a disclosure discloses, or nothing if it is not one."""
    value = CLAUSE_END.split(raw, maxsplit=1)[0]
    value = " ".join(value.split()).strip(" .,;:!?'\"")
    value = TRAILING_FILLER.sub("", value).strip()

    if not value or len(value.split()) > MAX_VALUE_WORDS:
        return None
    if value.split()[0].casefold() in NOT_A_NOUN:
        return None
    return value
