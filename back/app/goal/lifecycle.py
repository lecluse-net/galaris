"""Fail-open observers for committed Goal and GoalCycle source changes."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from uuid import UUID

from loguru import logger


GoalObserver = Callable[[UUID, str], None | Awaitable[None]]
_observers: dict[str, GoalObserver] = {}


def register_goal_observer(name: str, observer: GoalObserver) -> None:
    normalized = name.strip()
    if not normalized:
        raise ValueError("A Goal observer requires a name.")
    _observers[normalized] = observer


async def notify_goal(goal_id: UUID, action: str = "update") -> None:
    for name, observer in sorted(_observers.items()):
        try:
            value = observer(goal_id, action)
            if inspect.isawaitable(value):
                await value
        except Exception:
            logger.exception("Goal observer {} failed for Goal {}", name, goal_id)


def unregister_goal_observer(name: str) -> None:
    _observers.pop(name, None)


def reset_goal_observers() -> None:
    _observers.clear()


__all__ = [
    "notify_goal",
    "register_goal_observer",
    "reset_goal_observers",
    "unregister_goal_observer",
]
