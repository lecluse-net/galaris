"""Immutable document formats and dataset validation."""

import json
from collections.abc import Callable
from typing import Literal, NoReturn

DocumentType = Literal["text", "data", "html", "dataset", "process"]
_validators: dict[str, Callable[[str], object]] = {}


def register_document_validator(kind: str, validator: Callable[[str], object]) -> None:
    _validators[kind] = validator


def validate_document_content(kind: str, content: bytes) -> None:
    if kind in {"text", "html", "data"}:
        from .type_registry import document_type_definition
        document_type_definition(kind).validate(content.decode("utf-8"))
    elif kind == "dataset":
        validate_dataset(content)
    elif kind == "process":
        validator = _validators.get(kind)
        if validator is None:
            raise ValueError(f"The {kind} document validator is unavailable")
        validator(content.decode("utf-8"))


def document_media_type(kind: DocumentType) -> str:
    return {"text": "text/html", "data": "application/json", "html": "text/html", "dataset": "application/json", "process": "application/bpmn+xml"}[kind]


def validate_dataset(content: bytes) -> None:
    """Validate strict UTF-8 JSON without rewriting the author's source."""
    if len(content) > 2_000_000:
        raise ValueError("Dataset content exceeds 2,000,000 bytes.")

    def reject_constant(value: str) -> NoReturn:
        raise ValueError("Non-finite numbers are not valid JSON.")

    try:
        json.loads(content.decode("utf-8"), parse_constant=reject_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError("A Dataset document must contain valid UTF-8 JSON.") from exc
