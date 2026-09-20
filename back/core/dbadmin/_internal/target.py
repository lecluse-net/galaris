"""Generate Atlas SQL targets without mutating global SQLAlchemy metadata."""

from __future__ import annotations

from hashlib import sha256
from typing import Any

from sqlalchemy import MetaData, create_mock_engine

from core.database import Base, load_models

from ..contracts import RequiredColumnTransition
from ..snapshot import validate_target_schema


def load_target_metadata() -> MetaData:
    """Load active models and copy their metadata for isolated manipulation."""

    load_models()
    copied = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(copied)
    validate_target_schema(copied)
    return copied


def staged_metadata(
    target: MetaData,
    required_columns: tuple[RequiredColumnTransition, ...],
) -> MetaData:
    """Return a target where only newly required columns are temporarily nullable."""

    copied = MetaData()
    for table in target.tables.values():
        table.to_metadata(copied)
    for transition in required_columns:
        copied.tables[transition.table_name].columns[
            transition.column_name
        ].nullable = True
    return copied


def render_target_sql(metadata: MetaData) -> str:
    """Render deterministic PostgreSQL DDL accepted by Atlas's file source."""

    statements: list[str] = []

    def dump(sql: Any, *multiparams: Any, **params: Any) -> None:
        del multiparams, params
        compiled = sql.compile(dialect=engine.dialect)  # type: ignore[attr-defined]
        statements.append(compiled.string.rstrip() + ";")

    engine: Any = create_mock_engine("postgresql://", dump)
    metadata.create_all(engine)
    return "\n".join(statements) + "\n"


def target_fingerprint(target_sql: str) -> str:
    return sha256(target_sql.encode()).hexdigest()
