"""Bounded, read-only queries over a canonical Dataset snapshot.

Paths are RFC 6901 JSON pointers, never executable expressions or SQL. Numeric
aggregates use Decimal and return decimal strings, avoiding binary float totals.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from functools import cmp_to_key
import json
import re
from typing import Annotated, Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .contracts import DataActor, DatasetConflictError
from .service import parse_json, record


Pointer = Annotated[str, StringConstraints(max_length=1000)]
Scalar = Annotated[str, StringConstraints(max_length=4000)] | int | float | bool | None
_MISSING = object()
MAX_RESULT_BYTES = 64_000


class QueryFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: Pointer
    op: Literal["eq", "ne", "lt", "lte", "gt", "gte", "contains", "in", "exists"] = "eq"
    value: Scalar | Annotated[list[Scalar], Field(max_length=500)] = None


class QuerySort(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: Pointer
    descending: bool = False


class QueryAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: Annotated[str, StringConstraints(min_length=1, max_length=100)]
    op: Literal["count", "sum", "min", "max", "avg"]
    path: Pointer | None = None

    @model_validator(mode="after")
    def numeric_path(self) -> QueryAggregate:
        if self.op != "count" and self.path is None:
            raise ValueError("A numeric aggregation requires a path")
        return self


class DatasetQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: Pointer = ""
    filters: list[QueryFilter] = Field(default_factory=list[QueryFilter], max_length=20)
    fields: list[Pointer] = Field(default_factory=list[str], max_length=30)
    sort: list[QuerySort] = Field(default_factory=list[QuerySort], max_length=4)
    aggregates: list[QueryAggregate] = Field(default_factory=list[QueryAggregate], max_length=20)
    offset: int = Field(default=0, ge=0, le=20_000)
    limit: int = Field(default=50, ge=1, le=500)
    include_rows: bool = True
    expected_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_contract(self) -> DatasetQuery:
        for path in [self.path, *self.fields, *(f.path for f in self.filters),
                     *(s.path for s in self.sort), *(a.path for a in self.aggregates if a.path is not None)]:
            pointer_parts(path)
        if len({a.name for a in self.aggregates}) != len(self.aggregates):
            raise ValueError("Aggregation names must be unique")
        for condition in self.filters:
            if condition.op == "exists" and type(condition.value) is not bool:
                raise ValueError("exists requires a boolean value")
            if condition.op == "in" and not isinstance(condition.value, list):
                raise ValueError("in requires an array of scalar values")
        # Reject NaN/Infinity at the dynamic JSON boundary, including filter values.
        json.dumps(self.model_dump(), allow_nan=False)
        return self


def pointer_parts(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/") or re.search(r"~(?![01])", pointer):
        raise ValueError("Use an RFC 6901 JSON pointer, empty for the root")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def at_pointer(value: Any, pointer: str) -> Any:
    """Resolve a bounded dynamic JSON value without coercing keys or types."""
    for part in pointer_parts(pointer):
        if isinstance(value, dict):
            value = cast(dict[str, Any], value).get(part, _MISSING)
        elif isinstance(value, list) and re.fullmatch(r"0|[1-9][0-9]*", part):
            array = cast(list[Any], value)
            index = int(part) if len(part) < 8 else len(array)
            value = array[index] if index < len(array) else _MISSING
        else:
            return _MISSING
    return value


def _number(value: Any) -> Decimal:
    if type(value) not in (int, float, Decimal):
        raise ValueError("Numeric operations require numbers; null, booleans and strings are not numbers")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("Numeric operations require finite numbers")
    return result


def _equal(left: Any, right: Any) -> bool:
    if type(left) in (int, float, Decimal) and type(right) in (int, float, Decimal):
        return _number(left) == _number(right)
    return type(left) is type(right) and left == right


def _compare(left: Any, right: Any) -> int:
    if type(left) in (int, float, Decimal) and type(right) in (int, float, Decimal):
        left, right = _number(left), _number(right)
    elif not (isinstance(left, str) and isinstance(right, str)):
        raise ValueError("Ordering requires two numbers or two strings of the same kind")
    return (left > right) - (left < right)


def _matches(row: Any, condition: QueryFilter) -> bool:
    value = at_pointer(row, condition.path)
    if condition.op == "exists":
        return (value is not _MISSING) is condition.value
    if value is _MISSING:
        return False
    if condition.op == "eq":
        return _equal(value, condition.value)
    if condition.op == "ne":
        return not _equal(value, condition.value)
    if condition.op == "in":
        assert isinstance(condition.value, list)
        return any(_equal(value, candidate) for candidate in condition.value)
    if condition.op == "contains":
        return isinstance(value, str) and isinstance(condition.value, str) and condition.value.casefold() in value.casefold()
    if value is None:
        return False
    comparison = _compare(value, condition.value)
    return {"lt": comparison < 0, "lte": comparison <= 0,
            "gt": comparison > 0, "gte": comparison >= 0}[condition.op]


def _aggregate(rows: list[tuple[str, Any]], operation: QueryAggregate) -> dict[str, Any]:
    if operation.path is None:
        return {"value": len(rows), "present": len(rows), "missing": 0, "null": 0}
    values = [at_pointer(row, operation.path) for _, row in rows]
    present = [value for value in values if value is not _MISSING]
    non_null = [value for value in present if value is not None]
    result: dict[str, Any] = {"present": len(present), "missing": len(values) - len(present),
                              "null": len(present) - len(non_null)}
    if operation.op == "count":
        result["value"] = len(non_null)
        return result
    numbers = [_number(value) for value in non_null]
    value: Decimal | None = None
    with localcontext() as arithmetic:
        # Preserve all significant places in the sum, including widely different
        # exponents. Average may repeat; its explicit precision is returned.
        arithmetic.prec = max(34, max((n.adjusted() for n in numbers), default=0)
            - min((int(str(n.as_tuple().exponent)) for n in numbers), default=0)
            + len(str(len(numbers))) + 2)
        if operation.op == "sum":
            value = sum(numbers, Decimal(0))
        elif numbers:
            if operation.op == "avg":
                value = sum(numbers, Decimal(0)) / len(numbers)
                result["precision"] = arithmetic.prec
            else:
                value = min(numbers) if operation.op == "min" else max(numbers)
    result.update(value=str(value) if value is not None else None, encoding="decimal")
    return result


def execute_query(content: str, query: DatasetQuery) -> dict[str, Any]:
    root = parse_json(content)
    selected = at_pointer(root, query.path)
    if selected is _MISSING:
        raise ValueError("Query path does not exist in this Dataset revision")
    rows: list[tuple[str, Any]] = ([(f"{query.path}/{index}", row) for index, row in enumerate(cast(list[Any], selected))]
                                  if isinstance(selected, list) else [(query.path, selected)])
    matched = [(pointer, row) for pointer, row in rows if all(_matches(row, f) for f in query.filters)]

    def compare_rows(left: tuple[str, Any], right: tuple[str, Any]) -> int:
        for order in query.sort:
            a, b = at_pointer(left[1], order.path), at_pointer(right[1], order.path)
            missing_a, missing_b = a is _MISSING or a is None, b is _MISSING or b is None
            if missing_a or missing_b:
                comparison = int(missing_a) - int(missing_b)
            else:
                comparison = _compare(a, b) * (-1 if order.descending else 1)
            if comparison:
                return comparison
        return 0

    if query.sort:
        matched.sort(key=cmp_to_key(compare_rows))
    # Preserve the original decimal literals for arithmetic, rather than first
    # rounding them to binary floats through the ordinary resource reader.
    decimal_root: Any = json.loads(content, parse_float=Decimal) if query.aggregates else None
    arithmetic_rows = [(pointer, at_pointer(decimal_root, pointer)) for pointer, _ in matched]
    aggregates = {a.name: _aggregate(arithmetic_rows, a) for a in query.aggregates}
    items: list[dict[str, Any]] = []
    size = len(json.dumps(aggregates, ensure_ascii=False).encode())
    if size > MAX_RESULT_BYTES:
        raise ValueError("Aggregates exceed the query budget; request fewer aggregates")
    byte_limited = False
    if query.include_rows:
        for pointer, row in matched[query.offset:query.offset + query.limit]:
            projected = {path: value for path in query.fields if (value := at_pointer(row, path)) is not _MISSING} if query.fields else row
            item = {"json_pointer": pointer, "value": projected}
            item_size = len(json.dumps(item, ensure_ascii=False).encode())
            if size + item_size > MAX_RESULT_BYTES:
                if not items:
                    raise ValueError("A result row exceeds the query budget; select fewer fields")
                byte_limited = True
                break
            size += item_size
            items.append(item)
    next_offset = query.offset + len(items)
    has_more = query.include_rows and next_offset < len(matched)
    return {"items": items, "matched_rows": len(matched), "scanned_rows": len(rows),
            "aggregates": aggregates, "has_more": has_more,
            "next_offset": next_offset if has_more else None, "byte_limited": byte_limited}


async def query_dataset(identity: UUID, actor: DataActor, query: DatasetQuery) -> dict[str, Any]:
    dataset = await record(identity, actor)
    if query.expected_revision is not None and dataset.revision != query.expected_revision:
        raise DatasetConflictError("Dataset revision changed; reread before querying")
    return {"uri": f"data://{dataset.id}", "revision": dataset.revision,
            **execute_query(dataset.content, query)}
