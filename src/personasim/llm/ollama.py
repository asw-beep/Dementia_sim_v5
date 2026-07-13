"""The Ollama adapter — the only module in the codebase that imports `ollama`.

An invariant test enforces that. Everything above this file talks to `LLMClient`,
so replacing Ollama with another provider means writing a sibling of this module
and changing nothing else.

The model name is read from settings, never hard-coded, so switching models is a
configuration change rather than a code change.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

import ollama
import structlog

from personasim.config import Settings
from personasim.llm.base import ChatMessage, LLMError, LLMUnavailableError

log = structlog.get_logger(__name__)

# Thinking is disabled by default (`Settings.llm_thinking`), and current Ollama
# builds parse any scratchpad into a separate field rather than into the content.
# Neither is guaranteed: a model can be configured to think, and an older daemon
# leaves the block inline — where it would reach the user as the persona's own
# voice. Stripping it here means no caller has to know reasoning models exist.
THINK_OPEN = "<think>"
THINK_CLOSE = "</think>"


class OllamaClient:
    """Speaks to a local Ollama daemon. Satisfies `LLMClient`."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = ollama.Client(
            host=settings.llm_host,
            timeout=settings.llm_timeout_seconds,
        )

    @property
    def model(self) -> str:
        return self._settings.llm_model

    def generate(self, messages: Sequence[ChatMessage]) -> str:
        payload = _payload(messages)

        try:
            response = self._client.chat(
                model=self.model,
                messages=payload,
                options=self._options(),
                think=self._settings.llm_thinking,
            )
        except Exception as exc:
            raise _wrap(exc) from exc

        reply = strip_thinking(response.message.content or "").strip()
        if not reply:
            # A blank reply is a failure, not a turn: nothing downstream can build
            # a persona message from it.
            raise LLMError(f"{self.model} returned an empty response")

        log.debug("llm.generate", model=self.model, messages=len(payload), chars=len(reply))
        return reply

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        payload = _payload(messages)

        try:
            chunks = self._client.chat(
                model=self.model,
                messages=payload,
                options=self._options(),
                think=self._settings.llm_thinking,
                stream=True,
            )
            thinking = _ThinkingFilter()
            for chunk in chunks:
                visible = thinking.feed(chunk.message.content or "")
                if visible:
                    yield visible
            tail = thinking.flush()
        except Exception as exc:
            raise _wrap(exc) from exc

        if tail:
            yield tail

    def is_available(self) -> bool:
        """Whether the daemon is up *and* the configured model is pulled.

        Generating would answer the same question far more slowly, so the live
        smoke test asks this instead.
        """
        try:
            pulled = self._client.list()
        except Exception:
            return False
        return any(model.model == self.model for model in pulled.models)

    def _options(self) -> dict[str, Any]:
        return {"temperature": self._settings.llm_temperature}


def strip_thinking(text: str) -> str:
    """Remove any inline reasoning block. A no-op when the server already did."""
    thinking = _ThinkingFilter()
    return thinking.feed(text) + thinking.flush()


class _ThinkingFilter:
    """Suppresses `<think>…</think>` across a stream, tags split across chunks included.

    A tag can straddle a chunk boundary, so text that might yet turn out to be the
    start of a tag is held back until the next chunk settles it.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._thinking = False

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        visible: list[str] = []

        while True:
            if self._thinking:
                end = self._buffer.find(THINK_CLOSE)
                if end < 0:
                    self._buffer = _partial_tag_tail(self._buffer, THINK_CLOSE)
                    break
                self._buffer = self._buffer[end + len(THINK_CLOSE) :]
                self._thinking = False
                continue

            start = self._buffer.find(THINK_OPEN)
            if start < 0:
                held = _partial_tag_tail(self._buffer, THINK_OPEN)
                emit = self._buffer[: len(self._buffer) - len(held)]
                if emit:
                    visible.append(emit)
                self._buffer = held
                break

            if start:
                visible.append(self._buffer[:start])
            self._buffer = self._buffer[start + len(THINK_OPEN) :]
            self._thinking = True

        return "".join(visible)

    def flush(self) -> str:
        """Whatever was held back, once the stream is known to be over.

        An unclosed `<think>` means the model was cut off mid-thought; its
        scratchpad is discarded rather than spoken.
        """
        remainder = "" if self._thinking else self._buffer
        self._buffer = ""
        return remainder


def _partial_tag_tail(text: str, tag: str) -> str:
    """The trailing run of `text` that could still become `tag`."""
    for size in range(min(len(tag) - 1, len(text)), 0, -1):
        if text.endswith(tag[:size]):
            return text[-size:]
    return ""


def _payload(messages: Sequence[ChatMessage]) -> list[dict[str, str]]:
    if not messages:
        raise LLMError("cannot generate from an empty prompt")
    return [{"role": message.role.value, "content": message.content} for message in messages]


def _wrap(exc: Exception) -> LLMError:
    """No provider exception may escape this package.

    Callers must be able to handle a model failure without importing the provider
    that raised it — that is the whole point of the boundary.
    """
    if isinstance(exc, LLMError):
        return exc
    if isinstance(exc, ollama.ResponseError):
        # 404 is Ollama's answer for "that model is not pulled".
        if exc.status_code == 404:
            return LLMUnavailableError(f"model is not available: {exc}")
        return LLMError(f"model call failed: {exc}")
    if isinstance(exc, ConnectionError | TimeoutError | ollama.RequestError):
        return LLMUnavailableError(f"cannot reach the model host: {exc}")
    return LLMError(f"model call failed: {exc}")
