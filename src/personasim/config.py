"""Runtime configuration.

The rest of the system reads settings from here rather than reaching for
environment variables directly. In particular, the model name lives here so that
swapping models never requires touching business logic.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Application settings, overridable via `PERSONA_*` environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="PERSONA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---------------------------------------------------------------
    # Only the Ollama adapter reads these. Nothing else knows a model exists.
    llm_model: str = "qwen3:8b"
    llm_host: str = "http://localhost:11434"
    # Low on purpose, and lowered again. The model is verbalizing an authored life,
    # not writing one: every degree of creative freedom it is given, it spends
    # inventing biography. At 0.7 it invented people; at 0.4 it stopped inventing
    # people and kept inventing *reasons* — why she took the dog in, how the year
    # felt, the conversation in which she had been told a thing. High enough to
    # sound like a person, low enough to stop at the end of the memory.
    llm_temperature: float = Field(default=0.25, ge=0.0, le=2.0)
    llm_timeout_seconds: float = Field(default=120.0, gt=0.0)

    # Reasoning models deliberate before answering. The persona has nothing to
    # deliberate about: what she recalls was decided by retrieval, and what she is
    # was decided by identity. Thinking here buys minutes of latency and a
    # scratchpad that must then be kept out of her voice.
    #   False — ask the model not to think (the default).
    #   True  — let it think anyway; the adapter still strips the scratchpad.
    #   None  — never send the parameter, for a model that rejects it outright.
    llm_thinking: bool | None = False

    # --- Storage -----------------------------------------------------------
    database_path: Path = PROJECT_ROOT / "data" / "persona.db"
    data_dir: Path = PROJECT_ROOT / "data"

    # --- Working memory ----------------------------------------------------
    # A capacity bound, not a forgetting model: the window caps how much of the
    # live conversation is held in RAM. Nothing is "lost" from long-term memory.
    working_memory_turns: int = Field(default=12, gt=0)

    # --- Retrieval ---------------------------------------------------------
    # Eight, not six. Elena has a husband, two children, two parents and a brother —
    # and at six, "who is in your family?" returned five of them and dropped Tom. The
    # window has to fit a family, or she omits a brother while listing her relatives.
    retrieval_top_k: int = Field(default=8, gt=0)
    retrieval_min_score: float = Field(default=0.05, ge=0.0)
    # Relative weights of the inspectable components of the ranking score.
    rank_weight_keyword: float = Field(default=1.0, ge=0.0)
    rank_weight_importance: float = Field(default=0.5, ge=0.0)
    rank_weight_confidence: float = Field(default=0.25, ge=0.0)

    # Follow typed links out of the top results, so the memory that *explains* a
    # retrieved memory comes along with it. This is what hands the LLM the causal
    # bridge instead of leaving it to invent one.
    retrieval_expand_links: bool = True
    retrieval_max_expansions: int = Field(default=3, ge=0)

    # --- Improvisation ------------------------------------------------------
    # She has no clock and no memory of today, so "what did you have for breakfast?"
    # has no true answer. Left to the model she invented a different one every turn.
    # With this on, a value is synthesised once, written down as a memory, and
    # answered from ever after — consistent, and confined to her *day*. It can never
    # produce a person, a death, or a life event: see `conversation/improvise.py`.
    improvise_everyday: bool = True

    # --- Cognitive profile --------------------------------------------------
    # Which severity the persona is run at. Unset means healthy — the Phase 1
    # persona exactly, with no impairment layer constructed at all. A path here
    # (e.g. data/profiles/cdr05.yaml) loads a profile, and is how `persona serve`
    # and `./run start` select one without a code change:
    #
    #     PERSONA_PROFILE=data/profiles/cdr05.yaml ./run start
    #
    # `persona chat --profile` overrides it for a single conversation.
    profile: Path | None = None

    # --- Diagnostics -------------------------------------------------------
    debug: bool = False
    log_traces: bool = True

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path}"


def get_settings() -> Settings:
    """Build settings from the environment.

    Not cached: tests override the database path per-test, and a cache would
    leak one test's temp directory into the next.
    """
    return Settings()
