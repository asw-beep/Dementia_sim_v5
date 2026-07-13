"""Stage 5: retrieval is deterministic, explainable, and traverses typed links."""

from __future__ import annotations

from pathlib import Path

import pytest

from personasim.config import Settings
from personasim.models import (
    LinkRelation,
    MemoryType,
    Persona,
    RetrievalIntent,
    SemanticMemory,
)
from personasim.persona import build_persona, memory_id_for, read_seed_file
from personasim.retrieval import (
    PersonaMemorySource,
    RankWeights,
    RepositoryMemorySource,
    RetrievalEngine,
    Scope,
    classify,
    extract_keywords,
    find_person_mentions,
    memories_of,
    rank,
    scope_of,
    score_memory,
    types_for,
)
from personasim.storage import Database, MemoryRepository, PersonaRepository

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "personas" / "elena.yaml"


@pytest.fixture(scope="module")
def elena() -> Persona:
    return build_persona(read_seed_file(SEED_FILE))


@pytest.fixture
def engine(elena: Persona) -> RetrievalEngine:
    return RetrievalEngine(PersonaMemorySource(elena), Settings())


def mid(key: str) -> str:
    return memory_id_for("elena-marsh", key)


class TestEntityExtraction:
    def test_stopwords_are_dropped(self) -> None:
        assert extract_keywords("Where do you live?") == ["live"]

    def test_keywords_are_deduplicated_in_order(self) -> None:
        assert extract_keywords("boston Boston BOSTON maps") == ["boston", "maps"]

    def test_short_tokens_are_dropped_but_meaningful_ones_survive(self) -> None:
        assert "dog" in extract_keywords("do you have a dog")
        assert "do" not in extract_keywords("do you have a dog")

    def test_punctuation_is_stripped(self) -> None:
        assert extract_keywords("Compass, really?!") == ["compass", "really"]

    def test_possessives_reduce_to_the_noun(self) -> None:
        """ "your father's soup" must reach a memory keyworded 'father'."""
        assert extract_keywords("your father's soup") == ["father", "soup"]

    def test_empty_text_yields_no_keywords(self) -> None:
        assert extract_keywords("   ") == []

    def test_a_full_name_is_recognised(self) -> None:
        assert find_person_mentions("how is Maya Okonkwo?", ["Maya Okonkwo"]) == ["Maya Okonkwo"]

    def test_a_first_name_alone_is_recognised(self) -> None:
        assert find_person_mentions("how is Maya?", ["Maya Okonkwo"]) == ["Maya Okonkwo"]

    def test_a_place_is_not_mistaken_for_a_person(self) -> None:
        """Matching known names, not proper nouns, keeps this deterministic."""
        assert find_person_mentions("do you like Boston?", ["Maya Okonkwo"]) == []

    def test_unknown_people_are_not_invented(self) -> None:
        assert find_person_mentions("who is Napoleon?", ["Maya Okonkwo"]) == []


class TestIntent:
    @pytest.mark.parametrize("text", ["hi", "hello there", "thanks!", "good morning", "  "])
    def test_pleasantries_are_small_talk(self, text: str) -> None:
        assert classify(text) is RetrievalIntent.SMALL_TALK

    def test_naming_a_person_wins_over_every_other_cue(self) -> None:
        assert (
            classify("where did Maya live?", ["Maya Okonkwo"]) is RetrievalIntent.RELATIONSHIP_QUERY
        )

    @pytest.mark.parametrize(
        "text",
        ["who is your wife?", "tell me about your family", "does your brother call?"],
    )
    def test_relational_words_without_a_name(self, text: str) -> None:
        assert classify(text) is RetrievalIntent.RELATIONSHIP_QUERY

    @pytest.mark.parametrize(
        "text",
        ["do you remember the quarry?", "what happened in 2019?", "tell me about your wedding"],
    )
    def test_experiential_cues(self, text: str) -> None:
        assert classify(text) is RetrievalIntent.EXPERIENTIAL_RECALL

    def test_a_phrase_of_stopwords_still_signals_experience(self) -> None:
        """'tell me about' survives neither the token sets nor keyword extraction."""
        assert extract_keywords("tell me about the azores") == ["azores"]
        assert classify("tell me about the azores") is RetrievalIntent.EXPERIENTIAL_RECALL

    @pytest.mark.parametrize("text", ["where do you live?", "what is your favourite food?"])
    def test_factual_cues(self, text: str) -> None:
        assert classify(text) is RetrievalIntent.FACTUAL_RECALL

    def test_a_bare_content_statement_falls_back_to_factual(self) -> None:
        assert classify("your dog") is RetrievalIntent.FACTUAL_RECALL

    def test_small_talk_searches_no_memory_types(self) -> None:
        assert types_for(RetrievalIntent.SMALL_TALK) == ()

    def test_relationship_queries_search_relationships_first(self) -> None:
        assert types_for(RetrievalIntent.RELATIONSHIP_QUERY)[0] is MemoryType.RELATIONSHIP


class TestRanking:
    def test_components_sum_to_the_score(self, elena: Persona) -> None:
        weights = RankWeights(keyword=1.0, importance=0.5, confidence=0.25)
        scored = score_memory(elena.by_id(mid("city")), ["boston"], weights)
        assert scored.score == pytest.approx(scored.components.total)

    def test_overlap_is_a_fraction_of_the_question(self, elena: Persona) -> None:
        """Matching two of two keywords beats matching two of six."""
        weights = RankWeights(keyword=1.0, importance=0.0, confidence=0.0)
        focused = score_memory(elena.by_id(mid("city")), ["boston", "home"], weights)
        diluted = score_memory(
            elena.by_id(mid("city")), ["boston", "home", "a", "b", "c", "d"], weights
        )
        assert focused.score > diluted.score

    def test_importance_breaks_a_keyword_tie(self, elena: Persona) -> None:
        weights = RankWeights(keyword=1.0, importance=0.5, confidence=0.25)
        ranked = rank(
            [elena.by_id(mid("coffee")), elena.by_id(mid("wedding"))], [], weights, top_k=2
        )
        assert ranked[0].memory.id == mid("wedding")

    def test_no_keywords_yields_zero_overlap(self, elena: Persona) -> None:
        weights = RankWeights(keyword=1.0, importance=0.5, confidence=0.25)
        scored = score_memory(elena.by_id(mid("city")), [], weights)
        assert scored.components.keyword_overlap == 0.0

    def test_top_k_truncates(self, elena: Persona) -> None:
        weights = RankWeights(keyword=1.0, importance=0.5, confidence=0.25)
        assert len(rank(elena.memories, ["boston"], weights, top_k=2)) == 2

    def test_min_score_filters(self, elena: Persona) -> None:
        weights = RankWeights(keyword=1.0, importance=0.0, confidence=0.0)
        assert rank(elena.memories, ["nonexistent"], weights, top_k=10, min_score=0.01) == []

    def test_ranking_is_deterministic(self, elena: Persona) -> None:
        weights = RankWeights(keyword=1.0, importance=0.5, confidence=0.25)
        first = [s.memory.id for s in rank(elena.memories, ["maya"], weights, top_k=5)]
        second = [s.memory.id for s in rank(elena.memories, ["maya"], weights, top_k=5)]
        assert first == second


class TestEngine:
    def test_small_talk_retrieves_nothing(self, engine: RetrievalEngine) -> None:
        trace = engine.retrieve("hello there")
        assert trace.intent is RetrievalIntent.SMALL_TALK
        assert trace.is_empty
        assert trace.searched_types == []
        assert "no memory retrieval" in trace.reason

    def test_every_trace_carries_a_reason(self, engine: RetrievalEngine) -> None:
        for query in ["hi", "where do you live?", "who is Maya?", "xyzzy plugh"]:
            assert engine.retrieve(query).reason

    def test_a_factual_question_finds_the_fact(self, engine: RetrievalEngine) -> None:
        trace = engine.retrieve("Where do you live?")
        assert trace.intent is RetrievalIntent.FACTUAL_RECALL
        assert mid("city") in trace.memory_ids

    def test_a_relationship_question_finds_the_person(self, engine: RetrievalEngine) -> None:
        trace = engine.retrieve("Who is Maya?")
        assert trace.intent is RetrievalIntent.RELATIONSHIP_QUERY
        assert trace.entities == ["Maya Okonkwo"]
        assert mid("maya") in trace.memory_ids

    def test_an_experiential_question_finds_the_episode(self, engine: RetrievalEngine) -> None:
        trace = engine.retrieve("Tell me about your wedding")
        assert trace.intent is RetrievalIntent.EXPERIENTIAL_RECALL
        assert mid("wedding") in trace.memory_ids

    def test_an_unanswerable_question_retrieves_nothing_and_says_so(
        self, engine: RetrievalEngine
    ) -> None:
        trace = engine.retrieve("have you ever been to Antarctica?")
        assert trace.is_empty
        assert "no memory matched" in trace.reason

    def test_a_generic_keyword_does_not_cause_spurious_recall(
        self, engine: RetrievalEngine
    ) -> None:
        """'first' once matched the 2005 survey job, answering "first pet" with a job."""
        assert mid("first_survey_job") not in engine.retrieve("your first pet").memory_ids

    def test_retrieval_is_reproducible(self, engine: RetrievalEngine) -> None:
        """The same question, asked twice, retrieves the same memories in the same order."""
        first = engine.retrieve("Why did you adopt Compass?")
        second = engine.retrieve("Why did you adopt Compass?")
        assert first.memory_ids == second.memory_ids

    def test_score_equals_components_total_for_every_retrieved_memory(
        self, engine: RetrievalEngine
    ) -> None:
        for query in ["Where do you live?", "Why did you adopt Compass?", "Who is Maya?"]:
            for retrieved in engine.retrieve(query).retrieved:
                assert retrieved.score == pytest.approx(retrieved.components.total)

    def test_searched_types_are_recorded(self, engine: RetrievalEngine) -> None:
        trace = engine.retrieve("Who is Maya?")
        assert trace.searched_types[0] is MemoryType.RELATIONSHIP


class TestLinkExpansion:
    """The causal bridge is handed to the model, not invented by it."""

    def test_asking_why_the_dog_was_adopted_pulls_in_the_fathers_death(
        self, engine: RetrievalEngine
    ) -> None:
        trace = engine.retrieve("Why did you adopt Compass?")

        assert mid("compass_adoption") in trace.memory_ids
        assert mid("fathers_death") in trace.memory_ids

        death = next(r for r in trace.retrieved if r.memory_id == mid("fathers_death"))
        assert death.was_expanded
        assert death.via_relation is LinkRelation.CAUSED_BY
        assert death.linked_from == mid("compass_adoption")

    def test_the_fear_of_water_reaches_the_quarry(self, engine: RetrievalEngine) -> None:
        trace = engine.retrieve("Are you afraid of anything?")
        assert mid("near_drowning") in trace.memory_ids

    def test_expanded_memories_earn_no_keyword_credit(self, engine: RetrievalEngine) -> None:
        trace = engine.retrieve("Why did you adopt Compass?")
        for retrieved in trace.retrieved:
            if retrieved.was_expanded:
                assert retrieved.matched_keywords == []
                assert retrieved.components.keyword_overlap == 0.0

    def test_directly_matched_memories_are_not_marked_as_expanded(
        self, engine: RetrievalEngine
    ) -> None:
        trace = engine.retrieve("Where do you live?")
        city = next(r for r in trace.retrieved if r.memory_id == mid("city"))
        assert not city.was_expanded
        assert city.linked_from is None

    def test_expansion_is_capped(self, elena: Persona) -> None:
        settings = Settings(retrieval_max_expansions=1)
        trace = RetrievalEngine(PersonaMemorySource(elena), settings).retrieve(
            "Tell me about your wedding"
        )
        assert sum(1 for r in trace.retrieved if r.was_expanded) == 1

    def test_expansion_can_be_disabled(self, elena: Persona) -> None:
        settings = Settings(retrieval_expand_links=False)
        trace = RetrievalEngine(PersonaMemorySource(elena), settings).retrieve(
            "Why did you adopt Compass?"
        )
        assert not any(r.was_expanded for r in trace.retrieved)
        assert mid("fathers_death") not in trace.memory_ids

    def test_a_memory_is_never_retrieved_twice(self, engine: RetrievalEngine) -> None:
        trace = engine.retrieve("Who is Maya?")
        assert len(trace.memory_ids) == len(set(trace.memory_ids))

    def test_the_reason_names_the_relation_followed(self, engine: RetrievalEngine) -> None:
        trace = engine.retrieve("Why did you adopt Compass?")
        assert "caused_by" in trace.reason


class TestSourcesAgree:
    """The engine must behave identically over a persona and over the database."""

    def test_repository_and_persona_sources_retrieve_the_same_memories(
        self, database: Database, elena: Persona
    ) -> None:
        with database.session() as session:
            PersonaRepository(session).save(elena)

        settings = Settings()
        from_persona = RetrievalEngine(PersonaMemorySource(elena), settings)

        with database.session() as session:
            source = RepositoryMemorySource(MemoryRepository(session), elena.id)
            from_database = RetrievalEngine(source, settings)

            for query in ["Where do you live?", "Why did you adopt Compass?", "Who is Maya?"]:
                assert (
                    from_persona.retrieve(query).memory_ids
                    == from_database.retrieve(query).memory_ids
                )

    def test_memories_of_rehydrates_a_trace(self, elena: Persona, engine: RetrievalEngine) -> None:
        trace = engine.retrieve("Where do you live?")
        memories = memories_of(trace, PersonaMemorySource(elena))
        assert [m.id for m in memories] == trace.memory_ids


class TestWhoTheQuestionIsAbout:
    """The persona and the caregiver both have a city, a job, a family, and both are
    in memory. "Where do I live?" and "Where do you live?" retrieve on the same
    keyword and reach both — and it was the *model* deciding which to answer with.

    It got it wrong, and inconsistently: it answered "Where do I live?" correctly,
    then answered "Do you remember where I live?" with "I don't have a memory of
    where you live", and "What do I do for a living?" with "I am a cartographer".

    That is not a decision a model may make. Retrieval is deterministic so recall
    does not vary between two askings, and *whose fact is being asked for* is a
    retrieval decision. Pronouns settle it, and pronouns are rules.
    """

    @pytest.mark.parametrize(
        ("question", "expected"),
        [
            ("Where do I live?", Scope.CAREGIVER),
            ("What do I do for a living?", Scope.CAREGIVER),
            ("Do I have any kids?", Scope.CAREGIVER),
            ("Where do you live?", Scope.SELF),
            ("Why did you take in Compass?", Scope.SELF),
            ("Tell me about your mother.", Scope.SELF),
            ("I heard you have a dog?", Scope.UNSCOPED),
        ],
    )
    def test_pronouns_decide(self, question: str, expected: Scope) -> None:
        assert scope_of(question) == expected

    def test_the_address_before_the_question_word_is_ignored(self) -> None:
        """In "Do you remember where I live?", the "you" is only the address. The
        question word is `where`, and after it comes `I`."""
        assert scope_of("Do you remember where I live?") is Scope.CAREGIVER
        assert scope_of("Can you tell me what I do for work?") is Scope.CAREGIVER

    def test_a_question_about_the_caregiver_cannot_reach_her_life(self, elena: Persona) -> None:
        """Filtering, not ranking. A question about the caregiver must not merely
        *prefer* their memories — it must not be handed hers at all, or the model
        reaches for the one it finds more interesting."""
        persona = elena.model_copy(deep=True)
        persona.memories = [
            *persona.memories,
            SemanticMemory(
                summary="my caregiver is a nurse",
                keywords=["nurse", "caregiver", "job", "living"],
                subject="my caregiver",
                attribute="role",
                value="nurse",
            ),
        ]
        engine = RetrievalEngine(PersonaMemorySource(persona), Settings())

        theirs = engine.retrieve("What do I do for a living?")
        hers = engine.retrieve("What do you do for a living?")

        assert [item.summary for item in theirs.retrieved] == ["my caregiver is a nurse"]
        assert any("cartographer" in item.summary for item in hers.retrieved)

    def test_the_trace_says_whose_question_it_was(self, engine: RetrievalEngine) -> None:
        assert "asking about caregiver" in engine.retrieve("Where do I live?").reason
        assert "asking about self" in engine.retrieve("Where do you live?").reason

    def test_a_question_about_her_still_reaches_what_she_was_told(self, elena: Persona) -> None:
        """The mirror rule is tempting and wrong. "What do you know about Chicago?"
        asks what she *knows*, which includes what the caregiver told her — filtering
        it out made her forget a fact she had been given one turn earlier."""
        persona = elena.model_copy(deep=True)
        persona.memories = [
            *persona.memories,
            SemanticMemory(
                summary="my caregiver lives in Chicago",
                keywords=["chicago", "caregiver", "live"],
                subject="my caregiver",
                attribute="city",
                value="Chicago",
            ),
        ]
        engine = RetrievalEngine(PersonaMemorySource(persona), Settings())

        recalled = engine.retrieve("What do you know about Chicago?")

        assert any("Chicago" in item.summary for item in recalled.retrieved)
