"""First-party Chat application and native provider."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from .provider import InternalMessenger
from .events import register_events
from .storage import reconcile_storage
from .push_service import process_push_deliveries

register_events()


class PeriodicJobRegistrar(Protocol):
    def __call__(
        self,
        name: str,
        callback: Callable[[], Awaitable[object]],
        *,
        interval: float,
    ) -> None: ...


def register_scheduler_jobs(register_periodic_job: PeriodicJobRegistrar) -> None:
    """Register Chat-owned durable notification delivery."""

    register_periodic_job(
        "chat-web-push",
        process_push_deliveries,
        interval=1.0,
    )

__all__ = [
    "InternalMessenger",
    "PeriodicJobRegistrar",
    "reconcile_storage",
    "register_scheduler_jobs",
]
