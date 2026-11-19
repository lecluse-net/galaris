"""Execution-scoped declarations and messages for the Python capability broker."""

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

CapabilityName = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")]
OperationName = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_.-]{1,128}$")]


class Capability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["mcp", "rest"]
    operation: OperationName


capabilities: TypeAdapter[dict[str, Capability]] = TypeAdapter(
    Annotated[dict[CapabilityName, Capability], Field(max_length=16)]
)


class CapabilityCall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    handle: UUID
    arguments: dict[str, Any]
