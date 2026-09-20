"""Programmatic sources compiled into permanent database datasets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .dataset import DbAdminDataset


DbAdminDatasetFactory = Callable[[], tuple[DbAdminDataset, ...]]


@dataclass(frozen=True, slots=True)
class DbAdminDataSource:
    """Module-owned factory producing one or more datasets.

    A source is compiled only after every active module has contributed.  The
    produced datasets remain lazy: their row providers are evaluated just
    before their merge, after their declared dependencies have converged.
    """

    key: str
    factory: DbAdminDatasetFactory

    def compile(self) -> tuple[DbAdminDataset, ...]:
        return self.factory()
