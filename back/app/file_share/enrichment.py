"""Versioned catalogue enrichment port; preserves manually curated Memory fields."""

from pathlib import Path
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from uuid import UUID
from typing import Any
from sqlalchemy import select, Select, or_, func, update
from core.database import get_db
from core.util import complete_io
from app.memory import catalogue_projection_write, redact_secrets
from .catalogue import catalogue_binding_is_current, project_entry, descriptor_version, indexed_mail_account
from .models import FileCatalogEntry
from .resource_contracts import ResourceContext
from .resource_observation import suspend_observations
from .resource_uri import parse_resource_uri


def pending_enrichments() -> Select[tuple[FileCatalogEntry]]:
    return select(FileCatalogEntry).where(FileCatalogEntry.present.is_(True),
        FileCatalogEntry.memory_node_id.is_not(None),
        or_(FileCatalogEntry.enrichment_version.is_(None), FileCatalogEntry.source_version.is_(None),
            FileCatalogEntry.enrichment_version != FileCatalogEntry.source_version),
        FileCatalogEntry.descriptor["is_collection"].as_boolean().is_(False))


async def apply_enrichment(
    identity: UUID, version: str, description: str, *, force: bool = False,
    expected_item: tuple[UUID, int, int] | None = None,
) -> bool:
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
    if expected_item is not None:
        from app.memory import MemoryItem
        item_id, revision, agent_id = expected_item
        if entry.memory_node_id != item_id or entry.agent_id != agent_id:
            return False
        # Preserve the automatic path's binding -> entry -> Memory lock order.
        item = await get_db().scalar(select(MemoryItem).where(
            MemoryItem.id == item_id, MemoryItem.deleted_at.is_(None),
        ).with_for_update().execution_options(populate_existing=True))
        if item is None or item.revision != revision or item.owner_agent_id != agent_id:
            return False
    with suspend_observations():
        current = await resource_info(ctx, entry.uri)
    safe = current.model_dump(exclude={"metadata", "capabilities", "indexing_status"})
    if descriptor_version(safe) != version:
        return False
    if entry.enrichment_version == version and not force:
        return False
    if (entry.file_sha256 is not None and entry.memory_node_id is not None
            and indexed_mail_account(parse_resource_uri(entry.uri)) is None):
        from app.memory import catalogue_file_summary
        async with catalogue_projection_write():
            changed = await catalogue_file_summary(entry.memory_node_id, entry.file_sha256, description, force=force)
        await get_db().execute(update(FileCatalogEntry).where(
            FileCatalogEntry.memory_node_id == entry.memory_node_id,
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
    def __init__(self, *, shared_index: bool = False) -> None:
        self.shared_index = shared_index

    async def resource_index_pending(self, handled: Select[tuple[str]]) -> int:
        from .resource_index import pending_count, pending_vector_count
        return await pending_count(handled) + await pending_vector_count(handled)

    async def resource_index_subjects(self, handled: Select[tuple[str]]) -> list[str]:
        from .resource_index import pending_subjects, pending_vector_subject
        subjects = [subject.value for subject in await pending_subjects(handled)]
        if vectors := await pending_vector_subject(handled):
            subjects.append(vectors)
        return subjects

    async def index_resource(self, subject: str) -> bool:
        from .resource_index import IndexSubject, index_subject, refresh_vectors
        if subject.startswith("vectors:"):
            _kind, content, model = subject.split(":", 2)
            return await refresh_vectors(UUID(content), model)
        return await index_subject(IndexSubject.parse(subject))

    async def source_for_item(self, item_id: UUID, agent_id: int) -> dict[str, Any] | None:
        from .catalogue_resources import authorized_resource
        entries = await get_db().scalars(select(FileCatalogEntry).where(
            FileCatalogEntry.memory_node_id == item_id, FileCatalogEntry.agent_id == agent_id,
            FileCatalogEntry.present.is_(True),
        ).order_by(FileCatalogEntry.id).limit(500))
        for entry in entries:
            try:
                await authorized_resource(item_id, agent_id, entry.id)
            except (PermissionError, FileNotFoundError, IsADirectoryError):
                continue
            return {"identity": str(entry.id), "uri": entry.uri, "agent_id": agent_id,
                "runtime": entry.runtime, "version": descriptor_version(entry.descriptor),
                "descriptor": dict(entry.descriptor), "file_sha256": entry.file_sha256,
                "binding_stamp": entry.binding_stamp}
        return None

    async def apply_manual(self, source: dict[str, Any], description: str) -> bool:
        return await apply_enrichment(UUID(source["identity"]), str(source["version"]), description,
            force=True, expected_item=(UUID(source["item_id"]), int(source["memory_revision"]), int(source["agent_id"])))

    async def thumbnail_pending(self, handled: Select[tuple[str]]) -> int:
        from .thumbnail_service import count_pending
        return await count_pending(handled)

    async def thumbnail_source(self, handled: Select[tuple[str]]) -> dict[str, Any] | None:
        from .thumbnail_service import next_source
        return await next_source(handled)

    async def thumbnail_generate(self, source: dict[str, Any], *, force: bool = False) -> bool:
        from .thumbnail_service import generate
        return await generate(source, force=force)

    async def fingerprints(self) -> list[dict[str, object]]:
        entries = await get_db().execute(select(FileCatalogEntry, catalogue_binding_is_current()).where(
            FileCatalogEntry.present.is_(True), FileCatalogEntry.memory_node_id.is_not(None),
            FileCatalogEntry.descriptor["is_collection"].as_boolean().is_(False),
            or_(FileCatalogEntry.fingerprint_version.is_(None), FileCatalogEntry.fingerprint_version != FileCatalogEntry.source_version),
        ).order_by(func.coalesce(FileCatalogEntry.enrichment_attempted_at, FileCatalogEntry.last_seen_at), FileCatalogEntry.id).limit(500))
        result: list[dict[str, object]] = []
        for entry, current_binding in entries:
            if current_binding:
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

    async def candidates(self, *, plain_text_only: bool = False) -> list[dict[str, object]]:
        pending = pending_enrichments()
        if self.shared_index:
            from .resource_index import catalogue_text_supported
            if plain_text_only:
                return []
            pending = pending.where(~catalogue_text_supported())
        if plain_text_only:
            pending = pending.where(FileCatalogEntry.descriptor["media_type"].as_string() == "text/vnd.galaris.mail")
        entries = await get_db().execute(
            pending.add_columns(catalogue_binding_is_current())
            .order_by(func.coalesce(FileCatalogEntry.enrichment_attempted_at, FileCatalogEntry.last_seen_at), FileCatalogEntry.id)
            .limit(500)
        )
        result: list[dict[str, object]] = []
        for entry, current_binding in entries:
            if not current_binding:
                continue
            version = descriptor_version(entry.descriptor)
            if entry.enrichment_version == version:
                continue
            result.append({"identity": str(entry.id), "uri": entry.uri, "agent_id": entry.agent_id,
                "runtime": entry.runtime, "version": version, "descriptor": entry.descriptor,
                "file_sha256": entry.file_sha256, "memory_item_id": str(entry.memory_node_id),
                "deduplicate": indexed_mail_account(parse_resource_uri(entry.uri)) is None})
        return result

    async def claimed(self, identity: str) -> None:
        entry = await get_db().get(FileCatalogEntry, UUID(identity))
        if entry is not None:
            entry.enrichment_attempted_at = datetime.now(timezone.utc)

    async def materialize(self, source: dict[str, object], path: "Path") -> dict[str, object] | None:
        from .fingerprinting import hash_materialized_file
        from .resource_service import resource_info, materialize_resource
        ctx = ResourceContext(agent_id=int(str(source["agent_id"])), runtime=str(source["runtime"]))
        with suspend_observations():
            info = await resource_info(ctx, source["uri"])
            if descriptor_version(info.model_dump(exclude={"metadata", "capabilities", "indexing_status"})) != source["version"]:
                return None
            if info.size is not None and info.size > 32 * 1024 * 1024:
                return None
            await materialize_resource(ctx, source["uri"], path, max_bytes=32 * 1024 * 1024)
            expected_hash = source.get("file_sha256")
            if expected_hash is not None and await hash_materialized_file(path) != expected_hash:
                return None
            after = await resource_info(ctx, source["uri"])
            if descriptor_version(after.model_dump(exclude={"metadata", "capabilities", "indexing_status"})) != source["version"]:
                return None
        return {"name": info.name, "media_type": info.media_type, "agent_id": ctx.agent_id}

    async def apply(self, identity: str, version: str, description: str) -> bool:
        return await apply_enrichment(UUID(identity), version, description)

    async def index_plain_text(self, source: dict[str, object]) -> bool:
        # Keep the source text in its access-controlled projection, not in Dream diagnostics.
        with TemporaryDirectory(prefix="dream-mail-") as temporary:
            path = Path(temporary) / "body"
            info = await self.materialize(source, path)
            if info is None or info["media_type"] != "text/vnd.galaris.mail":
                return False
            text = redact_secrets(await complete_io(path.read_text, encoding="utf-8"))
        return text is not None and bool(text.strip()) and await self.apply(str(source["identity"]), str(source["version"]), text)
