"""Public contracts for configurable agent harnesses.

The internal Pydantic AI harness deliberately does not implement these protocols: the
absence of an agent selection chooses it and requires no provisioned runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TYPE_CHECKING
from uuid import UUID
from app.agent.contracts import HarnessCapability as HarnessCapability
from app.agent.contracts import DriverPipelinePolicy

if TYPE_CHECKING:
    from app.agent import Agent


type HarnessLifecycleStatus = Literal[
    "absent",
    "provisioning",
    "ready",
    "deprovisioning",
    "error",
]
type HarnessAction = Literal["start", "stop", "restart", "update", "refresh"]


def lifecycle_actions(status: str) -> tuple[HarnessAction, ...]:
    """Commands admissible for the durable lifecycle, independent of the UI."""
    if status == "ready":
        return ("start", "stop", "restart", "update", "refresh")
    if status in {"absent", "error"}:
        return ("restart", "update")
    return ()


@dataclass(frozen=True)
class HarnessTarget:
    """Secret-free assignment and catalogue target consumed by ``app.agent``."""

    id: UUID
    harness_id: UUID
    agent_id: int
    name: str
    provider_code: str
    driver_code: str
    base_url: str | None
    model: str | None
    revision: int
    status: HarnessLifecycleStatus
    max_parallel_tasks: int | None = 1
    last_error: str | None = None
    capabilities: frozenset[HarnessCapability] = frozenset()
    metadata: dict[str, str | int | float | bool | None] = field(
        default_factory=lambda: {}
    )


@dataclass(frozen=True)
class HarnessCredentials:
    """Private execution coordinates; never serialize this object into a Task."""

    harness_id: UUID
    catalogue_harness_id: UUID
    base_url: str
    model: str
    token: str | None


@dataclass(frozen=True)
class HarnessProvisioningRequest:
    """Bounded provider input joining a catalogue entry to one agent runtime."""

    harness_id: UUID
    catalogue_harness_id: UUID
    agent_id: int
    agent_code: str
    name: str
    base_url: str | None
    model: str | None
    revision: int
    settings: dict[str, Any] = field(default_factory=lambda: {})


@dataclass(frozen=True)
class HarnessProvisioningResult:
    """Coordinates generated or verified by a provider."""

    base_url: str | None = None
    model: str | None = None
    token: str | None = None
    capabilities: frozenset[HarnessCapability] = frozenset({"execute"})
    metadata: dict[str, Any] = field(default_factory=lambda: {})


class HarnessProvider(Protocol):
    """Optional runtime-specific installation and supervision contribution.

    Providers advertising ``mcp`` must inject the per-agent Galaris Streamable HTTP
    endpoint and rotate its hidden system token while provisioning. Providers advertising
    ``memory`` must keep ``app.memory`` authoritative, normally through that MCP endpoint.
    """

    code: str
    driver_code: str
    label: str
    containerized: bool
    enabled_param: str | None
    max_parallel_tasks: int
    pipeline_policy: DriverPipelinePolicy

    def capabilities(self) -> frozenset[HarnessCapability]: ...

    async def provision(
        self,
        agent: "Agent",
        request: HarnessProvisioningRequest,
        *,
        token: str | None,
    ) -> HarnessProvisioningResult: ...

    async def deprovision(
        self,
        agent: "Agent",
        request: HarnessProvisioningRequest,
    ) -> None: ...

    async def status(self, agent: "Agent") -> str: ...

    async def run_action(self, agent: "Agent", action: HarnessAction) -> str: ...

    async def logs(self, agent: "Agent", lines: int) -> list[str]: ...


__all__ = [
    "lifecycle_actions",
    "HarnessAction",
    "HarnessCapability",
    "HarnessCredentials",
    "HarnessLifecycleStatus",
    "HarnessProvider",
    "HarnessProvisioningRequest",
    "HarnessProvisioningResult",
    "HarnessTarget",
]
