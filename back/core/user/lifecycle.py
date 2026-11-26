"""Transactional account projections and notifications of committed access changes."""

from collections.abc import Awaitable, Callable

from loguru import logger


UserAccessObserver = Callable[[int | None], Awaitable[None]]
_observers: dict[str, UserAccessObserver] = {}
_projections: dict[str, Callable[[int, bool], Awaitable[None]]] = {}


def register_user_activation_projection(name: str, projection: Callable[[int, bool], Awaitable[None]]) -> None:
    _projections[name] = projection


async def project_user_activation(user_id: int, active: bool) -> None:
    """Run under the writer's sharing lock. A failed projection aborts the transaction."""
    for projection in tuple(_projections.values()):
        await projection(user_id, active)


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
