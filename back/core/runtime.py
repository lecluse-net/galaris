"""Supervise long-lived in-memory services without owning domain state.

Durable recovery remains the responsibility of each application domain.  This
module only observes root asyncio services, restarts a stopped root with bounded
backoff, and aggregates non-sensitive readiness checks.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict

from loguru import logger
import logfire


RuntimeStart = Callable[[], Awaitable[None]]
RuntimeStop = Callable[[], Awaitable[None]]
RuntimeRunning = Callable[[], bool]
RuntimeProbeCheck = Callable[[], Awaitable[bool]]
RuntimeCheckStatus = Literal["ok", "error"]
RuntimeOverallStatus = Literal["ready", "degraded", "not_ready"]


class RuntimeCheckPayload(TypedDict):
    """Public, non-sensitive state for one runtime check."""

    status: RuntimeCheckStatus
    critical: bool
    restarts: int


class RuntimeHealthPayload(TypedDict):
    """Aggregated readiness state returned by the HTTP API."""

    status: RuntimeOverallStatus
    checks: dict[str, RuntimeCheckPayload]
    loop_lag_seconds: float
    monitor_age_seconds: float


@dataclass(frozen=True, slots=True)
class RuntimeComponent:
    """A restartable root service registered by the composition layer."""

    name: str
    start: RuntimeStart
    stop: RuntimeStop
    is_running: RuntimeRunning
    critical: bool = True
    restart_initial_delay: float = 1.0
    restart_max_delay: float = 30.0
    start_timeout: float = 10.0
    stop_timeout: float = 5.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("A runtime component requires a name")
        if self.start_timeout <= 0 or self.stop_timeout <= 0:
            raise ValueError("Runtime lifecycle timeouts must be positive")
        if self.restart_initial_delay < 0:
            raise ValueError("restart_initial_delay must be non-negative")
        if self.restart_max_delay < self.restart_initial_delay:
            raise ValueError(
                "restart_max_delay must be greater than or equal to restart_initial_delay"
            )


@dataclass(frozen=True, slots=True)
class RuntimeProbe:
    """A read-only dependency check evaluated when readiness is requested."""

    name: str
    check: RuntimeProbeCheck
    critical: bool = True
    timeout: float = 2.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("A runtime probe requires a name")
        if self.timeout <= 0:
            raise ValueError("A runtime probe timeout must be positive")


@dataclass(slots=True)
class _ComponentState:
    spec: RuntimeComponent
    consecutive_failures: int = 0
    restart_count: int = 0
    next_restart_at: float = 0.0
    stable_since: float | None = None
    pending: asyncio.Task[None] | None = None
    needs_cleanup: bool = False


class RuntimeSupervisor:
    """Start, observe, and recover a small set of root runtime services."""

    def __init__(
        self,
        *,
        monitor_interval: float = 2.0,
        stable_after: float = 60.0,
        jitter: Callable[[float], float] | None = None,
    ) -> None:
        if monitor_interval <= 0:
            raise ValueError("monitor_interval must be positive")
        if stable_after < 0:
            raise ValueError("stable_after must be non-negative")
        self._monitor_interval = monitor_interval
        self._stable_after = stable_after
        self._jitter = jitter or self._default_jitter
        self._states: dict[str, _ComponentState] = {}
        self._probes: tuple[RuntimeProbe, ...] = ()
        self._monitor_task: asyncio.Task[None] | None = None
        self._started = False
        self._stopping = False
        self._last_monitor_tick = time.monotonic()
        self._loop_lag = 0.0
        self._loop_lag_metric = logfire.metric_histogram("runtime_event_loop_lag_seconds", unit="s")

    @staticmethod
    def _default_jitter(delay: float) -> float:
        return random.uniform(delay * 0.8, delay * 1.2)

    def configure(
        self,
        components: Sequence[RuntimeComponent],
        *,
        probes: Sequence[RuntimeProbe] = (),
    ) -> None:
        """Replace registrations while the supervisor is stopped."""
        if self._started:
            raise RuntimeError("Cannot configure a running supervisor")
        if any(state.needs_cleanup or (state.pending is not None and not state.pending.done()) for state in self._states.values()):
            raise RuntimeError("Cannot discard a component whose lifecycle is still pending")

        names = [component.name for component in components]
        names.extend(probe.name for probe in probes)
        if len(names) != len(set(names)):
            raise ValueError("Runtime component and probe names must be unique")

        self._states = {
            component.name: _ComponentState(spec=component)
            for component in components
        }
        self._probes = tuple(probes)

    @property
    def started(self) -> bool:
        return self._started

    async def start(self) -> None:
        """Start every registered component and the recovery monitor."""
        if self._started:
            return

        self._started = True
        self._stopping = False
        self._last_monitor_tick = time.monotonic()
        try:
            for state in self._states.values():
                await self._try_start(state)
            self._monitor_task = asyncio.create_task(
                self._monitor(), name="runtime-supervisor"
            )
        except asyncio.CancelledError:
            await self.stop()
            raise
        logger.info("Runtime supervisor started components={}", len(self._states))

    async def stop(self) -> None:
        """Stop monitoring, then stop components in reverse startup order."""
        if not self._started and not any(state.needs_cleanup for state in self._states.values()):
            return

        self._stopping = True
        monitor = self._monitor_task
        self._monitor_task = None
        if monitor is not None:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)

        for state in reversed(tuple(self._states.values())):
            try:
                await self._lifecycle(state, stopping=True)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Runtime component failed to stop name={}", state.spec.name
                )
            state.stable_since = None
            state.next_restart_at = 0.0

        self._started = False
        self._stopping = False
        logger.info("Runtime supervisor stopped")

    async def readiness_report(self) -> RuntimeHealthPayload:
        """Return current component and dependency health without error details."""
        checks: dict[str, RuntimeCheckPayload] = {}
        monitor = self._monitor_task
        monitor_age = max(0.0, time.monotonic() - self._last_monitor_tick)
        supervisor_running = (
            self._started
            and not self._stopping
            and monitor is not None
            and not monitor.done()
            and monitor_age <= max(30.0, self._monitor_interval * 3)
        )
        checks["runtime_supervisor"] = {
            "status": "ok" if supervisor_running else "error",
            "critical": True,
            "restarts": 0,
        }

        for name, state in self._states.items():
            checks[name] = {
                "status": "ok" if self._component_is_running(state) else "error",
                "critical": state.spec.critical,
                "restarts": state.restart_count,
            }

        for probe in self._probes:
            healthy = await self._run_probe(probe)
            checks[probe.name] = {
                "status": "ok" if healthy else "error",
                "critical": probe.critical,
                "restarts": 0,
            }

        critical_failure = any(
            check["critical"] and check["status"] == "error"
            for check in checks.values()
        )
        optional_failure = any(
            not check["critical"] and check["status"] == "error"
            for check in checks.values()
        )
        status: RuntimeOverallStatus
        if critical_failure:
            status = "not_ready"
        elif optional_failure:
            status = "degraded"
        else:
            status = "ready"
        return {
            "status": status, "checks": checks,
            "loop_lag_seconds": self._loop_lag, "monitor_age_seconds": monitor_age,
        }

    async def _monitor(self) -> None:
        while True:
            try:
                expected = time.monotonic() + self._monitor_interval
                await asyncio.sleep(self._monitor_interval)
                self._last_monitor_tick = time.monotonic()
                self._loop_lag = max(0.0, self._last_monitor_tick - expected)
                self._loop_lag_metric.record(self._loop_lag)
                await asyncio.gather(*(self._maintain(state) for state in self._states.values()))
            except asyncio.CancelledError:
                raise
            except Exception:
                # A faulty component callback must never terminate the monitor itself.
                logger.exception("Runtime supervisor monitoring iteration failed")

    async def _maintain(self, state: _ComponentState) -> None:
        if state.pending is not None:
            if not state.pending.done():
                return
            state.pending = None
        now = time.monotonic()
        if self._component_is_running(state, log_failure=True):
            if state.stable_since is None:
                state.stable_since = now
            if (
                state.consecutive_failures
                and now - state.stable_since >= self._stable_after
            ):
                state.consecutive_failures = 0
            state.next_restart_at = 0.0
            return

        state.stable_since = None
        if state.next_restart_at <= 0:
            self._schedule_retry(state, now)
            logger.warning(
                "Runtime component stopped name={} retry_in={:.1f}s",
                state.spec.name,
                max(0.0, state.next_restart_at - now),
            )
        if now < state.next_restart_at or self._stopping:
            return

        try:
            if not await self._lifecycle(state, stopping=True):
                self._schedule_retry(state, time.monotonic())
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Runtime component cleanup failed before restart name={}",
                state.spec.name,
            )
            self._schedule_retry(state, time.monotonic())
            return

        state.restart_count += 1
        state.next_restart_at = 0.0
        await self._try_start(state)
        if self._component_is_running(state):
            logger.info(
                "Runtime component restarted name={} restarts={}",
                state.spec.name,
                state.restart_count,
            )

    async def _try_start(self, state: _ComponentState) -> None:
        try:
            if state.needs_cleanup and not await self._lifecycle(state, stopping=True):
                self._schedule_retry(state, time.monotonic())
                return
            if not await self._lifecycle(state, stopping=False):
                self._schedule_retry(state, time.monotonic())
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Runtime component failed to start name={}", state.spec.name)
            self._schedule_retry(state, time.monotonic())
            return

        if self._component_is_running(state, log_failure=True):
            state.stable_since = time.monotonic()
            state.next_restart_at = 0.0
            return

        logger.error(
            "Runtime component start returned without a running root name={}",
            state.spec.name,
        )
        self._schedule_retry(state, time.monotonic())

    def _schedule_retry(self, state: _ComponentState, now: float) -> None:
        state.consecutive_failures += 1
        exponent = min(state.consecutive_failures - 1, 20)
        base_delay = min(
            state.spec.restart_initial_delay * (2**exponent),
            state.spec.restart_max_delay,
        )
        delay = min(
            state.spec.restart_max_delay,
            max(0.0, self._jitter(base_delay)),
        )
        state.next_restart_at = now + delay

    async def _lifecycle(self, state: _ComponentState, *, stopping: bool) -> bool:
        """Timeout without detaching ownership or starting a duplicate component."""
        if state.pending is not None and not state.pending.done():
            state.pending.cancel()
            return False
        state.pending = None
        callback = state.spec.stop if stopping else state.spec.start
        timeout = state.spec.stop_timeout if stopping else state.spec.start_timeout
        async def invoke() -> None:
            await callback()
        pending = asyncio.create_task(invoke(), name=f"runtime:{state.spec.name}:{'stop' if stopping else 'start'}")
        state.pending = pending

        def finished(task: asyncio.Task[None]) -> None:
            if not task.cancelled():
                task.exception()
            if not self._started and not stopping:
                # A start that ignored cancellation may finish after shutdown.
                state.pending = asyncio.create_task(self._late_cleanup(state))

        pending.add_done_callback(finished)
        try:
            done, _ = await asyncio.wait({pending}, timeout=timeout)
        except asyncio.CancelledError:
            state.needs_cleanup = True
            pending.cancel()
            raise
        if not done:
            state.needs_cleanup = True
            pending.cancel()
            logger.warning("Runtime component lifecycle timed out name={} stopping={}", state.spec.name, stopping)
            return False
        state.pending = None
        if pending.cancelled():
            state.needs_cleanup = True
            return False
        try:
            pending.result()
        except BaseException:
            state.needs_cleanup = True
            raise
        state.needs_cleanup = False
        return True

    async def _late_cleanup(self, state: _ComponentState) -> None:
        state.pending = None
        try:
            await self._lifecycle(state, stopping=True)
        except Exception:
            logger.exception("Runtime late cleanup failed name={}", state.spec.name)

    def _component_is_running(
        self,
        state: _ComponentState,
        *,
        log_failure: bool = False,
    ) -> bool:
        if state.needs_cleanup or (state.pending is not None and not state.pending.done()):
            return False
        try:
            return bool(state.spec.is_running())
        except Exception as exc:
            if log_failure:
                logger.warning(
                    "Runtime component probe failed name={} type={}",
                    state.spec.name,
                    type(exc).__name__,
                )
            return False

    @staticmethod
    async def _run_probe(probe: RuntimeProbe) -> bool:
        try:
            async with asyncio.timeout(probe.timeout):
                return bool(await probe.check())
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Runtime readiness probe failed name={} type={}",
                probe.name,
                type(exc).__name__,
            )
            return False


runtime_supervisor = RuntimeSupervisor()


__all__ = [
    "RuntimeComponent",
    "RuntimeHealthPayload",
    "RuntimeProbe",
    "RuntimeSupervisor",
    "runtime_supervisor",
]
