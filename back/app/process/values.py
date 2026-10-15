"""Compatibility imports for frozen Process v2 contracts.

The single value codec belongs to Dataset. Existing imports remain supported;
Process profile validation restricts its historical types separately.
"""

from app.dataset import (
    TypedValue as TypedValue, ValueType as ValueType, Variable as Variable,
    ValueContractError as ValueContractError, MAX_INTEGER as MAX_INTEGER,
    MAX_VALUE_BYTES as MAX_VALUE_BYTES, MAX_DEPTH as MAX_DEPTH, MAX_NODES as MAX_NODES,
    LEGACY_VALUE_TYPES as VALUE_TYPES,
    unwrap as unwrap, wrap_external as wrap_external,
)
from typing import Any
import app.dataset as codec


def validate_value(value: object, *, path: str = "value") -> dict[str, Any]:
    result = codec.validate_value(value, path=path)
    pending = [result]
    while pending:
        item = pending.pop()
        if item["type"] not in VALUE_TYPES:
            raise ValueContractError(f"{path}: Dataset references require an explicit newer Process profile")
        if item["value"] is not None:
            if item["type"] == "array":
                pending.extend(item["value"])
            elif item["type"] == "object":
                pending.extend(item["value"].values())
    return result


def validate_values(values: object, *, path: str = "data") -> dict[str, Any]:
    result = codec.validate_values(values, path=path)
    return {name: validate_value(value, path=f"{path}.{name}") for name, value in result.items()}


def validate_declarations(variables: list[Variable], *, path: str) -> None:
    codec.validate_declarations(variables, path=path)
    for variable in variables:
        if variable.type not in VALUE_TYPES:
            raise ValueContractError(f"{path}.{variable.name}: unsupported type in Process v2")
        if variable.default is not None:
            validate_value(variable.default.model_dump(mode="json"), path=f"{path}.{variable.name}.default")


def normalize(variables: list[Variable], values: object, *, path: str, allow_extra: bool = False) -> dict[str, Any]:
    validate_declarations(variables, path=path)
    return validate_values(codec.normalize(variables, values, path=path, allow_extra=allow_extra), path=path)


def loads_values(content: str, *, path: str) -> dict[str, Any]:
    return validate_values(codec.loads_values(content, path=path), path=path)


def external_outputs(variables: list[Variable], raw: object, *, path: str, typed_values: bool = False) -> dict[str, Any]:
    validate_declarations(variables, path=path)
    return validate_values(codec.external_outputs(variables, raw, path=path, typed_values=typed_values), path=path)

__all__ = ["TypedValue", "ValueType", "Variable", "ValueContractError", "MAX_INTEGER", "MAX_VALUE_BYTES", "MAX_DEPTH", "MAX_NODES",
    "VALUE_TYPES", "validate_value", "validate_values", "validate_declarations", "normalize", "loads_values", "unwrap", "wrap_external", "external_outputs"]
