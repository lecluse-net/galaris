"""Versioned, runtime-independent scope and effect provenance contracts."""
from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ScopeRequirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str = Field(min_length=1, max_length=100)
    instruction: str = Field(min_length=1, max_length=100_000)
    source_reference: str = Field(min_length=1, max_length=2_000)


class ScopeGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    target: str = Field(min_length=1, max_length=2_000)
    capability: str = Field(default="*", min_length=1, max_length=100)
    requirement_key: str = Field(min_length=1, max_length=100)
    source_reference: str = Field(min_length=1, max_length=2_000)


class ExecutionScopeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["galaris.execution-scope/v1"] = "galaris.execution-scope/v1"
    revision: int = Field(default=1, ge=1)
    source_task_id: UUID
    delivery_owner_task_id: UUID
    requirements: tuple[ScopeRequirement, ...] = Field(min_length=1, max_length=100)
    grants: tuple[ScopeGrant, ...] = Field(default=(), max_length=1_000)


class EffectDescriptorV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["galaris.effect/v1"] = "galaris.effect/v1"
    capability: str = Field(min_length=1, max_length=100)
    kind: Literal["read", "create", "mutate", "transport", "delete", "process", "execute"]
    target_arguments: tuple[str, ...] = ()
    target_prefix: str = ""
    reversible: bool = False
    visibility: Literal["private", "shared", "external", "unknown"] = "unknown"
    idempotence: Literal["read_only", "idempotent", "non_idempotent"] = "non_idempotent"
    receipt: Literal["resource", "message", "process", "unknown"] = "unknown"
    ordinary_creation_schemes: tuple[str, ...] = ()
    ordinary_creation_prefixes: tuple[str, ...] = Field(default=(), description=(
        "Private creation namespaces; {agent_id} is resolved only from the authenticated actor. "
        "Prefixes must end with / to preserve namespace boundaries."
    ))
    creation_parent_patterns: tuple[str, ...] = Field(default=(), description=(
        "Full-match creation destination patterns with a named parent group. "
        "The exact captured parent must have a sourced grant for this capability."
    ))
    domain_assigned_selection: bool = False


class ScopePreflightV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["galaris.scope-preflight/v1"] = "galaris.scope-preflight/v1"
    operation_id: UUID = Field(default_factory=uuid4)
    scope_revision: int | None = None
    tool_name: str = Field(min_length=1, max_length=200)
    decision: Literal["allow", "allow_and_record", "clarify", "deny"]
    reason: str = Field(min_length=1, max_length=500)
    targets: tuple[str, ...] = Field(default=(), max_length=20)
