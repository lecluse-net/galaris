"""Document-format extension contract shared by native modules and plugins.

Registration describes capabilities; qualification executes independent tests.
The host owns identities, policy, immutable revisions and resource transport.
"""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from html import escape
import re
from typing import Literal

DocumentFormat = str
StorageKind = Literal["text", "file"]
FormatCapability = Literal["editor", "preview", "embed", "thumbnail", "pdf", "native_export", "import"]
CapabilitySupport = Literal["native", "fallback", "unavailable"]
FORMAT_CONTRACT_VERSION = 1
FORMAT_CAPABILITIES: tuple[FormatCapability, ...] = (
    "editor", "preview", "embed", "thumbnail", "pdf", "native_export", "import",
)


def no_references(_content: str) -> tuple[str, ...]:
    return ()


def unchanged_references(content: str, _mapping: Mapping[str, str]) -> str:
    return content


def literal_snapshot(content: str) -> str:
    """Inert fallback; never interpret an unknown format as editorial HTML."""
    return "<pre>" + escape(content) + "</pre>"


@dataclass(frozen=True, slots=True)
class DocumentFormatDefinition:
    code: str
    media_type: str
    initial_content: str
    icon: str
    validate: Callable[[str], None]
    extract: Callable[[str], str]
    storage_kind: StorageKind = "text"
    version: int = 1
    contract_version: int = FORMAT_CONTRACT_VERSION
    provider: str = "galaris"
    references: Callable[[str], tuple[str, ...]] = no_references
    remap_references: Callable[[str, Mapping[str, str]], str] = unchanged_references
    static_snapshot: Callable[[str], str] = literal_snapshot
    surfaces: frozenset[FormatCapability] = frozenset()
    import_extensions: tuple[str, ...] = ()
    initial_binary: bytes | None = None
    validate_binary: Callable[[bytes], None] | None = None
    extract_binary: Callable[[bytes], str] | None = None

    def validate_content(self, content: bytes) -> None:
        if self.storage_kind == "file":
            if self.validate_binary is None:
                raise ValueError("Binary document validator unavailable")
            self.validate_binary(content)
        else:
            self.validate(content.decode("utf-8"))

    def extract_content(self, content: bytes) -> str:
        if self.storage_kind == "file":
            return self.extract_binary(content) if self.extract_binary is not None else ""
        return self.extract(content.decode("utf-8"))

    def capabilities(self) -> dict[FormatCapability, CapabilitySupport]:
        return {capability: "native" if capability in self.surfaces else
                "fallback" if capability in {"preview", "embed", "thumbnail", "pdf", "native_export"}
                else "unavailable" for capability in FORMAT_CAPABILITIES}


class DocumentFormatRegistry:
    """Deterministic registry per application generation; reject replacements."""

    def __init__(self) -> None:
        self._formats: dict[str, DocumentFormatDefinition] = {}

    def register(self, definition: DocumentFormatDefinition) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*", definition.code) or len(definition.code) > 80:
            raise ValueError("Invalid document format code")
        if definition.code in {"html", "form", "dataset", "process"}:
            raise ValueError("Reserved historical document format")
        if definition.code in self._formats:
            raise ValueError(f"Duplicate document format: {definition.code}")
        if definition.contract_version != FORMAT_CONTRACT_VERSION or definition.version < 1:
            raise ValueError("Unsupported document format contract/version")
        if not definition.provider or "/" not in definition.media_type:
            raise ValueError("A document format requires a provider and media type")
        if not definition.surfaces.issubset(FORMAT_CAPABILITIES):
            raise ValueError("Unknown document format capability")
        if definition.storage_kind == "file":
            if definition.initial_binary is None or definition.validate_binary is None:
                raise ValueError("A file format requires initial bytes and a binary validator")
            definition.validate_content(definition.initial_binary)
        else:
            definition.validate(definition.initial_content)
        self._formats[definition.code] = definition

    def definitions(self) -> tuple[DocumentFormatDefinition, ...]:
        return tuple(self._formats.values())

    def get(self, code: str) -> DocumentFormatDefinition:
        try:
            return self._formats[code]
        except KeyError:
            raise ValueError(f"Document format unavailable: {code}") from None


registry = DocumentFormatRegistry()
_native_registered = False


def register_document_format(definition: DocumentFormatDefinition) -> None:
    _ensure_native_formats()
    registry.register(definition)


def document_formats() -> tuple[DocumentFormatDefinition, ...]:
    _ensure_native_formats()
    return registry.definitions()


def document_format_definition(code: str) -> DocumentFormatDefinition:
    _ensure_native_formats()
    return registry.get(code)


def document_format_codes() -> tuple[str, ...]:
    return tuple(definition.code for definition in document_formats())


def _text_references(content: str) -> tuple[str, ...]:
    from core.util import image_references
    return tuple(sorted(image_references(content)))


def _text_remap(content: str, mapping: Mapping[str, str]) -> str:
    for source, target in mapping.items():
        content = content.replace(source, target)
    return content


def _ensure_native_formats() -> None:
    global _native_registered
    if _native_registered:
        return
    from .text import validate as validate_text, extract as extract_text
    from .data.content import validate as validate_data, extract as extract_data

    registry.register(DocumentFormatDefinition(
        "text", "text/html", "", "description", validate_text, extract_text,
        references=_text_references, remap_references=_text_remap,
        surfaces=frozenset({"editor", "preview", "embed", "thumbnail", "pdf", "native_export", "import"}),
        import_extensions=(".html", ".htm", ".md", ".markdown", ".txt"),
    ))
    registry.register(DocumentFormatDefinition(
        "data", "application/json", "[]", "data_object", validate_data, extract_data,
        surfaces=frozenset({"editor", "preview", "native_export", "import"}), import_extensions=(".json",),
    ))
    _native_registered = True
