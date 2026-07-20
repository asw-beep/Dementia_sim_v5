"""Stage 9: the web adapter.

A second front end over the Stage 7 orchestrator, alongside the CLI. It adds no
memory, no retrieval, and no persona logic — and the last test in this file is the
one that says so: what the browser can reach is exactly what `persona chat` can
reach, and nothing more.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from personasim.config import Settings
from personasim.impairment import load_profile
from personasim.llm.base import ChatMessage
from personasim.persona import build_persona, read_seed_file
from personasim.storage import Database, PersonaRepository
from personasim.web.app import Worksheet, create_app

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "personas" / "elena.yaml"
WEB = Path(__file__).resolve().parents[1] / "src" / "personasim" / "web"
PROFILES = Path(__file__).resolve().parents[1] / "data" / "profiles"


class ScriptedLLM:
    def __init__(self, *replies: str) -> None:
        self._replies = list(replies) or ["Mm."]
        self.calls = 0

    @property
    def model(self) -> str:
        return "scripted"

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        self.calls += 1
        return self._replies[min(self.calls, len(self._replies)) - 1]

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        yield self.generate(messages)

    def is_available(self) -> bool:
        return True


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # A file, not `Database.in_memory()`. SQLite gives each *thread* its own
    # in-memory database, and `TestClient` serves requests on a worker thread — so
    # the schema created here would not exist over there.
    database = Database.from_path(tmp_path / "web.db")
    database.create_schema()
    with database.session() as db:
        PersonaRepository(db).save(build_persona(read_seed_file(SEED_FILE)))

    monkeypatch.setattr(
        "personasim.web.app.build_client",
        lambda settings: ScriptedLLM("I took him in the winter after my father died."),
    )
    with TestClient(create_app(Settings(), database)) as test_client:
        yield test_client


@pytest.fixture
def impaired_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The same app, served at CDR 0.5."""
    database = Database.from_path(tmp_path / "web.db")
    database.create_schema()
    with database.session() as db:
        PersonaRepository(db).save(build_persona(read_seed_file(SEED_FILE)))

    monkeypatch.setattr(
        "personasim.web.app.build_client",
        lambda settings: ScriptedLLM("It's slipped my mind."),
    )
    profile = load_profile(PROFILES / "cdr05.yaml")
    with TestClient(create_app(Settings(), database, profile=profile)) as test_client:
        yield test_client


class TestTheServedProfile:
    """The web app is a second adapter over the same loop, and it must carry the
    profile the way the CLI does.

    This is pinned because it shipped broken for an hour: `--profile` reached
    `persona chat` and not `persona serve`, so `./run start` served the *healthy*
    persona — and a tester driving what they believe is CDR 0.5 while talking to a
    healthy woman concludes the impairment layer does not work.
    """

    def test_healthy_by_default(self, client: TestClient) -> None:
        assert client.get("/api/profile").json()["name"] == "healthy"

    def test_the_profile_is_named_so_a_tester_knows_which_elena_this_is(
        self, impaired_client: TestClient
    ) -> None:
        assert impaired_client.get("/api/profile").json()["name"] == "cdr05"

    def test_an_impaired_session_actually_gates_recall(self, impaired_client: TestClient) -> None:
        """Not merely reported — the served conversation is genuinely impaired.

        A just-disclosed fact, asked straight back, is *never recalled crisply* at
        CDR 0.5: depending on how well this session laid it down, it comes back
        hedged, in outline, or not at all — but never with the full confidence the
        healthy persona returns it with (`test_a_healthy_session_withholds_nothing`).
        That "never crisp" is the deterministic invariant; *which* of withheld or
        hedged it lands on is the encoding hash's business, and asserting one
        particular outcome made this test a coin toss that failed two runs in three.
        """
        session = open_session(impaired_client)

        told = impaired_client.post(
            f"/api/session/{session}/message", json={"text": "I live in Portland."}
        ).json()
        assert told["formed"]  # formation is not impaired

        asked = impaired_client.post(
            f"/api/session/{session}/message",
            json={"text": "how are things at home these days?"},
        ).json()

        trace = asked["trace"]
        withheld = any("Portland" in gone["summary"] for gone in trace["withheld"])
        hedged = any(
            "Portland" in got["summary"] and (got["hedged"] or got["detail_withheld"])
            for got in trace["retrieved"]
        )
        crisp = any(
            "Portland" in got["summary"] and not got["hedged"] and not got["detail_withheld"]
            for got in trace["retrieved"]
        )
        assert withheld or hedged  # impaired: it does not come back like her own name
        assert not crisp  # and never, in any session, at full confidence

    def test_a_healthy_session_withholds_nothing(self, client: TestClient) -> None:
        session = open_session(client)
        reply = client.post(
            f"/api/session/{session}/message", json={"text": "tell me about your dog"}
        ).json()

        assert reply["trace"]["withheld"] == []


def open_session(client: TestClient) -> str:
    response = client.post("/api/personas/elena-marsh/session")
    assert response.status_code == 200
    return str(response.json()["session_id"])


class TestTheGallery:
    def test_it_lists_the_personas_with_their_card(self, client: TestClient) -> None:
        [card] = client.get("/api/personas").json()

        assert card["id"] == "elena-marsh"
        assert card["name"] == "Elena Marsh"
        assert card["occupation"] == "Cartographer, retired"
        assert "Compass" in card["description"]

    def test_the_description_is_authored_not_generated(self, client: TestClient) -> None:
        """Deriving it from her memories would be the system writing its own blurb;
        generating it would be the model writing her biography, which is the one
        thing it may never do. So it is a field in the seed."""
        seeded = build_persona(read_seed_file(SEED_FILE))
        [card] = client.get("/api/personas").json()

        assert card["description"].strip() == (seeded.identity.description or "").strip()

    def test_a_gallery_of_one_is_still_a_gallery(self, client: TestClient) -> None:
        """There is one persona today. The endpoint returns a list, and the layout
        assumes there will be more — Phase 3 adds them."""
        assert isinstance(client.get("/api/personas").json(), list)


class TestAConversation:
    def test_a_card_opens_a_session(self, client: TestClient) -> None:
        assert open_session(client)

    def test_an_unknown_persona_is_a_404(self, client: TestClient) -> None:
        assert client.post("/api/personas/nobody/session").status_code == 404

    def test_she_answers_and_says_why(self, client: TestClient) -> None:
        session = open_session(client)

        reply = client.post(
            f"/api/session/{session}/message",
            json={"text": "Why did you take in Compass?"},
        ).json()

        assert reply["content"] == "I took him in the winter after my father died."
        # the trace travels with the answer: a response she cannot account for is a bug
        assert "compass" in reply["trace"]["reason"].lower()
        assert any(
            "died of a stroke" in memory["summary"] for memory in reply["trace"]["retrieved"]
        )

    def test_what_the_caregiver_discloses_is_remembered(self, client: TestClient) -> None:
        session = open_session(client)

        reply = client.post(f"/api/session/{session}/message", json={"text": "I'm the nurse."})

        assert reply.json()["formed"] == ["my caregiver is a nurse"]

    def test_an_empty_message_is_refused(self, client: TestClient) -> None:
        session = open_session(client)

        assert client.post(f"/api/session/{session}/message", json={"text": ""}).status_code == 422


class TestEndingAndDownloading:
    def test_the_end_button_ends_it(self, client: TestClient) -> None:
        session = open_session(client)
        client.post(f"/api/session/{session}/message", json={"text": "Hello."})

        assert client.post(f"/api/session/{session}/end").status_code == 200

        # and she cannot be spoken to afterwards
        after = client.post(f"/api/session/{session}/message", json={"text": "Still there?"})
        assert after.status_code == 404

    def test_ending_consolidates(self, client: TestClient) -> None:
        session = open_session(client)
        client.post(f"/api/session/{session}/message", json={"text": "I live in Chicago."})
        client.post(f"/api/session/{session}/message", json={"text": "Actually I live in Denver."})

        assert client.post(f"/api/session/{session}/end").json()["superseded"] == 1

    def test_the_transcript_is_this_conversation_and_only_this_one(
        self, client: TestClient
    ) -> None:
        first = open_session(client)
        client.post(f"/api/session/{first}/message", json={"text": "First conversation."})
        client.post(f"/api/session/{first}/end")

        second = open_session(client)
        client.post(f"/api/session/{second}/message", json={"text": "Second conversation."})

        downloaded = client.get(f"/api/session/{second}/transcript").json()
        said = [turn["content"] for turn in downloaded["turns"] if turn["role"] == "user"]

        assert said == ["Second conversation."]
        assert "First conversation." not in json.dumps(downloaded)

    def test_the_transcript_downloads_as_json(self, client: TestClient) -> None:
        session = open_session(client)
        client.post(f"/api/session/{session}/message", json={"text": "Hello."})

        response = client.get(f"/api/session/{session}/transcript")

        assert response.status_code == 200
        assert "attachment" in response.headers["content-disposition"]
        assert ".json" in response.headers["content-disposition"]

    def test_the_transcript_carries_the_trace(self, client: TestClient) -> None:
        """A record that cannot say *why* she answered as she did is half a record."""
        session = open_session(client)
        client.post(
            f"/api/session/{session}/message", json={"text": "Why did you take in Compass?"}
        )

        turns = client.get(f"/api/session/{session}/transcript").json()["turns"]
        [hers] = [turn for turn in turns if turn["role"] == "persona"]

        assert hers["trace"]["retrieved"]

    def test_it_is_still_downloadable_after_it_has_ended(self, client: TestClient) -> None:
        """You may well want the transcript *because* you just ended the session."""
        session = open_session(client)
        client.post(f"/api/session/{session}/message", json={"text": "Hello."})
        client.post(f"/api/session/{session}/end")

        assert client.get(f"/api/session/{session}/transcript").status_code == 200


class TestTheAdapterAddsNothing:
    """Stage 9's one architectural rule: the orchestrator is untouched.

    The web layer is a second adapter over `Conversation`, exactly as the CLI is. If
    it grew its own idea of what she remembers, there would be two answers to every
    question about her, and they would drift.
    """

    def test_the_web_layer_owns_no_memory_or_retrieval_logic(self) -> None:
        forbidden = ("personasim.memory", "personasim.retrieval", "personasim.llm.context_builder")

        offenders: list[str] = []
        for path in sorted(WEB.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                else:
                    continue
                offenders += [
                    f"{path.name} imports {module}"
                    for module in modules
                    if module.startswith(forbidden)
                ]

        assert not offenders, offenders

    def test_the_browser_decides_nothing(self) -> None:
        """The page holds a session id and no persona state. Every memory decision
        happens server-side, in the orchestrator the CLI drives."""
        script = (WEB / "static" / "app.js").read_text()

        assert "fetch(" in script
        for invented in ("memories =", "remember(", "retrieve("):
            assert invented not in script


# ---------------------------------------------------------------- Sprint 3B


@pytest.fixture
def assessment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[TestClient, Database]]:
    """The app in blind assessment mode: a hidden severity drawn per session."""
    database = Database.from_path(tmp_path / "web.db")
    database.create_schema()
    with database.session() as db:
        PersonaRepository(db).save(build_persona(read_seed_file(SEED_FILE)))

    monkeypatch.setattr(
        "personasim.web.app.build_client",
        lambda settings: ScriptedLLM("I could not say, dear."),
    )
    pool = [load_profile(path) for path in sorted(PROFILES.glob("*.yaml"))]
    with TestClient(create_app(Settings(), database, assessment_pool=pool)) as test_client:
        yield test_client, database


POOL_NAMES = {"healthy", "cdr05", "cdr1", "cdr2", "cdr3"}


class TestAssessmentMode:
    """The blind loop: draw hidden, interview blind, commit, and only then reveal.

    Blindness is a set of sealed leaks, and each seal is pinned here: the profile
    endpoint, the per-message trace (the answer key), the transcript download, and
    the open-session response. The draw itself goes to storage, where only the
    reveal reads it.
    """

    def test_the_profile_endpoint_hides_the_draw(
        self, assessment: tuple[TestClient, Database]
    ) -> None:
        client, _ = assessment
        profile = client.get("/api/profile").json()

        assert profile["assessment"] is True
        assert profile["name"] == "assessment"
        assert profile["name"] not in POOL_NAMES  # no severity name escapes
        assert "hidden" in profile["label"].lower()

    def test_opening_a_session_returns_only_a_session_id(
        self, assessment: tuple[TestClient, Database]
    ) -> None:
        client, _ = assessment
        payload = client.post("/api/personas/elena-marsh/session").json()
        assert set(payload) == {"session_id"}

    def test_a_blind_reply_carries_no_trace_and_no_formed(
        self, assessment: tuple[TestClient, Database]
    ) -> None:
        client, _ = assessment
        session = open_session(client)

        reply = client.post(
            f"/api/session/{session}/message", json={"text": "I live in Portland."}
        ).json()

        assert reply["trace"] is None  # the trace is the answer key
        assert reply["formed"] == []

    def test_the_transcript_download_is_blind_too(
        self, assessment: tuple[TestClient, Database]
    ) -> None:
        client, _ = assessment
        session = open_session(client)
        client.post(f"/api/session/{session}/message", json={"text": "What day is it?"})

        turns = client.get(f"/api/session/{session}/transcript").json()["turns"]
        assert turns
        assert all(turn["trace"] is None for turn in turns)

    def test_the_draw_is_recorded_in_storage_not_in_any_response(
        self, assessment: tuple[TestClient, Database]
    ) -> None:
        from personasim.storage import AssessmentRepository

        client, database = assessment
        session = open_session(client)

        with database.session() as db:
            record = AssessmentRepository(db).get(session)

        assert record is not None
        assert record.actual_profile in POOL_NAMES
        assert record.committed_at is None  # drawn, not yet rated

    def test_commit_reveals_actual_rating_and_the_ledger(
        self, assessment: tuple[TestClient, Database]
    ) -> None:
        from personasim.storage import AssessmentRepository

        client, database = assessment
        session = open_session(client)
        client.post(f"/api/session/{session}/message", json={"text": "What day is it today?"})

        outcome = client.post(
            f"/api/session/{session}/commit",
            json={"global": 1.0, "memory": 0.5, "orientation": None},
        )
        assert outcome.status_code == 200
        revealed = outcome.json()

        assert revealed["actual"]["name"] in POOL_NAMES
        assert revealed["ratings"]["global"] == 1.0
        assert revealed["ratings"]["memory"] == 0.5
        assert revealed["report"].startswith("Assessment ledger")
        assert "PROBE COVERAGE" in revealed["report"]

        with database.session() as db:
            record = AssessmentRepository(db).get(session)
        assert record is not None and record.committed_at is not None
        assert record.ratings == revealed["ratings"]

    def test_commit_ends_a_live_session_first(
        self, assessment: tuple[TestClient, Database]
    ) -> None:
        client, _ = assessment
        session = open_session(client)
        client.post(f"/api/session/{session}/message", json={"text": "Hello."})

        assert client.post(f"/api/session/{session}/commit", json={"global": 0}).status_code == 200
        # The conversation closed with the commitment; there is no talking after it.
        after = client.post(f"/api/session/{session}/message", json={"text": "One more?"})
        assert after.status_code == 404

    def test_a_second_commit_conflicts(self, assessment: tuple[TestClient, Database]) -> None:
        client, _ = assessment
        session = open_session(client)

        assert client.post(f"/api/session/{session}/commit", json={"global": 2}).status_code == 200
        assert client.post(f"/api/session/{session}/commit", json={"global": 3}).status_code == 409

    def test_a_rating_off_the_cdr_scale_is_rejected(
        self, assessment: tuple[TestClient, Database]
    ) -> None:
        client, _ = assessment
        session = open_session(client)
        assert (
            client.post(f"/api/session/{session}/commit", json={"global": 1.5}).status_code == 422
        )

    def test_a_plain_session_cannot_commit(self, client: TestClient) -> None:
        session = open_session(client)
        response = client.post(f"/api/session/{session}/commit", json={"global": 1.0})
        assert response.status_code == 404

    def test_a_plain_profiled_session_still_shows_its_trace(
        self, impaired_client: TestClient
    ) -> None:
        """Blindness belongs to assessment mode alone: the ordinary profiled app
        keeps the why-panel, exactly as Stage 9 built it."""
        session = open_session(impaired_client)
        reply = impaired_client.post(
            f"/api/session/{session}/message", json={"text": "Hello there."}
        ).json()
        assert reply["trace"] is not None


class TestWorksheetAnchors:
    """The worksheet's vocabulary, pinned from both sides.

    The domain names are written twice — once as `Worksheet` fields on the server,
    once as `DOMAINS` in `app.js` — and the reveal keys its per-domain rows by them.
    Drift would not raise anything; it would silently render a blank row against a
    rating the server did record. So the two lists are compared here, and the
    anchor text (condensed from `docs/disease_profiles/CDR*.md`, which is what makes
    a rating a reading of the scale rather than a guess) must cover every domain at
    every point on it.
    """

    APP_JS = (WEB / "static" / "app.js").read_text()

    def _js_domains(self) -> list[str]:
        block = self.APP_JS.split("const DOMAINS = [", 1)[1].split("];", 1)[0]
        return re.findall(r'\["(\w+)"', block)

    def test_the_ui_domains_are_the_servers_domains(self) -> None:
        assert self._js_domains() == list(Worksheet(**{"global": 1.0}).as_record())

    def test_every_domain_is_anchored_at_every_point_on_the_scale(self) -> None:
        block = self.APP_JS.split("const ANCHORS = {", 1)[1].split("\n};", 1)[0]
        anchored = {
            domain: set(re.findall(r"^\s+([\d.]+):", body, re.MULTILINE))
            for domain, body in re.findall(r"(\w+): \{\n(.*?)\n  \},", block, re.DOTALL)
        }
        scale = {"0", "0.5", "1", "2", "3"}
        assert anchored == {domain: scale for domain in self._js_domains()}
