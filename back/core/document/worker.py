"""Isolated document worker: conversion, page text, rasterization and optional OCR."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import resource
import shutil
import subprocess
import sys
from zipfile import ZipFile
from typing import Any

from PIL import Image
from .contracts import OFFICE_EXTENSIONS
from .spreadsheets import spreadsheet_text

MAX_BYTES = 512 * 1024 * 1024
MAX_PAGES = 2000
MAX_TEXT = 10_000_000


def _run(command: list[str], *, timeout: int = 180) -> bytes:
    result = subprocess.run(command, capture_output=True, timeout=timeout, check=False)
    if result.returncode:
        raise ValueError("Document converter failed")
    return result.stdout


def prepare(
    path: Path, name: str, media_type: str, directory: Path, *, preview_only: bool = False,
) -> dict[str, Any]:
    if path.stat().st_size > (64 * 1024 * 1024 if preview_only else MAX_BYTES):
        raise ValueError("Source exceeds document preparation limit")
    directory.mkdir(parents=True, exist_ok=True)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = directory / "manifest.json"
    identity = {"sha256": digest, "name": name, "media_type": media_type, "version": 3}
    if preview_only:
        # A thumbnail checkpoint must never be reused as complete document evidence.
        identity["preview_only"] = True
    previous: dict[str, Any] = {}
    if manifest.is_file():
        previous = json.loads(manifest.read_text(encoding="utf-8"))
        if previous.get("identity") != identity:
            raise ValueError("Document checkpoint belongs to another source or converter version")
        if previous.get("complete") and all(not p.get("image") or (directory / p["image"]).is_file() for p in previous["result"]["pages"]):
            return previous["result"]

    def checkpoint(result: dict[str, Any], *, complete: bool = False) -> None:
        if sum(p.stat().st_size for p in directory.rglob("*") if p.is_file() and not p.is_symlink()) > 2 * 1024**3:
            raise ValueError("Document derivative disk budget exhausted")
        if result["pages"]:
            page = result["pages"][-1]
            page_file = directory / f"unit-{page['number']}.json"
            page_tmp = page_file.with_suffix(".tmp")
            page_tmp.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
            page_tmp.replace(page_file)
        temporary = manifest.with_suffix(".tmp")
        # Partial checkpoints write only the cursor, not every previous page again.
        snapshot: dict[str, Any] = result if complete else {**result, "pages": list[dict[str, Any]]()}
        temporary.write_text(json.dumps({"identity": identity, "complete": complete,
            "completed_pages": len(result["pages"]), "result": snapshot}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(manifest)
    suffix = Path(name).suffix.lower()
    with path.open("rb") as stream:
        magic = stream.read(8)
    if magic.startswith(b"%PDF-"):
        suffix = ".pdf"
    elif suffix == ".pdf":
        raise ValueError("File is not a PDF")
    if magic.startswith(b"PK\x03\x04"):
        with ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 20000 or sum(e.file_size for e in entries) > MAX_BYTES or any(e.file_size > 64 * 1024 * 1024 for e in entries):
                raise ValueError("Expanded document exceeds archive limits")
    if magic.startswith((b"\x89PNG", b"\xff\xd8\xff", b"GIF8", b"II*\x00", b"MM\x00*")):
        media_type = "image/unknown"
    result: dict[str, Any] = {"name": name, "sha256": digest, "media_type": media_type,
                              "converted": False, "pages": [], "warnings": []}
    source = path
    if preview_only and suffix not in OFFICE_EXTENSIONS | {".pdf"}:
        raise ValueError("Unsupported document preview format")
    if suffix in OFFICE_EXTENSIONS:
        if shutil.which("soffice") is None:
            raise ValueError("LibreOffice is unavailable")
        office = directory / ("source" + suffix)
        shutil.copyfile(path, office)
        profile = (directory / "office-profile").absolute().as_uri()
        profile_dir = directory / "office-profile" / "user"
        profile_dir.mkdir(parents=True, exist_ok=True)
        (profile_dir / "registrymodifications.xcu").write_text(
            '<?xml version="1.0"?><oor:items xmlns:oor="http://openoffice.org/2001/registry">'
            '<item oor:path="/org.openoffice.Office.Common/Security/Scripting">'
            '<prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop>'
            '<prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop>'
            '</item></oor:items>', encoding="utf-8")
        source = directory / "source.pdf"
        if not source.is_file():
            output_format = "pdf"
            if preview_only:
                pdf_filter = (
                    "calc_pdf_Export" if suffix in {".xls", ".xlsx", ".ods"}
                    else "impress_pdf_Export" if suffix in {".ppt", ".pptx", ".odp"}
                    else "draw_pdf_Export" if suffix == ".odg"
                    else "writer_pdf_Export"
                )
                output_format = f'pdf:{pdf_filter}:{{"PageRange":{{"type":"string","value":"1"}}}}'
            _run(["soffice", f"-env:UserInstallation={profile}", "--headless", "--nologo",
                  "--nodefault", "--norestore", "--convert-to", output_format,
                  "--outdir", str(directory), str(office)], timeout=90 if preview_only else 180)
        if not source.is_file():
            raise ValueError("Office converter produced no PDF")
        result["converted"] = True
        suffix = ".pdf"
        if not preview_only and Path(name).suffix.lower() in {".xlsx", ".ods"}:
            result["structured_text"] = spreadsheet_text(path)
            result["warnings"].append("Spreadsheet source values, formulas and styles preserved separately from printed pages; cached values are not recalculated; display rendering may differ")
        elif not preview_only and Path(name).suffix.lower() == ".xls":
            result["warnings"].append("Legacy spreadsheet rendered to PDF; source formulas and hidden sheets are not fully extracted")
    if suffix == ".pdf":
        import pypdfium2 as pdfium  # type: ignore[import-untyped]

        doc: Any = pdfium.PdfDocument(str(source))
        try:
            if len(doc) > MAX_PAGES:
                raise ValueError("Document exceeds page limit")
            saved = previous.get("result", {}).get("pages", [])
            if previous and not previous.get("complete"):
                saved = [json.loads((directory / f"unit-{number}.json").read_text(encoding="utf-8"))
                         for number in range(1, int(previous.get("completed_pages", 0)) + 1)]
            result["pages"] = [p for p in saved if not p.get("image") or (directory / p["image"]).is_file()]
            if [p["number"] for p in result["pages"]] != list(range(1, len(result["pages"]) + 1)):
                result["pages"] = []
            text_size = sum(len(p["text"]) for p in result["pages"])
            for index in range(min(len(doc), 1) if preview_only else len(doc)):
                if index < len(saved) and index < len(result["pages"]):
                    continue
                page = doc[index]
                text = ""
                if not preview_only:
                    textpage = page.get_textpage()
                    text = textpage.get_text_range()
                    textpage.close()
                # Keep one bounded raster per page on disk; never all pages in memory.
                width, height = page.get_size()
                scale = min(1.0, 640 / max(width, height)) if preview_only else min(2.0, 2400 / max(width, height))
                bitmap = page.render(scale=scale)
                image_name = f"page-{index + 1}.png"
                bitmap.to_pil().save(directory / image_name, format="PNG")
                bitmap.close()
                page.close()
                ocr = False
                warnings: list[str] = []
                if not preview_only and len(text.strip()) < 40 and shutil.which("tesseract"):
                    recognized = _run(["tesseract", str(directory / image_name), "stdout",
                                       "-l", "fra+eng", "--psm", "3"], timeout=90).decode("utf-8").strip()
                    if recognized:
                        text = text + "\n[OCR; verify against page image]\n" + recognized
                        ocr = True
                if not preview_only and not text.strip():
                    warnings.append("no_text; image requires visual interpretation")
                text_size += len(text)
                if text_size > MAX_TEXT:
                    raise ValueError("Document text exceeds preparation budget")
                result["pages"].append({"number": index + 1, "text": text, "image": image_name,
                                         "ocr": ocr, "warnings": warnings})
                checkpoint(result)
        finally:
            doc.close()
    elif media_type.startswith("image/"):
        with Image.open(path) as image:
            frames = getattr(image, "n_frames", 1)
            if frames > MAX_PAGES:
                raise ValueError("Image frame limit exceeded")
            for index in range(frames):
                image.seek(index)
                if image.width * image.height > 40_000_000:
                    raise ValueError("Image pixel limit exceeded")
                frame = image.copy()
                frame.thumbnail((2400, 2400))
                image_name = f"page-{index + 1}.png"
                frame.convert("RGB").save(directory / image_name)
                text = (_run(["tesseract", str(directory / image_name), "stdout", "-l", "fra+eng"])
                        .decode("utf-8") if shutil.which("tesseract") else "")
                result["pages"].append({"number": index + 1, "text": text, "image": image_name, "ocr": bool(text),
                                         "warnings": ["OCR is incomplete evidence; inspect the source image"]})
                checkpoint(result)
    else:
        if suffix in {".md", ".html", ".htm", ".epub"} and shutil.which("pandoc"):
            extension = "html" if suffix in {".html", ".htm"} else "epub" if suffix == ".epub" else "markdown"
            text = _run(["pandoc", "--sandbox", "-f", extension, "-t", "plain", str(path)]).decode("utf-8")
            result["converted"] = True
        elif media_type.startswith("text/") or suffix in {".txt", ".csv", ".tsv", ".json", ".xml"}:
            if path.stat().st_size > MAX_TEXT:
                raise ValueError("Text source exceeds budget")
            data = path.read_bytes()
            text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
            if "\x00" in text:
                raise ValueError("Source is not readable text")
        else:
            raise ValueError("Unsupported document format")
        if len(text) > MAX_TEXT:
            raise ValueError("Converted text exceeds preparation budget")
        result["pages"].append({"number": 1, "text": text})
    if sum(len(p["text"]) for p in result["pages"]) + len(result.get("structured_text", "")) > MAX_TEXT:
        raise ValueError("Document evidence exceeds preparation budget")
    checkpoint(result, complete=True)
    return result


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    preview_only = len(sys.argv) > 5 and sys.argv[5] == "preview"
    cpu_budget = 120 if preview_only else 1200
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_budget, cpu_budget))
    try:
        print(json.dumps(prepare(Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]),
                                 preview_only=preview_only), ensure_ascii=False))
    except Exception:
        raise SystemExit(2)
