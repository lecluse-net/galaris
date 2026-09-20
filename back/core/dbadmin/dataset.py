"""Declarative, natural-key datasets and their merge engine."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import Table, and_, delete, insert, select, update
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession


_AUDIT_COLUMNS = frozenset(
    {"created_at", "created_by", "updated_at", "updated_by", "deleted_at", "deleted_by"}
)


DbAdminRows = tuple[Mapping[str, object], ...]
DbAdminRowsProvider = Callable[[AsyncSession], Awaitable[Sequence[Mapping[str, object]]]]
DbAdminColumnMerger = Callable[[object | None, object], object]
DbAdminAfterMerge = Callable[
    [AsyncSession, "DbAdminDatasetResult"], Awaitable[None]
]


def _empty_column_mergers() -> Mapping[str, DbAdminColumnMerger]:
    return {}


@dataclass(frozen=True, slots=True)
class DbAdminDataset:
    """One desired table dataset produced by a module-owned data source."""

    key: str
    table: Table
    natural_key: tuple[str, ...]
    rows: DbAdminRows | DbAdminRowsProvider
    update_columns: tuple[str, ...] | None = None
    update_only_null: bool = False
    delete_missing: bool = False
    column_mergers: Mapping[str, DbAdminColumnMerger] = field(
        default_factory=_empty_column_mergers
    )
    after_merge: DbAdminAfterMerge | None = None
    depends_on: tuple[str, ...] = ()
    required: bool = True


@dataclass(frozen=True, slots=True)
class DbAdminDatasetResult:
    inserted: int = 0
    updated: int = 0
    restored: int = 0
    removed: int = 0


def _validate(dataset: DbAdminDataset, rows: Sequence[Mapping[str, object]]) -> None:
    columns = frozenset(dataset.table.columns.keys())
    if not dataset.natural_key:
        raise ValueError("A DbAdmin dataset requires at least one natural-key column")
    unknown_keys = set(dataset.natural_key) - columns
    if unknown_keys:
        raise ValueError(f"Unknown dataset natural-key columns: {sorted(unknown_keys)}")
    if dataset.update_columns is not None:
        unknown_updates = set(dataset.update_columns) - columns
        if unknown_updates:
            raise ValueError(f"Unknown dataset update columns: {sorted(unknown_updates)}")
    unknown_mergers = set(dataset.column_mergers) - columns
    if unknown_mergers:
        raise ValueError(f"Unknown dataset column mergers: {sorted(unknown_mergers)}")
    seen: set[tuple[Hashable, ...]] = set()
    for row in rows:
        unknown_columns = set(row) - columns
        if unknown_columns:
            raise ValueError(f"Unknown dataset columns: {sorted(unknown_columns)}")
        forbidden = set(row) & _AUDIT_COLUMNS
        if forbidden:
            raise ValueError(
                "HistoryMixin audit columns are managed by DbAdmin, not datasets: "
                + ", ".join(sorted(forbidden))
            )
        try:
            key = tuple(row[column] for column in dataset.natural_key)
        except KeyError as exc:
            raise ValueError(f"Dataset row misses natural-key column {exc.args[0]!r}") from exc
        if not all(isinstance(value, Hashable) for value in key):
            raise ValueError("Dataset natural-key values must be hashable")
        normalized_key = tuple(value for value in key if isinstance(value, Hashable))
        if normalized_key in seen:
            raise ValueError(f"Duplicate dataset natural key: {normalized_key!r}")
        seen.add(normalized_key)


def _row_key(
    row: Mapping[str, object],
    columns: tuple[str, ...],
) -> tuple[Hashable, ...]:
    values = tuple(row[column] for column in columns)
    if not all(isinstance(value, Hashable) for value in values):
        raise ValueError("Dataset natural-key values must be hashable")
    return tuple(value for value in values if isinstance(value, Hashable))


def _key_clause(
    dataset: DbAdminDataset,
    row: Mapping[str, object],
) -> ColumnElement[bool]:
    return and_(
        *(
            dataset.table.columns[column] == row[column]
            for column in dataset.natural_key
        )
    )


async def reconcile_dataset(
    session: AsyncSession,
    dataset: DbAdminDataset,
) -> DbAdminDatasetResult:
    """INSERT/UPDATE/restore/delete a dataset and become a no-op when converged."""

    resolved_rows = (
        tuple(await dataset.rows(session))
        if callable(dataset.rows)
        else dataset.rows
    )
    _validate(dataset, resolved_rows)
    existing_rows = [
        dict(row)
        for row in (await session.execute(select(dataset.table))).mappings().all()
    ]
    existing_by_key = {
        _row_key(row, dataset.natural_key): row for row in existing_rows
    }
    desired_by_key = {
        _row_key(row, dataset.natural_key): row for row in resolved_rows
    }
    inserted = updated = restored = removed = 0

    for key, desired in desired_by_key.items():
        existing = existing_by_key.get(key)
        if existing is None:
            await session.execute(insert(dataset.table).values(dict(desired)))
            inserted += 1
            continue
        changes: dict[str, object] = {}
        update_columns = (
            dataset.update_columns
            if dataset.update_columns is not None
            else tuple(
                column for column in desired if column not in dataset.natural_key
            )
        )
        for column in update_columns:
            if column not in desired:
                continue
            if dataset.update_only_null and existing.get(column) is not None:
                continue
            desired_value = desired[column]
            merger = dataset.column_mergers.get(column)
            if merger is not None:
                desired_value = merger(existing.get(column), desired_value)
            if existing.get(column) != desired_value:
                changes[column] = desired_value
        if "deleted_at" in dataset.table.columns and existing.get("deleted_at") is not None:
            changes["deleted_at"] = None
            if "deleted_by" in dataset.table.columns:
                changes["deleted_by"] = None
            restored += 1
        if changes:
            await session.execute(
                update(dataset.table)
                .where(_key_clause(dataset, desired))
                .values(changes)
            )
            updated += 1

    if dataset.delete_missing:
        for key, existing in existing_by_key.items():
            if key in desired_by_key:
                continue
            if "deleted_at" in dataset.table.columns:
                if existing.get("deleted_at") is not None:
                    continue
                values: dict[str, object] = {"deleted_at": datetime.now(timezone.utc)}
                if "deleted_by" in dataset.table.columns:
                    values["deleted_by"] = None
                await session.execute(
                    update(dataset.table)
                    .where(_key_clause(dataset, existing))
                    .values(values)
                )
            else:
                await session.execute(
                    delete(dataset.table).where(_key_clause(dataset, existing))
                )
            removed += 1

    result = DbAdminDatasetResult(inserted, updated, restored, removed)
    if dataset.after_merge is not None:
        await dataset.after_merge(session, result)
    return result
