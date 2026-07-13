"""Stage 0 smoke tests: the toolchain works and the config seam behaves."""

from __future__ import annotations

from pathlib import Path

import personasim
from personasim.config import Settings, get_settings
from personasim.logging import configure_logging, get_logger


def test_package_imports() -> None:
    assert personasim.__version__


def test_the_default_model_is_one_a_laptop_can_run() -> None:
    """Asserted against the field default, not the resolved setting.

    A developer pointing `.env` at a bigger box — as the GPU host does — must not
    fail the suite for it. That the model is swappable at all is the point of the
    adapter; a test that forbade the swap would be testing the wrong thing.
    """
    assert Settings.model_fields["llm_model"].default == "qwen3:8b"


def test_settings_read_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("PERSONA_LLM_MODEL", "qwen3:14b")
    monkeypatch.setenv("PERSONA_RETRIEVAL_TOP_K", "3")
    settings = get_settings()
    assert settings.llm_model == "qwen3:14b"
    assert settings.retrieval_top_k == 3


def test_get_settings_is_not_cached(monkeypatch) -> None:
    """Tests override the database path; a cache would leak state between them."""
    monkeypatch.setenv("PERSONA_LLM_MODEL", "first")
    assert get_settings().llm_model == "first"
    monkeypatch.setenv("PERSONA_LLM_MODEL", "second")
    assert get_settings().llm_model == "second"


def test_database_url_derives_from_path() -> None:
    settings = Settings(database_path=Path("/tmp/x.db"))
    assert settings.database_url == "sqlite:////tmp/x.db"


def test_logging_configures_and_binds() -> None:
    configure_logging(debug=True)
    logger = get_logger("test", stage=0)
    logger.info("smoke", detail="ok")
