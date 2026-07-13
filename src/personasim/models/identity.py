"""Identity: who the persona is.

Identity never depends on the LLM. It is loaded from storage and injected into
every prompt; the model may express it but never revise it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    name: str = Field(min_length=1)
    age: int = Field(ge=0, le=130)
    occupation: str = Field(min_length=1)
    personality: list[str] = Field(min_length=1)
    values: list[str] = Field(min_length=1)
    speech_style: str = Field(min_length=1)

    # Two lines for the card that introduces her, before anyone has spoken to her.
    # Authored, like everything else about her — deriving it from her memories would
    # be the system writing its own blurb, and generating it would be the model
    # writing her biography, which is the one thing it may never do.
    description: str | None = None

    @field_validator("personality", "values")
    @classmethod
    def _non_blank_entries(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values if v.strip()]
        if not cleaned:
            raise ValueError("must contain at least one non-blank entry")
        return cleaned
