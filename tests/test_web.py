"""Stage 9: the web adapter.

A second front end over the Stage 7 orchestrator, alongside the CLI. It adds no
memory, no retrieval, and no persona logic — and the last test in this file is the
one that says so: what the browser can reach is exactly what `persona chat` can
reach, and nothing more.
"""

from __future__ import annotations

import ast
import json
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from personasim.config import Settings
from personasim.llm.base import ChatMessage
from personasim.persona import build_persona, read_seed_file
from personasim.storage import Database, PersonaRepository
from personasim.web.app import create_app

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "personas" / "elena.yaml"
WEB = Path(__file__).resolve().parents[1] / "src" / "personasim" / "web"


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


def open_session(client: TestClient) -> str:
    response = client.post("/api/personas/elena-marsh/session")
    assert response.status_code == 200
    return str(response.json()["session_id"])


class TestTheGallery:
    def test_it_lists_the_personas_with_their_card(self, client: TestClient) -> None:
        [card] = client.get("/api/personas").json()

        assert card["id"] == "elena-marsh"
        assert card["name"] == "Elena Marsh"
        assert card["occupation"] == "Cartographer"
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
