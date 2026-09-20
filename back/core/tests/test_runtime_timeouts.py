import asyncio

import pytest

from core.runtime import RuntimeComponent, RuntimeSupervisor


@pytest.mark.asyncio
async def test_uncooperative_optional_start_does_not_block_other_roots_or_duplicate():
    released = asyncio.Event()
    starts = 0
    healthy = False

    async def blocked():
        nonlocal starts
        starts += 1
        while not released.is_set():
            try:
                await released.wait()
            except asyncio.CancelledError:
                pass

    async def noop():
        pass

    async def working():
        nonlocal healthy
        healthy = True

    supervisor = RuntimeSupervisor(monitor_interval=0.005, jitter=lambda delay: delay)
    supervisor.configure([
        RuntimeComponent("optional", blocked, noop, lambda: False, critical=False,
                         start_timeout=0.01, stop_timeout=0.01, restart_initial_delay=0),
        RuntimeComponent("healthy", working, noop, lambda: healthy),
    ])
    try:
        await asyncio.wait_for(supervisor.start(), 0.5)
        await asyncio.sleep(0.03)
        assert healthy and starts == 1
        assert (await supervisor.readiness_report())["status"] == "degraded"
        await asyncio.wait_for(supervisor.stop(), 0.5)
    finally:
        released.set()
        await asyncio.sleep(0.02)
        await supervisor.stop()


@pytest.mark.asyncio
async def test_optional_stop_timeout_does_not_block_other_stops():
    stopped = asyncio.Event()

    async def noop():
        pass

    async def hang():
        await asyncio.Event().wait()

    async def stop():
        stopped.set()

    supervisor = RuntimeSupervisor()
    supervisor.configure([
        RuntimeComponent("healthy", noop, stop, lambda: True),
        RuntimeComponent("optional", noop, hang, lambda: True, critical=False, stop_timeout=0.01),
    ])
    await supervisor.start()
    await asyncio.wait_for(supervisor.stop(), 0.5)
    assert stopped.is_set()
