"""The LLM layer: language generation, and nothing else.

The model never decides what the persona remembers, who she is, or whether she is
being consistent. It is handed identity and memory, and asked to speak them.

Callers depend on `LLMClient` and construct one with `build_client`. No module
outside this package names a provider, so a second adapter — OpenAI, Anthropic,
vLLM — is a sibling of `ollama.py` and a one-line change here.
"""

from personasim.config import Settings
from personasim.llm.base import (
    ChatMessage,
    ChatRole,
    LLMClient,
    LLMError,
    LLMUnavailableError,
)
from personasim.llm.context_builder import (
    build_memory_context,
    build_messages,
    render_cast,
    render_now,
    render_speaker,
    to_chat_messages,
)
from personasim.llm.prompts import build_system_prompt, render_identity

__all__ = [
    "ChatMessage",
    "ChatRole",
    "LLMClient",
    "LLMError",
    "LLMUnavailableError",
    "build_client",
    "build_memory_context",
    "build_messages",
    "build_system_prompt",
    "render_cast",
    "render_identity",
    "render_now",
    "render_speaker",
    "to_chat_messages",
]


def build_client(settings: Settings) -> LLMClient:
    """The one place a provider is chosen.

    Imported lazily so that `personasim.llm` — and therefore the context builder
    and prompts, which never touch a model — can be used without the provider's
    package being importable at all.
    """
    from personasim.llm.ollama import OllamaClient

    return OllamaClient(settings)
