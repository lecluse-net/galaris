"""Native image, Office and PDF conversion in a resource-limited child process."""

from io import BytesIO
import json
from pathlib import Path
import resource
import shutil
import sys
from typing import Any
from zipfile import ZipFile

from PIL import Image, ImageOps, UnidentifiedImageError
from pypdf import PdfWriter

from .contracts import OFFICE_EXTENSIONS
from .office import office_pdf

MAX_BYTES = 64_000_000
IMAGE_FORMATS = frozenset({"PNG", "JPEG", "WEBP", "GIF", "TIFF", "BMP"})
OFFICE_MIMES = {
    "application/msword": ".doc", "application/rtf": ".rtf", "text/rtf": ".rtf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.ms-excel": ".xls", "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.oasis.opendocument.text": ".odt", "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp", "application/vnd.oasis.opendocument.graphics": ".odg",
}


def image_pdf(source: Path, destination: Path) -> bool:
    try:
        image = Image.open(source)
    except UnidentifiedImageError:
        return False
    with image:
        if image.format not in IMAGE_FORMATS:
            raise ValueError("Unsupported image format for PDF export")
        frames = getattr(image, "n_frames", 1)
        if frames > 100:
            raise ValueError("Image PDF export is limited to 100 frames/pages")
        pixels = 0
        encoded_size = 0
        writer = PdfWriter()
        for number in range(frames):
            image.seek(number)
            pixels += image.width * image.height
            if image.width * image.height > 40_000_000 or pixels > 100_000_000:
                raise ValueError("Image pixel budget exceeded")
            with ImageOps.exif_transpose(image) as frame:
                with Image.new("RGB", frame.size, "white") as flattened:
                    with frame.convert("RGBA") as rgba:
                        with rgba.getchannel("A") as alpha:
                            flattened.paste(rgba, mask=alpha)
                    with BytesIO() as content:
                        flattened.save(content, format="PDF", resolution=144, quality=95, subsampling=0)
                        encoded_size += content.getbuffer().nbytes
                        if encoded_size > MAX_BYTES:
                            raise ValueError("PDF output exceeds the 64 MB limit")
                        content.seek(0)
                        writer.append(content)
        writer.write(destination)
    return True


def export(source: Path, name: str, mime: str, directory: Path) -> dict[str, object]:
    if source.stat().st_size > MAX_BYTES:
        raise ValueError("Source exceeds the 64 MB PDF export limit")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "export.pdf"
    with source.open("rb") as stream:
        magic = stream.read(8)
    warnings: list[str] = []
    if magic.startswith(b"%PDF-"):
        shutil.copyfile(source, destination)
    elif not image_pdf(source, destination):
        suffix = Path(name).suffix.lower()
        if suffix not in OFFICE_EXTENSIONS:
            suffix = OFFICE_MIMES.get(mime, "")
        if suffix not in OFFICE_EXTENSIONS:
            raise ValueError("Unsupported source format for PDF export; use an image, Office/OpenDocument, HTML, Markdown or text resource")
        if magic.startswith(b"PK\x03\x04"):
            with ZipFile(source) as archive:
                entries = archive.infolist()
                if len(entries) > 20000 or sum(entry.file_size for entry in entries) > 512 * 1024**2 or any(entry.file_size > 64 * 1024**2 for entry in entries):
                    raise ValueError("Expanded document exceeds archive limits")
        converted = office_pdf(source, suffix, directory)
        shutil.copyfile(converted, destination)
        if suffix in {".xls", ".xlsx", ".ods"}:
            warnings.append("PDF contains the spreadsheet's printable layout; hidden or non-printing cells may not appear.")
    if destination.stat().st_size > MAX_BYTES:
        raise ValueError("PDF output exceeds the 64 MB limit")
    import pypdfium2 as pdfium  # type: ignore[import-untyped]

    document: Any = pdfium.PdfDocument(str(destination))
    try:
        count = len(document)
        if not 1 <= count <= 2000:
            raise ValueError("PDF export requires between 1 and 2000 pages")
        return {"page_count": count, "warnings": warnings}
    finally:
        document.close()


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (180, 180))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))
    try:
        print(json.dumps(export(Path(sys.argv[1]), sys.argv[2], sys.argv[3], Path(sys.argv[4]))))
    except ValueError as error:
        print(json.dumps({"error": str(error)[:300]}))
        raise SystemExit(2)
    except Exception:
        raise SystemExit(2)
