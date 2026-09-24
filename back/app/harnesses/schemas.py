"""HTTP schemas for the Harness catalogue and per-agent selection."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, computed_field, field_validator, model_validator

from .contracts import HarnessAction, HarnessCapability, HarnessLifecycleStatus, lifecycle_actions


class OpenAIMessagesSettings(BaseModel):
    model_config = ConfigDict(extra="allow")
    streams_ai_messages: StrictBool = True


class HarnessCatalogCreate(BaseModel):
    """Create one reusable Harness configuration."""

    model_config = ConfigDict(extra="forbid")

    provider_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=2_000)
    token: str | None = Field(default=None, max_length=20_000)
    model: str | None = Field(default=None, max_length=500)
    settings: dict[str, Any] = Field(default_factory=dict, validate_default=True)
    enabled: bool = False

    @field_validator("settings")
    @classmethod
    def validate_settings(cls, value: dict[str, Any]) -> dict[str, Any]:
        return OpenAIMessagesSettings.model_validate(value).model_dump()

    @field_validator("provider_code", "name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value must not be empty")
        return stripped

    @field_validator("base_url", "token", "model")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @model_validator(mode="after")
    def normalized_provider_code(self) -> "HarnessCatalogCreate":
        self.provider_code = self.provider_code.lower()
        return self


class HarnessCatalogUpdate(BaseModel):
    """Update catalogue configuration; an omitted token keeps the existing secret."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=2_000)
    token: str | None = Field(default=None, max_length=20_000)
    model: str | None = Field(default=None, max_length=500)
    settings: dict[str, Any] = Field(default_factory=dict, validate_default=True)
    enabled: bool

    @field_validator("settings")
    @classmethod
    def validate_settings(cls, value: dict[str, Any]) -> dict[str, Any]:
        return OpenAIMessagesSettings.model_validate(value).model_dump()

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value must not be empty")
        return stripped

    @field_validator("base_url", "token", "model")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class HarnessCatalogRead(BaseModel):
    id: UUID
    name: str
    provider_code: str
    provider_label: str
    driver_code: str
    enabled: bool
    base_url: str | None = None
    model: str | None = None
    token_configured: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)
    revision: int = 1
    capabilities: list[HarnessCapability] = Field(default_factory=lambda: [])
    containerized: bool = False
    max_parallel_tasks: int | None = 1
    assigned_agents: int = 0
    last_error: str | None = None


class HarnessSelectionUpdate(BaseModel):
    """Select an existing catalogue Harness for one agent."""

    model_config = ConfigDict(extra="forbid")

    harness_id: UUID


class HarnessRead(BaseModel):
    id: UUID | None = None
    harness_id: UUID | None = None
    agent_id: int
    internal: bool
    name: str
    provider_code: str
    driver_code: str
    base_url: str | None = None
    model: str | None = None
    token_configured: bool = False
    lifecycle_status: HarnessLifecycleStatus
    revision: int = 1
    capabilities: list[HarnessCapability] = Field(default_factory=lambda: [])
    containerized: bool = False
    max_parallel_tasks: int | None = 1
    last_error: str | None = None


class HarnessProviderRead(BaseModel):
    code: str
    label: str
    driver_code: str
    containerized: bool
    max_parallel_tasks: int
    capabilities: list[HarnessCapability]


class HarnessProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    harness_id: UUID | None = None
    base_url: str = Field(min_length=1, max_length=2_000)
    token: str | None = Field(default=None, max_length=20_000)

    @field_validator("base_url")
    @classmethod
    def strip_base_url(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Value must not be empty")
        return stripped

    @field_validator("token")
    @classmethod
    def strip_token(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class HarnessProbeResult(BaseModel):
    ok: bool = True
    base_url: str
    models: list[str]


class HarnessActionResult(BaseModel):
    status: str
    output: str = ""


class HarnessLogs(BaseModel):
    lines: list[str]


class HarnessRuntimeState(BaseModel):
    status: str
    capabilities: list[HarnessCapability]
    lifecycle_status: HarnessLifecycleStatus | Literal["internal"]
    managed: bool = True
    last_error: str | None = None
    skills_status: Literal["not_applicable", "pending", "current", "error"] = "not_applicable"

    @computed_field
    @property
    def available_actions(self) -> list[HarnessAction]:
        """Project durable lifecycle and observed runtime into actionable commands."""
        if not self.managed:
            return []
        return [
            action for action in lifecycle_actions(self.lifecycle_status)
            if action in self.capabilities
            and (action != "start" or self.status == "stopped")
            and (action != "stop" or self.status == "running")
        ]


class HarnessTaskBlocker(BaseModel):
    id: UUID
    label: str


class HarnessTaskBlockers(BaseModel):
    paused_tasks: list[HarnessTaskBlocker] = Field(default_factory=lambda: [])
    active_count: int = 0
    active_tasks: list[HarnessTaskBlocker] = Field(default_factory=lambda: [])


__all__ = [
    "HarnessActionResult",
    "HarnessCatalogCreate",
    "HarnessCatalogRead",
    "HarnessCatalogUpdate",
    "HarnessLogs",
    "HarnessProviderRead",
    "HarnessProbe",
    "HarnessProbeResult",
    "HarnessRead",
    "HarnessRuntimeState",
    "HarnessSelectionUpdate",
    "HarnessTaskBlocker",
    "HarnessTaskBlockers",
]
