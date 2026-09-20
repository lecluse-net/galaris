"""Immutable document formats and dataset validation."""

import json
from typing import Literal, NoReturn

DocumentType = Literal["html", "dataset"]


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
