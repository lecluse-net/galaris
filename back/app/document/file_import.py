"""Independent document snapshots, with source access delegated to File Sharing."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
from pathlib import PurePosixPath
from uuid import UUID

from app.agent import AgentManagementScope
from core.util import convert_to_html
from core.user import HumanActor
from .data.content import validate as validate_json
from .type_registry import DocumentKind
from . import resource_service as service
from .content_limits import validate_document_size
from .document_cloning import DocumentCloneSource


@dataclass(frozen=True)
class DocumentImportSource:
    name: str
    media_type: str
    content: bytes
    document_type: DocumentKind | None = None
    clone_source: DocumentCloneSource | None = None


ImportReader = Callable[[str, int, AgentManagementScope], Awaitable[DocumentImportSource]]
_reader: ImportReader | None = None


class UnsupportedDocumentImport(ValueError):
    pass


class _HtmlImport(HTMLParser):
    """Turn a complete page into a fragment, retaining body attributes and active content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.wrapped: set[str] = set()
        self.in_head = False
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "head":
            self.in_head = True
        elif tag in {"html", "body"}:
            if attrs:
                self.wrapped.add(tag)
                attributes = "".join(f' {key}="{escape(value or "", quote=True)}"' for key, value in attrs)
                self.parts.append(f"<div{attributes}>")
        elif self.in_head and tag == "title":
            self.in_title = True
        elif tag not in {"meta", "base", "link"}:
            self.parts.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"meta", "base", "link"}:
            self.parts.append(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self.in_head = False
        elif tag in {"html", "body"}:
            if tag in self.wrapped:
                self.wrapped.remove(tag)
                self.parts.append("</div>")
        elif self.in_title and tag == "title":
            self.in_title = False
        elif tag not in {"meta", "base", "link"}:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.in_title:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        self.handle_data(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.handle_data(f"&#{name};")


def register_document_import_reader(reader: ImportReader) -> None:
    global _reader
    _reader = reader


def convert_document_import(source: DocumentImportSource) -> tuple[DocumentKind, str]:
    """Determine the document type without retaining a source URI or attachment."""
    validate_document_size(source.content)
    formats = {".json": "application/json", ".html": "text/html", ".htm": "text/html",
               ".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain"}
    suffix = PurePosixPath(source.name).suffix.lower()
    media_type = source.media_type.split(";", 1)[0].strip().lower()
    # Providers may return generic MIME types. A known filename then supplies the format.
    if source.document_type is None:
        media_type = formats.get(suffix, media_type)
    if media_type not in {*formats.values(), "text/x-markdown"}:
        raise UnsupportedDocumentImport("File format is not supported for import")
    content = source.content.decode("utf-8-sig")
    if "\x00" in content:
        raise ValueError("File requires UTF-8 text")
    if media_type == "application/json":
        validate_json(content)
        return "data", content
    if media_type == "text/html":
        parser = _HtmlImport()
        parser.feed(content)
        parser.close()
        content = "".join(parser.parts)
    return "text", convert_to_html(content, media_type, profile="document")


async def import_document_content(uri: str, agent_id: int, scope: AgentManagementScope) -> tuple[DocumentKind, str, DocumentCloneSource | None]:
    if not scope.allows(agent_id):
        raise service.DocumentNotFoundError("Source Agent unavailable")
    if _reader is None:
        raise ValueError("File sharing unavailable")
    try:
        source = await _reader(uri, agent_id, scope)
    except (PermissionError, FileNotFoundError) as exc:
        raise service.DocumentNotFoundError("Source resource unavailable") from exc
    kind, content = convert_document_import(source)
    return kind, content, source.clone_source


async def read_native_document_import(identity: UUID, scope: AgentManagementScope) -> DocumentImportSource:
    """Read the entire authorized document, independent of paginated tool reads."""
    item = await service.item_record(identity)
    if item is None:
        raise service.DocumentNotFoundError("Source document unavailable")
    actor: int | HumanActor = HumanActor(scope.user_id)
    if not (await service.effective_access(item, actor)).can_read:
        readable, _ = await service.managed_item_agent_ids(item, scope.agent_ids)
        if not readable:
            raise service.DocumentNotFoundError("Source document unavailable")
        actor = readable[0]
    item, content, _access, _content_type, media_type = await service.get_item(identity, agent_id=actor)
    kind = "data" if item.document_type == "data" else "text"
    return DocumentImportSource(item.title, media_type, content, kind,
        DocumentCloneSource(identity, actor) if kind == "text" else None)
