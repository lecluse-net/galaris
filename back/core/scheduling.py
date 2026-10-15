"""Injected maintenance-job registration; independent of the concrete scheduler."""

from collections.abc import Awaitable, Callable
from typing import Protocol


class PeriodicJobRegistrar(Protocol):
    def __call__(
        self,
        name: str,
        callback: Callable[[], Awaitable[object]],
        *,
        interval: float,
        timeout: float = 900.0,
    ) -> None: ...


class PeriodicJobRemover(Protocol):
    def __call__(self, name: str) -> None: ...
