"""Authoring a persona without gaps.

Every seed defect this project has had was an *omission*: a mother nobody wrote
down, a plural nobody thought of, a death no question could reach, an ethnicity that
was never authored and so got invented. None of them were hard. They were simply
easy to forget, and each was found weeks later by talking to a persona and watching
her deny her own dog.

So the checklist asks, the checker finds what was skipped, and the two things
authors reliably get wrong — keywords and links — are not asked for at all. They are
derived.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from personasim.models import Persona, RelationshipMemory, SemanticMemory
from personasim.persona import build_persona, read_seed_file
from personasim.persona.checklist import ESSENTIAL, FACTS, RELATIONS, keywords_for
from personasim.persona.gaps import find_gaps, report
from personasim.persona.interview import Draft, Person, interview, render, to_seed, validate

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "personas" / "elena.yaml"

# The answers a real author would give, in the order the interview asks for them.
ANSWERS = [
    "Marcus Hale",
    "44",
    "Luthier",
    "patient, exacting",
    "craft, quiet",
    "A luthier in Bristol who builds guitars by hand.",
    "Slow and plain. Says little, and stops when he has said it.",
    # facts
    "I live in Bristol, above the workshop",
    "Bristol",
    "I grew up in Leeds",
    "Leeds",
    "I build guitars by hand",
    "luthier",
    "My family is Welsh on my mother's side and Irish on my father's",
    "Welsh and Irish",
    "I have one older sister, Nia",
    "one older sister, Nia",
    "I have never had a pet",
    "none",
    "",  # education
    "",  # food
    "",  # fear
    "",  # habit
    # people
    "Ruth Hale",
    "My mother Ruth",
    "",
    "Alan Hale",
    "My father Alan, a joiner",
    "2019-11-02",
    "",  # no partner
    "Nia Hale",
    "My older sister Nia",
    "",
    "",  # no friend
    "",  # no employer
    # events
    "I finished my first guitar in my father's workshop",
    "2001-06-14",
    "Leeds",
    "Alan",
    "I moved to Bristol and opened the shop",
    "2008-03-01",
    "Bristol",
    "Nia",
    "1",
    "",  # done
]


def scripted(answers: list[str]) -> Any:
    remaining = iter(answers)

    def ask(_: str) -> str:
        return next(remaining)

    return ask


@pytest.fixture
def marcus() -> dict[str, Any]:
    draft = interview(scripted(ANSWERS), lambda _: None)
    return to_seed(draft)


class TestTheReferencePersonaPassesHerOwnChecklist:
    def test_elena_has_no_gaps(self) -> None:
        """She does *now*. She did not when she was written, and that is the point of
        the checklist."""
        gaps = find_gaps(build_persona(read_seed_file(SEED_FILE)))

        assert gaps.is_clean, report(gaps)


class TestTheCheckerFindsWhatWasSkipped:
    def base(self) -> dict[str, Any]:
        return {
            "id": "gappy",
            "identity": {
                "name": "Gappy Person",
                "age": 40,
                "occupation": "Tester",
                "personality": ["thin"],
                "values": ["brevity"],
                "speech_style": "Terse.",
            },
        }

    def test_a_missing_mother_is_reported(self) -> None:
        """Elena had no mother in her seed and no explanation for the omission, so
        asked about one she said "I don't have a mother" — true of her memory, and
        false of any human being. The cast is closed: an omission is a *denial*."""
        gaps = find_gaps(build_persona(read_seed_file(SEED_FILE)))
        assert gaps.is_clean

        thin = Persona(id="thin", identity=build_persona(read_seed_file(SEED_FILE)).identity)
        gaps = find_gaps(thin)

        assert any(relation.relation == "mother" for relation in gaps.missing_relations)
        assert "DENIAL" in report(gaps)

    def test_a_missing_ancestry_is_reported(self) -> None:
        """Authored nowhere, so she invented an English and Scottish descent — and a
        Nigerian one for her wife."""
        thin = Persona(id="thin", identity=build_persona(read_seed_file(SEED_FILE)).identity)

        assert any(fact.attribute == "ancestry" for fact in find_gaps(thin).missing_facts)

    def test_a_death_nothing_can_reach_is_reported(self) -> None:
        """Asked "are they all alive?", Elena said yes — and both her parents were
        dead. The death was in the summary and not in the keywords, and retrieval
        matches literally."""
        identity = build_persona(read_seed_file(SEED_FILE)).identity
        unreachable = Persona(
            id="thin",
            identity=identity,
            memories=[
                RelationshipMemory(
                    summary="My father Alan, who died last winter",
                    keywords=["father", "alan"],  # no `alive`, no `died`
                    person_name="Alan Hale",
                    relation="father",
                )
            ],
        )

        gaps = find_gaps(unreachable)

        assert gaps.unreachable_deaths == ["Alan Hale"]
        assert "alive" in report(gaps)

    def test_a_clean_persona_says_so(self) -> None:
        assert "No gaps" in report(find_gaps(build_persona(read_seed_file(SEED_FILE))))


class TestTheInterviewWritesAValidPersona:
    def test_the_answers_make_a_persona_that_loads(self, marcus: dict[str, Any]) -> None:
        """A seed that cannot load is not a seed. This is where an impossible life is
        caught — a cause that postdates its effect, one fact stated twice."""
        validate(marcus)

    def test_the_yaml_round_trips_and_has_no_gaps(
        self, marcus: dict[str, Any], tmp_path: Path
    ) -> None:
        """The whole point: a persona authored by interview cannot ship with the
        holes Elena shipped with."""
        path = tmp_path / "marcus.yaml"
        path.write_text(render(marcus))

        persona = build_persona(read_seed_file(path))

        assert persona.identity.name == "Marcus Hale"
        assert find_gaps(persona).is_clean, report(find_gaps(persona))


class TestKeywordsAndLinksAreDerivedNeverAsked:
    """The two things authors reliably get wrong. The author writes what is true; the
    machine makes it findable and connects it."""

    def test_the_plural_is_never_forgotten(self, marcus: dict[str, Any], tmp_path: Path) -> None:
        """Keyworded `pet` and not `pets`, Elena denied her own dog on a plural."""
        path = tmp_path / "m.yaml"
        path.write_text(render(marcus))
        persona = build_persona(read_seed_file(path))

        [pet] = [
            memory
            for memory in persona.memories
            if isinstance(memory, SemanticMemory) and memory.attribute == "pet"
        ]
        assert {"pet", "pets", "animal", "animals"} <= set(pet.keywords)

    def test_the_past_tense_is_never_forgotten(
        self, marcus: dict[str, Any], tmp_path: Path
    ) -> None:
        """Keyworded `grew up` as one string, "where did you *grow* up?" reached
        nothing. Retrieval matches literally."""
        path = tmp_path / "m.yaml"
        path.write_text(render(marcus))
        persona = build_persona(read_seed_file(path))

        [hometown] = [
            memory
            for memory in persona.memories
            if isinstance(memory, SemanticMemory) and memory.attribute == "hometown"
        ]
        assert {"grew", "grow", "from", "raised"} <= set(hometown.keywords)

    def test_a_death_is_reachable_from_alive(self, marcus: dict[str, Any], tmp_path: Path) -> None:
        path = tmp_path / "m.yaml"
        path.write_text(render(marcus))
        persona = build_persona(read_seed_file(path))

        [father] = [
            memory
            for memory in persona.memories
            if isinstance(memory, RelationshipMemory) and memory.relation == "father"
        ]
        assert {"alive", "dead", "died"} <= set(father.keywords)

    def test_a_death_becomes_an_event_of_its_own(self, marcus: dict[str, Any]) -> None:
        """So that "when did he die?" reaches something, and the person's memory can
        point at it."""
        keys = {event["key"] for event in marcus["episodic"]}

        assert "alan-hale_death" in keys

    def test_naming_who_was_there_builds_the_involves_edges(self, marcus: dict[str, Any]) -> None:
        [first] = [event for event in marcus["episodic"] if event["key"].startswith("i-finished")]

        assert {"target": "alan-hale", "relation": "involves"} in first["links"]

    def test_the_causal_spine_is_built_from_the_answers(self, marcus: dict[str, Any]) -> None:
        """The links are what stop the model inventing its own reasons, differently
        every session."""
        [moved] = [event for event in marcus["episodic"] if event["key"].startswith("i-moved")]

        assert any(
            link["relation"] == "caused_by" and link["target"].startswith("i-finished")
            for link in moved["links"]
        )

    def test_keywords_fold_in_the_question_vocabulary(self) -> None:
        keywords = keywords_for("I live in Bristol", ("live", "lives", "city", "home"))

        assert "bristol" in keywords
        assert {"live", "lives", "city", "home"} <= set(keywords)


class TestTheChecklistItself:
    def test_every_essential_item_says_why(self) -> None:
        """An author who is told to fill in a field will skip it. An author who is
        told what breaks if he skips it will not."""
        for fact in ESSENTIAL:
            assert fact.because, fact.key
        for relation in RELATIONS:
            if relation.essential:
                assert relation.because, relation.relation

    def test_both_parents_are_essential(self) -> None:
        """Everyone has them, and the cast is closed, so an omission is a denial."""
        essential = {relation.relation for relation in RELATIONS if relation.essential}

        assert {"mother", "father"} <= essential

    def test_ancestry_is_essential(self) -> None:
        assert "ancestry" in {fact.attribute for fact in ESSENTIAL}

    def test_the_negative_space_is_prompted_for(self) -> None:
        """ "He is the only pet I have ever had" answers "what was your first pet?"
        truthfully, instead of inviting an invention."""
        [pet] = [fact for fact in FACTS if fact.key == "pet"]

        assert "negative space" in pet.hint


def test_a_person_who_died_carries_the_death_vocabulary() -> None:
    person = Person(
        key="alan",
        name="Alan Hale",
        relation="father",
        vocabulary=("father", "dad"),
        closeness=0.9,
        importance=0.9,
        note="My father Alan",
        died_on=__import__("datetime").date(2019, 11, 2),
    )
    seed = to_seed(Draft(persona_id="x", identity={}, people=[person]))

    [father] = seed["relationships"]
    assert {"alive", "dead", "died", "passed"} <= set(father["keywords"])
