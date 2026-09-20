"""Live application of database-backed task runtime settings."""

from __future__ import annotations

from core.params import params_service

from . import scheduler


async def on_parameter_change(name: str, _value: str | None) -> None:
    """Wake the scheduler when a task limit changes.

    The parameter service has already applied the validated typed value to the
    runtime-parameter singleton. Consumers read it at action boundaries; waking
    here makes a concurrency change effective without waiting for polling.
    """
    if name.startswith("TASK_"):
        scheduler.wake()


def register_runtime_settings() -> None:
    """Register the task-domain reaction to runtime parameter changes."""
    params_service.register_change_listener(on_parameter_change)
