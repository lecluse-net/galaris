"""Bounded qualification workload for the Process Python runner."""

import asyncio
from datetime import datetime, timezone
import json
from math import ceil
import os
from pathlib import Path
from statistics import median
from time import perf_counter
from uuid import UUID, uuid4

import pytest

from app.process.engine import ProcessEngineError
from app.process.isolated_code import CodeInvocation, CodeObservation, IsolatedCodeRunner, MontyCodeRunner
from app.process.remote_python import configured_python_runner


_PARALLEL = 4
_SOURCE = 'output = {"checksum": sample * sample + 17}'


async def _stop(runner: IsolatedCodeRunner, identifier: UUID) -> None:
    async with asyncio.timeout(60):
        while True:
            try:
                if (await runner.cancel(identifier)).stopped:
                    return
            except ProcessEngineError as error:
                if not error.retryable:
                    raise
            await asyncio.sleep(0.2)


async def _campaign(runner: IsolatedCodeRunner, *, jobs_per_worker: int) -> dict[str, int | float]:
    pending: set[UUID] = set()
    latencies: list[float] = []

    async def worker(index: int) -> None:
        for sample in range(index * jobs_per_worker, (index + 1) * jobs_per_worker):
            invocation = CodeInvocation(uuid4(), uuid4(), uuid4(), 1, "activity", _SOURCE, {"sample": sample})
            pending.add(invocation.id)  # A lost submit response may hide an admitted sandbox.
            started = perf_counter()
            async with asyncio.timeout(45):
                result = await runner.submit(invocation)
                while not result.stopped:
                    assert result.status in {"queued", "running"}, result.status
                    assert result.capability_call is None
                    await asyncio.sleep(0.2)
                    result = await runner.observe(invocation.id)
            pending.remove(invocation.id)
            assert result.status == "success", result.status
            assert result.result["output"] == {"checksum": sample * sample + 17}
            latencies.append(perf_counter() - started)

    started = perf_counter()
    try:
        async with asyncio.timeout(600), asyncio.TaskGroup() as workers:
            for index in range(_PARALLEL):
                workers.create_task(worker(index))
    except BaseException as error:
        cleanup = await asyncio.gather(*(_stop(runner, identifier) for identifier in pending), return_exceptions=True)
        unconfirmed = sum(isinstance(item, BaseException) for item in cleanup)
        if unconfirmed:
            error.add_note(f"Could not confirm cleanup for {unconfirmed} qualification invocations")
        raise

    elapsed = perf_counter() - started
    return {
        "completed": len(latencies),
        "concurrency": _PARALLEL,
        "elapsed_seconds": round(elapsed, 3),
        "runs_per_minute": round(len(latencies) * 60 / elapsed, 2),
        "median_seconds": round(median(latencies), 3),
        "p95_seconds": round(sorted(latencies)[ceil(0.95 * len(latencies)) - 1], 3),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("dedicated", [
    pytest.param(False, id="local-monty"),
    pytest.param(True, id="dedicated-tls", marks=pytest.mark.skipif(
        os.environ.get("QUALIFY_PROCESS_PYTHON") != "1", reason="requires a dedicated TLS runner")),
])
async def test_python_runner_endurance(dedicated: bool) -> None:
    runner = configured_python_runner() if dedicated else MontyCodeRunner()
    assert runner is not None, "Dedicated qualification requires HTTPS URL and token"
    report = await _campaign(runner, jobs_per_worker=28 if dedicated else 2)
    assert report["completed"] == (112 if dedicated else 8)
    if dedicated:
        directory = Path(__file__).resolve().parents[4] / "artifacts" / "process-python-qualification"
        directory.mkdir(parents=True, exist_ok=True)
        completed_at = datetime.now(timezone.utc)
        report_path = directory / f"endurance-{completed_at:%Y%m%dT%H%M%S%fZ}.json"
        report_path.write_text(json.dumps({"completed_at": completed_at.isoformat(), **report}, indent=2) + "\n",
            encoding="utf-8")


@pytest.mark.asyncio
async def test_python_runner_endurance_cleans_up_after_lost_submit_response() -> None:
    class LostResponseRunner(MontyCodeRunner):
        def __init__(self) -> None:
            super().__init__()
            self.admitted: set[UUID] = set()

        async def submit(self, invocation: CodeInvocation) -> CodeObservation:
            result = await super().submit(invocation)
            self.admitted.add(invocation.id)
            if invocation.values["sample"] == 0:
                raise ProcessEngineError("remote_python_unreachable", "Synthetic lost submit response", retryable=True)
            return result

    runner = LostResponseRunner()
    with pytest.RaisesGroup(pytest.RaisesExc(ProcessEngineError, match="Synthetic lost submit response")):
        await _campaign(runner, jobs_per_worker=2)
    assert runner.admitted
    for identifier in runner.admitted:
        assert (await runner.observe(identifier)).stopped
