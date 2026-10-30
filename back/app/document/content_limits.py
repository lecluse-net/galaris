"""Use the existing resource quota for document content, including imports."""

from core.params import runtime_settings


def validate_document_size(content: str | bytes) -> None:
    size = len(content if isinstance(content, bytes) else content.encode("utf-8"))
    limit = runtime_settings.MEMORY_RESOURCE_MAX_BYTES
    if size > limit:
        raise ValueError(f"Document exceeds the configured {limit}-byte resource quota")
