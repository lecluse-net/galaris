"""Sample drawing codec. Documents remains the owner of the bytes and revisions."""

from io import BytesIO
from collections.abc import Callable

from PIL import Image, ImageChops, UnidentifiedImageError
from PIL.PngImagePlugin import PngImageFile
from pydantic import JsonValue

from app.document import DocumentFormatDefinition, DocumentRevisionRegion, register_document_format

CODE = "sample.drawing"
PROVIDER = "sample.drawing"
MAX_BYTES = 8 * 1024 * 1024
MAX_SIDE = 2048


def validate_png(content: bytes) -> None:
    if len(content) > MAX_BYTES:
        raise ValueError("PNG exceeds the drawing size limit")
    try:
        with Image.open(BytesIO(content), formats=["PNG"]) as image:
            if not isinstance(image, PngImageFile) or max(image.size) > MAX_SIDE or image.is_animated:
                raise ValueError("Drawing requires a single PNG frame up to 2048 pixels per side")
            image.verify()
        with Image.open(BytesIO(content), formats=["PNG"]) as image:
            image.load()
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("Invalid PNG drawing") from exc


def _reject_text(_: str) -> None:
    raise ValueError("Drawings use PNG bytes")


def empty_drawing() -> bytes:
    output = BytesIO()
    with Image.new("RGBA", (960, 640)) as image:
        image.save(output, format="PNG")
    return output.getvalue()


def compare_drawings(before: bytes, after: bytes, region: DocumentRevisionRegion | None) -> dict[str, JsonValue]:
    validate_png(before)
    validate_png(after)
    with Image.open(BytesIO(before)) as left, Image.open(BytesIO(after)) as right:
        width, height = max(left.width, right.width), max(left.height, right.height)
        x, y = (region.x, region.y) if region is not None else (0, 0)
        if x >= width or y >= height:
            raise ValueError("The comparison region is outside the drawings")
        if region is not None:
            width, height = min(width, x + region.width), min(height, y + region.height)
        area = (x, y, width, height)
        # Premultiply alpha so different hidden colours count as the same visible pixel.
        with left.convert("RGBA").convert("RGBa").crop(area) as old_pixels, right.convert("RGBA").convert("RGBa").crop(area) as new_pixels:
            difference = ImageChops.difference(old_pixels, new_pixels)
            red, green, blue, alpha = difference.split()
            mask = ImageChops.lighter(ImageChops.lighter(red, green), ImageChops.lighter(blue, alpha))
            box = mask.getbbox()
            changed = mask.width * mask.height - mask.histogram()[0]
        return {"unit": "pixel", "before_size": [left.width, left.height], "after_size": [right.width, right.height],
            "compared_region": {"x": x, "y": y, "width": width - x, "height": height - y},
            "changed_pixels": changed, "changed_bounds": None if box is None else {
                "x": x + box[0], "y": y + box[1], "width": box[2] - box[0], "height": box[3] - box[1],
            }}


def definition() -> DocumentFormatDefinition:
    return DocumentFormatDefinition(
        code=CODE,
        provider=PROVIDER,
        version=1,
        media_type="image/png",
        storage_kind="file",
        icon="brush",
        initial_content="",
        initial_binary=empty_drawing(),
        validate=_reject_text,
        validate_binary=validate_png,
        extract=lambda _: "",
        surfaces=frozenset({"editor", "preview", "pdf", "native_export", "import"}),
        import_extensions=(".png",),
        compare_revisions=compare_drawings,
    )


def register(*, available: Callable[[], bool] | None = None) -> None:
    register_document_format(definition(), available=available)
