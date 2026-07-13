"""Stage 3: the `persona seed` command."""

from __future__ import annotations

from pathlib import Path

import pytest

from personasim.cli import main
from personasim.config import Settings
from personasim.conversation import Conversation
from personasim.conversation.render import render_session
from personasim.models import Persona
from personasim.persona import build_persona, read_seed_file
from personasim.storage import Database, PersonaRepository, SessionRepository
from tests.test_conversation import ScriptedLLM

SEED_FILE = Path(__file__).resolve().parents[1] / "data" / "personas" / "elena.yaml"


@pytest.fixture
def elena() -> Persona:
    return build_persona(read_seed_file(SEED_FILE))


def test_seed_command_reports_what_it_created(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--database", str(tmp_path / "p.db"), "seed", str(SEED_FILE)])
    assert exit_code == 0

    out = capsys.readouterr().out
    assert "Elena Marsh" in out
    assert "36 memories created" in out


def test_reseeding_reports_a_noop(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = tmp_path / "p.db"
    main(["--database", str(database), "seed", str(SEED_FILE)])
    capsys.readouterr()

    assert main(["--database", str(database), "seed", str(SEED_FILE)]) == 0
    assert "already seeded" in capsys.readouterr().out


def test_seed_creates_the_database_file(tmp_path: Path) -> None:
    database = tmp_path / "nested" / "p.db"
    assert main(["--database", str(database), "seed", str(SEED_FILE)]) == 0
    assert database.is_file()


def test_missing_seed_file_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["--database", str(tmp_path / "p.db"), "seed", str(tmp_path / "absent.yaml")])
    assert exit_code == 1
    assert "error:" in capsys.readouterr().err


def test_invalid_seed_file_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("id: p\nidentity: {}\n")
    assert main(["--database", str(tmp_path / "p.db"), "seed", str(bad)]) == 1
    assert "error:" in capsys.readouterr().err


class TestTraceReplaysWhySheSaidIt:
    """The trace was always recorded and never readable.

    Every defect in this project was found by talking to the persona, and until this
    existed, explaining one afterwards meant writing a throwaway script. The account
    sat in a JSON column nobody read.
    """

    def talked(self, database: Database, elena: Persona) -> str:
        with database.session() as db:
            PersonaRepository(db).save(elena)

        llm = ScriptedLLM("I took him in the winter after my father died.")
        with Conversation(elena, llm, database, Settings()) as chat:
            chat.send("Why did you take in Compass?")
            return chat.session_id

    def test_a_session_replays_the_memories_behind_each_reply(
        self, database: Database, elena: Persona
    ) -> None:
        session_id = self.talked(database, elena)

        with database.session() as db:
            turns = SessionRepository(db).get_turns(session_id)

        replay = render_session(turns, session_id=session_id)

        assert "Why did you take in Compass?" in replay
        assert "I took him in the winter after my father died." in replay
        # the memory that explains the one asked for, and the relation that fetched it
        assert "died of a stroke" in replay
        assert "caused_by" in replay

    def test_the_replay_says_it_is_history_not_current_memory(
        self, database: Database, elena: Persona
    ) -> None:
        """A trace quotes summaries *as they read at the time*, and `--force` exists
        so they can be rewritten since. A replay may therefore quote text that no
        longer exists anywhere — correct for a log, misleading for a memory browser,
        and the difference has to be said out loud."""
        session_id = self.talked(database, elena)

        with database.session() as db:
            turns = SessionRepository(db).get_turns(session_id)

        assert "not a view of memory now" in render_session(turns, session_id=session_id)

    def test_an_empty_session_says_so_rather_than_printing_nothing(self) -> None:
        assert "no turns recorded" in render_session([], session_id="abc")

    def test_listing_sessions_reports_when_there_are_none(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        database = tmp_path / "p.db"
        main(["--database", str(database), "seed", str(SEED_FILE)])
        capsys.readouterr()

        assert main(["--database", str(database), "trace", "elena-marsh", "--list"]) == 1
        assert "no recorded sessions" in capsys.readouterr().err

    def test_tracing_a_persona_that_never_spoke_exits_nonzero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        database = tmp_path / "p.db"
        main(["--database", str(database), "seed", str(SEED_FILE)])
        capsys.readouterr()

        assert main(["--database", str(database), "trace", "elena-marsh"]) == 1
        assert "no recorded sessions" in capsys.readouterr().err


def test_no_subcommand_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


def edited_copy(tmp_path: Path) -> Path:
    """The shipped seed, with one summary rewritten — the Stage 6 edit in miniature."""
    edited = tmp_path / "edited.yaml"
    edited.write_text(
        SEED_FILE.read_text().replace(
            "I own an elderly beagle named Compass",
            "I own a very old beagle named Compass",
        )
    )
    return edited


def test_an_edited_seed_warns_instead_of_lying_about_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It used to say "already seeded; nothing to do" while discarding the edit.

    That silence is what would let a database keep summaries whose author had
    already fixed them.
    """
    database = tmp_path / "p.db"
    main(["--database", str(database), "seed", str(SEED_FILE)])
    capsys.readouterr()

    assert main(["--database", str(database), "seed", str(edited_copy(tmp_path))]) == 0

    captured = capsys.readouterr()
    assert "1 memories in" in captured.err
    assert "NOT applied" in captured.err
    assert "--force" in captured.err
    # "Nothing to do" is exactly the lie that let an edited seed rot in a database.
    assert "nothing to do" not in captured.out
    assert "the seed file has changed" in captured.out


def test_force_applies_the_edit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    database = tmp_path / "p.db"
    main(["--database", str(database), "seed", str(SEED_FILE)])
    capsys.readouterr()

    exit_code = main(["--database", str(database), "seed", str(edited_copy(tmp_path)), "--force"])

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "1 rewritten" in captured.out
    assert captured.err == ""
