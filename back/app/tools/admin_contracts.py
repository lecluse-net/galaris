"""Transport-independent administration authority and bounded input contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .schemas import ToolCreate, ToolMcpTestRequest, ToolUpdate

HUMAN_ONLY_TOOL_CODES = frozenset({
    "tool_admin", "agent_admin", "galaris_admin", "process_admin", "lab",
    "goal_management", "skill_management", "console",
})


class AdministrationError(ValueError):
    def __init__(self, kind: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.details = details


@dataclass(frozen=True)
class AdministrationContext:
    """Constructed by the authenticated entry point, never accepted as model input."""

    agent_id: int | None = None
    function_name: str = ""
    managed_agent_ids: frozenset[int] | None = None

    async def require(self) -> None:
        if self.agent_id is not None:
            from app.connection.facade import has_active_tool_function

            if not await has_active_tool_function(self.agent_id, "tool_admin", self.function_name):
                raise AdministrationError("access_denied", "The exact live ToolAdmin function grant is required.")

    def require_target(self, code: str, *, can_disable: bool, definition: bool = False,
                       executable: bool = False) -> None:
        from .assertions import tool_can_edit

        if not can_disable or (definition and not tool_can_edit(code)):
            raise AdministrationError("access_denied", "This Tool is managed by the software.")
        if self.agent_id is not None and (code in HUMAN_ONLY_TOOL_CODES or executable):
            raise AdministrationError("access_denied", "This capability can only be delegated by a human.")

    def require_agent(self, agent_id: int) -> None:
        if self.managed_agent_ids is not None and agent_id not in self.managed_agent_ids:
            raise AdministrationError("not_found", "Agent not found in the management scope.")


class PageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class AdminToolCreate(ToolCreate):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=255)


class AdminToolUpdate(ToolUpdate):
    model_config = ConfigDict(extra="forbid")


class CandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent_id: int = Field(gt=0)
    definition: AdminToolCreate
    params: dict[str, str | None] = Field(default_factory=dict)


class CandidatePreview(ToolMcpTestRequest):
    """Secret-free model input; human candidates use CandidateRequest instead."""

    model_config = ConfigDict(extra="forbid")


class ParamWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str | None = None
    clear: bool = False
    forced: bool = False
    secret_reference: str | None = None


FunctionState = Literal["default", "enabled", "disabled", "ask"]
