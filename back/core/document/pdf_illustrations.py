"""Editable PDF graphics, separate from the full-page evidence used by readers."""

from html import escape
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from PIL import Image

Box = tuple[int, int, int, int]


class _Layout(HTMLParser):
    """Read Tesseract's image regions and recognized text without loading XML entities."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.photos: list[Box] = []
        self.words: list[str] = []
        self.in_word = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        classes = (values.get("class") or "").split()
        if "ocr_photo" in classes:
            match = re.search(r"\bbbox (\d+) (\d+) (\d+) (\d+)", values.get("title") or "")
            if match:
                left, top, right, bottom = (int(value) for value in match.groups())
                self.photos.append((left, top, right, bottom))
        if "ocrx_word" in classes:
            self.in_word = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "span":
            self.in_word = False
        if tag == "p" and self.words:
            self.words.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_word and data.strip():
            self.words.append(data.strip())


def _overlaps(a: Box, b: Box, gap: int = 0) -> bool:
    return a[0] <= b[2] + gap and b[0] <= a[2] + gap and a[1] <= b[3] + gap and b[1] <= a[3] + gap


def _merge(boxes: list[Box]) -> list[Box]:
    result: list[Box] = []
    for box in boxes:
        # Repeat after each union: a composite figure can bridge earlier regions.
        while True:
            adjacent = [other for other in result if _overlaps(box, other, gap=6)]
            if not adjacent:
                break
            result = [other for other in result if other not in adjacent]
            box = (min(b[0] for b in [box, *adjacent]), min(b[1] for b in [box, *adjacent]),
                   max(b[2] for b in [box, *adjacent]), max(b[3] for b in [box, *adjacent]))
        result.append(box)
    return sorted(result, key=lambda box: (box[1], box[0]))


def _text_outside_figures(page: Any, position: Any, boxes: list[Box], fallback: str) -> str:
    if not boxes:
        return fallback
    textpage = page.get_textpage()
    try:
        # Labels inside a diagram remain part of its crop, without a second copy
        # in the editable paragraph. Preserve contiguous native text ranges.
        count = textpage.count_chars()
        if count == 0:
            return fallback
        parts: list[str] = []
        start = 0
        for index in range(count):
            left, bottom, right, top = textpage.get_charbox(index)
            x, y = position.to_bitmap((left + right) / 2, (bottom + top) / 2)
            if any(box[0] <= x <= box[2] and box[1] <= y <= box[3] for box in boxes):
                if start < index:
                    parts.append(textpage.get_text_range(start, index - start))
                start = index + 1
        if start < count:
            parts.append(textpage.get_text_range(start, count - start))
        return "".join(parts)
    finally:
        textpage.close()


def page_content(page: Any, bitmap: Any, text: str, directory: Path, number: int) -> tuple[str, list[str], str, bool]:
    """PDFium objects are a dynamic boundary; only bounded PNG crops leave this worker."""
    import pypdfium2.raw as raw  # type: ignore[import-untyped]

    width, height = int(bitmap.width), int(bitmap.height)
    has_native_text = bool(text.strip())
    position = bitmap.get_posconv(page)
    boxes: list[Box] = []
    needs_layout = False
    for count, obj in enumerate(page.get_objects()):
        if count >= 20000:
            raise ValueError("PDF page object limit exceeded")
        if obj.type not in {raw.FPDF_PAGEOBJ_IMAGE, raw.FPDF_PAGEOBJ_PATH, raw.FPDF_PAGEOBJ_SHADING}:
            continue
        bounds = obj.get_bounds()
        container = obj.container
        while container is not None:
            bounds = container.get_matrix().on_rect(*bounds)
            container = container.container
        left, bottom, right, top = bounds
        points = [position.to_bitmap(x, y) for x, y in ((left, bottom), (left, top), (right, bottom), (right, top))]
        box = (max(0, min(p[0] for p in points)), max(0, min(p[1] for p in points)),
               min(width, max(p[0] for p in points)), min(height, max(p[1] for p in points)))
        area = (box[2] - box[0]) * (box[3] - box[1])
        if area >= width * height * 0.65:
            if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                needs_layout = True  # A scanned page is one image, not one illustration.
            continue  # Also discard page backgrounds.
        if box[2] > box[0] and box[3] > box[1]:
            boxes.append(box)
        if len(boxes) > 2048:
            raise ValueError("PDF illustration complexity limit exceeded")

    boxes = _merge(boxes)
    if any((box[2] - box[0]) * (box[3] - box[1]) >= width * height * 0.65 for box in boxes):
        needs_layout = True  # A scan may also be stored as several adjacent tiles.
    ocr = False
    if needs_layout or not text.strip():
        if shutil.which("tesseract"):
            process = subprocess.run(["tesseract", str(directory / f"page-{number}.png"), "stdout",
                "-l", "fra+eng", "--psm", "3", "hocr"], capture_output=True, timeout=90, check=False)
            if process.returncode:
                raise ValueError("PDF illustration segmentation failed")
            layout = _Layout()
            layout.feed(process.stdout.decode("utf-8"))
            layout.close()
            recognized = " ".join(layout.words).strip()
            if not text.strip() and recognized:
                text, ocr = recognized, True
            if needs_layout or (not has_native_text and recognized):
                boxes = layout.photos
                if not text.strip() and not boxes:
                    boxes = [(0, 0, width, height)]  # A picture with no recognized text.
        elif needs_layout:
            if text.strip():
                raise ValueError("Scanned PDF illustrations require OCR segmentation")
            boxes = [(0, 0, width, height)]

    boxes = [box for box in _merge(boxes) if box[2] - box[0] >= 4 and box[3] - box[1] >= 4]
    assets: list[str] = []
    editable_text = _text_outside_figures(page, position, boxes, text)
    parts = ["<p>" + escape(editable_text).replace("\n", "<br>") + "</p>"] if editable_text.strip() else []
    with Image.open(directory / f"page-{number}.png") as image:
        for index, box in enumerate(boxes, start=1):
            box = (max(0, box[0]), max(0, box[1]), min(width, box[2]), min(height, box[3]))
            if box[0] >= box[2] or box[1] >= box[3]:
                raise ValueError("Invalid PDF illustration bounds")
            asset = f"illustration-{number}-{index}.png"
            with image.crop(box) as crop:
                crop.save(directory / asset)
            assets.append(asset)
            parts.append(f'<figure><img src="{asset}" alt=""></figure>')
    return "".join(parts), assets, text, ocr
