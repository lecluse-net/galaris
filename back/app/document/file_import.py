"""Independent document snapshots, with source access delegated to File Sharing."""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from html import escape
from html.parser import HTMLParser
import mimetypes
from pathlib import PurePosixPath
from uuid import UUID

from app.agent import AgentManagementScope
from core.util import convert_to_html
from core.user import HumanActor
from .data.content import validate as validate_json
from .type_registry import DocumentKind
from . import resource_service as service
from .content_limits import validate_document_size
from .document_cloning import DocumentCloneSource, PreparedDocumentClone


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


@dataclass(frozen=True)
class PreparedDocumentImport:
    kind: DocumentKind
    content: str
    clone_source: DocumentCloneSource | None = None
    prepared_clone: PreparedDocumentClone | None = None


class _HtmlImport(HTMLParser):
    """Keep a page's displayable fragment without its scripts or executable embeds."""

    _discard = {"script", "iframe", "object", "embed"}
    _void = {"meta", "base", "link", "br", "hr", "img", "input", "source", "wbr", "col", "embed"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []
        self.wrapped: set[str] = set()
        self.in_head = False
        self.in_title = False
        self.ignored: list[str] = []

    def _attributes(self, attrs: list[tuple[str, str | None]]) -> str:
        result: dict[str, str] = {}
        for key, raw in attrs:
            if key.startswith("on") or key == "data-html-page" or key in result:
                continue
            value = raw or ""
            if key in {"href", "src", "action", "formaction", "xlink:href"} and value.strip().lower().startswith("javascript:"):
                continue
            result[key] = value
        return "".join(f' {key}="{escape(value, quote=True)}"' for key, value in result.items())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.ignored or tag in self._discard:
            if tag not in self._void:
                self.ignored.append(tag)
            return
        if tag == "head":
            self.in_head = True
        elif tag in {"html", "body"}:
            if attrs:
                self.wrapped.add(tag)
                attributes = self._attributes(attrs)
                self.parts.append(f"<div{attributes}>")
        elif self.in_head and tag == "title":
            self.in_title = True
        elif tag not in {"meta", "base", "link"}:
            self.parts.append(f"<{tag}{self._attributes(attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self.ignored and tag not in self._discard | {"meta", "base", "link"}:
            self.parts.append(f"<{tag}{self._attributes(attrs)}>")

    def handle_endtag(self, tag: str) -> None:
        if self.ignored:
            if tag in self.ignored:
                self.ignored = self.ignored[:self.ignored.index(tag)]
            return
        if tag in self._discard:
            return
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
        if not self.in_title and not self.ignored:
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
    if media_type == "text/html" and source.document_type is None:
        parser = _HtmlImport()
        parser.feed(content)
        parser.close()
        content = "".join(parser.parts)
    return "text", convert_to_html(content, media_type, profile="document")


@asynccontextmanager
async def import_document_content(uri: str, agent_id: int, scope: AgentManagementScope) -> AsyncGenerator[PreparedDocumentImport]:
    source = await read_document_import_source(uri, agent_id, scope)
    async with prepare_document_import(source) as prepared:
        yield prepared


async def read_document_import_source(uri: str, agent_id: int, scope: AgentManagementScope) -> DocumentImportSource:
    if not scope.allows(agent_id):
        raise service.DocumentNotFoundError("Source Agent unavailable")
    if _reader is None:
        raise ValueError("File sharing unavailable")
    try:
        source = await _reader(uri, agent_id, scope)
    except (PermissionError, FileNotFoundError) as exc:
        raise service.DocumentNotFoundError("Source resource unavailable") from exc
    return source


@asynccontextmanager
async def prepare_document_import(source: DocumentImportSource) -> AsyncGenerator[PreparedDocumentImport]:
    from .converted_import import converted_import_name, prepare_converted_import
    validate_document_size(source.content)
    name = converted_import_name(source.name, source.media_type, source.content)
    if name is None or source.document_type is not None:
        try:
            kind, content = convert_document_import(source)
        except UnsupportedDocumentImport:
            if name is None:
                async with prepare_converted_import(source.name, source.media_type, source.content, convert=False) as prepared:
                    yield PreparedDocumentImport("text", prepared.content, prepared_clone=prepared)
                return
        else:
            yield PreparedDocumentImport(kind, content, clone_source=source.clone_source)
            return
    assert name is not None
    async with prepare_converted_import(name, source.media_type, source.content, original_name=source.name) as prepared:
        yield PreparedDocumentImport("text", prepared.content, prepared_clone=prepared)


def supported_import_formats() -> dict[str, list[str]]:
    from .converted_import import CONVERTED_IMPORT_EXTENSIONS
    extensions = CONVERTED_IMPORT_EXTENSIONS | {".json", ".html", ".htm", ".md", ".markdown", ".txt"}
    media_types = {mime for extension in extensions if (mime := mimetypes.guess_type("source" + extension)[0])}
    media_types.update({"text/markdown", "text/x-markdown", "application/rtf"})
    return {"extensions": sorted(extensions), "media_types": sorted(media_types)}


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
