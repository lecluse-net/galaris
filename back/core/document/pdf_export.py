"""Export supported resource content to a validated PDF without inference."""

import asyncio
import base64
from html import escape
import json
import os
from pathlib import Path
import signal
import sys

from markdown_it import MarkdownIt
from pydantic import BaseModel, Field

from core.util import complete_await, complete_io

_slots = asyncio.Semaphore(2)
MAX_PDF_EXPORT_BYTES = 64_000_000
_TEXT_MAX_BYTES = 8_000_000
_TEXT_EXTENSIONS = frozenset({".html", ".htm", ".md", ".markdown", ".txt", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml"})
_TEXT_MIMES = frozenset({"application/json", "application/xml", "application/yaml", "image/svg+xml"})


class PdfExport(BaseModel):
    page_count: int = Field(ge=1, le=2000)
    warnings: list[str] = Field(default_factory=list)


def _source_html(source: Path, name: str, mime: str) -> str | None:
    suffix = Path(name).suffix.lower()
    with source.open("rb") as stream:
        magic = stream.read(8)
    if magic.startswith(b"%PDF-") or suffix == ".rtf" or mime in {"text/rtf", "application/rtf"}:
        return None
    if not (mime.startswith("text/") or mime in _TEXT_MIMES or suffix in _TEXT_EXTENSIONS or suffix == ".svg"):
        return None
    if source.stat().st_size > _TEXT_MAX_BYTES:
        raise ValueError("Text/HTML PDF export exceeds the 8 MB input limit")
    data = source.read_bytes()
    text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
    if "\x00" in text:
        raise ValueError("Source is not readable text")
    if suffix in {".html", ".htm"} or mime == "text/html":
        return text
    if suffix == ".svg" or mime == "image/svg+xml":
        content = '<img src="data:image/svg+xml;base64,' + base64.b64encode(data).decode("ascii") + '">'
    elif suffix in {".md", ".markdown"} or mime in {"text/markdown", "text/x-markdown"}:
        content = MarkdownIt("commonmark").render(text)
    else:
        content = "<pre>" + escape(text) + "</pre>"
    return ('<!doctype html><meta charset="utf-8"><style>@page{size:A4;margin:16mm}'
        'body{font-family:DejaVu Sans,sans-serif;font-size:11pt}img{max-width:100%}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:10pt}</style>' + content)


async def convert_to_pdf(source: Path, name: str, media_type: str, directory: Path) -> PdfExport:
    """Write directory/export.pdf, preserving all supported pages and the original bytes."""
    mime = media_type.split(";", 1)[0].strip().lower()
    if await complete_io(lambda: source.stat().st_size) > MAX_PDF_EXPORT_BYTES:
        raise ValueError("Source exceeds the 64 MB PDF export limit")
    async with _slots:
        await complete_io(directory.mkdir, parents=True, exist_ok=True)
        markup = await complete_io(_source_html, source, name, mime)
        warnings: list[str] = []
        if markup is not None:
            from core.preview import render_html_pdf

            data = await render_html_pdf(markup)
            source = directory / "rendered.pdf"
            await complete_io(source.write_bytes, data)
            name, mime = "rendered.pdf", "application/pdf"
            warnings.append("Static PDF rendering: scripts and external resources were not loaded.")
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "core.document.pdf_export_worker", str(source), name, mime, str(directory),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
        )
        try:
            async with asyncio.timeout(210):
                output, _ = await process.communicate()
            if process.returncode != 0:
                try:
                    error = str(json.loads(output).get("error", ""))
                except (ValueError, TypeError, AttributeError):
                    error = ""
                raise ValueError(error or "PDF export failed; check format, encryption and conversion limits")
            result = PdfExport.model_validate_json(output)
            return result.model_copy(update={"warnings": [*warnings, *result.warnings]})
        except TimeoutError as error:
            raise ValueError("PDF export exceeded its time budget") from error
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await complete_await(process.wait())
