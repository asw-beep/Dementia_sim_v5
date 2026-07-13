"""Stage 3: seed file parsing, loading, and idempotency."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from personasim.memory.formation import consolidate
from personasim.models import (
    EpisodicMemory,
    LinkRelation,
    MemoryType,
    RelationshipMemory,
    SemanticMemory,
)
from personasim.persona import (
    PersonaSeed,
    SeedError,
    memory_id_for,
    read_seed_file,
    seed_from_file,
    seed_persona,
)
from personasim.storage import Database, MemoryRepository, PersonaRepository

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "personas" / "elena.yaml"

MINIMAL_SEED = """
id: test-persona
identity:
  name: Test Person
  age: 30
  occupation: Tester
  personality: [precise]
  values: [rigour]
  speech_style: Terse.
semantic:
  - key: city
    summary: Lives in Boston
    keywords: [boston]
    subject: self
    attribute: city
    value: Boston
episodic:
  - key: wedding
    summary: Married in Vermont
    keywords: [wedding]
    occurred_on: 2014-09-06
    links:
      - {target: spouse, relation: involves}
relationships:
  - key: spouse
    summary: Married to Maya
    keywords: [maya]
    person_name: Maya
    relation: wife
"""


@pytest.fixture
def seed_path(tmp_path: Path) -> Path:
    path = tmp_path / "seed.yaml"
    path.write_text(MINIMAL_SEED)
    return path


class TestSeedParsing:
    def test_keys_resolve_to_deterministic_ids(self) -> None:
        first = memory_id_for("elena-marsh", "wedding")
        second = memory_id_for("elena-marsh", "wedding")
        assert first == second

    def test_ids_differ_across_personas_and_keys(self) -> None:
        assert memory_id_for("a", "wedding") != memory_id_for("b", "wedding")
        assert memory_id_for("a", "wedding") != memory_id_for("a", "graduation")

    def test_links_are_resolved_from_keys(self, seed_path: Path) -> None:
        persona = read_seed_file(seed_path).to_persona()
        wedding = persona.by_id(memory_id_for("test-persona", "wedding"))
        assert wedding.linked_ids() == [memory_id_for("test-persona", "spouse")]

    def test_missing_file_raises_seed_error(self, tmp_path: Path) -> None:
        with pytest.raises(SeedError, match="cannot read"):
            read_seed_file(tmp_path / "absent.yaml")

    def test_invalid_yaml_raises_seed_error(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("id: [unclosed")
        with pytest.raises(SeedError, match="not valid YAML"):
            read_seed_file(path)

    def test_non_mapping_raises_seed_error(self, tmp_path: Path) -> None:
        path = tmp_path / "list.yaml"
        path.write_text("- a\n- b\n")
        with pytest.raises(SeedError, match="mapping"):
            read_seed_file(path)

    def test_unknown_field_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "extra.yaml"
        path.write_text(MINIMAL_SEED + "\nmood: wistful\n")
        with pytest.raises(SeedError):
            read_seed_file(path)

    def test_duplicate_keys_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate memory keys"):
            PersonaSeed.model_validate(
                {
                    "id": "p",
                    "identity": {
                        "name": "N",
                        "age": 1,
                        "occupation": "o",
                        "personality": ["p"],
                        "values": ["v"],
                        "speech_style": "s",
                    },
                    "semantic": [
                        {
                            "key": "dup",
                            "summary": "a",
                            "keywords": ["a"],
                            "subject": "s",
                            "attribute": "a",
                            "value": "v",
                        }
                    ],
                    "episodic": [{"key": "dup", "summary": "b", "keywords": ["b"]}],
                }
            )

    def test_link_to_unknown_key_names_the_key(self, tmp_path: Path) -> None:
        path = tmp_path / "dangling.yaml"
        path.write_text(MINIMAL_SEED.replace("target: spouse", "target: nobody"))
        with pytest.raises(SeedError, match=r"unknown keys.*nobody"):
            read_seed_file(path)

    def test_self_link_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "selflink.yaml"
        path.write_text(MINIMAL_SEED.replace("target: spouse", "target: wedding"))
        with pytest.raises(SeedError, match="links to itself"):
            read_seed_file(path)


class TestSeeding:
    def test_seeding_creates_all_memories(self, database: Database, seed_path: Path) -> None:
        report = seed_from_file(database, seed_path)
        assert report.memories_created == 3
        assert report.memories_skipped == 0
        assert report.identity_updated
        assert not report.was_noop

    def test_reseeding_is_a_noop(self, database: Database, seed_path: Path) -> None:
        seed_from_file(database, seed_path)
        report = seed_from_file(database, seed_path)

        assert report.memories_created == 0
        assert report.memories_skipped == 3
        assert not report.identity_updated
        assert report.was_noop

    def test_reseeding_does_not_duplicate_rows(self, database: Database, seed_path: Path) -> None:
        seed_from_file(database, seed_path)
        seed_from_file(database, seed_path)

        with database.session() as session:
            persona = PersonaRepository(session).load("test-persona")
        assert persona is not None
        assert len(persona.memories) == 3

    def test_changed_identity_is_updated_on_reseed(
        self, database: Database, tmp_path: Path, seed_path: Path
    ) -> None:
        seed_from_file(database, seed_path)

        revised = tmp_path / "revised.yaml"
        revised.write_text(MINIMAL_SEED.replace("age: 30", "age: 31"))
        report = seed_from_file(database, revised)

        assert report.identity_updated
        assert report.memories_created == 0

        with database.session() as session:
            persona = PersonaRepository(session).load("test-persona")
        assert persona is not None
        assert persona.identity.age == 31

    def test_persona_reconstructs_identically(self, database: Database, seed_path: Path) -> None:
        expected = read_seed_file(seed_path).to_persona()
        seed_persona(database, expected)

        with database.session() as session:
            loaded = PersonaRepository(session).load(expected.id)

        assert loaded is not None
        assert loaded.identity == expected.identity
        assert {m.id for m in loaded.memories} == {m.id for m in expected.memories}
        for original in expected.memories:
            assert loaded.by_id(original.id) == original

    def test_links_survive_the_database(self, database: Database, seed_path: Path) -> None:
        seed_from_file(database, seed_path)
        with database.session() as session:
            persona = PersonaRepository(session).load("test-persona")

        assert persona is not None
        wedding = persona.by_id(memory_id_for("test-persona", "wedding"))
        assert wedding.linked_ids() == [memory_id_for("test-persona", "spouse")]


class TestAnEditedSeedIsNotLostInSilence:
    """Seeding is idempotent by memory id, and ids come from the seed *key*, not
    the content. So an edited memory resolves to one that already exists and is
    skipped — the edit never lands.

    Stage 6 rewrote all 27 of Elena's summaries to fix a defect that made her hand
    her own father to her wife's family. Any database seeded before that would
    still hold the broken originals, while `persona seed` reported "already
    seeded; nothing to do."
    """

    def edited(self, tmp_path: Path) -> Path:
        path = tmp_path / "edited.yaml"
        path.write_text(MINIMAL_SEED.replace("Lives in Boston", "I live in Boston"))
        return path

    def test_an_edit_is_reported_rather_than_swallowed(
        self, database: Database, tmp_path: Path, seed_path: Path
    ) -> None:
        seed_from_file(database, seed_path)
        report = seed_from_file(database, self.edited(tmp_path))

        assert report.has_stale_memories
        assert report.memories_stale == 1
        assert report.memories_updated == 0

    def test_an_unchanged_seed_is_never_reported_stale(
        self, database: Database, seed_path: Path
    ) -> None:
        """`created_at` is stamped at construction, so a memory rebuilt from an
        unchanged file differs from the stored one on every run. Compare it and
        every memory looks edited, always."""
        seed_from_file(database, seed_path)
        report = seed_from_file(database, seed_path)

        assert not report.has_stale_memories
        assert report.was_noop

    def test_force_lands_the_edit(
        self, database: Database, tmp_path: Path, seed_path: Path
    ) -> None:
        seed_from_file(database, seed_path)
        report = seed_from_file(database, self.edited(tmp_path), force=True)

        assert report.memories_updated == 1
        assert report.memories_created == 0

        with database.session() as session:
            persona = PersonaRepository(session).load("test-persona")
        assert persona is not None
        assert persona.by_id(memory_id_for("test-persona", "city")).summary == "I live in Boston"

    def test_force_does_not_reset_when_the_memory_was_formed(
        self, database: Database, tmp_path: Path, seed_path: Path
    ) -> None:
        """Rewriting what a memory *says* must not restate when it was formed, or
        every re-seed quietly resets the persona's memory birthdates — and Phase 5
        is built on memories having an age."""
        seed_from_file(database, seed_path)
        city = memory_id_for("test-persona", "city")

        with database.session() as session:
            born = MemoryRepository(session).get(city)
        assert born is not None

        seed_from_file(database, self.edited(tmp_path), force=True)

        with database.session() as session:
            rewritten = MemoryRepository(session).get(city)
        assert rewritten is not None
        assert rewritten.created_at == born.created_at

    def test_force_cannot_touch_what_the_persona_learned(
        self, database: Database, tmp_path: Path, seed_path: Path
    ) -> None:
        """The test worth more than the flag.

        A formed memory's id is a random uuid4, which no seed key resolves to, so
        it is not in the set `--force` may write. That is not a filter that could
        be misconfigured — it is the shape of the id space.
        """
        seed_from_file(database, seed_path)

        learned = SemanticMemory(
            summary="Sam lives in Chicago",
            keywords=["chicago"],
            subject="Sam",
            attribute="city",
            value="Chicago",
        )
        with database.session() as session:
            MemoryRepository(session).add("test-persona", learned)

        seed_from_file(database, self.edited(tmp_path), force=True)

        with database.session() as session:
            survivor = MemoryRepository(session).get(learned.id)

        assert survivor == learned

    def test_a_seeded_id_is_derivable_from_the_seed_file(self, seed_path: Path) -> None:
        """What tells an authored memory from a learned one — with no column for it.

        `--force` writes exactly the ids this seed file resolves. Relying on that
        is only sound if it is enforced, so it is enforced here rather than left as
        an accident of two code paths.
        """
        persona = read_seed_file(seed_path).to_persona()

        assert {memory.id for memory in persona.memories} == {
            memory_id_for("test-persona", key) for key in ("city", "wedding", "spouse")
        }


class TestASeedMayNotContradictItself:
    """A persona cannot both live in Boston and live in Denver.

    This is also what makes a guarantee the roadmap already claims *true*.
    Session-end consolidation reduces each duplicated (subject, attribute) to its
    most recent statement, and is documented as never touching the authored life.
    That held only by luck — four of Elena's authored facts are eligible right now.
    Forbidding the duplicate makes the group of two impossible, so consolidation
    cannot find one to merge.
    """

    def with_extra_fact(self, tmp_path: Path, subject: str, key: str) -> Path:
        """A second semantic memory, spliced into the seed's `semantic:` section."""
        extra = (
            f"  - key: {key}\n"
            f"    summary: Lives in Denver\n"
            f"    keywords: [denver]\n"
            f"    subject: {subject}\n"
            f"    attribute: city\n"
            f"    value: Denver\n"
            f"episodic:"
        )
        path = tmp_path / f"{key}.yaml"
        path.write_text(MINIMAL_SEED.replace("episodic:", extra, 1))
        return path

    def test_two_facts_stating_the_same_attribute_are_refused(self, tmp_path: Path) -> None:
        path = self.with_extra_fact(tmp_path, subject="self", key="other_city")

        with pytest.raises(SeedError, match="a fact may be stated once"):
            read_seed_file(path)

    def test_the_error_names_the_authors_keys(self, tmp_path: Path) -> None:
        path = self.with_extra_fact(tmp_path, subject="self", key="other_city")

        with pytest.raises(SeedError, match="'city' and 'other_city'"):
            read_seed_file(path)

    def test_the_same_attribute_for_different_subjects_is_fine(self, tmp_path: Path) -> None:
        """The persona lives in Boston and Sam lives in Denver. Both are true."""
        path = self.with_extra_fact(tmp_path, subject="Sam", key="sams_city")

        assert len(read_seed_file(path).semantic) == 2

    def test_consolidation_can_never_find_an_authored_duplicate(self) -> None:
        """The guarantee, asserted against the persona that ships."""
        persona = read_seed_file(SEED_FILE).to_persona()

        assert consolidate(persona.memories).is_empty


class TestShippedSeedPersona:
    """The persona that ships with the repo must be valid and coherent."""

    def test_seed_file_exists(self) -> None:
        assert SEED_FILE.is_file()

    def test_seed_file_is_valid(self) -> None:
        persona = read_seed_file(SEED_FILE).to_persona()
        assert persona.identity.name == "Elena Marsh"

    def test_has_memories_of_every_type(self) -> None:
        persona = read_seed_file(SEED_FILE).to_persona()
        assert len(persona.of_type(MemoryType.SEMANTIC)) >= 10
        assert len(persona.of_type(MemoryType.EPISODIC)) >= 5
        assert len(persona.timeline()) == len(persona.of_type(MemoryType.EPISODIC))
        assert len(persona.of_type(MemoryType.RELATIONSHIP)) >= 3

    def test_cross_type_links_resolve(self) -> None:
        """The wedding links to the spouse; the spouse links back to the wedding."""
        persona = read_seed_file(SEED_FILE).to_persona()
        wedding = persona.by_id(memory_id_for("elena-marsh", "wedding"))
        maya = persona.by_id(memory_id_for("elena-marsh", "maya"))

        assert maya.id in wedding.linked_ids(LinkRelation.INVOLVES)
        assert wedding.id in maya.linked_ids(LinkRelation.CONCERNS)
        assert isinstance(maya, RelationshipMemory)
        assert maya.person_name == "Maya Okonkwo"

    def test_dates_parse(self) -> None:
        persona = read_seed_file(SEED_FILE).to_persona()
        wedding = persona.by_id(memory_id_for("elena-marsh", "wedding"))
        assert isinstance(wedding, EpisodicMemory)
        assert wedding.occurred_on == date(2014, 9, 6)

    def test_round_trips_through_storage(self, database: Database) -> None:
        expected = read_seed_file(SEED_FILE).to_persona()
        seed_persona(database, expected)

        with database.session() as session:
            loaded = PersonaRepository(session).load(expected.id)

        assert loaded is not None
        assert len(loaded.memories) == len(expected.memories)
        for original in expected.memories:
            assert loaded.by_id(original.id) == original


class TestNarrativeSpine:
    """The authored story: every episode dated, causally connected, chronologically sound."""

    def test_every_episode_is_dated(self) -> None:
        """An undated episode has no place in the spine and cannot be ordered."""
        persona = read_seed_file(SEED_FILE).to_persona()
        episodes = persona.of_type(MemoryType.EPISODIC)
        assert persona.timeline() == sorted(
            episodes,
            key=lambda m: (m.occurred_on, m.id),  # type: ignore[attr-defined,arg-type]
        )

    def test_timeline_runs_from_childhood_to_the_present(self) -> None:
        persona = read_seed_file(SEED_FILE).to_persona()
        timeline = persona.timeline()
        assert timeline[0].occurred_on == date(1998, 7, 19)
        assert timeline[-1].occurred_on == date(2019, 12, 14)

    def test_the_spine_is_causally_connected(self) -> None:
        """Most episodes explain themselves: they were caused by, or led to, something."""
        persona = read_seed_file(SEED_FILE).to_persona()
        causal = {LinkRelation.CAUSED_BY, LinkRelation.LED_TO}
        connected = [
            episode
            for episode in persona.timeline()
            if any(link.relation in causal for link in episode.links)
        ]
        assert len(connected) >= len(persona.timeline()) - 1

    def test_the_dog_was_adopted_because_the_father_died(self) -> None:
        """The causal bridge the LLM would otherwise have invented is authored data."""
        persona = read_seed_file(SEED_FILE).to_persona()
        adoption = persona.by_id(memory_id_for("elena-marsh", "compass_adoption"))
        death = persona.by_id(memory_id_for("elena-marsh", "fathers_death"))

        assert death.id in adoption.linked_ids(LinkRelation.CAUSED_BY)
        assert isinstance(adoption, EpisodicMemory)
        assert isinstance(death, EpisodicMemory)
        assert death.occurred_on is not None
        assert adoption.occurred_on is not None
        assert death.occurred_on < adoption.occurred_on

    def test_the_fear_of_water_traces_to_the_quarry(self) -> None:
        persona = read_seed_file(SEED_FILE).to_persona()
        quarry = persona.by_id(memory_id_for("elena-marsh", "near_drowning"))
        fear = persona.by_id(memory_id_for("elena-marsh", "fear"))
        assert fear.id in quarry.linked_ids(LinkRelation.LED_TO)

    def test_a_causally_backwards_seed_is_rejected(self, tmp_path: Path) -> None:
        """Move the adoption before the death that caused it; the persona must refuse to load."""
        text = SEED_FILE.read_text().replace(
            "    occurred_on: 2019-12-14", "    occurred_on: 2018-01-01"
        )
        broken = tmp_path / "broken.yaml"
        broken.write_text(text)

        with pytest.raises(ValueError, match="which happens later"):
            read_seed_file(broken).to_persona()

    def test_a_causally_backwards_seed_fails_the_loader_as_a_seed_error(
        self, database: Database, tmp_path: Path
    ) -> None:
        text = SEED_FILE.read_text().replace(
            "    occurred_on: 2019-12-14", "    occurred_on: 2018-01-01"
        )
        broken = tmp_path / "broken.yaml"
        broken.write_text(text)

        with pytest.raises(SeedError, match="incoherent"):
            seed_from_file(database, broken)
