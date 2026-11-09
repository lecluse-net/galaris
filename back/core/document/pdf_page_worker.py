"""Render one physical PDF page in a resource-limited child process."""

import json
from pathlib import Path
import resource
import sys
from typing import Any


def render(source: Path, destination: Path, number: int) -> dict[str, int]:
    if source.stat().st_size > 64_000_000:
        raise ValueError("PDF exceeds the 64 MB rendering limit")
    with source.open("rb") as stream:
        if not stream.read(8).startswith(b"%PDF-"):
            raise ValueError("The source is not a PDF")
    import pypdfium2 as pdfium  # type: ignore[import-untyped]

    document: Any = pdfium.PdfDocument(str(source))
    try:
        count = len(document)
        if not 1 <= number <= count:
            raise ValueError(f"Select a physical page between 1 and {count}")
        page = document[number - 1]
        try:
            width, height = page.get_size()
            if not (0 < width <= 1_000_000 and 0 < height <= 1_000_000):
                raise ValueError("PDF page dimensions are invalid")
            bitmap = page.render(scale=min(2.0, 3000 / max(width, height)))
            try:
                image = bitmap.to_pil()
                try:
                    image.save(destination, format="PNG")
                    return {"page": number, "page_count": count, "width": image.width, "height": image.height}
                finally:
                    image.close()
            finally:
                bitmap.close()
        finally:
            page.close()
    finally:
        document.close()


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (2 * 1024**3, 2 * 1024**3))
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32_000_000, 32_000_000))
    try:
        print(json.dumps(render(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))))
    except ValueError as error:
        # Only our bounded validation messages cross the worker boundary.
        print(json.dumps({"error": str(error)[:200]}))
        raise SystemExit(2)
    except Exception:
        raise SystemExit(2)
