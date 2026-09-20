"""Pydantic request and response schemas for the Hermes bridge."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.memory import MemorySearchHit


class HermesConfigUpdate(BaseModel):
    """Editable configuration owned exclusively by the Hermes bridge."""

    hermes_dashboard_enabled: bool = False
    hermes_dashboard_port: int | None = None
    hermes_dashboard_username: str | None = None
    hermes_dashboard_password: str | None = None
    hermes_config: str | None = None
    hermes_compose: str | None = None
    hermes_data_env: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "hermes_dashboard_username",
        "hermes_dashboard_password",
        "hermes_config",
        "hermes_compose",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, value: object) -> object:
        return None if value == "" else value


class HermesAgentConfiguration(BaseModel):
    """Agent identity plus its bridge-owned, secret-safe Hermes configuration."""

    id: int
    code: str
    first_name: str
    last_name: str
    hermes_dashboard_enabled: bool = False
    hermes_dashboard_port: int | None = None
    hermes_dashboard_username: str | None = None
    hermes_dashboard_password_configured: bool = False
    hermes_config: str | None = None
    hermes_compose: str | None = None
    hermes_data_env: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(from_attributes=True)


class HermesMemorySearchRequest(BaseModel):
    """Hermes MemoryProvider recall request authenticated by its system token."""

    query: str = Field(default="", max_length=4_000)
    limit: int = Field(default=8, ge=1, le=20)


class HermesMemorySearchResult(BaseModel):
    context: str
    memories: list[MemorySearchHit]


class HermesMemoryRememberRequest(BaseModel):
    """A built-in Hermes memory write applied through Galaris governance."""

    content: str = Field(min_length=1, max_length=2_000_000)
    title: str = Field(default="Hermes memory", min_length=1, max_length=500)
    target: Literal["memory", "user"] = "memory"
    action: Literal["add", "replace"] = "add"
    session_id: str = Field(default="", max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)
