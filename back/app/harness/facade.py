"""Generic facade for harness lifecycle and operational supervision."""

from __future__ import annotations

import importlib
from typing import cast

from app.agent import Agent

from .contracts import HarnessAction, HarnessCapability, HarnessSupervisor


class HarnessSupervisorNotFoundError(LookupError):
    """No runtime-supervision contribution exists for an agent driver."""


class UnsupportedHarnessCapabilityError(RuntimeError):
    """The selected runtime supervisor does not implement an operation."""


_SUPERVISORS: dict[str, HarnessSupervisor] = {}
_contributions_loaded = False


def register_harness_supervisor(supervisor: HarnessSupervisor) -> None:
    """Register one driver-owned implementation behind the generic facade."""

    driver_code = supervisor.driver_code.strip().lower()
    if not driver_code or driver_code != supervisor.driver_code:
        raise ValueError(
            f"Harness supervisor driver codes must be normalized: {supervisor.driver_code!r}."
        )
    existing = _SUPERVISORS.get(driver_code)
    if existing is not None and existing is not supervisor:
        raise ValueError(f"Harness supervisor {driver_code!r} is already registered.")
    _SUPERVISORS[driver_code] = supervisor


def _load_contributions() -> None:
    global _contributions_loaded
    if _contributions_loaded:
        return
    _contributions_loaded = True

    from modules import HARNESS_SUPERVISOR_MODULES

    for module_name in HARNESS_SUPERVISOR_MODULES:
        module = importlib.import_module(module_name)
        contribution = getattr(module, "supervisor", None)
        if contribution is None:
            raise RuntimeError(
                f"Harness supervisor contribution {module_name!r} does not expose 'supervisor'."
            )
        register_harness_supervisor(cast(HarnessSupervisor, contribution))


def supervisor_for(agent: Agent) -> HarnessSupervisor:
    """Resolve the supervisor contributed by the agent's selected driver."""

    _load_contributions()
    driver_code = str(agent.agent_driver or "internal").strip().lower()
    try:
        return _SUPERVISORS[driver_code]
    except KeyError as exc:
        raise HarnessSupervisorNotFoundError(driver_code) from exc


def capabilities(agent: Agent) -> frozenset[HarnessCapability]:
    return supervisor_for(agent).capabilities(agent)


async def status(agent: Agent) -> str:
    supervisor = supervisor_for(agent)
    _require_capability(supervisor, agent, "status")
    return await supervisor.status(agent)


async def run_action(agent: Agent, action: HarnessAction) -> str:
    supervisor = supervisor_for(agent)
    _require_capability(supervisor, agent, action)
    return await supervisor.run_action(agent, action)


async def logs(agent: Agent, lines: int) -> list[str]:
    supervisor = supervisor_for(agent)
    _require_capability(supervisor, agent, "logs")
    return await supervisor.logs(agent, lines)


async def refresh(agent: Agent) -> None:
    supervisor = supervisor_for(agent)
    _require_capability(supervisor, agent, "refresh")
    await supervisor.refresh(agent)


def _require_capability(
    supervisor: HarnessSupervisor,
    agent: Agent,
    capability: HarnessCapability,
) -> None:
    if capability not in supervisor.capabilities(agent):
        raise UnsupportedHarnessCapabilityError(
            f"Harness supervisor {supervisor.driver_code!r} does not support {capability!r}."
        )


__all__ = [
    "HarnessSupervisorNotFoundError",
    "UnsupportedHarnessCapabilityError",
    "capabilities",
    "logs",
    "refresh",
    "register_harness_supervisor",
    "run_action",
    "status",
    "supervisor_for",
]
