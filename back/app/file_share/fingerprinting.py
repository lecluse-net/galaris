"""Complete byte fingerprints acquired by Dream through authorized transports."""

import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID
from sqlalchemy import select
from core.database import get_db
from core.util import complete_io
from app.memory import identify_catalogue_file, catalogue_projection_write, MemoryItem
from .catalogue import descriptor_version, observation_scope, lock_binding, refresh_file_locations
from .models import FileCatalogEntry
from .resource_contracts import ResourceContext
from .resource_observation import suspend_observations


async def fingerprint(source: dict[str, object]) -> str | None:
    from .resource_service import materialize_resource, resource_info
    ctx = ResourceContext(agent_id=int(str(source["agent_id"])), runtime=str(source["runtime"]))
    with suspend_observations():
        before = await resource_info(ctx, source["uri"])
        if before.is_collection or descriptor_version(before.model_dump(exclude={"metadata", "capabilities", "indexing_status"})) != source["version"]:
            return None
        with TemporaryDirectory(prefix="dream-fingerprint-") as temporary:
            path = Path(temporary) / "source"
            # Hash every format, independently of the 32 MiB analysis budget.
            await materialize_resource(ctx, source["uri"], path, max_bytes=before.size or 64 * 1024**3)
            def digest() -> str:
                with path.open("rb") as stream:
                    return hashlib.file_digest(stream, "sha256").hexdigest()
            result = await complete_io(digest)
        after = await resource_info(ctx, source["uri"])
        if descriptor_version(after.model_dump(exclude={"metadata", "capabilities", "indexing_status"})) != source["version"]:
            return None
    return result


async def apply_fingerprint(identity: str, version: str, sha256: str) -> bool:
    db = get_db()
    entry = await db.get(FileCatalogEntry, UUID(identity))
    if entry is None or not entry.present or entry.source_version != version:
        return False
    scope = await observation_scope(ResourceContext(agent_id=entry.agent_id, runtime=entry.runtime), entry.uri)
    if scope is None or scope.stamp != entry.binding_stamp or scope.connection_id != entry.connection_id:
        return False
    await lock_binding(scope)
    entry = await db.scalar(select(FileCatalogEntry).where(FileCatalogEntry.id == entry.id).with_for_update().execution_options(populate_existing=True))
    if entry is None or not entry.present or entry.source_version != version or entry.memory_node_id is None:
        return False
    if entry.fingerprint_version == version and entry.file_sha256 == sha256:
        return False
    from .resource_service import resource_info
    with suspend_observations():
        current = await resource_info(ResourceContext(agent_id=entry.agent_id, runtime=entry.runtime), entry.uri)
    if descriptor_version(current.model_dump(exclude={"metadata", "capabilities", "indexing_status"})) != version:
        return False
    async with catalogue_projection_write():
        previous = entry.memory_node_id
        canonical = await identify_catalogue_file(previous, entry.agent_id, sha256)
        # Byte identity is evidence; Memory maintenance will merge duplicates.
        entry.file_sha256 = sha256
        entry.fingerprint_version = version
        fiche = await db.get(MemoryItem, canonical)
        if fiche is not None and fiche.metadata_.get("file_summary_sha256") == sha256:
            entry.enrichment_text = str(fiche.metadata_.get("file_summary", ""))
            entry.enrichment_version = version
        await db.flush()
        await refresh_file_locations(canonical)
    return True
