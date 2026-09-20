"""Standalone bounded document-to-text worker, executed without app bootstrap."""

from __future__ import annotations

import json
from pathlib import Path
import resource
import sys
from xml.etree import ElementTree
from zipfile import ZipFile

MAX_CHARS = 2_000_000
MAX_BYTES = 32 * 1024 * 1024
TEXT_TYPES = frozenset({
    "application/json", "application/xml", "application/xhtml+xml",
    "application/yaml", "application/x-yaml", "application/csv",
})
OFFICE_SUFFIXES = frozenset({".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp"})


def _xml(data: bytes) -> ElementTree.Element:
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("Document XML entities are not supported")
    return ElementTree.fromstring(data)


def extract(path: Path, name: str, media_type: str) -> str | None:
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("Document exceeds the 32 MiB extraction limit")
    suffix = Path(name).suffix.lower()
    if media_type == "application/pdf" or suffix == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(path)
        if len(reader.pages) > 500:
            raise ValueError("Document exceeds the 500-page analysis limit")
        parts: list[str] = []
        size = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            size += len(text)
            if size > MAX_CHARS:
                raise ValueError("Extracted document exceeds the text limit")
            parts.append(text)
        return "\n\n".join(parts)
    if suffix in OFFICE_SUFFIXES:
        with ZipFile(path) as archive:
            entries = [entry for entry in archive.infolist() if (
                entry.filename in {"word/document.xml", "word/footnotes.xml", "word/endnotes.xml", "xl/sharedStrings.xml", "content.xml"}
                or entry.filename.startswith(("word/header", "word/footer", "ppt/slides/slide", "ppt/notesSlides/notesSlide", "xl/worksheets/sheet"))
            ) and entry.filename.endswith(".xml")]
            if sum(entry.file_size for entry in entries) > MAX_BYTES:
                raise ValueError("Expanded document exceeds the extraction limit")
            parts = []
            shared: list[str] = []
            if suffix == ".xlsx" and "xl/sharedStrings.xml" in archive.namelist():
                shared = ["".join(item.itertext()) for item in _xml(archive.read("xl/sharedStrings.xml"))]
            for entry in entries:
                if entry.filename == "xl/sharedStrings.xml":
                    continue
                root = _xml(archive.read(entry))
                if entry.filename.startswith("xl/worksheets/"):
                    rows: list[str] = []
                    for row in root.findall(".//{*}row"):
                        cells: list[str] = []
                        for cell in row.findall("{*}c"):
                            value = cell.findtext("{*}v", default="")
                            if cell.get("t") == "s" and value:
                                value = shared[int(value)]
                            elif cell.get("t") == "inlineStr":
                                value = "".join(cell.itertext())
                            cells.append(f"{cell.get('r', '')}: {value}")
                        rows.append(" | ".join(cells))
                    parts.append(entry.filename + "\n" + "\n".join(rows))
                else:
                    parts.append(" ".join(root.itertext()))
            text = "\n\n".join(parts)
    elif media_type.startswith("text/") or media_type in TEXT_TYPES:
        data = path.read_bytes()
        text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        if "\x00" in text:
            raise ValueError("Attachment is not readable text")
    else:
        return None
    if len(text) > MAX_CHARS:
        raise ValueError("Extracted document exceeds the text limit")
    return text


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    try:
        result = {"text": extract(Path(sys.argv[1]), sys.argv[2], sys.argv[3])}
    except Exception as exc:
        result = {"error": str(exc)}
    sys.stdout.write(json.dumps(result))
