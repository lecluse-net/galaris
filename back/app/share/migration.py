"""Additive ACL transfer. Legacy rows are retained as read-only upgrade evidence."""

import hashlib
import json
from uuid import uuid5, NAMESPACE_URL

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# These are storage bindings for the one cross-domain schema transfer, not
# runtime resource dispatch. No domain ORM or business service is imported.
_SOURCES = {
    "documents": ("document", ()),
    "document_tags": ("document", ()),
    "memory_items": (
        "memory",
        (
            ("memory_item_grants", "item_id", "agent_id"),
            ("document_user_grants", "item_id", "user_id"),
            ("document_team_grants", "item_id", "team_id"),
        ),
    ),
    "datasets": ("dataset", (("dataset_grants", "dataset_id", None),)),
    "process_definitions": ("process", (("process_definition_grants", "process_id", None),)),
}


async def transfer_resource_acl(session: AsyncSession, table: str) -> None:
    """Backfill a fixed, trusted resource binding without commits or DDL."""
    kind, grant_sources = _SOURCES[table]
    while rows := list(
        (
            await session.execute(
                text(
                    f"SELECT id, to_jsonb(r) AS source FROM public.{table} r WHERE share_id IS NULL ORDER BY id LIMIT 100 FOR UPDATE"
                )
            )
        ).all()
    ):
        for identity, source in rows:
            resource_kind = (
                "document"
                if table == "memory_items" and source.get("node_kind") == "document"
                else kind
            )
            access_source = source
            if table == "memory_items":
                document = await session.scalar(
                    text(
                        "SELECT to_jsonb(d) FROM public.documents d WHERE memory_item_id = :identity"
                    ),
                    {"identity": identity},
                )
                if document is not None:
                    access_source = document
                    resource_kind = "document"
            global_access = int(
                access_source.get("global_access")
                or (1 if access_source.get("visibility") == "public" else 0)
            )
            group_access = int(access_source.get("group_access") or 0)
            grants: list[dict[str, object]] = []
            for grants_table, foreign, principal in grant_sources:
                for grant in (
                    await session.execute(
                        text(
                            f"SELECT to_jsonb(g) FROM public.{grants_table} g WHERE {foreign} = :identity"
                        ),
                        {"identity": identity},
                    )
                ).scalars():
                    values = {key: grant.get(key) for key in ("agent_id", "user_id", "team_id")}
                    if principal is not None:
                        values = {
                            key: grant.get(key) if key == principal else None for key in values
                        }
                    grants.append({**values, "can_write": bool(grant["can_write"])})
            snapshot = {
                "global_access": global_access,
                "group_access": group_access,
                "grants": sorted(grants, key=lambda g: json.dumps(g, sort_keys=True)),
            }
            digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
            share_id = uuid5(NAMESPACE_URL, f"galaris:sharing:{table}:{identity}")
            await session.execute(
                text("""INSERT INTO public.share_configs
                (id, resource_kind, global_access, group_access, revision, legacy_acl_hash)
                VALUES (:id, :kind, :global_access, :group_access, 1, :digest)
                ON CONFLICT (id) DO NOTHING"""),
                {
                    "id": share_id,
                    "kind": resource_kind,
                    "global_access": global_access,
                    "group_access": group_access,
                    "digest": digest,
                },
            )
            existing = (
                await session.execute(
                    text(
                        "SELECT resource_kind, legacy_acl_hash FROM public.share_configs WHERE id = :id"
                    ),
                    {"id": share_id},
                )
            ).one()
            if existing != (resource_kind, digest):
                raise ValueError("Legacy sharing identity conflicts with an existing configuration")
            for grant in grants:
                principal_key = next(
                    f"{key}:{value}"
                    for key, value in grant.items()
                    if key.endswith("_id") and value is not None
                )
                grant_id = uuid5(share_id, principal_key)
                await session.execute(
                    text("""INSERT INTO public.share_grants
                    (id, share_id, agent_id, user_id, team_id, can_write)
                    VALUES (:id, :share_id, :agent_id, :user_id, :team_id, :can_write)
                    ON CONFLICT (id) DO NOTHING"""),
                    {"id": grant_id, "share_id": share_id, **grant},
                )
            copied = [
                dict(row)
                for row in (
                    await session.execute(
                        text(
                            "SELECT agent_id, user_id, team_id, can_write FROM public.share_grants WHERE share_id = :id"
                        ),
                        {"id": share_id},
                    )
                ).mappings()
            ]
            if sorted(copied, key=lambda g: json.dumps(g, sort_keys=True)) != snapshot["grants"]:
                raise ValueError("Legacy sharing transfer did not preserve all grants")
            await session.execute(
                text(
                    f"UPDATE public.{table} SET share_id = :share, share_kind = :kind WHERE id = :identity"
                ),
                {"share": share_id, "kind": resource_kind, "identity": identity},
            )
    if table == "memory_items":
        await session.execute(
            text("""UPDATE public.documents d SET share_id = m.share_id, share_kind = 'document'
            FROM public.memory_items m WHERE m.id = d.memory_item_id AND d.share_id IS NULL""")
        )


async def transfer(session: AsyncSession) -> None:
    for table in ("memory_items", *(table for table in _SOURCES if table != "memory_items")):
        if await _has_column(session, table, "share_id"):
            await transfer_resource_acl(session, table)


async def _has_column(session: AsyncSession, table: str, column: str) -> bool:
    return bool(await session.scalar(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=:table AND column_name=:column)"
    ), {"table": table, "column": column}))


async def complete(session: AsyncSession) -> bool:
    for table in _SOURCES:
        # Memory is only an old-schema migration source, never a policy owner in
        # the canonical target. Its source columns survive expansion until verified.
        if not await _has_column(session, table, "share_id"):
            continue
        if await session.scalar(
            text(
                f"SELECT EXISTS (SELECT 1 FROM public.{table} r LEFT JOIN public.share_configs s ON s.id = r.share_id WHERE r.share_id IS NULL OR s.id IS NULL OR s.resource_kind IS DISTINCT FROM r.share_kind)"
            )
        ):
            return False
    if await _has_column(session, "documents", "memory_item_id") and await _has_column(session, "memory_items", "share_id"):
        if await session.scalar(text("""SELECT EXISTS (SELECT 1 FROM public.documents d
            JOIN public.memory_items m ON m.id = d.memory_item_id
            WHERE d.share_id IS DISTINCT FROM m.share_id)""")):
            return False
    # Canonical policies are exclusive to one document, folder, dataset or process.
    # Checking live owners catches an incorrectly reused policy even when every FK
    # happens to point to a valid configuration.
    return not bool(await session.scalar(text("""SELECT EXISTS (
        SELECT share_id FROM (
            SELECT share_id FROM documents UNION ALL SELECT share_id FROM document_tags
            UNION ALL SELECT share_id FROM datasets UNION ALL SELECT share_id FROM process_definitions
        ) owners WHERE share_id IS NOT NULL GROUP BY share_id HAVING count(*) > 1
    )""")))
