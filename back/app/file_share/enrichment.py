"""Versioned catalogue enrichment port; preserves manually curated Memory fields."""

from pathlib import Path
from datetime import datetime, timezone
from uuid import UUID
from typing import Any
from sqlalchemy import select, Select, or_, func, update
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
    if entry.file_sha256 is not None and entry.memory_item_id is not None:
        from app.memory import catalogue_file_summary
        async with catalogue_projection_write():
            changed = await catalogue_file_summary(entry.memory_item_id, entry.file_sha256, description)
        await get_db().execute(update(FileCatalogEntry).where(
            FileCatalogEntry.memory_item_id == entry.memory_item_id,
            FileCatalogEntry.file_sha256 == entry.file_sha256,
        ).values(enrichment_version=FileCatalogEntry.source_version, enrichment_text=description[:50000]))
        return changed
    entry.enrichment_version = version
    entry.enrichment_text = description[:50000]
    async with catalogue_projection_write():
        await project_entry(entry)
    await get_db().flush()
    return True


class FileCatalogueEnrichmentPort:
    async def thumbnail_pending(self, handled: Select[tuple[str]]) -> int:
        from .thumbnail_service import count_pending
        return await count_pending(handled)

    async def thumbnail_source(self, handled: Select[tuple[str]]) -> dict[str, Any] | None:
        from .thumbnail_service import next_source
        return await next_source(handled)

    async def thumbnail_generate(self, source: dict[str, Any]) -> bool:
        from .thumbnail_service import generate
        return await generate(source)

    async def fingerprints(self) -> list[dict[str, object]]:
        from .catalogue import current_binding, ObservationScope
        entries = await get_db().scalars(select(FileCatalogEntry).where(
            FileCatalogEntry.present.is_(True), FileCatalogEntry.memory_item_id.is_not(None),
            FileCatalogEntry.descriptor["is_collection"].as_boolean().is_(False),
            or_(FileCatalogEntry.fingerprint_version.is_(None), FileCatalogEntry.fingerprint_version != FileCatalogEntry.source_version),
        ).order_by(func.coalesce(FileCatalogEntry.enrichment_attempted_at, FileCatalogEntry.last_seen_at), FileCatalogEntry.id).limit(500))
        result: list[dict[str, object]] = []
        for entry in entries:
            if entry.connection_id is not None and await current_binding(ObservationScope(entry.connection_id, entry.agent_id, entry.binding_stamp, entry.runtime, entry.operation_started_at)):
                result.append({"identity": str(entry.id), "uri": entry.uri, "agent_id": entry.agent_id,
                    "runtime": entry.runtime, "version": entry.source_version})
        return result

    async def fingerprint(self, source: dict[str, object]) -> str | None:
        from .fingerprinting import fingerprint
        return await fingerprint(source)

    async def identify(self, identity: str, version: str, sha256: str) -> bool:
        from .fingerprinting import apply_fingerprint
        return await apply_fingerprint(identity, version, sha256)

    async def discovery_pending(self, claimed: list[dict[str, str]]) -> int:
        from .indexing import discovery_pending
        return await discovery_pending(claimed)

    async def discovery_subjects(self, unavailable: list[dict[str, str]]) -> list[dict[str, str]]:
        from .indexing import discovery_subjects
        return await discovery_subjects(unavailable)

    async def discover(self, subject: dict[str, str], *, attempt: int, max_attempts: int) -> int:
        from .indexing import discover_directory
        return await discover_directory(subject, attempt=attempt, max_attempts=max_attempts)

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
                "runtime": entry.runtime, "version": descriptor_version(entry.descriptor), "descriptor": entry.descriptor,
                "file_sha256": entry.file_sha256, "memory_item_id": str(entry.memory_item_id)})
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
