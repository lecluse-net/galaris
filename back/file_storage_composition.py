"""DbAdmin composition of legacy Chat and document attachment stores."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet
from core.storage.migration import (
    LegacyFile, cleanup_legacy_files, legacy_files_verified, transfer_legacy_files,
)


def needs_file_storage(delta: SchemaTransitionSet) -> bool:
    return delta.table_added("files") or delta.table_added("file_aliases")


@dataclass
class _Candidate:
    name: str
    media_type: str
    aliases: set[str] = field(default_factory=set[str])


async def legacy_inventory(session: AsyncSession) -> list[LegacyFile]:
    """Read local ownership only. No transport/provider is instantiated here."""
    # SHARE locks exclude legacy writers for the transaction. Upgrade orchestration
    # also stops old application workers before launching DbAdmin.
    await session.execute(text("SET LOCAL lock_timeout = '10s'"))
    for table in ("documents", "document_revisions", "memory_items", "memory_revisions", "document_attachments", "messenger_files", "messenger_messages", "messenger_message_files"):
        await session.execute(text(f"LOCK TABLE {table} IN SHARE MODE"))
    entries: dict[tuple[str, str], _Candidate] = {}

    def add(kind: str, identifier: object, name: object, mime: object, alias: str) -> None:
        uuid = str(UUID(str(identifier)))
        entry = entries.setdefault((kind, uuid), _Candidate(
            name=str(name or uuid), media_type=str(mime or "application/octet-stream"),
        ))
        entry.aliases.add(alias)

    rows = await session.execute(text("""
        SELECT id AS document_uuid, metadata FROM documents
        UNION ALL SELECT document_id, metadata FROM document_revisions
        UNION ALL SELECT id, metadata FROM memory_items
        UNION ALL SELECT item_id, metadata FROM memory_revisions
    """))
    snapshots = [(row.document_uuid, row.metadata, False) for row in rows]
    if await session.scalar(text("SELECT to_regclass('galaris_migration.memory_document_split_rows') IS NOT NULL")):
        archived = await session.execute(text("""
            SELECT COALESCE(snapshot->>'item_id', snapshot->>'id') AS document_uuid,
                   snapshot->'metadata' AS metadata
            FROM galaris_migration.memory_document_split_rows
            WHERE table_name IN ('memory_items', 'memory_revisions')
        """))
        snapshots.extend((row.document_uuid, row.metadata, True) for row in archived)
    if await session.scalar(text("SELECT to_regclass('galaris_migration.document_independence_rows') IS NOT NULL")):
        archived = await session.execute(text("""
            SELECT COALESCE(snapshot->>'document_id', snapshot->>'item_id', snapshot->>'id') AS document_uuid,
                   snapshot->'metadata' AS metadata
            FROM galaris_migration.document_independence_rows
            WHERE source IN ('documents', 'document_revisions', 'memory_items', 'memory_revisions')
        """))
        snapshots.extend((row.document_uuid, row.metadata, True) for row in archived)
    for document_uuid, metadata, is_archived in snapshots:
        if not isinstance(metadata, dict):
            continue
        payload = cast(dict[str, object], metadata)
        document_id = UUID(str(document_uuid))
        for key in ("document_attachments", "retained_document_attachments"):
            attachments = payload.get(key, [])
            if not isinstance(attachments, list):
                raise ValueError("Invalid internal document attachment inventory")
            for raw in cast(list[object], attachments):
                if not isinstance(raw, dict):
                    raise ValueError("Invalid internal document attachment identity")
                attachment = cast(dict[str, object], raw)
                if not attachment.get("id"):
                    raise ValueError("Invalid internal document attachment identity")
                identifier = UUID(str(attachment["id"]))
                add("document", identifier, attachment.get("name"), attachment.get("media_type"),
                    f"document://{document_id}/attachments/{identifier}")
                if is_archived:
                    add("document", identifier, attachment.get("name"), attachment.get("media_type"),
                        f"archive-file://memory-document-split/{document_id}/{identifier}")
    # Explicit forget leaves attachment-description tombstones. Their bytes may
    # already have been erased by the old store and are not migration sources.
    # Historical manifests and immutable archives above remain authoritative.
    for row in await session.execute(text("""
        SELECT a.id, a.document_id FROM document_attachments a
        JOIN documents d ON d.id = a.document_id AND d.deleted_at IS NULL
    """)):
        if ("document", str(row.id)) not in entries:
            add("document", row.id, str(row.id), None, f"document://{row.document_id}/attachments/{row.id}")
    # Tool ownership, rather than a non-null local UUID, distinguishes native
    # files from Nextcloud/Matrix/etc. Their existing rows and URIs are untouched.
    rows = await session.execute(text("""
        SELECT f.id, f.name, f.mime_type, m.room_id
        FROM messenger_files f
        JOIN connections c ON c.id = f.connection_id
        JOIN tools t ON t.id = c.tool_id AND t.code = 'chat'
        LEFT JOIN messenger_message_files a ON a.file_id = f.id
        LEFT JOIN messenger_messages m ON m.id = a.message_id
        ORDER BY f.id, m.room_id
    """))
    from app.messenger import attachment_resource_uri

    for row in rows:
        alias = attachment_resource_uri("chat", row.room_id, row.id) if row.room_id else f"unattached://{row.id}"
        add("chat", row.id, row.name, row.mime_type, alias)
    return [LegacyFile(kind, uuid, entry.name, entry.media_type, tuple(sorted(entry.aliases)))
            for (kind, uuid), entry in sorted(entries.items())]


async def transfer(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await transfer_legacy_files(session, await legacy_inventory(session))


async def verified(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    return await legacy_files_verified(session, await legacy_inventory(session))


async def cleanup(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await cleanup_legacy_files(session, await legacy_inventory(session))


async def cleaned(session: AsyncSession, delta: SchemaTransitionSet) -> bool:
    sources = await legacy_inventory(session)
    if any(source.source.exists() for source in sources):
        return False
    return await legacy_files_verified(session, sources)


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="core.storage.transfer_internal_files", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="verified-inventory-v1", predicate=needs_file_storage,
        handler=transfer, postcondition=verified,
    ))
    registry.register_action(DbAdminAction(
        key="core.storage.remove_verified_legacy_sources", phase=DbAdminPhase.AFTER_CONTRACT,
        checksum="verified-inventory-v1", predicate=needs_file_storage,
        handler=cleanup, postcondition=cleaned,
    ))
