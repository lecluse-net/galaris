"""Source-derived visual evidence shared by all document consumers."""

from pathlib import Path
from PIL import Image


def page_images(path: Path, text: str) -> list[Path]:
    result = [path]
    if len(text.strip()) >= 500:
        return result
    with Image.open(path) as image:
        width, height = image.size
        if min(width, height) < 800:
            return result
        for number, box in enumerate(((0, 0, width // 2, height // 2),
                                     (width // 2, 0, width, height // 2),
                                     (0, height // 2, width // 2, height),
                                     (width // 2, height // 2, width, height)), 1):
            target = path.with_name(f"{path.stem}-detail-{number}.png")
            image.crop(box).save(target)
            result.append(target)
    return result
