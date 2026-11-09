"""Process variables and typed transport using the shared value codec.

The shared codec belongs to Data documents; Process owns resource expectations.
"""

from app.dataset import (
    TypedValue as TypedValue, ValueType as ValueType, Variable as Variable,
    ValueContractError as ValueContractError, MAX_INTEGER as MAX_INTEGER,
    MAX_VALUE_BYTES as MAX_VALUE_BYTES, MAX_DEPTH as MAX_DEPTH, MAX_NODES as MAX_NODES,
    VALUE_TYPES as VALUE_TYPES,
    unwrap as unwrap, wrap_external as wrap_external,
)
from typing import Any, cast
import app.dataset as codec


def validate_value(value: object, *, path: str = "value") -> dict[str, Any]:
    return codec.validate_value(value, path=path)


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


def normalize_patch(variables: list[Variable], values: object, *, path: str) -> dict[str, Any]:
    """Validate supplied process variables without resetting omitted values."""
    validate_declarations(variables, path=path)
    if not isinstance(values, dict):
        raise ValueContractError(f"{path}: expected an object of named values")
    values = cast(dict[str, Any], values)
    names = {variable.name for variable in variables}
    if set(values) - names:
        raise ValueContractError(f"{path}: undeclared variable {next(iter(set(values) - names))}")
    return normalize([variable for variable in variables if variable.name in values], values, path=path)


def initialize_variables(variables: list[Variable], values: object, *, inputs: list[str] | None = None) -> dict[str, Any]:
    """Defaults apply once; uninitialized variables remain absent, distinct from null."""
    supplied = normalize_patch([variable for variable in variables if inputs is None or variable.name in inputs], values, path="process.input")
    defaults = normalize([variable for variable in variables
        if variable.name not in supplied and variable.default is not None], {}, path="process.defaults")
    result = validate_values({**defaults, **supplied}, path="process.input")
    if inputs is not None:
        missing = [name for name in inputs if name not in result]
        if missing:
            raise ValueContractError("process.input: missing selected process inputs: " + ", ".join(missing))
    return result


def normalize_reply(variables: list[Variable], values: object, *, path: str) -> dict[str, Any]:
    """A requested human answer supplies its fields; process defaults apply only at launch."""
    result = normalize_patch(variables, values, path=path)
    missing = [variable.name for variable in variables if variable.name not in result]
    if missing:
        raise ValueContractError(f"{path}.{missing[0]}: missing requested variable")
    return result


def external_patch(variables: list[Variable], raw: object, *, path: str,
                   typed_values: bool = False) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueContractError(f"{path}: expected an object of named values")
    raw = cast(dict[str, Any], raw)
    # Validate names before adapting ordinary JSON, including object-shaped values.
    names = {variable.name for variable in variables}
    if set(raw) - names:
        raise ValueContractError(f"{path}: undeclared variable {next(iter(set(raw) - names))}")
    return external_outputs([variable for variable in variables if variable.name in raw], raw,
        path=path, typed_values=typed_values)


def conversational_patch(variables: list[Variable], values: dict[str, Any], *, path: str,
                         typed_values: bool = False) -> dict[str, Any]:
    """Adapt ordinary MCP values, retaining historical scalar envelopes.

    Objects always mean business JSON unless the caller explicitly selects typed
    transport, so business keys named type/value are never mistaken for metadata.
    """
    if typed_values:
        return normalize_patch(variables, values, path=path)
    if set(values) - {variable.name for variable in variables}:
        raise ValueContractError(f"{path}: undeclared variable")
    selected: dict[str, Any] = {}
    for variable in variables:
        if variable.name not in values:
            continue
        value = values[variable.name]
        is_typed = (isinstance(value, dict) and set(cast(dict[str, Any], value)) == {"type", "value"}
            and variable.type != "object")
        selected.update(external_outputs([variable], {variable.name: cast(Any, value)}, path=path, typed_values=is_typed))
    return normalize_patch(variables, selected, path=path)


def loads_values(content: str, *, path: str) -> dict[str, Any]:
    return validate_values(codec.loads_values(content, path=path), path=path)


def external_outputs(variables: list[Variable], raw: object, *, path: str, typed_values: bool = False) -> dict[str, Any]:
    validate_declarations(variables, path=path)
    return validate_values(codec.external_outputs(variables, raw, path=path, typed_values=typed_values), path=path)


async def validate_resource_constraints(variables: list[Variable], values: dict[str, Any], *, agent_id: int) -> None:
    """Check constrained resources through File Sharing's live permissions and metadata."""
    from app.file_share import ResourceContext, resource_info
    context = ResourceContext(agent_id=agent_id, runtime="internal")
    media_types: dict[str, str] = {}
    for variable in variables:
        if variable.mime_type is None and variable.document_type is None:
            continue
        envelope = values.get(variable.name)
        if envelope is None or envelope["value"] is None:
            continue
        uri = str(envelope["value"])
        if uri not in media_types:
            descriptor = await resource_info(context, uri)
            media_types[uri] = descriptor.media_type.split(";", 1)[0].strip().lower()
        actual = media_types[uri]
        expected = variable.mime_type or ("application/json" if variable.document_type == "data" else "text/html")
        if actual != expected and not (expected.endswith("/*") and actual.startswith(expected[:-1])):
            raise ValueContractError(f"process.{variable.name}: expected media type {expected}, received {actual}")

__all__ = ["TypedValue", "ValueType", "Variable", "ValueContractError", "MAX_INTEGER", "MAX_VALUE_BYTES", "MAX_DEPTH", "MAX_NODES",
    "VALUE_TYPES", "validate_value", "validate_values", "validate_declarations", "normalize", "loads_values", "unwrap", "wrap_external", "external_outputs"]
