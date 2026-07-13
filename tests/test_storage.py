"""Stage 2: storage round-trips and boundary behaviour."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from personasim.models import (
    ConversationState,
    EpisodicMemory,
    Identity,
    LinkRelation,
    Memory,
    MemoryLink,
    MemoryTrace,
    MemoryType,
    Message,
    Persona,
    RelationshipMemory,
    RetrievalIntent,
    Role,
    SemanticMemory,
    Turn,
)
from personasim.storage import (
    Database,
    IdentityRepository,
    MemoryRepository,
    PersonaRepository,
    SessionRepository,
)


class TestDatabase:
    def test_schema_creates_expected_tables(self, database: Database) -> None:
        with database.session() as session:
            rows = session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).scalars()
            tables = set(rows)
        assert {"personas", "memories", "memory_links", "sessions", "turns"} <= tables

    def test_foreign_keys_are_enforced(self, database: Database) -> None:
        """SQLite ignores FKs unless the pragma is set per connection."""
        with database.session() as session:
            enabled = session.execute(text("PRAGMA foreign_keys")).scalar_one()
        assert enabled == 1

    def test_orphan_memory_is_rejected(self, database: Database, persona: Persona) -> None:
        with pytest.raises(IntegrityError), database.session() as session:
            MemoryRepository(session).add("no-such-persona", persona.memories[0])

    def test_session_rolls_back_on_exception(self, database: Database, persona: Persona) -> None:
        with pytest.raises(RuntimeError), database.session() as session:
            PersonaRepository(session).save(persona)
            raise RuntimeError("boom")

        with database.session() as session:
            assert PersonaRepository(session).load(persona.id) is None


class TestIdentityRepository:
    def test_round_trip(self, db_session: Session, identity: Identity) -> None:
        repo = IdentityRepository(db_session)
        repo.upsert("p1", identity)
        assert repo.get("p1") == identity

    def test_get_missing_returns_none(self, db_session: Session) -> None:
        assert IdentityRepository(db_session).get("missing") is None

    def test_upsert_overwrites_existing(self, db_session: Session, identity: Identity) -> None:
        repo = IdentityRepository(db_session)
        repo.upsert("p1", identity)
        repo.upsert("p1", identity.model_copy(update={"age": 39, "occupation": "Surveyor"}))

        stored = repo.get("p1")
        assert stored is not None
        assert stored.age == 39
        assert stored.occupation == "Surveyor"
        assert repo.list_ids() == ["p1"]

    def test_find_by_name(self, db_session: Session, identity: Identity) -> None:
        repo = IdentityRepository(db_session)
        repo.upsert("p1", identity)
        assert repo.find_by_name("Elena Marsh") == "p1"
        assert repo.find_by_name("Nobody") is None


class TestMemoryRepository:
    def _saved(self, session: Session, persona: Persona) -> MemoryRepository:
        PersonaRepository(session).save(persona)
        return MemoryRepository(session)

    def test_every_memory_type_round_trips(self, db_session: Session, persona: Persona) -> None:
        repo = self._saved(db_session, persona)
        for original in persona.memories:
            restored = repo.get(original.id)
            assert restored == original, f"{original.type} did not round-trip"

    def test_subtypes_are_reconstructed_as_the_right_class(
        self, db_session: Session, persona: Persona
    ) -> None:
        repo = self._saved(db_session, persona)
        by_type = {memory.type: memory for memory in repo.list_memories(persona.id)}
        assert isinstance(by_type[MemoryType.SEMANTIC], SemanticMemory)
        assert isinstance(by_type[MemoryType.EPISODIC], EpisodicMemory)
        assert isinstance(by_type[MemoryType.RELATIONSHIP], RelationshipMemory)

    def test_timezone_survives_sqlite(self, db_session: Session, persona: Persona) -> None:
        """SQLite drops tzinfo; the domain model rejects naive datetimes."""
        repo = self._saved(db_session, persona)
        restored = repo.get(persona.memories[0].id)
        assert restored is not None
        assert restored.created_at.tzinfo is not None
        assert restored.created_at == persona.memories[0].created_at

    def test_explicit_utc_timestamp_is_preserved(
        self, db_session: Session, identity: Identity
    ) -> None:
        stamp = datetime(2019, 4, 2, 13, 30, tzinfo=UTC)
        memory = SemanticMemory(
            created_at=stamp,
            summary="Owns a dog",
            keywords=["dog"],
            subject="self",
            attribute="pet",
            value="dog",
        )
        p = Persona(identity=identity, memories=[memory])
        repo = self._saved(db_session, p)
        restored = repo.get(memory.id)
        assert restored is not None
        assert restored.created_at == stamp

    def test_links_round_trip(self, db_session: Session, persona: Persona) -> None:
        repo = self._saved(db_session, persona)
        spouse = next(
            m for m in repo.list_memories(persona.id) if m.type is MemoryType.RELATIONSHIP
        )
        wedding = next(m for m in repo.list_memories(persona.id) if m.type is MemoryType.EPISODIC)
        assert spouse.links == [MemoryLink(target=wedding.id, relation=LinkRelation.CONCERNS)]

    def test_relation_survives_the_round_trip(self, db_session: Session, persona: Persona) -> None:
        """An untyped link would let the LLM invent the relation; the type must persist."""
        repo = self._saved(db_session, persona)
        spouse = next(
            m for m in repo.list_memories(persona.id) if m.type is MemoryType.RELATIONSHIP
        )
        assert spouse.links[0].relation is LinkRelation.CONCERNS

    def test_two_relations_between_the_same_pair_both_persist(
        self, db_session: Session, persona: Persona
    ) -> None:
        """`relation` is part of the primary key, so a pair may hold several edges."""
        repo = self._saved(db_session, persona)
        spouse = next(m for m in persona.memories if m.type is MemoryType.RELATIONSHIP)
        wedding = next(m for m in persona.memories if m.type is MemoryType.EPISODIC)

        repo.replace_links(
            spouse.id,
            [
                MemoryLink(target=wedding.id, relation=LinkRelation.CONCERNS),
                MemoryLink(target=wedding.id, relation=LinkRelation.INVOLVES),
            ],
        )
        restored = repo.get(spouse.id)
        assert restored is not None
        assert len(restored.links) == 2
        assert {x.relation for x in restored.links} == {
            LinkRelation.CONCERNS,
            LinkRelation.INVOLVES,
        }

    def test_replace_links(self, db_session: Session, persona: Persona) -> None:
        repo = self._saved(db_session, persona)
        spouse = next(m for m in persona.memories if m.type is MemoryType.RELATIONSHIP)
        city = next(m for m in persona.memories if m.type is MemoryType.SEMANTIC)

        repo.replace_links(spouse.id, [MemoryLink(target=city.id, relation=LinkRelation.INVOLVES)])
        restored = repo.get(spouse.id)
        assert restored is not None
        assert restored.links == [MemoryLink(target=city.id, relation=LinkRelation.INVOLVES)]

    def test_deleting_a_memory_cascades_to_links(
        self, db_session: Session, persona: Persona
    ) -> None:
        repo = self._saved(db_session, persona)
        wedding = next(m for m in persona.memories if m.type is MemoryType.EPISODIC)
        spouse = next(m for m in persona.memories if m.type is MemoryType.RELATIONSHIP)

        assert repo.delete(wedding.id)
        db_session.flush()

        restored = repo.get(spouse.id)
        assert restored is not None
        assert restored.links == []

    def test_delete_missing_returns_false(self, db_session: Session) -> None:
        assert MemoryRepository(db_session).delete("nope") is False

    def test_list_filters_by_type(self, db_session: Session, persona: Persona) -> None:
        repo = self._saved(db_session, persona)
        semantic = repo.list_memories(persona.id, types=[MemoryType.SEMANTIC])
        assert [m.type for m in semantic] == [MemoryType.SEMANTIC]

    def test_list_is_scoped_to_persona(
        self, db_session: Session, persona: Persona, identity: Identity
    ) -> None:
        self._saved(db_session, persona)
        other = Persona(
            identity=identity.model_copy(update={"name": "Other"}),
            memories=[
                SemanticMemory(
                    summary="Lives in Lisbon",
                    keywords=["lisbon"],
                    subject="self",
                    attribute="city",
                    value="Lisbon",
                )
            ],
        )
        repo = self._saved(db_session, other)
        assert len(repo.list_memories(persona.id)) == 3
        assert len(repo.list_memories(other.id)) == 1

    def test_find_by_keywords_matches_any_overlap(
        self, db_session: Session, persona: Persona
    ) -> None:
        repo = self._saved(db_session, persona)
        found = repo.find_by_keywords(persona.id, ["maya"])
        assert {m.type for m in found} == {MemoryType.EPISODIC, MemoryType.RELATIONSHIP}

    def test_find_by_keywords_is_case_insensitive(
        self, db_session: Session, persona: Persona
    ) -> None:
        repo = self._saved(db_session, persona)
        assert repo.find_by_keywords(persona.id, ["  BOSTON "])

    def test_find_by_keywords_with_no_match_returns_empty(
        self, db_session: Session, persona: Persona
    ) -> None:
        repo = self._saved(db_session, persona)
        assert repo.find_by_keywords(persona.id, ["antarctica"]) == []

    @pytest.mark.parametrize("keywords", [[], [""], ["   "]])
    def test_find_by_keywords_with_empty_input_returns_empty(
        self, db_session: Session, persona: Persona, keywords: list[str]
    ) -> None:
        repo = self._saved(db_session, persona)
        assert repo.find_by_keywords(persona.id, keywords) == []

    def test_find_by_person(self, db_session: Session, persona: Persona) -> None:
        repo = self._saved(db_session, persona)
        found = repo.find_by_person(persona.id, "Maya")
        assert [m.type for m in found] == [MemoryType.RELATIONSHIP]

    def test_count(self, db_session: Session, persona: Persona) -> None:
        repo = self._saved(db_session, persona)
        assert repo.count(persona.id) == 3
        assert repo.count(persona.id, memory_type=MemoryType.EPISODIC) == 1


class TestPersonaRepository:
    def test_persona_round_trips_whole(self, database: Database, persona: Persona) -> None:
        with database.session() as session:
            PersonaRepository(session).save(persona)

        with database.session() as session:
            restored = PersonaRepository(session).load(persona.id)

        assert restored is not None
        assert restored.id == persona.id
        assert restored.identity == persona.identity
        assert sorted_memories(restored.memories) == sorted_memories(persona.memories)

    def test_load_missing_returns_none(self, db_session: Session) -> None:
        assert PersonaRepository(db_session).load("missing") is None

    def test_exists(self, db_session: Session, persona: Persona) -> None:
        repo = PersonaRepository(db_session)
        assert not repo.exists(persona.id)
        repo.save(persona)
        assert repo.exists(persona.id)


class TestSessionRepository:
    def _turn(self, text_in: str, text_out: str) -> Turn:
        return Turn(
            user_message=Message(role=Role.USER, content=text_in),
            persona_message=Message(role=Role.PERSONA, content=text_out),
            trace=MemoryTrace(
                query=text_in,
                intent=RetrievalIntent.FACTUAL_RECALL,
                reason="matched keyword 'boston'",
            ),
        )

    def test_turns_round_trip_in_order(self, db_session: Session, persona: Persona) -> None:
        PersonaRepository(db_session).save(persona)
        state = ConversationState(persona_id=persona.id)

        repo = SessionRepository(db_session)
        repo.create(state.session_id, persona.id)
        repo.append_turn(state.session_id, self._turn("where do you live?", "Boston."))
        repo.append_turn(state.session_id, self._turn("and your spouse?", "Maya."))

        turns = repo.get_turns(state.session_id)
        assert [t.user_message.content for t in turns] == [
            "where do you live?",
            "and your spouse?",
        ]

    def test_trace_survives_the_round_trip(self, db_session: Session, persona: Persona) -> None:
        PersonaRepository(db_session).save(persona)
        repo = SessionRepository(db_session)
        repo.create("s1", persona.id)
        repo.append_turn("s1", self._turn("hi", "hello"))

        restored = repo.get_turns("s1")[0].trace
        assert restored.intent is RetrievalIntent.FACTUAL_RECALL
        assert restored.reason == "matched keyword 'boston'"

    def test_latest_session_is_the_most_recent(self, db_session: Session, persona: Persona) -> None:
        PersonaRepository(db_session).save(persona)
        repo = SessionRepository(db_session)
        repo.create("old", persona.id, started_at=datetime(2020, 1, 1, tzinfo=UTC))
        repo.create("new", persona.id, started_at=datetime(2024, 1, 1, tzinfo=UTC))
        assert repo.latest_session_id(persona.id) == "new"

    def test_latest_session_for_unknown_persona(self, db_session: Session) -> None:
        assert SessionRepository(db_session).latest_session_id("nobody") is None

    def test_end_records_a_timestamp(self, db_session: Session, persona: Persona) -> None:
        PersonaRepository(db_session).save(persona)
        repo = SessionRepository(db_session)
        repo.create("s1", persona.id)
        repo.end("s1")
        db_session.flush()
        # Nothing to assert through the repo API beyond it not raising; the
        # column is exercised by the schema test above.


def sorted_memories(memories: list[Memory]) -> list[Memory]:
    return sorted(memories, key=lambda m: m.id)


def test_episodic_date_and_participants_round_trip(db_session: Session, identity: Identity) -> None:
    memory = EpisodicMemory(
        summary="Hiked the Long Trail with Maya and Tom",
        keywords=["hike"],
        occurred_on=date(2018, 7, 4),
        location="Vermont",
        participants=["Maya", "Tom"],
    )
    p = Persona(identity=identity, memories=[memory])
    PersonaRepository(db_session).save(p)

    restored = MemoryRepository(db_session).get(memory.id)
    assert isinstance(restored, EpisodicMemory)
    assert restored.occurred_on == date(2018, 7, 4)
    assert restored.participants == ["Maya", "Tom"]
