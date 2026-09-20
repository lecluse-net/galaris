import asyncio
from unittest.mock import AsyncMock

import pytest

from core.runtime import RuntimeComponent, RuntimeProbe, RuntimeSupervisor


@pytest.mark.parametrize("options", [{"name": " "}, {"start_timeout": 0}, {"stop_timeout": -1},
    {"restart_initial_delay": -1}, {"restart_initial_delay": 2, "restart_max_delay": 1}])
def test_invalid_component_configuration_is_rejected_before_start(options):
    start = AsyncMock()
    with pytest.raises(ValueError):
        RuntimeComponent(**{"name": "worker", "start": start, "stop": AsyncMock(), "is_running": lambda: True, **options})
    start.assert_not_called()


@pytest.mark.parametrize("options", [{"name": " "}, {"timeout": 0}])
def test_invalid_probe_configuration_is_rejected(options):
    with pytest.raises(ValueError):
        RuntimeProbe(**{"name": "database", "check": AsyncMock(), **options})


@pytest.mark.parametrize("options", [{"monitor_interval": 0}, {"stable_after": -1}])
def test_invalid_monitor_timing_is_rejected(options):
    with pytest.raises(ValueError):
        RuntimeSupervisor(**options)


@pytest.mark.asyncio
async def test_duplicate_or_live_registration_cannot_drop_a_running_service():
    start, stop = AsyncMock(), AsyncMock()
    worker = RuntimeComponent("worker", start, stop, lambda: True)
    supervisor = RuntimeSupervisor()
    with pytest.raises(ValueError, match="unique"):
        supervisor.configure([worker], probes=[RuntimeProbe("worker", AsyncMock())])
    supervisor.configure([worker])
    await supervisor.start()
    try:
        with pytest.raises(RuntimeError, match="running"):
            supervisor.configure([])
        assert (await supervisor.readiness_report())["status"] == "ready"
    finally:
        await supervisor.stop()
    start.assert_awaited_once()
    stop.assert_awaited_once()
    await supervisor.stop()
    stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_stop_does_not_abandon_other_services():
    stopped = AsyncMock()
    supervisor = RuntimeSupervisor()
    supervisor.configure([
        RuntimeComponent("healthy", AsyncMock(), stopped, lambda: True),
        RuntimeComponent("broken", AsyncMock(), AsyncMock(side_effect=RuntimeError("stop failed")), lambda: True),
    ])
    await supervisor.start()
    await supervisor.stop()
    stopped.assert_awaited_once()
    assert not supervisor.started
    with pytest.raises(RuntimeError, match="pending"):
        supervisor.configure([])


@pytest.mark.asyncio
async def test_faulty_optional_probe_does_not_break_health_or_monitoring():
    def broken():
        raise RuntimeError("credential=must-not-be-exposed")
    supervisor = RuntimeSupervisor(monitor_interval=0.005)
    supervisor.configure([RuntimeComponent("optional", AsyncMock(), AsyncMock(), broken, critical=False)],
                         probes=[RuntimeProbe("dependency", AsyncMock(side_effect=ValueError("secret")), critical=False)])
    await supervisor.start()
    try:
        await asyncio.sleep(0.015)
        report = await supervisor.readiness_report()
        assert report["status"] == "degraded"
        assert report["checks"]["runtime_supervisor"]["status"] == "ok"
        assert "secret" not in str(report) and "credential" not in str(report)
    finally:
        await supervisor.stop()


@pytest.mark.asyncio
async def test_cancelling_start_cleans_up_services_already_started():
    entered = asyncio.Event()
    stopped = AsyncMock()
    async def blocked():
        entered.set()
        await asyncio.Event().wait()
    supervisor = RuntimeSupervisor()
    supervisor.configure([RuntimeComponent("first", AsyncMock(), stopped, lambda: True),
                          RuntimeComponent("blocked", blocked, AsyncMock(), lambda: False)])
    operation = asyncio.create_task(supervisor.start())
    await entered.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert not supervisor.started
    stopped.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelling_readiness_cancels_the_dependency_check():
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def probe():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    supervisor = RuntimeSupervisor()
    supervisor.configure([], probes=[RuntimeProbe("database", probe)])
    operation = asyncio.create_task(supervisor.readiness_report())
    await entered.wait()
    operation.cancel()
    with pytest.raises(asyncio.CancelledError):
        await operation
    assert cancelled.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_fault", ["error", "timeout"])
async def test_failed_cleanup_must_finish_before_a_worker_can_restart(cleanup_fault):
    running = False
    starts = 0
    stops = 0
    recovered = asyncio.Event()

    async def start():
        nonlocal running, starts
        starts += 1
        running = True
        if starts == 2:
            assert stops == 2
            recovered.set()

    async def stop():
        nonlocal running, stops
        stops += 1
        if stops == 1:
            if cleanup_fault == "error":
                raise RuntimeError("Connection cleanup interrupted")
            await asyncio.Event().wait()
        running = False

    supervisor = RuntimeSupervisor(monitor_interval=0.005, stable_after=0, jitter=lambda delay: delay)
    supervisor.configure([RuntimeComponent("worker", start, stop, lambda: running,
        stop_timeout=0.01, restart_initial_delay=0.005, restart_max_delay=0.01)])
    await supervisor.start()
    try:
        running = False
        await asyncio.wait_for(recovered.wait(), 1)
        await asyncio.sleep(0.02)
        report = await supervisor.readiness_report()
        assert starts == 2 and report["status"] == "ready"
        assert report["checks"]["worker"]["restarts"] == 1
    finally:
        await supervisor.stop()
    assert not running


@pytest.mark.asyncio
async def test_component_cancelling_its_own_start_is_cleaned_before_recovery():
    events = []
    recovered = asyncio.Event()
    running = False

    async def start():
        nonlocal running
        events.append("start")
        if events == ["start"]:
            raise asyncio.CancelledError
        running = True
        recovered.set()

    async def stop():
        nonlocal running
        events.append("stop")
        running = False

    supervisor = RuntimeSupervisor(monitor_interval=0.005, jitter=lambda delay: delay)
    supervisor.configure([RuntimeComponent("worker", start, stop, lambda: running, restart_initial_delay=0)])
    await supervisor.start()
    try:
        await asyncio.wait_for(recovered.wait(), 1)
        assert events == ["start", "stop", "start"]
        assert (await supervisor.readiness_report())["status"] == "ready"
    finally:
        await supervisor.stop()


@pytest.mark.asyncio
async def test_supervisor_starts_once_and_stops_in_reverse_order() -> None:
    events: list[str] = []
    running = {"first": False, "second": False}

    def component(name: str) -> RuntimeComponent:
        async def start() -> None:
            events.append(f"start:{name}")
            running[name] = True

        async def stop() -> None:
            events.append(f"stop:{name}")
            running[name] = False

        return RuntimeComponent(
            name=name,
            start=start,
            stop=stop,
            is_running=lambda: running[name],
        )

    supervisor = RuntimeSupervisor(monitor_interval=1.0, jitter=lambda delay: delay)
    supervisor.configure((component("first"), component("second")))

    await supervisor.start()
    await supervisor.start()
    assert events == ["start:first", "start:second"]
    assert (await supervisor.readiness_report())["status"] == "ready"

    await supervisor.stop()
    assert events == [
        "start:first",
        "start:second",
        "stop:second",
        "stop:first",
    ]


@pytest.mark.asyncio
async def test_supervisor_restarts_a_stopped_root_without_duplicates() -> None:
    running = False
    starts = 0
    stops = 0

    async def start() -> None:
        nonlocal running, starts
        starts += 1
        running = True

    async def stop() -> None:
        nonlocal running, stops
        stops += 1
        running = False

    supervisor = RuntimeSupervisor(
        monitor_interval=0.005,
        stable_after=1.0,
        jitter=lambda delay: delay,
    )
    supervisor.configure(
        (
            RuntimeComponent(
                name="worker",
                start=start,
                stop=stop,
                is_running=lambda: running,
                restart_initial_delay=0.005,
                restart_max_delay=0.02,
            ),
        )
    )

    await supervisor.start()
    running = False
    for _ in range(20):
        if starts == 2:
            break
        await asyncio.sleep(0.005)

    assert starts == 2
    assert stops == 1
    await asyncio.sleep(0.02)
    assert starts == 2
    report = await supervisor.readiness_report()
    assert report["checks"]["worker"]["restarts"] == 1

    await supervisor.stop()


@pytest.mark.asyncio
async def test_supervisor_recovers_from_an_initial_start_failure() -> None:
    running = False
    starts = 0

    async def start() -> None:
        nonlocal running, starts
        starts += 1
        if starts == 1:
            raise RuntimeError("temporary startup failure")
        running = True

    async def stop() -> None:
        nonlocal running
        running = False

    supervisor = RuntimeSupervisor(
        monitor_interval=0.005,
        jitter=lambda delay: delay,
    )
    supervisor.configure(
        (
            RuntimeComponent(
                name="worker",
                start=start,
                stop=stop,
                is_running=lambda: running,
                restart_initial_delay=0.005,
                restart_max_delay=0.02,
            ),
        )
    )

    await supervisor.start()
    for _ in range(20):
        if running:
            break
        await asyncio.sleep(0.005)

    assert running is True
    assert starts == 2
    assert (await supervisor.readiness_report())["status"] == "ready"
    await supervisor.stop()


@pytest.mark.asyncio
async def test_optional_failure_degrades_but_critical_failure_blocks_readiness() -> None:
    async def noop() -> None:
        return None

    optional = RuntimeComponent(
        name="optional",
        start=noop,
        stop=noop,
        is_running=lambda: False,
        critical=False,
    )
    supervisor = RuntimeSupervisor(monitor_interval=1.0, jitter=lambda delay: delay)
    supervisor.configure((optional,))
    await supervisor.start()

    assert (await supervisor.readiness_report())["status"] == "degraded"
    await supervisor.stop()

    critical = RuntimeComponent(
        name="critical",
        start=noop,
        stop=noop,
        is_running=lambda: False,
    )
    supervisor.configure((critical,))
    await supervisor.start()

    assert (await supervisor.readiness_report())["status"] == "not_ready"
    await supervisor.stop()


@pytest.mark.asyncio
async def test_readiness_includes_bounded_dependency_probes() -> None:
    async def noop() -> None:
        return None

    async def unavailable() -> bool:
        return False

    supervisor = RuntimeSupervisor(monitor_interval=1.0, jitter=lambda delay: delay)
    supervisor.configure(
        (
            RuntimeComponent(
                name="worker",
                start=noop,
                stop=noop,
                is_running=lambda: True,
            ),
        ),
        probes=(RuntimeProbe(name="database", check=unavailable),),
    )
    await supervisor.start()

    report = await supervisor.readiness_report()

    assert report["status"] == "not_ready"
    assert report["checks"]["database"] == {
        "status": "error",
        "critical": True,
        "restarts": 0,
    }
    await supervisor.stop()


@pytest.mark.asyncio
async def test_readiness_times_out_a_blocked_probe() -> None:
    async def noop() -> None:
        return None

    async def blocked() -> bool:
        await asyncio.Event().wait()
        return True

    supervisor = RuntimeSupervisor(monitor_interval=1.0, jitter=lambda delay: delay)
    supervisor.configure(
        (
            RuntimeComponent(
                name="worker",
                start=noop,
                stop=noop,
                is_running=lambda: True,
            ),
        ),
        probes=(RuntimeProbe(name="database", check=blocked, timeout=0.01),),
    )
    await supervisor.start()

    report = await supervisor.readiness_report()

    assert report["status"] == "not_ready"
    assert report["checks"]["database"]["status"] == "error"
    await supervisor.stop()


@pytest.mark.asyncio
async def test_a_live_but_stalled_monitor_is_not_reported_ready():
    supervisor = RuntimeSupervisor(monitor_interval=1)
    supervisor.configure(())
    await supervisor.start()
    try:
        supervisor._last_monitor_tick -= 60
        report = await supervisor.readiness_report()
        assert report["status"] == "not_ready"
        assert report["monitor_age_seconds"] >= 60
    finally:
        await supervisor.stop()
