"""Command-line entry point.

`seed` loads a persona. `chat` talks to one. Neither knows which model is running:
`chat` asks `llm.build_client` for something satisfying `LLMClient` and never finds
out what it got.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from personasim.config import Settings, get_settings
from personasim.conversation import Conversation
from personasim.conversation.render import render_session, render_trace
from personasim.llm import LLMClient, LLMError, build_client
from personasim.logging import configure_logging
from personasim.models.persona import Persona, PersonaId
from personasim.persona.gaps import find_gaps, report
from personasim.persona.interview import interview, render, to_seed, validate
from personasim.persona.loader import SeedError, build_persona, read_seed_file, seed_from_file
from personasim.storage.database import Database
from personasim.storage.repositories.persona import PersonaRepository
from personasim.storage.repositories.session import SessionRepository, SessionSummary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="persona", description="Persona Simulator")
    parser.add_argument("--database", type=Path, help="override the configured database path")
    parser.add_argument("--debug", action="store_true", help="verbose logging")

    subcommands = parser.add_subparsers(dest="command", required=True)

    seed = subcommands.add_parser("seed", help="load a persona seed file into the database")
    seed.add_argument("file", type=Path, help="path to a persona YAML seed file")
    seed.add_argument(
        "--force",
        action="store_true",
        help=(
            "rewrite memories the seed file already created, so an edit to the file "
            "lands. Touches only the memories the seed names; anything the persona "
            "learned in conversation is left alone."
        ),
    )

    chat = subcommands.add_parser("chat", help="talk to a seeded persona")
    chat.add_argument("persona", help="the persona id, e.g. elena-marsh")
    chat.add_argument(
        "--trace",
        action="store_true",
        help="print the memory trace behind every reply — which memories fired, and why",
    )

    new = subcommands.add_parser(
        "new", help="author a new persona by answering questions — no gaps, no conflicts"
    )
    new.add_argument("--output", type=Path, help="where to write the seed file")

    check = subcommands.add_parser(
        "check", help="check a seed file for the gaps that make a persona refuse or invent"
    )
    check.add_argument("file", type=Path, help="path to a persona YAML seed file")

    serve = subcommands.add_parser("serve", help="serve the web frontend")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    trace = subcommands.add_parser(
        "trace",
        help="replay why a persona said what it said, from the session log",
    )
    trace.add_argument("persona", help="the persona id, e.g. elena-marsh")
    trace.add_argument(
        "--session",
        help="the session to replay; defaults to the most recent one",
    )
    trace.add_argument(
        "--list",
        action="store_true",
        help="list this persona's sessions instead of replaying one",
    )

    return parser


def _open_database(settings: Settings, override: Path | None) -> Database:
    database = Database.from_path(override or settings.database_path)
    database.create_schema()
    return database


def _seed(settings: Settings, database_override: Path | None, file: Path, force: bool) -> int:
    database = _open_database(settings, database_override)
    try:
        report = seed_from_file(database, file, force=force)
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        database.dispose()

    if report.was_noop and not report.has_stale_memories:
        print(f"{report.persona_name} is already seeded; nothing to do.")
    elif report.was_noop:
        # "Nothing to do" is exactly the lie that let an edited seed rot in a
        # database. There is something to do; it just needs --force.
        print(f"{report.persona_name} is already seeded, but the seed file has changed.")
    else:
        print(
            f"Seeded {report.persona_name} ({report.persona_id}): "
            f"{report.memories_created} memories created, "
            f"{report.memories_updated} rewritten, "
            f"{report.memories_skipped} already present."
        )

    # The footgun, said out loud. Seeding is idempotent by memory id, and ids come
    # from the seed *key*, not the content — so an edited memory resolves to one
    # that already exists and is skipped. Silence here is what let a database keep
    # summaries their author had already fixed.
    if report.has_stale_memories:
        print(
            f"\nwarning: {report.memories_stale} memories in {file} differ from the "
            f"database and were NOT applied.\n"
            f"         Re-run with --force to rewrite them. Memories the persona "
            f"formed in conversation are not affected.",
            file=sys.stderr,
        )

    return 0


def _load(database: Database, persona_id: PersonaId) -> Persona | None:
    with database.session() as session:
        return PersonaRepository(session).load(persona_id)


def _chat(
    settings: Settings, database_override: Path | None, persona_id: PersonaId, show_trace: bool
) -> int:
    database = _open_database(settings, database_override)
    try:
        persona = _load(database, persona_id)
        if persona is None:
            print(f"error: no persona {persona_id!r}; seed one first.", file=sys.stderr)
            return 1

        llm = build_client(settings)
        if not llm.is_available():
            print(f"error: {llm.model} is not reachable at {settings.llm_host}.", file=sys.stderr)
            return 1

        return _talk(persona, llm, database, settings, show_trace)
    finally:
        database.dispose()


def _talk(
    persona: Persona,
    llm: LLMClient,
    database: Database,
    settings: Settings,
    show_trace: bool,
) -> int:
    """The loop. `Conversation` is a context manager, so the session is closed and
    working memory discarded even if this falls over."""
    print(f"Talking to {persona.identity.name}. Ctrl-D or /quit to end the session.")

    with Conversation(persona, llm, database, settings) as chat:
        print()

        while True:
            try:
                text = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not text:
                continue
            if text in ("/quit", "/exit"):
                break

            try:
                reply = chat.send(text)
            except LLMError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 1

            print(f"\n{persona.identity.name.split()[0]}> {reply.text}\n")

            if show_trace:
                print(render_trace(reply.trace))
                if reply.formed:
                    print(f"  formed: {[m.summary for m in reply.formed]}")
                print()

    print(f"Session ended. {persona.identity.name} remembers {len(persona.memories)} things.")
    return 0


def _trace(
    settings: Settings,
    database_override: Path | None,
    persona_id: PersonaId,
    session_id: str | None,
    show_list: bool,
) -> int:
    """Replay the retrieval decisions behind a session, from the log.

    The trace was always recorded and never readable. Every defect in this project
    was found by talking to the persona, and until now explaining one afterwards
    meant writing a throwaway script.
    """
    database = _open_database(settings, database_override)
    try:
        with database.session() as db:
            sessions = SessionRepository(db)

            if show_list:
                return _list_sessions(sessions.list_sessions(persona_id), persona_id)

            chosen = session_id or sessions.latest_session_id(persona_id)
            if chosen is None:
                print(f"error: {persona_id} has no recorded sessions.", file=sys.stderr)
                return 1

            turns = sessions.get_turns(chosen)

        print(render_session(turns, session_id=chosen))
        return 0
    finally:
        database.dispose()


def _list_sessions(sessions: list[SessionSummary], persona_id: PersonaId) -> int:
    if not sessions:
        print(f"error: {persona_id} has no recorded sessions.", file=sys.stderr)
        return 1

    print(f"{len(sessions)} sessions, newest first:")
    for summary in sessions:
        when = summary.started_at.strftime("%Y-%m-%d %H:%M")
        state = "" if summary.ended_at else "  (never ended)"
        print(f"  {summary.session_id}  {when}  {summary.turns} turns{state}")
    return 0


def _new(output: Path | None) -> int:
    """Author a persona by being asked, rather than by remembering to.

    Every seed defect this project has had was an *omission* — a mother nobody wrote
    down, a plural nobody thought of. None were hard; they were simply easy to forget.
    """
    draft = interview(input, print)
    seed = to_seed(draft)

    try:
        validate(seed)
    except (SeedError, ValueError) as exc:
        print(f"\nerror: the answers do not make a possible life:\n  {exc}", file=sys.stderr)
        print("\nNothing was written. Run again.", file=sys.stderr)
        return 1

    path = output or Path("data/personas") / f"{draft.persona_id}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(seed))

    print(f"\nWrote {path}")
    print(
        f"  {len(seed.get('semantic', []))} facts, "
        f"{len(seed.get('episodic', []))} events, "
        f"{len(seed.get('relationships', []))} people"
    )
    print(f"\nSeed her:  uv run persona seed {path}")
    return 0


def _check(file: Path) -> int:
    try:
        persona = build_persona(read_seed_file(file))
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    gaps = find_gaps(persona)
    print(f"{persona.identity.name}: {len(persona.memories)} memories\n")
    print(report(gaps))
    return 0 if gaps.is_clean else 1


def _serve(settings: Settings, database_override: Path | None, host: str, port: int) -> int:
    """Run the web adapter.

    Imported here, not at module scope: `persona seed` and `persona chat` must not
    require FastAPI to be installed to run.
    """
    import uvicorn

    from personasim.web import create_app

    database = Database.from_path(database_override or settings.database_path)
    app = create_app(settings, database)

    print(f"Serving on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    configure_logging(debug=args.debug)
    settings = get_settings()

    if args.command == "seed":
        return _seed(settings, args.database, args.file, args.force)

    if args.command == "chat":
        return _chat(settings, args.database, args.persona, args.trace)

    if args.command == "trace":
        return _trace(settings, args.database, args.persona, args.session, args.list)

    if args.command == "serve":
        return _serve(settings, args.database, args.host, args.port)

    if args.command == "new":
        return _new(args.output)

    if args.command == "check":
        return _check(args.file)

    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
