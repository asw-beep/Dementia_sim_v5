"""Authoring a persona by being asked, rather than by remembering to.

Every seed defect this project has had was an *omission*: a mother nobody wrote
down, a plural nobody thought of, a death that no question could reach. None of them
were hard. They were simply easy to forget, and they were only discovered by talking
to a persona weeks later and watching her deny her own dog.

So the checklist asks. And the two things authors reliably get wrong — keywords and
links — are not asked at all; they are derived:

**Keywords** come from `checklist.keywords_for`, which folds in every form a question
is known to arrive in. The author writes what is true; the machine makes it findable.

**Links** come from the answers. Naming who was present at an event creates the
`involves` edges. Saying which earlier event brought a later one about creates the
`caused_by` spine. Saying a person has died creates the death memory, keyworded so
that "are they still alive?" can reach it.

The result is validated before it is written: a seed that cannot load is not a seed.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yaml

from personasim.persona.checklist import (
    DEATH_VOCABULARY,
    FACTS,
    RELATIONS,
    Fact,
    Relation,
    keywords_for,
)
from personasim.persona.loader import SeedError, build_persona
from personasim.persona.seed import PersonaSeed

Ask = Callable[[str], str]


@dataclass
class Person:
    key: str
    name: str
    relation: str
    vocabulary: tuple[str, ...]
    closeness: float
    importance: float
    note: str
    died_on: date | None = None


@dataclass
class Event:
    key: str
    happened: str
    on: date
    where: str
    participants: list[str] = field(default_factory=list)
    #: The key of the earlier event that brought this one about.
    caused_by: str | None = None


@dataclass
class Draft:
    """The persona as answered, before it is a file."""

    persona_id: str = ""
    identity: dict[str, Any] = field(default_factory=dict)
    facts: list[dict[str, Any]] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)


def interview(ask: Ask, say: Callable[[str], None]) -> Draft:
    """Ask the questions. `ask` returns a line; a blank line means "skip"."""
    draft = Draft()

    say("\n=== Who is she? ===\n")
    name = _required(ask, "Full name")
    draft.persona_id = _slug(name)
    draft.identity = {
        "name": name,
        "age": int(_required(ask, "Age")),
        "occupation": _required(ask, "Occupation"),
        "personality": _list(ask, "Personality traits (comma separated)"),
        "values": _list(ask, "What she cares about (comma separated)"),
        "description": _required(ask, "Two lines for her card, as a stranger would read them"),
        # Two traps here, and both were paid for.
        #
        # Never quote a phrase: a sample line becomes a catchphrase, and the model
        # will apply "a bit of a stretch" to a wedding and to a dog.
        #
        # Never say she digresses. A style that says she "drifts into talk of timber"
        # is an instruction to digress — and having nothing true to digress *with*,
        # the model invents. Marcus was given that style and answered a question about
        # his mother with a long line of Welsh makers and the sound of her voice, none
        # of which was authored. Made plain, he said only what he knew.
        "speech_style": _speech_style(ask, say),
    }

    say("\n=== What she knows about herself ===")
    say("Blank to skip, but read the reason first — each of these broke a persona.\n")
    for fact in FACTS:
        answered = _fact(ask, say, fact)
        if answered:
            draft.facts.append(answered)

    say("\n=== The people in her life ===")
    say("The cast is CLOSED: asked about anyone not here, she says she has none.")
    say("An omission is not a gap — it is a denial. Elena had no mother, so she")
    say("told a caregiver she did not have one.\n")
    for relation in RELATIONS:
        person = _person(ask, say, relation)
        if person:
            draft.people.append(person)

    say("\n=== Her life, in order ===")
    say("Dated events, each caused by an earlier one. This is the narrative spine:")
    say("a life with no unexplained jumps. The causal links are what stop the model")
    say("inventing its own reasons, differently every session.\n")
    draft.events = _events(ask, say, draft.people)

    return draft


def to_seed(draft: Draft) -> dict[str, Any]:
    """The draft as a seed file. Keywords and links are derived, never asked for."""
    people_by_name = {person.name: person for person in draft.people}

    semantic = [
        {
            "key": fact["key"],
            "summary": fact["summary"],
            "keywords": keywords_for(f"{fact['summary']} {fact['value']}", fact["vocabulary"]),
            "subject": "self",
            "attribute": fact["attribute"],
            "value": fact["value"],
            "importance": fact["importance"],
        }
        for fact in draft.facts
    ]

    episodic: list[dict[str, Any]] = []
    for event in draft.events:
        links = [
            {"target": people_by_name[who].key, "relation": "involves"}
            for who in event.participants
            if who in people_by_name
        ]
        if event.caused_by:
            links.append({"target": event.caused_by, "relation": "caused_by"})

        episodic.append(
            {
                "key": event.key,
                "summary": event.happened,
                "keywords": keywords_for(event.happened),
                "occurred_on": event.on,
                "location": event.where,
                "participants": list(event.participants),
                "importance": 0.8,
                "links": links,
            }
        )

    relationships: list[dict[str, Any]] = []
    for person in draft.people:
        entry: dict[str, Any] = {
            "key": person.key,
            "summary": person.note,
            # A dead relative must be reachable from the word "alive". Elena's were
            # not: asked "are they all alive?" she said yes, and both parents were dead.
            "keywords": keywords_for(
                f"{person.name} {person.note}",
                person.vocabulary + (DEATH_VOCABULARY if person.died_on else ()),
            ),
            "person_name": person.name,
            "relation": person.relation,
            "closeness": person.closeness,
            "importance": person.importance,
        }
        relationships.append(entry)

    # A death is an *event*, so that "when did she die?" and "are they alive?" both
    # reach something, and so the person's memory can point at it.
    for person in draft.people:
        if person.died_on is None:
            continue
        key = f"{person.key}_death"
        episodic.append(
            {
                "key": key,
                "summary": f"My {person.relation} {person.name} died",
                "keywords": keywords_for(f"{person.name} {person.relation}", DEATH_VOCABULARY),
                "occurred_on": person.died_on,
                "participants": [person.name],
                "importance": 0.95,
                "links": [{"target": person.key, "relation": "involves"}],
            }
        )
        for entry in relationships:
            if entry["key"] == person.key:
                entry["links"] = [{"target": key, "relation": "concerns"}]

    seed: dict[str, Any] = {"id": draft.persona_id, "identity": draft.identity}
    if semantic:
        seed["semantic"] = semantic
    if episodic:
        seed["episodic"] = sorted(episodic, key=lambda event: event["occurred_on"])
    if relationships:
        seed["relationships"] = relationships
    return seed


def validate(seed: dict[str, Any]) -> None:
    """A seed that cannot load is not a seed.

    This is where an impossible life is caught — a cause that postdates its effect,
    one fact stated twice, a link to nobody.
    """
    build_persona(PersonaSeed.model_validate(seed))


def render(seed: dict[str, Any]) -> str:
    return yaml.safe_dump(seed, sort_keys=False, allow_unicode=True, width=100)


# --- the questions -----------------------------------------------------------


def _fact(ask: Ask, say: Callable[[str], None], fact: Fact) -> dict[str, Any] | None:
    say(f"\n  {fact.question}")
    if fact.because:
        say(f"    why: {fact.because}")
    if fact.hint:
        say(f"    tip: {fact.hint}")

    summary = ask("    > ").strip()
    if not summary:
        if fact.essential:
            say("    ! essential — she will refuse or invent without it. Try again.")
            return _fact(ask, say, fact)
        return None

    value = ask("    in a few words, the fact itself (e.g. 'Boston') > ").strip() or summary
    return {
        "key": fact.key,
        "summary": summary,
        "value": value,
        "attribute": fact.attribute,
        "vocabulary": fact.vocabulary,
        "importance": fact.importance,
    }


def _person(ask: Ask, say: Callable[[str], None], relation: Relation) -> Person | None:
    say(f"\n  {relation.question}")
    if relation.because:
        say(f"    why: {relation.because}")

    name = ask("    name (blank to skip) > ").strip()
    if not name:
        if relation.essential:
            say("    ! essential — omitting her makes the persona DENY having one.")
            say("      If she is dead or estranged, say so; do not leave her out.")
            return _person(ask, say, relation)
        return None

    note = ask("    who they are, in her own words > ").strip() or f"My {relation.relation}"
    died = ask("    died? date as YYYY-MM-DD, or blank if living > ").strip()

    return Person(
        key=_slug(name),
        name=name,
        relation=relation.relation,
        vocabulary=relation.vocabulary,
        closeness=relation.closeness,
        importance=relation.importance,
        note=note,
        died_on=date.fromisoformat(died) if died else None,
    )


def _events(ask: Ask, say: Callable[[str], None], people: Sequence[Person]) -> list[Event]:
    events: list[Event] = []

    while True:
        happened = ask(f"\n  Event {len(events) + 1} — what happened? (blank to finish) > ").strip()
        if not happened:
            break

        on = date.fromisoformat(ask("    when? YYYY-MM-DD > ").strip())
        where = ask("    where? > ").strip()

        # Asked once, not once per person — the question lived inside a comprehension
        # and interrogated the author separately about every member of the cast.
        roster = ", ".join(person.name for person in people) or "nobody"
        named = ask(f"    who was there? ({roster}) > ").strip().lower()
        present = [person.name for person in people if person.name.split()[0].lower() in named]

        caused_by = None
        if events:
            say("    which earlier event brought this about?")
            for index, earlier in enumerate(events, start=1):
                say(f"      {index}. {earlier.happened[:60]}")
            choice = ask("    number, or blank for none > ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(events):
                caused_by = events[int(choice) - 1].key

        key = _slug(happened, words=5)
        if any(existing.key == key for existing in events):
            key = f"{key}-{len(events) + 1}"

        events.append(
            Event(
                key=key,
                happened=happened,
                on=on,
                where=where,
                participants=present,
                caused_by=caused_by,
            )
        )

    return events


def _speech_style(ask: Ask, say: Callable[[str], None]) -> str:
    say("\n  How she speaks.")
    say("    Describe the MANNER. Do not quote a phrase she uses — it becomes a")
    say("    catchphrase the model reaches for in every answer.")
    say("    Do not say she digresses, elaborates, or embellishes. That is an")
    say("    instruction to invent: with nothing true to digress with, the model")
    say("    supplies something. 'Slow and plain' is a better style than 'drifts")
    say("    into talk of timber', and it is the difference between a persona who")
    say("    says what she knows and one who decorates it.")
    return _required(ask, "in a line")


def _required(ask: Ask, question: str) -> str:
    while True:
        answer = ask(f"  {question} > ").strip()
        if answer:
            return answer


def _list(ask: Ask, question: str) -> list[str]:
    while True:
        parts = [part.strip() for part in ask(f"  {question} > ").split(",") if part.strip()]
        if parts:
            return parts


def _slug(text: str, *, words: int | None = None) -> str:
    """A key a human can read in an error message. That is the whole point of keys:
    an authoring mistake should name `maya`, not a UUID."""
    cleaned = "".join(char if char.isalnum() or char.isspace() else " " for char in text.lower())
    parts = cleaned.split()[:words]
    return "-".join(parts) or "unnamed"


__all__ = ["Draft", "SeedError", "interview", "render", "to_seed", "validate"]
