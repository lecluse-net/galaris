"""Small observer registries for agent-profile and terminal-task events.

This module is deliberately not a runtime lifecycle manager. It only decouples short,
idempotent projections from the services that publish profile or terminal-task changes.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable

from loguru import logger

from .contracts import AgentTask


TerminalTaskObserver = Callable[[AgentTask], None | Awaitable[None]]
AgentProfileObserver = Callable[[int, str], None | Awaitable[None]]
_terminal_observers: dict[str, TerminalTaskObserver] = {}
_profile_observers: dict[str, AgentProfileObserver] = {}


def register_terminal_task_observer(
    name: str, observer: TerminalTaskObserver
) -> None:
    normalized = name.strip()
    if not normalized:
        raise ValueError("A terminal-task observer requires a name.")
    _terminal_observers[normalized] = observer


async def notify_terminal_task(task: AgentTask) -> None:
    for name, observer in sorted(_terminal_observers.items()):
        try:
            value = observer(task)
            if inspect.isawaitable(value):
                await value
        except Exception:
            logger.exception("Terminal-task observer {} failed for task {}", name, task.id)


def unregister_terminal_task_observer(name: str) -> None:
    _terminal_observers.pop(name, None)


def reset_terminal_task_observers() -> None:
    _terminal_observers.clear()


def register_agent_profile_observer(
    name: str, observer: AgentProfileObserver
) -> None:
    normalized = name.strip()
    if not normalized:
        raise ValueError("An agent-profile observer requires a name.")
    _profile_observers[normalized] = observer


async def notify_agent_profile(agent_id: int, action: str = "update") -> None:
    for name, observer in sorted(_profile_observers.items()):
        try:
            value = observer(agent_id, action)
            if inspect.isawaitable(value):
                await value
        except Exception:
            logger.exception(
                "Agent-profile observer {} failed for agent {}",
                name,
                agent_id,
            )


def unregister_agent_profile_observer(name: str) -> None:
    _profile_observers.pop(name, None)


def reset_agent_profile_observers() -> None:
    _profile_observers.clear()


__all__ = [
    "notify_agent_profile",
    "register_agent_profile_observer",
    "reset_agent_profile_observers",
    "notify_terminal_task",
    "register_terminal_task_observer",
    "reset_terminal_task_observers",
    "unregister_terminal_task_observer",
    "unregister_agent_profile_observer",
]
