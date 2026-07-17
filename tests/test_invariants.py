"""Architectural invariants, enforced by test rather than convention.

These grow as stages land. Each one guards a boundary the docs declare
non-negotiable, so a future refactor that quietly crosses it fails here.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "personasim"

# Cognitive impairment lives in `impairment/` and nowhere else. During Phase 1
# this ban covered the whole tree, so impairment could not be smuggled in even as
# a disabled flag; with Phase 2 underway it is narrowed — not deleted — to the
# healthy core, per the decision recorded in docs/roadmap.md. The impairment
# package is the one place this vocabulary belongs; everything else must stay
# exactly as clean as Phase 1 left it.
PHASE_2_CONCEPTS = [
    "dementia",
    "alzheimer",
    "confabulat",
    "false_memory",
    "memory_decay",
    "decay_rate",
    "retrieval_noise",
    "temporal_confusion",
    "cognitive_decline",
]


def python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def healthy_core_files() -> list[Path]:
    """Everything outside `impairment/` — the Phase 1 core, which stays clean."""
    return [path for path in python_files() if "impairment" not in path.parts]


def test_source_tree_is_non_empty() -> None:
    assert python_files()


@pytest.mark.parametrize("concept", PHASE_2_CONCEPTS)
def test_no_impairment_concepts_in_the_healthy_core(concept: str) -> None:
    pattern = re.compile(concept, re.IGNORECASE)
    offenders = [
        path.relative_to(SRC) for path in healthy_core_files() if pattern.search(path.read_text())
    ]
    assert not offenders, f"impairment concept {concept!r} in the healthy core: {offenders}"


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text())
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
    return modules


def test_storage_does_not_import_reasoning_layers() -> None:
    """`storage/` persists; it does not retrieve or reason.

    It may depend on `models` (it returns them) and nothing else of ours.
    """
    forbidden_prefixes = (
        "personasim.retrieval",
        "personasim.memory",
        "personasim.llm",
        "personasim.conversation",
        "personasim.persona",
    )
    offenders = [
        f"{path.relative_to(SRC)} imports {module}"
        for path in sorted((SRC / "storage").rglob("*.py"))
        for module in _imported_modules(path)
        if module.startswith(forbidden_prefixes)
    ]
    assert not offenders, offenders


def _identifiers(path: Path) -> set[str]:
    """Names defined or referenced in a module — ignoring comments and docstrings.

    Matching raw text would flag a docstring that merely *says* "no ranking here".
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                names.add(node.name)
            case ast.Name():
                names.add(node.id)
            case ast.Attribute():
                names.add(node.attr)
            case ast.arg():
                names.add(node.arg)
    return names


def test_storage_contains_no_ranking_logic() -> None:
    """Scoring and ranking belong to `retrieval/`, never to persistence."""
    banned = re.compile(r"rank|score|scoring|relevance", re.IGNORECASE)
    offenders = [
        f"{path.relative_to(SRC)}: {sorted(bad)}"
        for path in sorted((SRC / "storage").rglob("*.py"))
        if (bad := {name for name in _identifiers(path) if banned.search(name)})
    ]
    assert not offenders, f"ranking logic leaked into storage: {offenders}"


def test_orm_rows_do_not_escape_storage() -> None:
    """Nothing above `storage/` may import the ORM or its row classes."""
    offenders: list[str] = []
    for path in python_files():
        if path.is_relative_to(SRC / "storage"):
            continue
        for module in _imported_modules(path):
            if module.split(".")[0] == "sqlalchemy" or module.startswith(
                "personasim.storage.schemas"
            ):
                offenders.append(f"{path.relative_to(SRC)} imports {module}")
    assert not offenders, offenders


def test_working_memory_cannot_reach_the_database() -> None:
    """Working memory is volatile by construction, not by policy.

    If it could import storage, a future change could quietly persist a session
    fact without it passing through memory formation.
    """
    offenders = [
        f"{path.relative_to(SRC)} imports {module}"
        for path in sorted((SRC / "memory" / "working").rglob("*.py"))
        for module in _imported_modules(path)
        if module.startswith("personasim.storage") or module.split(".")[0] == "sqlalchemy"
    ]
    assert not offenders, offenders


def test_retrieval_never_consults_the_llm() -> None:
    """Retrieval is deterministic.

    If the model decided what a question was about, the persona's recall would
    vary between two askings of the same question.
    """
    offenders = [
        f"{path.relative_to(SRC)} imports {module}"
        for path in sorted((SRC / "retrieval").rglob("*.py"))
        for module in _imported_modules(path)
        if module.split(".")[0] == "ollama" or module.startswith("personasim.llm")
    ]
    assert not offenders, offenders


def test_nothing_outside_llm_imports_a_provider() -> None:
    """The rest of the system must not know which model is in use.

    This is what makes a second adapter — OpenAI, Anthropic, vLLM — a new file in
    `llm/` rather than an edit to business logic. Importing `personasim.llm.ollama`
    is equally forbidden: naming the adapter module is naming the provider. Use
    `personasim.llm.build_client`, which returns an `LLMClient`.
    """
    offenders = [
        f"{path.relative_to(SRC)} imports {module}"
        for path in python_files()
        if not path.is_relative_to(SRC / "llm")
        for module in _imported_modules(path)
        if module.split(".")[0] == "ollama" or module == "personasim.llm.ollama"
    ]
    assert not offenders, offenders


def test_the_llm_layer_does_not_reach_into_memory_or_storage() -> None:
    """The model verbalizes; it does not remember.

    `llm/` may read identity, memories, and a trace (it renders them into a
    prompt), and it depends on the retrieval *source protocol* to look a memory
    back up. It may not touch the database or working memory — if it could, a
    model's output could become a memory without passing through formation.
    """
    forbidden = ("personasim.storage", "personasim.memory")
    offenders = [
        f"{path.relative_to(SRC)} imports {module}"
        for path in sorted((SRC / "llm").rglob("*.py"))
        for module in _imported_modules(path)
        if module.startswith(forbidden) or module.split(".")[0] == "sqlalchemy"
    ]
    assert not offenders, offenders


def test_memory_formation_never_consults_the_llm() -> None:
    """What is remembered is decided by rule, not by a model.

    Two consequences, and both are the point of the stage. A model deciding what
    was disclosed would decide differently on two hearings of the same sentence,
    and a memory formed by a coin toss is worse than no memory. And a formation
    step that could *call* a model is a formation step that could be handed the
    model's own output — which is precisely how an invented biography would become
    a permanent memory.
    """
    offenders = [
        f"{path.relative_to(SRC)} imports {module}"
        for path in sorted((SRC / "memory" / "formation").rglob("*.py"))
        for module in _imported_modules(path)
        if module.split(".")[0] == "ollama" or module.startswith("personasim.llm")
    ]
    assert not offenders, offenders


def test_models_package_performs_no_io() -> None:
    """Domain models are pure data: no storage, no LLM, no filesystem."""
    forbidden = {"sqlalchemy", "ollama", "httpx", "requests", "sqlite3"}
    offenders: list[str] = []

    for path in sorted((SRC / "models").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.split(".")[0] in forbidden:
                    offenders.append(f"{path.name} imports {name}")

    assert not offenders, offenders


def test_impairment_is_deterministic_and_recall_side_only() -> None:
    """The impairment layer withholds and hedges; it never manufactures.

    Three imports would each break that, and all three are banned. An LLM (or the
    adapter that wraps one) would let impairment *generate* — and generated content
    beside a permanent store is how an invented life gets written down. Storage
    would let it touch the store directly, turning "cannot reach a memory" into
    "the memory is gone". And `random` would make the same question fail
    differently on two askings — fluctuating confusion, a later severity, and the
    end of reproducibility, which a clinical validation cannot survive.
    """
    forbidden = ("personasim.llm", "personasim.storage")
    offenders = [
        f"{path.relative_to(SRC)} imports {module}"
        for path in sorted((SRC / "impairment").rglob("*.py"))
        for module in _imported_modules(path)
        if module.startswith(forbidden)
        or module.split(".")[0] in {"ollama", "random", "sqlalchemy"}
    ]
    assert not offenders, offenders


def test_the_healthy_core_does_not_import_impairment() -> None:
    """Phase 2 wraps Phase 1; Phase 1 must not know it exists.

    The conversation loop is the single compositional exception: it is the
    compositor, and wiring the wrapper in front of the engine is its job. The CLI
    and web adapters load profiles, and `assessment/` (Phase 3) reads them to put
    intended numbers beside observed behaviour — consumers all, above the core. If
    retrieval, formation, working memory, the models, or storage ever import the
    impairment package, the layer has stopped being a wrapper and started being
    an edit — which is the entire architectural promise of the phase, broken.
    """
    allowed = {
        SRC / "conversation" / "loop.py",
        SRC / "cli.py",
        SRC / "web",
        SRC / "assessment",
    }
    offenders = [
        f"{path.relative_to(SRC)} imports {module}"
        for path in healthy_core_files()
        if path not in allowed and not any(parent in allowed for parent in path.parents)
        for module in _imported_modules(path)
        if module.startswith("personasim.impairment")
    ]
    assert not offenders, offenders


def test_assessment_never_consults_the_llm() -> None:
    """The reveal is a replay of the trace, not a judgment by a model.

    Assessment aggregates what the session log recorded and renders text. A model
    in that path would make the explanation vary between two readings of the same
    session — and able to be wrong, which an answer key must never be. The same
    invariant, for the same reason, as formation. Storage stays out too: the CLI
    hands assessment its turns, so the package cannot quietly grow a write path.
    """
    forbidden = ("personasim.llm", "personasim.storage")
    offenders = [
        f"{path.relative_to(SRC)} imports {module}"
        for path in sorted((SRC / "assessment").rglob("*.py"))
        for module in _imported_modules(path)
        if module.startswith(forbidden) or module.split(".")[0] in {"ollama", "sqlalchemy"}
    ]
    assert not offenders, offenders
