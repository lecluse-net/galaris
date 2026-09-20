"""Public notifications of committed user and effective-access changes."""

from collections.abc import Awaitable, Callable

from loguru import logger


UserAccessObserver = Callable[[int | None], Awaitable[None]]
_observers: dict[str, UserAccessObserver] = {}


def register_user_access_observer(name: str, observer: UserAccessObserver) -> None:
    _observers[name] = observer


def unregister_user_access_observer(name: str) -> None:
    _observers.pop(name, None)


async def notify_user_access_changed(user_id: int | None = None) -> None:
    """None means an access-policy change potentially affecting every user."""
    for name, observer in tuple(_observers.items()):
        try:
            await observer(user_id)
        except Exception:
            logger.exception("User access observer {} failed for user {}", name, user_id)
