"""Stage 1: domain model validation rules."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import TypeAdapter, ValidationError

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
    RetrievedMemory,
    Role,
    ScoreComponents,
    SemanticMemory,
)


def make_semantic(**overrides: object) -> SemanticMemory:
    defaults: dict[str, object] = {
        "summary": "Lives in Boston",
        "keywords": ["boston", "home"],
        "subject": "self",
        "attribute": "city",
        "value": "Boston",
    }
    return SemanticMemory(**{**defaults, **overrides})  # type: ignore[arg-type]


def link(target: str, relation: LinkRelation = LinkRelation.CONCERNS) -> MemoryLink:
    return MemoryLink(target=target, relation=relation)


class TestMemoryBase:
    def test_defaults_populate_required_fields(self) -> None:
        memory = make_semantic()
        assert memory.id
        assert memory.type is MemoryType.SEMANTIC
        assert memory.created_at.tzinfo is not None
        assert memory.importance == 0.5
        assert memory.confidence == 1.0
        assert memory.links == []

    @pytest.mark.parametrize("field", ["importance", "confidence"])
    @pytest.mark.parametrize("bad_value", [-0.01, 1.01])
    def test_scores_are_bounded_to_unit_interval(self, field: str, bad_value: float) -> None:
        with pytest.raises(ValidationError):
            make_semantic(**{field: bad_value})

    @pytest.mark.parametrize("boundary", [0.0, 1.0])
    def test_score_boundaries_are_inclusive(self, boundary: float) -> None:
        assert make_semantic(importance=boundary).importance == boundary

    def test_keywords_must_not_be_empty(self) -> None:
        with pytest.raises(ValidationError):
            make_semantic(keywords=[])

    def test_keywords_of_only_whitespace_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="non-blank"):
            make_semantic(keywords=["  ", ""])

    def test_keywords_are_normalized_and_deduplicated_preserving_order(self) -> None:
        memory = make_semantic(keywords=["  Boston ", "HOME", "boston", "", "home"])
        assert memory.keywords == ["boston", "home"]

    def test_blank_summary_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_semantic(summary="   ")

    def test_summary_is_stripped(self) -> None:
        assert make_semantic(summary="  Lives in Boston  ").summary == "Lives in Boston"

    def test_naive_created_at_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            make_semantic(created_at=datetime(2020, 1, 1))

    def test_aware_created_at_is_accepted(self) -> None:
        stamp = datetime(2020, 1, 1, tzinfo=UTC)
        assert make_semantic(created_at=stamp).created_at == stamp

    def test_memory_may_not_link_to_itself(self) -> None:
        memory = make_semantic()
        with pytest.raises(ValidationError, match="link to itself"):
            make_semantic(id=memory.id, links=[link(memory.id)])

    def test_duplicate_links_are_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicates"):
            make_semantic(links=[link("a"), link("a")])

    def test_same_target_may_hold_two_distinct_relations(self) -> None:
        memory = make_semantic(
            links=[link("a", LinkRelation.INVOLVES), link("a", LinkRelation.CONCERNS)]
        )
        assert len(memory.links) == 2

    def test_contradictory_relations_to_one_target_are_rejected(self) -> None:
        """A cannot both cause and be caused by B."""
        with pytest.raises(ValidationError, match="contradictory relations"):
            make_semantic(links=[link("a", LinkRelation.CAUSED_BY), link("a", LinkRelation.LED_TO)])

    def test_links_are_canonically_ordered(self) -> None:
        """Links are a set; storage returns them in row order, so order must not matter."""
        ordered = make_semantic(links=[link("c"), link("a"), link("b")]).links
        assert [x.target for x in ordered] == ["a", "b", "c"]

    def test_linked_ids_filters_by_relation(self) -> None:
        memory = make_semantic(
            links=[link("a", LinkRelation.CAUSED_BY), link("b", LinkRelation.INVOLVES)]
        )
        assert memory.linked_ids(LinkRelation.CAUSED_BY) == ["a"]
        assert sorted(memory.linked_ids()) == ["a", "b"]

    def test_unknown_fields_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            make_semantic(mood="wistful")

    def test_assignment_is_revalidated(self) -> None:
        memory = make_semantic()
        with pytest.raises(ValidationError):
            memory.importance = 5.0


class TestMemorySubtypes:
    def test_episodic_carries_experience_fields(self) -> None:
        memory = EpisodicMemory(
            summary="Graduated from university",
            keywords=["graduation"],
            occurred_on=date(2009, 5, 20),
            location="Amherst",
            participants=["Maya"],
        )
        assert memory.type is MemoryType.EPISODIC
        assert memory.occurred_on == date(2009, 5, 20)

    def test_relationship_closeness_is_bounded(self) -> None:
        with pytest.raises(ValidationError):
            RelationshipMemory(
                summary="Spouse",
                keywords=["maya"],
                person_name="Maya",
                relation="spouse",
                closeness=1.5,
            )

    def test_semantic_requires_structured_triple(self) -> None:
        """Memory is structured, never free text: a bare summary is not a fact."""
        with pytest.raises(ValidationError):
            SemanticMemory(summary="Lives in Boston", keywords=["boston"])  # type: ignore[call-arg]

    def test_discriminated_union_round_trips_by_type(self) -> None:
        adapter: TypeAdapter[Memory] = TypeAdapter(Memory)
        original = EpisodicMemory(summary="Wedding day", keywords=["wedding"])
        restored = adapter.validate_python(original.model_dump())
        assert isinstance(restored, EpisodicMemory)
        assert restored.summary == "Wedding day"


class TestIdentity:
    def test_valid_identity(self) -> None:
        identity = Identity(
            name="Elena",
            age=38,
            occupation="Cartographer",
            personality=["curious"],
            values=["honesty"],
            speech_style="warm",
        )
        assert identity.name == "Elena"

    @pytest.mark.parametrize("age", [-1, 131])
    def test_age_is_bounded(self, age: int) -> None:
        with pytest.raises(ValidationError):
            Identity(
                name="Elena",
                age=age,
                occupation="Cartographer",
                personality=["curious"],
                values=["honesty"],
                speech_style="warm",
            )

    def test_personality_must_be_non_empty(self) -> None:
        with pytest.raises(ValidationError):
            Identity(
                name="Elena",
                age=38,
                occupation="Cartographer",
                personality=[],
                values=["honesty"],
                speech_style="warm",
            )


@pytest.fixture
def identity() -> Identity:
    return Identity(
        name="Elena",
        age=38,
        occupation="Cartographer",
        personality=["curious"],
        values=["honesty"],
        speech_style="warm",
    )


class TestPersona:
    def test_links_must_resolve_within_the_persona(self, identity: Identity) -> None:
        orphan = make_semantic(links=[link("does-not-exist")])
        with pytest.raises(ValidationError, match="links to unknown memories"):
            Persona(identity=identity, memories=[orphan])

    def test_resolved_links_are_accepted(self, identity: Identity) -> None:
        wedding = EpisodicMemory(summary="Wedding day", keywords=["wedding"])
        spouse = RelationshipMemory(
            summary="Married to Maya",
            keywords=["maya"],
            person_name="Maya",
            relation="spouse",
            links=[link(wedding.id)],
        )
        persona = Persona(identity=identity, memories=[wedding, spouse])
        assert persona.by_id(spouse.id).linked_ids() == [wedding.id]

    def test_linked_to_resolves_targets(self, identity: Identity) -> None:
        wedding = EpisodicMemory(summary="Wedding day", keywords=["wedding"])
        spouse = RelationshipMemory(
            summary="Married to Maya",
            keywords=["maya"],
            person_name="Maya",
            relation="spouse",
            links=[link(wedding.id, LinkRelation.CONCERNS)],
        )
        persona = Persona(identity=identity, memories=[wedding, spouse])
        assert persona.linked_to(spouse.id, LinkRelation.CONCERNS) == [wedding]
        assert persona.linked_to(spouse.id, LinkRelation.INVOLVES) == []

    def test_duplicate_memory_ids_are_rejected(self, identity: Identity) -> None:
        first = make_semantic()
        second = make_semantic(id=first.id)
        with pytest.raises(ValidationError, match="unique"):
            Persona(identity=identity, memories=[first, second])

    def test_of_type_filters(self, identity: Identity) -> None:
        fact = make_semantic()
        event = EpisodicMemory(summary="Wedding day", keywords=["wedding"])
        persona = Persona(identity=identity, memories=[fact, event])
        assert persona.of_type(MemoryType.SEMANTIC) == [fact]
        assert persona.of_type(MemoryType.EPISODIC) == [event]

    def test_by_id_raises_for_unknown_memory(self, identity: Identity) -> None:
        persona = Persona(identity=identity)
        with pytest.raises(KeyError):
            persona.by_id("nope")


class TestCausalChronology:
    """The authored life story must be possible: a cause cannot postdate its effect."""

    @staticmethod
    def _episode(summary: str, when: date, links: list[MemoryLink] | None = None) -> EpisodicMemory:
        return EpisodicMemory(
            summary=summary,
            keywords=[summary.split()[0].lower()],
            occurred_on=when,
            links=links or [],
        )

    def test_effect_may_follow_its_cause(self, identity: Identity) -> None:
        death = self._episode("Father died", date(2019, 4, 11))
        adoption = self._episode(
            "Adopted Compass", date(2019, 12, 14), [link(death.id, LinkRelation.CAUSED_BY)]
        )
        assert Persona(identity=identity, memories=[death, adoption])

    def test_cause_may_not_postdate_its_effect(self, identity: Identity) -> None:
        death = self._episode("Father died", date(2019, 4, 11))
        earlier = self._episode(
            "Adopted Compass", date(2018, 1, 1), [link(death.id, LinkRelation.CAUSED_BY)]
        )
        with pytest.raises(ValidationError, match="which happens later"):
            Persona(identity=identity, memories=[death, earlier])

    def test_led_to_may_not_point_backwards(self, identity: Identity) -> None:
        early = self._episode("Near drowning", date(1998, 7, 19))
        late = self._episode("Wedding", date(2014, 9, 6), [link(early.id, LinkRelation.LED_TO)])
        with pytest.raises(ValidationError, match="which happened earlier"):
            Persona(identity=identity, memories=[early, late])

    def test_undated_memories_are_not_checked(self, identity: Identity) -> None:
        """A semantic fact has no date; a causal edge to it says nothing about time."""
        fact = make_semantic()
        event = self._episode("Moved", date(2010, 2, 1), [link(fact.id, LinkRelation.LED_TO)])
        assert Persona(identity=identity, memories=[fact, event])

    def test_timeline_is_ordered_by_when_it_happened(self, identity: Identity) -> None:
        late = self._episode("Wedding", date(2014, 9, 6))
        early = self._episode("Graduation", date(2009, 5, 22))
        undated = EpisodicMemory(summary="Sometime", keywords=["sometime"])
        persona = Persona(identity=identity, memories=[late, early, undated])

        assert [m.summary for m in persona.timeline()] == ["Graduation", "Wedding"]


class TestTrace:
    def test_score_components_sum_to_total(self) -> None:
        components = ScoreComponents(keyword_overlap=0.5, importance=0.3, confidence=0.2)
        assert components.total == pytest.approx(1.0)

    def test_empty_trace_is_reported_as_empty(self) -> None:
        trace = MemoryTrace(
            query="hello",
            intent=RetrievalIntent.SMALL_TALK,
            reason="small talk needs no memory",
        )
        assert trace.is_empty
        assert trace.memory_ids == []

    def test_trace_exposes_retrieved_ids(self) -> None:
        retrieved = RetrievedMemory(
            memory_id="m1",
            memory_type=MemoryType.SEMANTIC,
            summary="Lives in Boston",
            score=0.9,
            components=ScoreComponents(keyword_overlap=0.6, importance=0.2, confidence=0.1),
            matched_keywords=["boston"],
        )
        trace = MemoryTrace(
            query="where do you live?",
            intent=RetrievalIntent.FACTUAL_RECALL,
            retrieved=[retrieved],
            reason="matched keyword 'boston'",
        )
        assert not trace.is_empty
        assert trace.memory_ids == ["m1"]

    def test_reason_is_mandatory(self) -> None:
        """Every retrieval must be explainable."""
        with pytest.raises(ValidationError):
            MemoryTrace(query="hi", intent=RetrievalIntent.SMALL_TALK, reason="")


class TestConversation:
    def test_session_starts_empty(self) -> None:
        state = ConversationState(persona_id="p1")
        assert state.turns == []
        assert state.temporary_facts == []
        assert state.active_topic is None
        assert state.session_id

    def test_messages_are_frozen(self) -> None:
        message = Message(role=Role.USER, content="hello")
        with pytest.raises(ValidationError):
            message.content = "changed"

    def test_empty_message_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Message(role=Role.USER, content="")
