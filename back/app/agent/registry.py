"""Explicit, strict registry of agent drivers."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from functools import lru_cache
from typing import Any, cast

from core.params import runtime_settings

from .contracts import (
    AgentDriverSpec,
    AgentDriver,
    DisabledAgentDriverError,
    DriverPipelinePolicy,
    DriverStatus,
    ExecutionEffort,
    ToolExposureProfile,
    UnknownAgentDriverError,
)


INTERNAL_HARNESS = AgentDriverSpec(
    code="internal",
    label_key="agent.harnessInternal",
    factory_path="app.harness.driver:create_driver",
    tool_profile=ToolExposureProfile(
        voice_calling=True,
        file_tools=True,
        console_execution=True,
    ),
    pipeline_policy=DriverPipelinePolicy(
        use_planner=True,
        execution_efforts=frozenset({"standard", "high"}),
        uses_llm_calls=True,
        # Retain the briefing mechanism and its historical results while production
        # execution evaluates whether standalone Task objectives make it redundant.
        use_briefing=False,
        briefing_efforts=frozenset(),
    ),
    supports_cancellation=True,
    max_parallel_tasks=None,
    transport="embedded",
    checkpoint_policy_path="app.harness.checkpoint_policy:create_policy",
    execution_capabilities=frozenset(
        {
            "streaming",
            "cancellation",
            "local_interrupt",
            "checkpoints",
            "semantic_events",
            "structured_tool_events",
            "normalized_usage",
            "taskless_runs",
        }
    ),
)

_DRIVER_SPECS: dict[str, AgentDriverSpec] = {
    INTERNAL_HARNESS.code: INTERNAL_HARNESS,
}
_driver_contributions_loaded = False


def register_driver_spec(spec: AgentDriverSpec) -> None:
    """Register one runtime contribution without teaching ``app.agent`` its identity."""

    code = spec.code.strip().lower()
    if not code or code != spec.code:
        raise ValueError(f"Agent driver codes must be normalized: {spec.code!r}.")
    existing = _DRIVER_SPECS.get(code)
    if existing is not None and existing != spec:
        raise ValueError(f"Agent driver {code!r} is already registered.")
    _DRIVER_SPECS[code] = spec


def _load_driver_contributions() -> None:
    """Discover optional ``agent_driver`` contributions at the composition boundary."""

    global _driver_contributions_loaded
    if _driver_contributions_loaded:
        return
    _driver_contributions_loaded = True

    from modules import AGENT_DRIVER_MODULES

    try:
        for contribution_name in AGENT_DRIVER_MODULES:
            importlib.import_module(contribution_name)
    except BaseException:
        _driver_contributions_loaded = False
        raise


def all_driver_specs() -> tuple[AgentDriverSpec, ...]:
    _load_driver_contributions()
    return tuple(_DRIVER_SPECS.values())


def get_driver_spec(code: str | None) -> AgentDriverSpec:
    """Resolve a code without a silent fallback.

    ``None`` represents only the legacy column default and maps to ``internal``. Any
    unknown string is an explicit configuration error.
    """
    normalized = ("internal" if code is None else code).strip().lower()
    _load_driver_contributions()
    try:
        return _DRIVER_SPECS[normalized]
    except KeyError as exc:
        raise UnknownAgentDriverError(normalized) from exc


def driver_status(spec_or_code: AgentDriverSpec | str | None) -> DriverStatus:
    spec = (
        spec_or_code
        if isinstance(spec_or_code, AgentDriverSpec)
        else get_driver_spec(spec_or_code)
    )
    enabled = (
        True
        if spec.enabled_setting is None
        else bool(getattr(runtime_settings, spec.enabled_setting, False))
    )
    missing_settings = tuple(
        name
        for name in spec.required_settings
        if not str(getattr(runtime_settings, name, "") or "").strip()
    )
    configured = enabled and not missing_settings
    reason: str | None = None
    if not enabled:
        reason = f"{spec.enabled_setting}=false"
    elif missing_settings:
        reason = "missing settings: " + ", ".join(missing_settings)
    return DriverStatus(
        code=spec.code,
        declared=True,
        enabled=enabled,
        configured=configured,
        ready=configured,
        reason=reason,
    )


def all_driver_statuses() -> tuple[DriverStatus, ...]:
    return tuple(driver_status(spec) for spec in all_driver_specs())


def require_available_driver(code: str | None) -> AgentDriverSpec:
    spec = get_driver_spec(code)
    status = driver_status(spec)
    if not status.available:
        raise DisabledAgentDriverError(spec.code, status.reason)
    return spec


def pipeline_policy_for(code: str | None) -> DriverPipelinePolicy:
    return get_driver_spec(code).pipeline_policy


def should_use_briefing(code: str | None, effort: str) -> bool:
    normalized: ExecutionEffort = "high" if effort == "high" else "standard"
    return pipeline_policy_for(code).allows_briefing(normalized)


def tool_profile_for_runtime(runtime: str) -> ToolExposureProfile:
    return get_driver_spec(runtime).tool_profile


@lru_cache(maxsize=None)
def _resolve_entrypoint(path: str) -> Callable[..., Any]:
    module_name, separator, function_name = path.partition(":")
    if not separator or not module_name or not function_name:
        raise RuntimeError(f"Invalid driver entry point: {path!r}.")
    module = importlib.import_module(module_name)
    entrypoint = getattr(module, function_name)
    if not callable(entrypoint):
        raise TypeError(f"Driver entry point is not callable: {path!r}.")
    return entrypoint


def resolve_driver_factory(spec_or_code: AgentDriverSpec | str | None) -> Callable[..., Any]:
    spec = (
        spec_or_code
        if isinstance(spec_or_code, AgentDriverSpec)
        else require_available_driver(spec_or_code)
    )
    status = driver_status(spec)
    if not status.available:
        raise DisabledAgentDriverError(spec.code, status.reason)
    return _resolve_entrypoint(spec.factory_path)


def resolve_checkpoint_factory(path: str) -> Callable[..., Any]:
    """Composition-only entry point for a driver's optional opaque checkpoint policy."""
    return _resolve_entrypoint(path)


def create_driver(spec_or_code: AgentDriverSpec | str | None) -> AgentDriver:
    """Build a declared, available driver through its single factory."""
    spec = (
        spec_or_code
        if isinstance(spec_or_code, AgentDriverSpec)
        else require_available_driver(spec_or_code)
    )
    driver = resolve_driver_factory(spec)()
    actual_spec = getattr(driver, "spec", None)
    if actual_spec != spec:
        raise TypeError(
            f"The factory for driver {spec.code!r} returned an incompatible object."
        )
    if not callable(getattr(driver, "run", None)):
        raise TypeError(f"Driver {spec.code!r} does not implement run().")
    if spec.supports_streaming and not callable(getattr(driver, "stream", None)):
        raise TypeError(f"Driver {spec.code!r} does not implement stream().")
    if spec.supports_cancellation and not callable(getattr(driver, "cancel", None)):
        raise TypeError(f"Driver {spec.code!r} does not implement cancel().")
    return cast(AgentDriver, driver)
