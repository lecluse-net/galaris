"""Source-derived visual evidence shared by all document consumers."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from PIL import Image


def page_images(path: Path, text: str) -> list[Path]:
    result = [path]
    if len(text.strip()) >= 500:
        return result
    # Hash the same bytes that we decode: timestamps cannot prove that a source
    # is unchanged, and retries must never reuse details from an older version.
    source = path.read_bytes()
    digest = sha256(source).hexdigest()
    targets = [path.with_name(f"{path.stem}-detail-v1-{digest}-{number}.png") for number in range(1, 5)]
    if all(_ready(target) for target in targets):
        return [path, *targets]
    with Image.open(BytesIO(source)) as image:
        width, height = image.size
        if min(width, height) < 800:
            return result
        for target, box in zip(targets, ((0, 0, width // 2, height // 2),
                                     (width // 2, 0, width, height // 2),
                                     (0, height // 2, width // 2, height),
                                     (width // 2, height // 2, width, height)), strict=True):
            if not _ready(target):
                # Publish only complete images, including when two readers race
                # or a cancelled caller is waiting for its worker to finish.
                with NamedTemporaryFile(dir=path.parent, suffix=".png", delete=False) as handle:
                    temporary = Path(handle.name)
                    try:
                        with image.crop(box) as detail:
                            detail.save(handle, format="PNG")
                        handle.close()
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
            result.append(target)
    return result


def _ready(path: Path) -> bool:
    return not path.is_symlink() and path.is_file() and path.stat().st_size > 0
