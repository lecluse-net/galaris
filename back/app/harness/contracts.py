"""Public supervision contract for externally managed agent harnesses."""

from typing import Literal, Protocol

from app.agent import Agent


type HarnessAction = Literal["start", "stop", "restart", "update"]
type HarnessCapability = Literal[
    "status",
    "start",
    "stop",
    "restart",
    "update",
    "logs",
    "refresh",
]


class HarnessSupervisor(Protocol):
    """Driver contribution consumed exclusively through the harness facade."""

    driver_code: str

    def capabilities(self, agent: Agent) -> frozenset[HarnessCapability]: ...

    async def status(self, agent: Agent) -> str: ...

    async def run_action(self, agent: Agent, action: HarnessAction) -> str: ...

    async def logs(self, agent: Agent, lines: int) -> list[str]: ...

    async def refresh(self, agent: Agent) -> None: ...


__all__ = [
    "HarnessAction",
    "HarnessCapability",
    "HarnessSupervisor",
]
