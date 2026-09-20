"""Small SQLAlchemy type for pgvector-backed rebuildable projections."""

from __future__ import annotations

from typing import Any

from sqlalchemy.types import UserDefinedType

from core.util import as_list


class Vector(UserDefinedType[Any]):
    """PostgreSQL ``vector`` with an optional dimension constraint."""

    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kwargs: Any) -> str:
        if self.dimensions is None:
            return "public.vector"
        return f"public.vector({self.dimensions})"

    def bind_processor(self, dialect: Any):
        del dialect

        def process(value: Any) -> str | None:
            if value is None:
                return None
            if isinstance(value, str):
                return value
            return "[" + ",".join(str(float(entry)) for entry in as_list(value)) + "]"

        return process

    def result_processor(self, dialect: Any, coltype: Any):
        del dialect, coltype

        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(entry) for entry in as_list(value)]
            serialized = str(value).strip()
            if serialized.startswith("[") and serialized.endswith("]"):
                serialized = serialized[1:-1]
            if not serialized:
                return []
            return [float(entry) for entry in serialized.split(",")]

        return process


__all__ = ["Vector"]
