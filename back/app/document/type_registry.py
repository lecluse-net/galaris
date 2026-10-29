"""Document formats; storage and permissions remain owned by Document."""

from dataclasses import dataclass
from collections.abc import Callable
from typing import Literal

from .text import validate as validate_text, extract as extract_text
from .data.content import validate as validate_data, extract as extract_data

DocumentKind = Literal["text", "data"]
StorageKind = Literal["text", "file"]


@dataclass(frozen=True)
class DocumentTypeDefinition:
    code: DocumentKind
    media_type: str
    initial_content: str
    icon: str
    validate: Callable[[str], None]
    extract: Callable[[str], str]
    storage_kind: StorageKind = "text"


DOCUMENT_TYPES = (
    DocumentTypeDefinition("text", "text/html", "", "description", validate_text, extract_text),
    DocumentTypeDefinition("data", "application/json", "[]", "data_object", validate_data, extract_data),
)


def document_type_definition(code: str) -> DocumentTypeDefinition:
    normalized = "text" if code in {"html", "form"} else code
    for definition in DOCUMENT_TYPES:
        if definition.code == normalized:
            return definition
    raise ValueError("Unsupported document type")
