"""Typed, bounded AgentAdmin inputs; explicit nulls retain their meaning."""

from typing import Annotated

from pydantic import ConfigDict, Field, model_validator

from .schemas import AgentCreate, AgentUpdate

PageLimit = Annotated[int, Field(ge=1, le=500)]
PageOffset = Annotated[int, Field(ge=0)]


class AdminAgentCreate(AgentCreate):
    model_config = ConfigDict(extra="forbid")
    @model_validator(mode="after")
    def require_manager(self) -> "AdminAgentCreate":
        if self.user_id is None or self.user_id <= 0:
            raise ValueError("An explicit human manager is required")
        return self


class AdminAgentUpdate(AgentUpdate):
    model_config = ConfigDict(extra="forbid")
