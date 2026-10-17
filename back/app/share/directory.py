"""Injected application principal directory; Share never imports a consumer."""

from typing import Protocol
from .contracts import SharingState


class SharingDirectory(Protocol):
    async def __call__(
        self, *, owner_agent_id: int | None, owner_user_id: int | None
    ) -> SharingState: ...


_provider: SharingDirectory | None = None


def register_sharing_directory(provider: SharingDirectory) -> None:
    global _provider
    _provider = provider


async def directory(*, owner_agent_id: int | None, owner_user_id: int | None) -> SharingState:
    if _provider is None:
        raise RuntimeError("The sharing principal directory is not configured")
    return await _provider(owner_agent_id=owner_agent_id, owner_user_id=owner_user_id)
