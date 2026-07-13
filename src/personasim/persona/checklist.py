"""What a persona must know about herself, and the words a question will arrive in.

Elena is the reference. Every entry below exists because its *absence* broke her in
a real conversation:

- She had no mother in her seed and no explanation for the omission, so asked about
  one she said "I don't have a mother" — true of her memory, false of any human.
- Her dog was keyworded `pet` and not `pets`, so "do you have any pets?" reached
  nothing and she denied Compass — two turns after describing him.
- Her hometown was keyworded `grew up`, one string, so "where did you *grow* up?"
  reached nothing. Retrieval matches literally; there is no stemmer.
- Her ethnicity was authored nowhere, so she invented an English and Scottish
  descent, and a Nigerian one for her wife.

So `VOCABULARY` is not a convenience. It is the accumulated list of ways a question
actually gets asked, and deriving keywords from it means an author cannot forget the
plural, the past tense, or the synonym. The author writes what is true; the machine
writes what makes it findable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from personasim.retrieval.entities import extract_keywords

SELF = "self"


@dataclass(frozen=True)
class Fact:
    """One thing a persona should be able to say about herself."""

    key: str
    attribute: str
    #: What the author is asked.
    question: str
    #: Why it matters — shown when the author is tempted to skip it.
    because: str
    #: Every form a question about it arrives in. Retrieval matches literally.
    vocabulary: tuple[str, ...]
    importance: float = 0.5
    #: A persona without this will refuse or invent. Do not skip these.
    essential: bool = False
    #: Prompts the author to state the negative space too.
    hint: str = ""


# Ordered as an interview, not as a schema: the easy ones first, and the ones that
# bit us in the places they bit us.
FACTS: tuple[Fact, ...] = (
    Fact(
        key="city",
        attribute="city",
        question="Where does she live now?",
        because="The first thing anyone asks.",
        vocabulary=("live", "lives", "living", "city", "home", "address"),
        importance=0.85,
        essential=True,
    ),
    Fact(
        key="hometown",
        attribute="hometown",
        question="Where did she grow up?",
        because="Asked as 'where are you from?', which has no other content word in it.",
        vocabulary=(
            "hometown",
            "grew",
            "grow",
            "raised",
            "born",
            "childhood",
            "from",
            "originally",
        ),
        importance=0.8,
        essential=True,
    ),
    Fact(
        key="job",
        attribute="occupation",
        question="What does she do for a living?",
        because="Her identity says her trade; this says what the work actually is.",
        vocabulary=("job", "work", "works", "occupation", "profession", "living", "career"),
        importance=0.85,
        essential=True,
    ),
    Fact(
        key="ancestry",
        attribute="ancestry",
        question="What is her background — ethnicity, ancestry, where her people are from?",
        because=(
            "Elena had none, and invented an English and Scottish descent on nothing. "
            "Ancestry *feels* like something a person simply knows, so the model "
            "supplies it."
        ),
        vocabulary=("ethnicity", "ancestry", "descent", "heritage", "background", "roots"),
        importance=0.45,
        essential=True,
    ),
    Fact(
        key="siblings",
        attribute="siblings",
        question="Does she have brothers or sisters? (say so plainly if she has none)",
        because=(
            "This is the memory that answers 'do you have a sister?' — with a brother, "
            "or with nothing. A question about a relation she does not have must still "
            "reach the memory that says so, or she has nothing to answer from."
        ),
        vocabulary=(
            "brother",
            "brothers",
            "sister",
            "sisters",
            "sibling",
            "siblings",
            "family",
        ),
        importance=0.75,
        essential=True,
        hint="e.g. 'I have one younger brother, Tom' — or 'I am an only child'",
    ),
    Fact(
        key="pet",
        attribute="pet",
        question="Does she have a pet? (say so plainly if she has none)",
        because="Keyworded `pet` and not `pets`, Elena denied her own dog on a plural.",
        vocabulary=("pet", "pets", "animal", "animals", "dog", "cat"),
        importance=0.6,
        hint="State the negative space: 'he is the only pet I have ever had' answers "
        "'what was your first pet?' truthfully instead of inviting an invention.",
    ),
    Fact(
        key="education",
        attribute="education",
        question="What did she study, and where?",
        because="",
        vocabulary=("school", "studied", "study", "university", "college", "degree", "educated"),
        importance=0.7,
    ),
    Fact(
        key="food",
        attribute="favourite_food",
        question="What is her favourite food?",
        because="",
        vocabulary=("food", "eat", "favourite", "favorite", "meal", "cook"),
        importance=0.45,
    ),
    Fact(
        key="fear",
        attribute="fear",
        question="What is she afraid of, or uneasy about?",
        because="",
        vocabulary=("fear", "afraid", "scared", "frightened", "uneasy"),
        importance=0.5,
    ),
    Fact(
        key="habit",
        attribute="habit",
        question="A small habit or quirk of hers?",
        because="",
        vocabulary=("habit", "quirk", "always", "usually"),
        importance=0.3,
    ),
)

ESSENTIAL = tuple(fact for fact in FACTS if fact.essential)


@dataclass(frozen=True)
class Relation:
    """One kind of person a persona is asked about."""

    relation: str
    question: str
    because: str
    vocabulary: tuple[str, ...]
    closeness: float = 0.7
    importance: float = 0.7
    essential: bool = False


# The cast is *closed*: the persona is told these are the only people in her life,
# and asked about anyone else she says she has none. That is what stops her
# inventing a sister — and it is why an omission here is not a gap, it is a denial.
# Elena's seed had no mother, so she said she did not have one.
RELATIONS: tuple[Relation, ...] = (
    Relation(
        relation="mother",
        question="Her mother",
        because=(
            "Everyone has one. Omit her and the persona does not merely fail to "
            "recall her — she flatly denies having a mother, which is what Elena did."
        ),
        vocabulary=("mother", "mum", "mom", "parent", "parents", "family"),
        closeness=0.9,
        importance=0.9,
        essential=True,
    ),
    Relation(
        relation="father",
        question="Her father",
        because="Same as the mother: an omission reads as a denial.",
        vocabulary=("father", "dad", "papa", "parent", "parents", "family"),
        closeness=0.9,
        importance=0.9,
        essential=True,
    ),
    Relation(
        relation="partner",
        question="Her partner or spouse, if she has one",
        because="",
        vocabulary=("wife", "husband", "spouse", "partner", "married", "family"),
        closeness=0.95,
        importance=0.95,
    ),
    Relation(
        relation="sibling",
        question="A brother or sister, if she has one",
        because="Must agree with what you said about siblings above.",
        vocabulary=("brother", "sister", "sibling", "siblings", "family"),
        closeness=0.7,
        importance=0.8,
    ),
    Relation(
        relation="close friend",
        question="A close friend",
        because="",
        vocabulary=("friend", "friends", "best friend"),
        closeness=0.8,
        importance=0.65,
    ),
    Relation(
        relation="employer",
        question="Her boss or colleague",
        because="",
        vocabulary=("boss", "employer", "colleague", "work"),
        closeness=0.35,
        importance=0.4,
    ),
)

# A dead relative must still be reachable from the word "alive". Elena's were not:
# asked "are they all alive?" she said yes, and both her parents were dead.
DEATH_VOCABULARY: tuple[str, ...] = ("died", "death", "dead", "alive", "passed", "funeral")


def keywords_for(text: str, vocabulary: tuple[str, ...] = ()) -> list[str]:
    """What the memory is about, plus every form a question about it arrives in.

    The single most valuable line in this module. An author writes what is true; this
    makes it findable — and it is *not* optional politeness. A memory nobody can
    reach is a memory the persona does not have, and that failure is silent.
    """
    return list(dict.fromkeys([*extract_keywords(text), *vocabulary]))


@dataclass
class Gaps:
    """What a seed is missing, measured against the reference persona."""

    missing_facts: list[Fact] = field(default_factory=list)
    missing_relations: list[Relation] = field(default_factory=list)
    unreachable_deaths: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return not (self.missing_facts or self.missing_relations or self.unreachable_deaths)
