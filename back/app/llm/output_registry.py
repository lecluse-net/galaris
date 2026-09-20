"""Code-owned output contracts restored independently of a submitting caller."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal

from pydantic import BaseModel, JsonValue

from .contracts import StructuredOutputSpec


@dataclass(frozen=True)
class OutputContract:
    output_type: type[BaseModel]
    validator: Callable[[Any], Any] | None
    validator_factory: Callable[[dict[str, JsonValue]], Callable[[Any], Any]] | None = None


_contracts: dict[str, OutputContract] = {}


def register[T: BaseModel](
    key: str, output_type: type[T], *, validator: Callable[[T], T] | None = None,
    validator_factory: Callable[[dict[str, JsonValue]], Callable[[T], T]] | None = None,
) -> None:
    if not key.strip():
        raise ValueError("An output contract needs a versioned key.")
    if validator is not None and validator_factory is not None:
        raise ValueError("Choose a static validator or a contextual validator factory.")
    contract = OutputContract(output_type, validator, validator_factory)
    if key in _contracts and _contracts[key] != contract:
        raise ValueError(f"Output contract {key!r} is already registered.")
    _contracts[key] = contract


def specification(
    key: str, *, mode: Literal["tool", "prompted"] = "tool",
    context: dict[str, JsonValue] | None = None,
) -> StructuredOutputSpec:
    contract = _contracts.get(key)
    if contract is None:
        raise LookupError(f"Unknown inference output contract: {key}")
    return StructuredOutputSpec(
        contract=key, json_schema=contract.output_type.model_json_schema(), mode=mode,
        context=context or {},
    )


def resolve(spec: StructuredOutputSpec) -> OutputContract:
    current = specification(spec.contract, mode=spec.mode)
    if current.json_schema != spec.json_schema:
        raise ValueError(f"Inference output schema changed for {spec.contract!r}.")
    contract = _contracts[spec.contract]
    if contract.validator_factory is not None:
        # Bind fresh, validated data for this request; never mutate the shared registry.
        validator = contract.validator_factory(spec.model_copy(deep=True).context)
        return replace(contract, validator=validator)
    if spec.context:
        raise ValueError("This output contract does not accept validation context.")
    return contract


def for_type(
    output_type: type[Any],
    validator: Callable[[Any], Any] | None,
    *,
    mode: Literal["tool", "prompted"],
    context: dict[str, JsonValue] | None = None,
) -> StructuredOutputSpec:
    matches = [key for key, item in _contracts.items()
               if item.output_type is output_type and item.validator is validator]
    if len(matches) != 1:
        raise ValueError("Durable output requires one registered type and validator contract.")
    return specification(matches[0], mode=mode, context=context)
