"""First-party Chat application and native provider."""

from core.scheduling import PeriodicJobRegistrar

from .provider import InternalMessenger
from .events import register_events
from .storage import reconcile_storage
from .push_service import process_push_deliveries

register_events()


def register_scheduler_jobs(register_periodic_job: PeriodicJobRegistrar) -> None:
    """Register Chat-owned durable notification delivery."""
    from .desktop_screen import prune_screen_requests

    register_periodic_job(
        "chat-web-push",
        process_push_deliveries,
        interval=1.0,
    )
    register_periodic_job("chat-desktop-screen-expiry", prune_screen_requests, interval=30.0)

__all__ = [
    "InternalMessenger",
    "PeriodicJobRegistrar",
    "reconcile_storage",
    "register_scheduler_jobs",
]
