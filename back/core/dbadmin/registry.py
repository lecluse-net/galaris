"""Registration surface for permanent datasets and conditional upgrade actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .contracts import DbAdminPhase, SchemaTransitionSet
from .dataset import DbAdminDataset
from .datasource import DbAdminDataSource


DbAdminPredicate = Callable[[SchemaTransitionSet], bool]
DbAdminHandler = Callable[[AsyncSession, SchemaTransitionSet], Awaitable[None]]
DbAdminPostcondition = Callable[
    [AsyncSession, SchemaTransitionSet], Awaitable[bool]
]
DbAdminReconcilerHandler = Callable[[AsyncSession], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class DbAdminAction:
    """Idempotent state-conditioned transformation contributed by a module."""

    key: str
    phase: DbAdminPhase
    checksum: str
    predicate: DbAdminPredicate
    handler: DbAdminHandler
    postcondition: DbAdminPostcondition
    required: bool = True
    # Explicit assertion that this handler/postcondition safely resumes each
    # listed unfinished implementation, including its partially written data.
    compatible_checksums: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class DbAdminReconciler:
    """Derived-state repair that is deliberately not presented as a dataset."""

    key: str
    handler: DbAdminReconcilerHandler
    depends_on: tuple[str, ...] = ()
    required: bool = True


@dataclass(frozen=True, slots=True)
class DbAdminEnumMapping:
    """Developer-owned mapping used when an enum label disappears or is renamed."""

    enum_name: str
    values: dict[str, str]


class DbAdminRegistry:
    """Mutable only during bootstrap; duplicate keys are rejected immediately."""

    def __init__(self) -> None:
        self._actions: dict[str, DbAdminAction] = {}
        self._data_sources: dict[str, DbAdminDataSource] = {}
        self._compiled_datasets: dict[str, DbAdminDataset] | None = None
        self._reconcilers: dict[str, DbAdminReconciler] = {}
        self._enum_mappings: dict[str, DbAdminEnumMapping] = {}

    def register_action(self, action: DbAdminAction) -> None:
        if action.key in self._actions:
            raise ValueError(f"Duplicate DbAdmin action key: {action.key}")
        self._actions[action.key] = action

    def register_data_source(self, source: DbAdminDataSource) -> None:
        if source.key in self._data_sources:
            raise ValueError(f"Duplicate DbAdmin data source key: {source.key}")
        self._data_sources[source.key] = source
        self._compiled_datasets = None

    def register_reconciler(self, reconciler: DbAdminReconciler) -> None:
        if reconciler.key in self._reconcilers:
            raise ValueError(f"Duplicate DbAdmin reconciler key: {reconciler.key}")
        self._reconcilers[reconciler.key] = reconciler

    def register_enum_mapping(self, mapping: DbAdminEnumMapping) -> None:
        if mapping.enum_name in self._enum_mappings:
            raise ValueError(f"Duplicate DbAdmin enum mapping: {mapping.enum_name}")
        self._enum_mappings[mapping.enum_name] = mapping

    @property
    def actions(self) -> tuple[DbAdminAction, ...]:
        return tuple(self._actions[key] for key in sorted(self._actions))

    @property
    def data_sources(self) -> tuple[DbAdminDataSource, ...]:
        return tuple(self._data_sources[key] for key in sorted(self._data_sources))

    def _compile_datasets(self) -> dict[str, DbAdminDataset]:
        if self._compiled_datasets is not None:
            return self._compiled_datasets
        compiled: dict[str, DbAdminDataset] = {}
        owners: dict[str, str] = {}
        for source in self.data_sources:
            for dataset in source.compile():
                if dataset.key in compiled:
                    raise ValueError(
                        f"Duplicate DbAdmin dataset key {dataset.key!r} from "
                        f"{owners[dataset.key]!r} and {source.key!r}"
                    )
                compiled[dataset.key] = dataset
                owners[dataset.key] = source.key
        self._compiled_datasets = compiled
        return compiled

    @property
    def datasets(self) -> tuple[DbAdminDataset, ...]:
        remaining = dict(self._compile_datasets())
        registered_keys = frozenset(remaining)
        resolved: set[str] = set()
        ordered: list[DbAdminDataset] = []
        while remaining:
            ready = sorted(
                key
                for key, dataset in remaining.items()
                if set(dataset.depends_on) <= resolved
            )
            if ready:
                for key in ready:
                    ordered.append(remaining.pop(key))
                    resolved.add(key)
                continue
            missing = sorted(
                {
                    dependency
                    for dataset in remaining.values()
                    for dependency in dataset.depends_on
                    if dependency not in registered_keys
                }
            )
            if missing:
                raise ValueError(
                    "DbAdmin datasets depend on unknown keys: " + ", ".join(missing)
                )
            raise ValueError(
                "DbAdmin dataset dependency cycle: " + ", ".join(sorted(remaining))
            )
        return tuple(ordered)

    @property
    def reconcilers(self) -> tuple[DbAdminReconciler, ...]:
        datasets = {dataset.key for dataset in self.datasets}
        remaining = dict(self._reconcilers)
        known = datasets | set(remaining)
        resolved = set(datasets)
        ordered: list[DbAdminReconciler] = []
        while remaining:
            ready = sorted(
                key
                for key, reconciler in remaining.items()
                if set(reconciler.depends_on) <= resolved
            )
            if ready:
                for key in ready:
                    ordered.append(remaining.pop(key))
                    resolved.add(key)
                continue
            missing = sorted(
                {
                    dependency
                    for reconciler in remaining.values()
                    for dependency in reconciler.depends_on
                    if dependency not in known
                }
            )
            if missing:
                raise ValueError(
                    "DbAdmin reconcilers depend on unknown keys: " + ", ".join(missing)
                )
            raise ValueError(
                "DbAdmin reconciler dependency cycle: " + ", ".join(sorted(remaining))
            )
        return tuple(ordered)

    def enum_mapping(self, enum_name: str) -> DbAdminEnumMapping | None:
        return self._enum_mappings.get(enum_name)


registry = DbAdminRegistry()
