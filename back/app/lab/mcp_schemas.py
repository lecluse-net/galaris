"""Bounded commands for the Lab MCP surface."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .contracts import LabInput
from .schemas import CaseCategory


class Page(BaseModel):
    model_config = ConfigDict(extra="forbid")
    limit: Literal[10, 20, 50, 100, 500] = 50
    offset: int = Field(default=0, ge=0)
    summary_only: bool = False


class DatasetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10000)
    purpose: Literal["work", "validation", "holdout"] | None = None
    parameters: dict[str, Any] | None = None
    configuration: dict[str, Any] | None = None
    prompt_suffix: str | None = Field(default=None, max_length=50000)


class CasePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=400)
    input_data: LabInput | None = None
    expected_output: Any = None
    categories: list[CaseCategory] | None = Field(default=None, max_length=8)
    enabled: bool | None = None
    readiness: Literal["draft", "ready"] | None = None


class SourceImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_kind: Literal[
        "task", "llm_call", "messenger_message", "conversation_round", "voice_turn"
    ]
    source_id: UUID
    name: str | None = Field(default=None, max_length=400)
    confirmation_token: str | None = Field(default=None, min_length=64, max_length=64)
