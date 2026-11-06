"""Editable imports with document-owned media and failure-safe publication."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
import mimetypes
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.parse import unquote
from uuid import UUID, uuid4

import nh3
from loguru import logger

from core.document import OFFICE_EXTENSIONS, prepare_document
from core.storage import get_attachment_storage
from core.util import complete_await, complete_io, image_references, normalize_html
from .content_limits import validate_document_size
from .document_attachment_service import validate_attachment_content
from .document_cloning import PreparedDocumentClone
from .schemas import DocumentAttachmentPublic


CONVERTED_IMPORT_EXTENSIONS = OFFICE_EXTENSIONS | {".pdf", ".epub", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff"}


def converted_import_name(name: str, media_type: str, content: bytes) -> str | None:
    name = PurePosixPath(name.replace("\\", "/")).name
    suffix = PurePosixPath(name).suffix.lower()
    if suffix in CONVERTED_IMPORT_EXTENSIONS:
        return name
    if suffix in {".json", ".html", ".htm", ".md", ".markdown", ".txt"}:
        return None
    if content.startswith(b"%PDF-"):
        return "source.pdf"
    suffix = mimetypes.guess_extension(media_type.split(";", 1)[0].strip().lower())
    return "source" + suffix if suffix in CONVERTED_IMPORT_EXTENSIONS else None


class _MediaReferences(HTMLParser):
    def __init__(self, references: dict[str, str]) -> None:
        super().__init__(convert_charrefs=True)
        self.references = references
        self.owned_uris = set(references.values())
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        rewritten: list[tuple[str, str]] = []
        for key, raw in attrs:
            value = raw or ""
            if (tag, key) in {("img", "src"), ("a", "href")}:
                value = self.references.get(unquote(value), value)
                if tag == "img" and value not in self.owned_uris:
                    raise ValueError("Converted image is missing or refers outside the imported file")
            rewritten.append((key, value))
        self.parts.append("<" + tag + "".join(f' {key}="{escape(value, quote=True)}"' for key, value in rewritten) + ">")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag not in {"img", "br", "hr", "col"}:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data, quote=False))


def _editable_html(content: str, references: dict[str, str]) -> str:
    parser = _MediaReferences(references)
    parser.feed(content)
    parser.close()
    # Imported Office styling, scripts and external embeds are not authored apps.
    clean = nh3.clean("".join(parser.parts),
        tags=set("p h1 h2 h3 h4 h5 h6 strong em b i u s del blockquote ul ol li hr a table thead tbody tfoot tr th td pre code br span img figure figcaption caption colgroup col sub sup".split()),
        attributes={"a": {"href", "title"}, "img": {"src", "alt"}, "th": {"colspan", "rowspan"},
                    "td": {"colspan", "rowspan"}, "ol": {"start"}},
        clean_content_tags={"script", "style", "iframe", "object", "embed"},
        url_schemes={"https", "http", "mailto", "document", "memory", "data", "galaris"}, link_rel=None)
    return normalize_html(clean, profile="document")


@asynccontextmanager
async def prepare_converted_import(
    name: str, media_type: str, content: bytes, *, original_name: str | None = None, convert: bool = True,
) -> AsyncGenerator[PreparedDocumentClone]:
    identity = uuid4()
    storage = get_attachment_storage()
    attachments: list[DocumentAttachmentPublic] = []

    async def attach(filename: str, mime: str, raw: bytes) -> str:
        validate_document_size(raw)
        mime = validate_attachment_content(mime, filename, raw)
        identifier = UUID(await storage.create(raw))
        attachments.append(DocumentAttachmentPublic(id=identifier, name=filename[:500], media_type=mime,
            size_bytes=len(raw), created_at=datetime.now(timezone.utc)))
        return f"document://{identity}/attachments/{identifier}"

    try:
        with TemporaryDirectory(prefix="document-content-import-") as temporary:
            directory = Path(temporary)
            source = directory / "source"
            await complete_io(source.write_bytes, content)
            prepared_dir = directory / "prepared"
            prepared = await prepare_document(source, name, media_type, prepared_dir, editable=True) if convert else None
            await attach(PurePosixPath((original_name or name).replace("\\", "/")).name or name,
                         mimetypes.guess_type(name)[0] or media_type, content)
            if prepared is None:
                html = ""
            elif prepared.html:
                references: dict[str, str] = {}
                for relative in prepared.assets:
                    path = prepared_dir / relative
                    if path.is_symlink() or not path.resolve().is_relative_to(prepared_dir.resolve()) or not path.is_file():
                        raise ValueError("Invalid imported media path")
                    references[relative] = await attach(path.name, mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                                                        await complete_io(path.read_bytes))
                html = _editable_html(prepared.html, references)
            else:
                parts: list[str] = []
                for page in prepared.pages:
                    if page.text.strip():
                        parts.append("<p>" + escape(page.text).replace("\n", "<br>") + "</p>")
                    image = prepared.image_path(page, prepared_dir)
                    if image is None:
                        raise ValueError("Document conversion produced no page image")
                    uri = await attach(f"page-{page.number}.png", "image/png", await complete_io(image.read_bytes))
                    parts.append(f'<figure><img src="{uri}" alt=""></figure>')
                if not prepared.pages:
                    raise ValueError("Document conversion produced no content")
                html = "".join(parts)
            html = normalize_html(html, profile="document")
            validate_document_size(html)
            embedded = image_references(html)
            retained = frozenset(attachment.id for attachment in attachments
                if f"document://{identity}/attachments/{attachment.id}" in embedded)
            yield PreparedDocumentClone(identity, html, tuple(attachments), retained)
    except BaseException:
        async def discard_unpublished() -> None:
            for attachment in attachments:
                try:
                    await storage.delete(str(attachment.id))
                except Exception:
                    logger.exception("Unable to clean up unpublished imported document media")
        await complete_await(discard_unpublished())
        raise
