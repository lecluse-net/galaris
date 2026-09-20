from __future__ import annotations

from types import SimpleNamespace
from dataclasses import replace
from uuid import uuid4

import pytest

from core.params.runtime_settings import runtime_settings
from app.agent.contracts import (
    ExecutionEffort,
    UnknownAgentDriverError,
)
from app.agent.registry import (
    driver_status,
    get_driver_spec,
    pipeline_policy_for,
    require_available_driver,
    should_use_briefing,
)
from app.agent.workflow import route_to_driver_pipeline
from app.task.models import Task, TaskStatus


@pytest.mark.parametrize("current_decision, expected", [
    (False, TaskStatus.BRIEFING), (True, TaskStatus.DISPATCH),
])
def test_explicit_execution_choice_supersedes_legacy_automatic_briefing(monkeypatch, current_decision, expected):
    from app.agent import registry
    from app.agent.contracts import DispatchDecision, DispatchResult

    monkeypatch.setattr(registry, "should_use_briefing", lambda *_: True)
    task = Task(id=uuid4(), label="Resume", status=TaskStatus.CREATE, effort="high")
    task.set_dispatch_result(DispatchResult(
        prompt="", decision=DispatchDecision(route="EXEC", effort="high"),
        pipeline_policy={"dispatch_choices": [{"route": "EXEC", "effort": "high"}]} if current_decision else {},
    ))

    route_to_driver_pipeline(task)

    assert task.status == expected


def test_driver_policies_are_explicit_and_immutable() -> None:
    internal_spec = get_driver_spec("internal")
    hermes_spec = get_driver_spec("hermes")
    internal = pipeline_policy_for("internal")
    hermes = pipeline_policy_for("hermes")

    assert internal.use_planner is True
    assert internal.use_briefing is False
    assert internal.briefing_efforts == frozenset()
    assert hermes.use_planner is False
    assert hermes.use_briefing is False
    assert hermes.briefing_efforts == frozenset()
    assert should_use_briefing("internal", "standard") is False
    assert should_use_briefing("internal", "high") is False
    assert should_use_briefing("hermes", "high") is False
    assert internal_spec.execution_strategy_for("standard") == "direct"
    assert internal_spec.execution_strategy_for("high") == "direct"
    assert hermes_spec.execution_strategy_for("standard") == "direct"
    assert hermes_spec.execution_strategy_for("high") == "direct"
    assert "checkpoints" in internal_spec.execution_capabilities
    assert "normalized_usage" in hermes_spec.execution_capabilities
    assert "update" in hermes_spec.management_capabilities
    assert "update" not in internal_spec.management_capabilities


def test_unknown_driver_never_falls_back_to_internal() -> None:
    with pytest.raises(UnknownAgentDriverError, match="Unknown"):
        get_driver_spec("typo")


def test_internal_and_hermes_drivers_are_available_without_a_global_switch() -> None:
    internal_status = driver_status("internal")
    assert internal_status.enabled is True
    assert internal_status.configured is True
    assert internal_status.available is True
    assert internal_status.reason is None

    status = driver_status("hermes")
    assert status.enabled is True
    assert status.configured is True
    assert status.available is True
    assert status.reason is None
    assert require_available_driver("hermes").code == "hermes"


def test_none_keeps_only_the_legacy_internal_default() -> None:
    assert get_driver_spec(None).code == "internal"


@pytest.mark.parametrize("code", ["", " ", "missing-driver"])
def test_explicit_invalid_driver_never_selects_a_default(code):
    with pytest.raises(UnknownAgentDriverError):
        get_driver_spec(code)


def test_declared_cancellation_requires_an_implementation(monkeypatch):
    from app.agent import registry

    spec = get_driver_spec("internal")
    invalid = SimpleNamespace(spec=spec, run=lambda: None, stream=lambda: None)
    monkeypatch.setattr(registry, "_resolve_entrypoint", lambda _: lambda: invalid)
    with pytest.raises(TypeError, match="cancel"):
        registry.create_driver(spec)


def test_descriptor_cannot_bypass_driver_availability(monkeypatch):
    from app.agent import registry
    from app.agent.contracts import DisabledAgentDriverError

    spec = replace(get_driver_spec("internal"), enabled_setting="TEST_DISABLED_HARNESS")
    monkeypatch.setattr(registry, "runtime_settings", SimpleNamespace(TEST_DISABLED_HARNESS=False))
    with pytest.raises(DisabledAgentDriverError):
        registry.create_driver(spec)


def test_driver_discovery_can_retry_a_failed_contribution(monkeypatch):
    from app.agent import registry
    import modules

    monkeypatch.setattr(registry, "_driver_contributions_loaded", False)
    monkeypatch.setattr(modules, "AGENT_DRIVER_MODULES", ["fixture.contribution"])
    calls = []

    def import_contribution(name):
        calls.append(name)
        if len(calls) == 1:
            raise ImportError("transient contribution failure")

    monkeypatch.setattr(registry.importlib, "import_module", import_contribution)
    with pytest.raises(ImportError):
        registry.all_driver_specs()
    registry.all_driver_specs()
    assert calls == ["fixture.contribution", "fixture.contribution"]


@pytest.mark.parametrize("streaming,cancellation", [(False, False), (False, True), (True, False), (True, True)])
def test_capability_advertisement_agrees_with_dispatch_flags(streaming, cancellation):
    spec = replace(get_driver_spec("internal"), supports_streaming=streaming, supports_cancellation=cancellation)
    assert ("streaming" in spec.execution_capabilities) is streaming
    assert ("cancellation" in spec.execution_capabilities) is cancellation


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_driver_cannot_disable_terminal_closure_bound(timeout):
    with pytest.raises(ValueError, match="finite and positive"):
        replace(get_driver_spec("internal"), stream_close_timeout_seconds=timeout)


def test_network_driver_does_not_advertise_noop_remote_cancellation():
    assert get_driver_spec("openai_messages").supports_cancellation is False
    assert "cancellation" not in get_driver_spec("openai_messages").execution_capabilities


def test_hermes_driver_has_no_ui_managed_transport_requirements() -> None:
    status = driver_status("hermes")

    assert status.enabled is True
    assert status.configured is True
    assert status.ready is True
    assert status.reason is None


@pytest.mark.parametrize(
    ("driver_code", "effort", "expected"),
    [
        ("internal", "standard", TaskStatus.DISPATCH),
        ("internal", "high", TaskStatus.DISPATCH),
        ("hermes", "standard", TaskStatus.DISPATCH),
        ("hermes", "high", TaskStatus.DISPATCH),
    ],
)
def test_driver_pipeline_matrix_is_applied_before_execution(
    driver_code: str,
    effort: ExecutionEffort,
    expected: TaskStatus,
) -> None:
    task = Task(
        id=uuid4(),
        label="pipeline-policy",
        status=TaskStatus.CREATE,
        effort=effort,
        cost=0.0,
    )
    task.agent = SimpleNamespace(agent_driver=driver_code)

    route_to_driver_pipeline(task)

    assert task.status == expected
