"""One disposable capture per document, named by its persisted thumbnail UUID."""

from pathlib import Path
from collections.abc import Iterator
from uuid import UUID

from core.settings import settings


def directory(document_id: UUID) -> Path:
    key = str(document_id)
    return Path(settings.GALARIS_THUMBNAIL_ROOT) / "documents" / key[:2] / key[2:4] / key


def cache_path(document_id: UUID, thumbnail_id: UUID) -> Path:
    return directory(document_id) / f"{thumbnail_id}.webp"


def discard_legacy(document_id: UUID) -> None:
    _clear(Path(settings.GALARIS_THUMBNAIL_ROOT) / "documents" / str(document_id))


def _clear(directory: Path, keep: UUID | None = None) -> None:
    for pattern in ("*.revision.json", "*.png", "*.webp"):
        for path in directory.glob(pattern):
            if keep is None or path.name != f"{keep}.webp":
                path.unlink(missing_ok=True)
    try:
        directory.rmdir()
    except OSError:
        pass


def invalidate(document_id: UUID, keep: UUID | None = None) -> None:
    discard_legacy(document_id)
    _clear(directory(document_id), keep)


def legacy_files() -> Iterator[Path]:
    """Old revision sidecars and hash-named captures; other preview JSONs survive."""
    root = Path(settings.GALARIS_THUMBNAIL_ROOT) / "documents"
    for path in root.rglob("*"):
        if path.suffix == ".png" or path.name.endswith(".revision.json"):
            yield path
        elif path.suffix == ".webp":
            try:
                UUID(path.stem)
            except ValueError:
                yield path


def discard_all_legacy() -> None:
    for path in legacy_files():
        path.unlink(missing_ok=True)
