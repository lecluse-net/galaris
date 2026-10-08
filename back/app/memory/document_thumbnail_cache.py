"""Document-scoped disposable captures, invalidated after committed changes."""

from pathlib import Path
from uuid import UUID

from core.preview import thumbnails
from core.settings import settings


def cache_path(document_id: UUID, reference: str) -> Path:
    key = str(document_id)
    return Path(settings.GALARIS_THUMBNAIL_ROOT) / "documents" / key[:2] / key[2:4] / key / thumbnails.cache_path(reference).name


def discard_legacy(document_id: UUID) -> None:
    _clear(Path(settings.GALARIS_THUMBNAIL_ROOT) / "documents" / str(document_id))


def _clear(directory: Path) -> None:
    for pattern in ("*.revision.json", "*.png", "*.webp"):
        for path in directory.glob(pattern):
            path.unlink(missing_ok=True)
    try:
        directory.rmdir()
    except OSError:
        pass


def invalidate(document_id: UUID) -> None:
    discard_legacy(document_id)
    _clear(cache_path(document_id, "").parent)
