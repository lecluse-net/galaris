"""Review old unreferenced native files before an explicitly quiescent cleanup."""

import heapq
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select, union

from core import settings
from core.database import get_db
from core.util import complete_io

from .models import MemoryItem, MemoryRevision


@dataclass(frozen=True)
class OrphanCandidate:
    resource_id: str
    size: int
    modified_ns: int


def _scan(root: Path, after: str, limit: int, cutoff: float) -> list[OrphanCandidate]:
    def candidates():
        for shard in root.iterdir() if root.exists() else ():
            if shard.is_symlink() or not shard.is_dir() or len(shard.name) != 2:
                continue
            for path in shard.iterdir():
                if path.name <= after or path.is_symlink() or not path.is_file():
                    continue
                try:
                    if str(UUID(path.name)) != path.name or path.name[:2] != shard.name:
                        continue
                    stat = path.stat()
                except (ValueError, FileNotFoundError):
                    continue
                if stat.st_mtime <= cutoff:
                    yield OrphanCandidate(path.name, stat.st_size, stat.st_mtime_ns)
    return heapq.nsmallest(limit, candidates(), key=lambda item: item.resource_id)


async def _referenced(ids: list[str]) -> set[str]:
    result = await get_db().scalars(union(
        select(MemoryItem.resource_id).where(MemoryItem.provider_code == "native", MemoryItem.resource_id.in_(ids)),
        select(MemoryRevision.resource_id).where(MemoryRevision.provider_code == "native", MemoryRevision.resource_id.in_(ids)),
    ).execution_options(include_historized=True))
    return set(result)


async def preview_native_orphans(*, root: Path | None = None, minimum_age: float = 86400,
                                 after: str = "", limit: int = 500) -> tuple[list[OrphanCandidate], str | None]:
    """Return a bounded review page and cursor; historical revisions remain protected."""
    if minimum_age < 86400 or not 1 <= limit <= 500:
        raise ValueError("Orphan review requires at least one day of age and 1..500 entries")
    candidates = await complete_io(_scan, root or Path(settings.GALARIS_MEMORY_ROOT), after, limit, time.time() - minimum_age)
    references = await _referenced([item.resource_id for item in candidates])
    return [item for item in candidates if item.resource_id not in references], candidates[-1].resource_id if len(candidates) == limit else None


async def remove_reviewed_orphans(reviewed: list[OrphanCandidate], *, quiescent: bool = False,
                                  root: Path | None = None) -> int:
    """Recheck references and exact file metadata; callers must stop all writers first."""
    if not quiescent:
        raise ValueError("Stop application writers before applying the reviewed orphan inventory")
    if len(reviewed) > 500:
        raise ValueError("Cleanup batches are limited to 500 files")
    references = await _referenced([item.resource_id for item in reviewed])
    directory = (root or Path(settings.GALARIS_MEMORY_ROOT)).resolve()
    removed = 0
    for item in reviewed:
        if item.resource_id in references or str(UUID(item.resource_id)) != item.resource_id:
            continue
        path = directory / item.resource_id[:2] / item.resource_id
        if path.parent.is_symlink() or path.is_symlink():
            continue
        try:
            stat = path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (item.size, item.modified_ns) or stat.st_mtime > time.time() - 86400:
                continue
            path.unlink()
            removed += 1
        except FileNotFoundError:
            continue
    return removed
