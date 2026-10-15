"""Versioned JSON values and the common activity boundary contract.

This codec never dereferences a resource or grants authority to an identity.
"""

from __future__ import annotations

from copy import deepcopy
import json
import math
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

ValueType = Literal["int", "float", "string", "bool", "Agent", "File", "User", "Document", "Dataset", "array", "object"]
VALUE_TYPES = frozenset({"int", "float", "string", "bool", "Agent", "File", "User", "Document", "Dataset", "array", "object"})
LEGACY_VALUE_TYPES = VALUE_TYPES - {"Dataset"}
MAX_INTEGER = 2**53 - 1
MAX_VALUE_BYTES = 2_000_000
MAX_DEPTH = 32
MAX_NODES = 20_000


class ValueContractError(ValueError):
    """A bounded, payload-free diagnostic identifying the invalid variable."""


def _error(path: str, message: str) -> ValueContractError:
    return ValueContractError(f"{path[:500]}: {message}")


def _validate(value: object, path: str, depth: int, remaining: list[int]) -> None:
    remaining[0] -= 1
    if depth > MAX_DEPTH or remaining[0] < 0:
        raise _error(path, "typed values exceed the depth or item limit")
    if not isinstance(value, dict):
        raise _error(path, "expected a typed {type, value} envelope")
    envelope = cast(dict[str, Any], value)
    if set(envelope) != {"type", "value"}:
        raise _error(path, "an envelope requires exactly type and value")
    kind = envelope["type"]
    if not isinstance(kind, str) or kind not in VALUE_TYPES:
        raise _error(path, "unknown value type")
    raw: object = envelope["value"]
    if raw is None:
        return
    if kind in {"int", "Agent", "User"}:
        if type(raw) is not int or abs(raw) > MAX_INTEGER:
            raise _error(path, f"{kind} requires an exact safe integer")
        if kind in {"Agent", "User"} and raw <= 0:
            raise _error(path, f"{kind} requires a positive identifier")
    elif kind == "float":
        if type(raw) is int and abs(raw) > MAX_INTEGER:
            raise _error(path, "integer representation exceeds the exact transport range")
        if type(raw) not in {int, float} or not math.isfinite(cast(float, raw)):
            raise _error(path, "float requires a finite number")
    elif kind == "bool":
        if type(raw) is not bool:
            raise _error(path, "bool requires a JSON boolean")
    elif kind == "string":
        if not isinstance(raw, str):
            raise _error(path, "string requires text")
    elif kind in {"File", "Document", "Dataset"}:
        from app.file_share import parse_resource_uri
        if not isinstance(raw, str):
            raise _error(path, "a resource reference requires a canonical URI")
        try:
            uri = parse_resource_uri(raw)
        except ValueError:
            raise _error(path, "invalid resource URI") from None
        if str(uri) != raw or uri.is_collection:
            raise _error(path, "a resource reference requires an exact canonical resource URI")
        if kind == "Document" and (uri.scheme != "document" or len(uri.segments) != 1):
            raise _error(path, "Document requires document://<uuid>")
        if kind == "Dataset" and (uri.scheme != "data" or len(uri.segments) != 1):
            raise _error(path, "Dataset requires data://<uuid>")
    elif kind == "array":
        if not isinstance(raw, list):
            raise _error(path, "array requires a JSON array")
        for index, child in enumerate(cast(list[object], raw)):
            _validate(child, f"{path}[{index}]", depth + 1, remaining)
    elif kind == "object":
        if not isinstance(raw, dict):
            raise _error(path, "object requires a JSON object")
        for key, child in cast(dict[object, object], raw).items():
            if not isinstance(key, str):
                raise _error(path, "object keys must be strings")
            _validate(child, f"{path}.{key}", depth + 1, remaining)


def validate_value(value: object, *, path: str = "value") -> dict[str, Any]:
    _validate(value, path, 0, [MAX_NODES])
    try:
        serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, UnicodeError):
        raise _error(path, "value cannot be serialized as JSON") from None
    try:
        size = len(serialized.encode("utf-8"))
    except UnicodeError:
        raise _error(path, "value is not valid UTF-8") from None
    if size > MAX_VALUE_BYTES:
        raise _error(path, "value exceeds the JSON size limit")
    return deepcopy(cast(dict[str, Any], value))


class TypedValue(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    type: ValueType
    value: JsonValue

    @model_validator(mode="before")
    @classmethod
    def check_value(cls, value: Any) -> Any:
        return validate_value(value)


class Variable(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=200)
    type: ValueType
    nullable: bool
    default: TypedValue | None = Field(default=None, exclude_if=lambda value: value is None)

    @model_validator(mode="after")
    def check_default(self) -> Variable:
        if self.name != self.name.strip():
            raise _error(self.name, "variable names cannot start or end with whitespace")
        if "default" in self.model_fields_set:
            if self.default is None:
                raise _error(self.name, "a default must be a typed envelope, including for null")
            if self.default.type != self.type:
                raise _error(self.name, "default type differs from the variable type")
            if self.default.value is None and not self.nullable:
                raise _error(self.name, "a notnull variable cannot have a null default")
        return self


def validate_declarations(variables: list[Variable], *, path: str) -> None:
    if len(variables) > 500:
        raise _error(path, "too many declared variables")
    names: set[str] = set()
    for variable in variables:
        # Also validate objects built by trusted composition or model_copy.
        Variable.model_validate(variable.model_dump(mode="json"))
        if variable.name in names:
            raise _error(path, f"duplicate variable {variable.name}")
        names.add(variable.name)


def validate_values(values: object, *, path: str = "data") -> dict[str, Any]:
    if not isinstance(values, dict):
        raise _error(path, "expected an object of named typed values")
    result: dict[str, Any] = {}
    remaining = [MAX_NODES]
    for key, value in cast(dict[object, object], values).items():
        if not isinstance(key, str):
            raise _error(path, "variable names must be strings")
        _validate(value, f"{path}.{key}", 0, remaining)
        result[key] = deepcopy(value)
    try:
        size = len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except UnicodeError:
        raise _error(path, "values are not valid UTF-8") from None
    if size > MAX_VALUE_BYTES:
        raise _error(path, "values exceed the JSON size limit")
    return result


def normalize(variables: list[Variable], values: object, *, path: str,
              allow_extra: bool = False) -> dict[str, Any]:
    validate_declarations(variables, path=path)
    if not isinstance(values, dict):
        raise _error(path, "expected an object of named typed values")
    source = cast(dict[str, Any], values)
    names = {variable.name for variable in variables}
    if not allow_extra and set(source) - names:
        raise _error(path, "undeclared variable " + str(next(iter(set(source) - names))))
    result: dict[str, Any] = {}
    for variable in variables:
        location = f"{path}.{variable.name}"
        if variable.name in source:
            value = validate_value(source[variable.name], path=location)
        elif variable.default is not None:
            value = variable.default.model_dump(mode="json")
        elif variable.nullable:
            value = {"type": variable.type, "value": None}
        else:
            raise _error(location, "missing notnull variable without a default")
        if value["type"] != variable.type:
            raise _error(location, f"expected type {variable.type}")
        if value["value"] is None and not variable.nullable:
            raise _error(location, "null is not allowed")
        result[variable.name] = value
    return validate_values(result, path=path)


def loads_values(content: str, *, path: str) -> dict[str, Any]:
    if len(content.encode("utf-8")) > MAX_VALUE_BYTES:
        raise _error(path, "JSON exceeds the size limit")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise _error(path, "duplicate JSON key")
            result[key] = value
        return result

    try:
        value: Any = json.loads(content, object_pairs_hook=pairs)
    except (json.JSONDecodeError, RecursionError):
        raise _error(path, "invalid JSON object") from None
    return validate_values(value, path=path)


def unwrap(value: dict[str, Any]) -> Any:
    """An explicit adapter to an external JSON contract, without resource reads."""
    raw: Any = value["value"]
    if raw is None:
        return None
    if value["type"] == "array":
        return [unwrap(item) for item in raw]
    if value["type"] == "object":
        return {key: unwrap(item) for key, item in raw.items()}
    return raw


def wrap_external(kind: ValueType, raw: Any) -> dict[str, Any]:
    """Use the declared type at an adapter boundary; never infer a reference."""
    def nested(value: Any) -> dict[str, Any]:
        inferred: ValueType
        if type(cast(object, value)) is bool:
            inferred = "bool"
        elif type(cast(object, value)) is int:
            inferred = "int"
        elif type(cast(object, value)) is float:
            inferred = "float"
        elif isinstance(value, str):
            inferred = "string"
        elif isinstance(value, list):
            inferred = "array"
        elif isinstance(value, dict):
            inferred = "object"
        else:
            raise _error("output", "a nested null requires an explicit typed output mapping")
        return wrap_external(inferred, value)

    value = raw
    if raw is not None and kind == "array" and isinstance(raw, list):
        value = [nested(item) for item in cast(list[Any], raw)]
    elif raw is not None and kind == "object" and isinstance(raw, dict):
        value = {key: nested(item) for key, item in cast(dict[str, Any], raw).items()}
    return validate_value({"type": kind, "value": value})


def external_outputs(variables: list[Variable], raw: object, *, path: str,
                     typed_values: bool = False) -> dict[str, Any]:
    if typed_values:
        return normalize(variables, raw, path=path)
    if not isinstance(raw, dict):
        raise _error(path, "external output needs an object or an explicit output mapping")
    values = cast(dict[str, Any], raw)
    selected = {variable.name: wrap_external(variable.type, values[variable.name])
        for variable in variables if variable.name in values}
    return normalize(variables, selected, path=path)
