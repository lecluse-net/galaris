"""Versioned catalogue enrichment port; preserves manually curated Memory fields."""

from pathlib import Path
from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select, Select, or_, func
from core.database import get_db
from app.memory import catalogue_projection_write
from .catalogue import project_entry, descriptor_version
from .models import FileCatalogEntry
from .resource_contracts import ResourceContext
from .resource_observation import suspend_observations


def pending_enrichments() -> Select[tuple[FileCatalogEntry]]:
    return select(FileCatalogEntry).where(FileCatalogEntry.present.is_(True),
        FileCatalogEntry.memory_item_id.is_not(None),
        or_(FileCatalogEntry.enrichment_version.is_(None), FileCatalogEntry.source_version.is_(None),
            FileCatalogEntry.enrichment_version != FileCatalogEntry.source_version),
        FileCatalogEntry.descriptor["is_collection"].as_boolean().is_(False))


async def apply_enrichment(identity: UUID, version: str, description: str) -> bool:
    from .resource_service import resource_info
    entry = await get_db().scalar(select(FileCatalogEntry).where(FileCatalogEntry.id == identity))
    if entry is None or not entry.present or descriptor_version(entry.descriptor) != version:
        return False
    ctx = ResourceContext(agent_id=entry.agent_id, runtime=entry.runtime)
    from .catalogue import observation_scope, lock_binding
    scope = await observation_scope(ctx, entry.uri)
    if scope is None or scope.connection_id != entry.connection_id or scope.stamp != entry.binding_stamp:
        return False
    await lock_binding(scope)
    entry = await get_db().scalar(select(FileCatalogEntry).where(FileCatalogEntry.id == identity).with_for_update().execution_options(populate_existing=True))
    if entry is None or not entry.present or descriptor_version(entry.descriptor) != version:
        return False
    with suspend_observations():
        current = await resource_info(ctx, entry.uri)
    safe = current.model_dump(exclude={"metadata", "capabilities", "indexing_status"})
    if descriptor_version(safe) != version:
        return False
    if entry.enrichment_version == version:
        return False
    entry.enrichment_version = version
    entry.enrichment_text = description[:50000]
    async with catalogue_projection_write():
        await project_entry(entry)
    await get_db().flush()
    return True


class FileCatalogueEnrichmentPort:
    async def candidates(self) -> list[dict[str, object]]:
        from .catalogue import current_binding, ObservationScope
        entries = await get_db().scalars(pending_enrichments().order_by(func.coalesce(FileCatalogEntry.enrichment_attempted_at, FileCatalogEntry.last_seen_at), FileCatalogEntry.id).limit(500))
        result: list[dict[str, object]] = []
        for entry in entries:
            if entry.connection_id is None or entry.enrichment_version == descriptor_version(entry.descriptor):
                continue
            if not await current_binding(ObservationScope(entry.connection_id, entry.agent_id, entry.binding_stamp,
                entry.runtime, entry.operation_started_at)):
                continue
            result.append({"identity": str(entry.id), "uri": entry.uri, "agent_id": entry.agent_id,
                "runtime": entry.runtime, "version": descriptor_version(entry.descriptor), "descriptor": entry.descriptor})
        return result

    async def claimed(self, identity: str) -> None:
        entry = await get_db().get(FileCatalogEntry, UUID(identity))
        if entry is not None:
            entry.enrichment_attempted_at = datetime.now(timezone.utc)

    async def materialize(self, source: dict[str, object], path: "Path") -> dict[str, object] | None:
        from .resource_service import resource_info, materialize_resource
        ctx = ResourceContext(agent_id=int(str(source["agent_id"])), runtime=str(source["runtime"]))
        with suspend_observations():
            info = await resource_info(ctx, source["uri"])
            if descriptor_version(info.model_dump(exclude={"metadata", "capabilities", "indexing_status"})) != source["version"]:
                return None
            if info.size is not None and info.size > 32 * 1024 * 1024:
                return None
            await materialize_resource(ctx, source["uri"], path, max_bytes=32 * 1024 * 1024)
            after = await resource_info(ctx, source["uri"])
            if descriptor_version(after.model_dump(exclude={"metadata", "capabilities", "indexing_status"})) != source["version"]:
                return None
        return {"name": info.name, "media_type": info.media_type, "agent_id": ctx.agent_id}

    async def apply(self, identity: str, version: str, description: str) -> bool:
        return await apply_enrichment(UUID(identity), version, description)
