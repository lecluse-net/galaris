"""Document-scoped disposable captures, invalidated after committed changes."""

from pathlib import Path
from uuid import UUID

from core.preview import thumbnails
from core.settings import settings


def cache_path(document_id: UUID, reference: str) -> Path:
    return Path(settings.GALARIS_THUMBNAIL_ROOT) / "documents" / str(document_id) / thumbnails.cache_path(reference).name


def invalidate(document_id: UUID) -> None:
    directory = Path(settings.GALARIS_THUMBNAIL_ROOT) / "documents" / str(document_id)
    for pattern in ("*.revision.json", "*.png"):
        for path in directory.glob(pattern):
            path.unlink(missing_ok=True)
