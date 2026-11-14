"""Public operations for document-format modules and future plugin contributions."""
from collections.abc import Mapping
from uuid import UUID

from core.user import HumanActor
from .formats import (
    DocumentFormatDefinition as DocumentFormatDefinition,
    DocumentFormatRegistry as DocumentFormatRegistry,
    document_format_definition as document_format_definition,
    document_formats as document_formats,
    register_document_format as register_document_format,
)


def document_format_catalogue() -> list[dict[str, object]]:
    return [{"code": definition.code, "media_type": definition.media_type,
             "storage_kind": definition.storage_kind, "icon": definition.icon,
             "version": definition.version, "contract_version": definition.contract_version,
             "provider": definition.provider, "capabilities": definition.capabilities(),
             "capability_complete": all(value != "unavailable" for value in definition.capabilities().values()),
             "qualification": "not_run", "import_extensions": definition.import_extensions}
            for definition in document_formats()]


def extract_document_content(code: str, content: str) -> str:
    definition = document_format_definition(code)
    definition.validate(content)
    return definition.extract(content)


def remap_document_references(code: str, content: str, mapping: Mapping[str, str]) -> str:
    definition = document_format_definition(code)
    result = definition.remap_references(content, mapping)
    definition.validate(result)
    return result


async def document_source(document_id: UUID, actor: int | HumanActor, *, revision: int | None = None) -> tuple[bytes, str]:
    """Recovery and native export remain available without the format's plugin."""
    from .resource_service import get_item
    _item, content, _access, _kind, mime = await get_item(document_id, agent_id=actor, revision=revision)
    return content, mime
