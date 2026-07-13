"""The LLM interface: the only shape the rest of the system may know a model by.

No module outside this package names a provider. Everything above talks to
`LLMClient`, so swapping Ollama for OpenAI, Anthropic, or vLLM is an adapter
change and nothing else.

The model's job is language generation. It is never asked what a memory means,
which memory is relevant, or whether the persona is being consistent — those
belong to the persona engine, and a model that decided them would make recall
vary between two askings of the same question.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field


class LLMError(Exception):
    """The model layer failed. Raised instead of any provider's own exception.

    Provider exceptions are wrapped here so that catching a model failure never
    requires importing the provider.
    """


class LLMUnavailableError(LLMError):
    """The model could not be reached, or is not pulled."""


class ChatRole(StrEnum):
    """Roles as a chat model understands them.

    Deliberately not `models.conversation.Role`. That enum speaks of the persona
    and the user — domain concepts. This one speaks of a chat API's system/user/
    assistant slots — a provider concept. Collapsing them would leak the model's
    vocabulary into the domain.
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    """One message in a prompt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: ChatRole
    content: str = Field(min_length=1)


class LLMClient(Protocol):
    """What the conversation layer is allowed to ask of a model."""

    @property
    def model(self) -> str:
        """The model actually in use. For the trace and for logs — never for branching."""
        ...

    def generate(self, messages: Sequence[ChatMessage]) -> str: ...

    def stream(self, messages: Sequence[ChatMessage]) -> Iterator[str]: ...

    def is_available(self) -> bool:
        """Whether the model can be reached right now, without generating anything."""
        ...
