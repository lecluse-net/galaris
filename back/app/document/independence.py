"""Preserve and transfer the former Memory-owned documentary state before contraction."""
from collections.abc import Collection
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet

_ARCHIVE = "galaris_migration.document_independence_rows"
_MANIFEST = "galaris_migration.document_independence_manifest"
_SOURCES = ("documents", "document_revisions", "document_tags", "memory_items", "memory_revisions", "memory_summary_revisions", "memory_sources", "memory_urls", "memory_item_grants", "document_user_grants", "document_team_grants", "share_configs", "share_grants", "memory_automation_jobs")

# Old shared knowledge must keep its recipients when retiring the generic
# Memory policy. Private memories never enter this source set.
_DOCUMENT_SOURCE = f"""(m.snapshot->>'node_kind'='document' OR (
    m.snapshot->>'node_kind'='memory' AND NOT coalesce((m.snapshot->>'source_managed')::boolean,false)
    AND (coalesce(m.snapshot->>'visibility','private')<>'private'
        OR coalesce((m.snapshot->>'global_access')::integer,0)>0
        OR coalesce((m.snapshot->>'group_access')::integer,0)>0
        OR EXISTS(SELECT 1 FROM {_ARCHIVE} cfg WHERE cfg.source='share_configs'
            AND cfg.identity=(m.snapshot->>'share_id')::uuid AND (
                coalesce((cfg.snapshot->>'global_access')::integer,0)>0
                OR coalesce((cfg.snapshot->>'group_access')::integer,0)>0
                OR EXISTS(SELECT 1 FROM {_ARCHIVE} grant_row WHERE grant_row.source='share_grants'
                    AND grant_row.snapshot->>'share_id'=cfg.identity::text)))
        OR EXISTS(SELECT 1 FROM {_ARCHIVE} grant_row WHERE
            grant_row.source IN ('memory_item_grants','document_user_grants','document_team_grants')
            AND grant_row.snapshot->>'item_id'=m.identity::text))))"""


def needs_independence(delta: SchemaTransitionSet) -> bool:
    return ("memory_items.share_id" in delta.removed_columns
        or delta.table_added("documents") or delta.column_added("documents", "owner_agent_id")
        or delta.table_added("document_urls"))


def needs_nullable_legacy_memory_policy(delta: SchemaTransitionSet) -> bool:
    return bool({"memory_items.share_id", "memory_items.share_kind"}.intersection(delta.removed_columns))


async def _required_legacy_memory_policy_columns(session: AsyncSession) -> tuple[str, ...]:
    return tuple(str(column) for column in await session.scalars(text("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='public' AND table_name='memory_items'
          AND column_name IN ('share_id','share_kind') AND is_nullable='NO'
        ORDER BY column_name
    """)))


async def legacy_memory_policy_nullable(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    return not await _required_legacy_memory_policy_columns(session)


async def relax_legacy_memory_policy(session: AsyncSession, delta: SchemaTransitionSet) -> None:
    # Expansion retains retired columns until all reconcilers succeed. New
    # private memories have no sharing policy, so those retained columns must
    # allow their inserts before contraction. Preserve and verify sources first;
    # this action must work independently of other BEFORE_EXPAND action ordering.
    await backup(session, delta)
    # Backup normalizes both sides of deferred legacy sharing FKs. Check them
    # now: PostgreSQL forbids ALTER TABLE while their trigger events are pending.
    # Keep archive, normalization and DDL in the same rollback boundary.
    await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    for column in await _required_legacy_memory_policy_columns(session):
        await session.execute(text(f'ALTER TABLE public.memory_items ALTER COLUMN "{column}" DROP NOT NULL'))


async def _exists(session: AsyncSession, table: str) -> bool:
    return bool(await session.scalar(text("SELECT to_regclass(:table) IS NOT NULL"), {"table": table}))


async def backup_complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await _exists(session, _MANIFEST):
        return False
    if not await session.scalar(text(f"SELECT backed_up FROM {_MANIFEST}")):
        return False
    damaged = await session.scalar(text(f"SELECT EXISTS (SELECT 1 FROM {_ARCHIVE} WHERE digest <> encode(sha256(convert_to(snapshot::text,'UTF8')),'hex'))"))
    missing = await session.scalar(text(f"""SELECT EXISTS (
        SELECT 1 FROM {_MANIFEST} m CROSS JOIN LATERAL jsonb_each_text(m.counts) expected
        WHERE expected.value::bigint <> (SELECT count(*) FROM {_ARCHIVE} a WHERE a.source=expected.key))"""))
    return not damaged and not missing


async def backup(session: AsyncSession, delta: SchemaTransitionSet) -> None:
    await session.execute(text("CREATE SCHEMA IF NOT EXISTS galaris_migration"))
    await session.execute(text(f"CREATE TABLE IF NOT EXISTS {_ARCHIVE} (source text NOT NULL, identity uuid NOT NULL, snapshot jsonb NOT NULL, digest text NOT NULL, PRIMARY KEY(source,identity))"))
    await session.execute(text(f"CREATE TABLE IF NOT EXISTS {_MANIFEST} (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), backed_up boolean NOT NULL DEFAULT false, transferred boolean NOT NULL DEFAULT false, counts jsonb NOT NULL DEFAULT '{{}}')"))
    await session.execute(text(f"INSERT INTO {_MANIFEST}(singleton) VALUES(true) ON CONFLICT DO NOTHING"))
    if await session.scalar(text(f"SELECT backed_up FROM {_MANIFEST}")):
        if not await backup_complete(session, delta):
            raise RuntimeError("Document independence archive integrity check failed")
        return
    # Lock all sources before the first copy, so policies, history and content
    # describe the same committed state even if a writer is still finishing.
    for table in _SOURCES:
        if await _exists(session, f"public.{table}"):
            await session.execute(text(f"LOCK TABLE public.{table} IN SHARE MODE"))
    for table in _SOURCES:
        if not await _exists(session, f"public.{table}"):
            continue
        where = ""
        if table == "memory_automation_jobs":
            where = " WHERE kind='goal_folder_reconcile'"
        # Legacy integer grant keys are preserved inside their snapshots; archive identities
        # are deterministic UUIDs derived from the table and original primary key.
        identity = "id" if table not in {"memory_item_grants", "document_user_grants", "document_team_grants"} else "md5(:source || ':' || id::text)::uuid"
        await session.execute(text(f"INSERT INTO {_ARCHIVE}(source,identity,snapshot,digest) SELECT :source,{identity},to_jsonb(row),encode(sha256(convert_to(to_jsonb(row)::text,'UTF8')),'hex') FROM public.{table} row{where} ON CONFLICT DO NOTHING"), {"source": table})
        count = await session.scalar(text(f"SELECT count(*) FROM public.{table}{where}"))
        copied = await session.scalar(text(f"SELECT count(*) FROM {_ARCHIVE} WHERE source=:source"), {"source": table})
        if count != copied:
            raise RuntimeError(f"Incomplete document preservation for {table}")
    legacy_shares = await session.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='memory_items' AND column_name='share_id')"))
    if legacy_shares:
        await session.execute(text(f"INSERT INTO {_ARCHIVE}(source,identity,snapshot,digest) SELECT 'memory_policies',id,jsonb_build_object('share_id',share_id),encode(sha256(convert_to(jsonb_build_object('share_id',share_id)::text,'UTF8')),'hex') FROM memory_items ON CONFLICT DO NOTHING"))
    if await session.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='dataset_revisions' AND column_name='source_revision_id')")):
        await session.execute(text(f"""INSERT INTO {_ARCHIVE}(source,identity,snapshot,digest)
            SELECT 'dataset_revision_origins',id,jsonb_build_object('source_revision_id',source_revision_id),
                encode(sha256(convert_to(jsonb_build_object('source_revision_id',source_revision_id)::text,'UTF8')),'hex')
            FROM dataset_revisions WHERE source_revision_id IS NOT NULL ON CONFLICT DO NOTHING"""))
    await session.execute(text(f"""UPDATE {_MANIFEST} SET backed_up=true, counts=(
        SELECT coalesce(jsonb_object_agg(source,total),'{{}}') FROM (
            SELECT source,count(*) total FROM {_ARCHIVE} GROUP BY source) counts)"""))
    # Old composite FKs are deferred. Normalize their obsolete kind before Atlas
    # tightens the canonical sharing constraint, retaining every policy and grant.
    if await _exists(session, "public.share_configs"):
        legacy = await session.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='memory_items' AND column_name='share_kind')"))
        if legacy:
            await session.execute(text("UPDATE memory_items SET share_kind='document' WHERE share_kind='memory'"))
        await session.execute(text("UPDATE share_configs SET resource_kind='document' WHERE resource_kind='memory'"))


async def transfer_complete(session: AsyncSession, delta: SchemaTransitionSet) -> bool:
    if not await backup_complete(session, delta):
        return False
    if not await session.scalar(text(f"SELECT transferred FROM {_MANIFEST}")):
        return False
    invalid = await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM documents WHERE
        num_nonnulls(owner_agent_id,owner_user_id)<>1 OR lock_version IS NULL OR keywords IS NULL
        OR metadata IS NULL)
        OR EXISTS(SELECT 1 FROM document_revisions WHERE provider_code IS NULL OR resource_id IS NULL
        OR content_hash IS NULL OR media_type IS NULL OR created_at IS NULL)
        OR EXISTS(SELECT 1 FROM document_tags WHERE share_id IS NULL OR share_kind<>'document')"""))
    if invalid:
        return False
    if await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM memory_urls source
        JOIN documents d ON d.id=source.memory_node_id
        LEFT JOIN document_urls target ON target.document_id=d.id AND target.url=source.url
        WHERE target.id IS NULL)""")):
        return False
    if await session.scalar(text(f"""SELECT EXISTS(SELECT 1 FROM {_ARCHIVE} a
        JOIN documents d ON d.id=(a.snapshot->>'memory_node_id')::uuid
        LEFT JOIN document_urls target ON target.id=a.identity
        WHERE a.source='memory_urls' AND (target.id IS NULL OR target.document_id<>d.id
            OR target.url IS DISTINCT FROM a.snapshot->>'url'))""")):
        return False
    if await session.scalar(text(f"""SELECT EXISTS(SELECT 1 FROM {_ARCHIVE} m
        LEFT JOIN documents d ON d.id=m.identity
        WHERE m.source='memory_items' AND {_DOCUMENT_SOURCE} AND d.id IS NULL)""")):
        return False
    if await session.scalar(text(f"""SELECT EXISTS(SELECT 1 FROM {_ARCHIVE} a
        LEFT JOIN dataset_revisions target ON target.id=a.identity
        WHERE a.source='dataset_revision_origins' AND (target.id IS NULL OR
            target.document_source_revision_id IS DISTINCT FROM (a.snapshot->>'source_revision_id')::uuid))""")):
        return False
    # Check identities and payload pointers, not just counts: a missing or
    # mismatched revision must prevent contraction of its only original copy.
    for source, table, parent in (
        ("memory_revisions", "document_revisions", "item_id"),
        ("memory_sources", "document_sources", "item_id"),
    ):
        mismatch = await session.scalar(text(f"""SELECT EXISTS (
            SELECT 1 FROM {_ARCHIVE} a JOIN documents d ON d.id=(a.snapshot->>'{parent}')::uuid
            LEFT JOIN {table} target ON target.id=a.identity
            WHERE a.source=:source AND (target.id IS NULL OR target.document_id<>d.id
                OR to_jsonb(target)->>'resource_id' IS DISTINCT FROM a.snapshot->>'resource_id'
                OR to_jsonb(target)->>'content_hash' IS DISTINCT FROM a.snapshot->>'content_hash'))"""), {"source": source})
        if mismatch:
            return False
    return not bool(await session.scalar(text(f"""SELECT EXISTS (
        SELECT 1 FROM {_ARCHIVE} a LEFT JOIN documents d ON d.id=a.identity
        WHERE a.source='documents' AND (d.id IS NULL
            OR d.revision < (a.snapshot->>'revision')::integer
            OR (d.revision = (a.snapshot->>'revision')::integer AND (
                d.resource_id IS DISTINCT FROM a.snapshot->>'resource_id'
                OR d.content_hash IS DISTINCT FROM a.snapshot->>'content_hash'))))""")))


async def transfer(session: AsyncSession, delta: SchemaTransitionSet) -> None:
    if not await backup_complete(session, delta):
        raise RuntimeError("A verified documentary archive is required before transfer")
    if await session.scalar(text(f"SELECT transferred FROM {_MANIFEST}")):
        await _transfer_locations(session)
        if not await transfer_complete(session, delta):
            raise RuntimeError("Previously transferred Document state failed verification")
        return
    # Source rows remain available during expansion. Refuse an edit between archive
    # and transfer, rather than restoring an older body or attribution over it.
    changed = await session.scalar(text(f"""SELECT EXISTS(SELECT 1 FROM {_ARCHIVE} a
        JOIN memory_items current ON current.id=a.identity WHERE a.source='memory_items'
        AND a.snapshot->>'node_kind'='document' AND (
            current.lock_version IS DISTINCT FROM (a.snapshot->>'lock_version')::integer
            OR current.content_hash IS DISTINCT FROM a.snapshot->>'content_hash'))"""))
    if changed:
        raise RuntimeError("Documentary source changed after preservation; transfer refused")
    # The same UUID retains published URI identity. Old Document bodies remain
    # authoritative; the former Memory payload becomes the Document-owned summary.
    payloads = f"""WITH sources AS (
        SELECT m.identity, m.snapshot AS node, d.snapshot AS doc
        FROM {_ARCHIVE} m LEFT JOIN {_ARCHIVE} d ON d.source='documents' AND d.identity=m.identity
        WHERE m.source='memory_items' AND {_DOCUMENT_SOURCE}
    ), payloads AS (SELECT coalesce(doc,node) || jsonb_build_object(
        'id',identity,'owner_agent_id',node->'owner_agent_id','owner_user_id',node->'owner_user_id',
        'share_id',coalesce(doc->>'share_id',node->>'share_id',md5('galaris:document:'||identity::text)),
        'lock_version',coalesce((node->>'lock_version')::integer,1)+1,
        'keywords',coalesce(node->'keywords','[]'::jsonb),'metadata',coalesce(node->'metadata','{{}}'::jsonb),
        'deletion_protected',coalesce((node->>'deletion_protected')::boolean,false),
        'valid_from',node->'valid_from','valid_until',node->'valid_until','temporal',node->'temporal',
        'last_accessed_at',node->'last_accessed_at','access_count',coalesce((node->>'access_count')::integer,0),
        'search_text',coalesce(node->>'search_text',''),'share_kind','document',
        'summary_provider_code',CASE WHEN doc IS NULL THEN 'native' ELSE node->>'provider_code' END,
        'summary_resource_id',CASE WHEN doc IS NULL THEN '' ELSE node->>'resource_id' END,
        'summary_content',CASE WHEN doc IS NULL THEN '' ELSE node->>'content' END,
        'summary_content_hash',CASE WHEN doc IS NULL THEN encode(sha256(''::bytea),'hex') ELSE node->>'content_hash' END,
        'summary_size_bytes',CASE WHEN doc IS NULL THEN 0 ELSE coalesce((node->>'size_bytes')::bigint,0) END,
        'visibility',CASE WHEN coalesce(doc->>'visibility',node->>'visibility','private')='public' THEN 'shared' ELSE coalesce(doc->>'visibility',node->>'visibility','private') END,
        'read_only',coalesce((doc->>'read_only')::boolean,false),
        'document_type',coalesce(doc->>'document_type','text'),
        'storage_kind',coalesce(doc->>'storage_kind','text'),
        'summary_media_type',coalesce(doc->>'summary_media_type','text/html'),
        'revision',coalesce((doc->>'revision')::integer,(node->>'revision')::integer,1),
        'summary_initialized',true) AS value FROM sources)
    """
    from .models import Document, DocumentRevision, DocumentSource, DocumentAutomationJob
    # Explicit projections omit generated columns and preserve native resource pointers.
    columns = [column.name for column in Document.__table__.columns if column.computed is None and column.name not in {"summary_generated", "summary_pending", "summary_source_text"}]
    names = ",".join(f'"{column}"' for column in columns)
    projection = ",".join(f'record."{column}"' for column in columns)
    # PostgreSQL checks old NOT NULL columns before resolving ON CONFLICT.
    # Keep the original identity populated until Atlas contracts that column.
    legacy_columns = set(await session.scalars(text("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='documents'")))
    if "memory_item_id" in legacy_columns:
        names += ',"memory_item_id"'
        projection += ",coalesce(value->>'memory_item_id',value->>'id')::uuid"
    moved = ("owner_agent_id","owner_user_id","lock_version","keywords","metadata","deletion_protected","valid_from","valid_until","temporal","last_accessed_at","access_count","search_text","summary_provider_code","summary_resource_id","summary_content","summary_content_hash","summary_size_bytes")
    updates = ",".join(f'"{column}"=EXCLUDED."{column}"' for column in moved)
    await session.execute(text(payloads+"""INSERT INTO share_configs(id,resource_kind,global_access,group_access,revision)
        SELECT (value->>'share_id')::uuid,'document',
            coalesce((value->>'global_access')::integer,CASE WHEN value->>'visibility'='shared' THEN 1 ELSE 0 END),
            coalesce((value->>'group_access')::integer,0),1 FROM payloads
        ON CONFLICT(id) DO NOTHING"""))
    await session.execute(text(payloads+f"INSERT INTO documents({names}) SELECT {projection} FROM payloads CROSS JOIN LATERAL jsonb_populate_record(NULL::documents,value) record ON CONFLICT(id) DO UPDATE SET {updates}"))
    await session.execute(text(f"""INSERT INTO document_urls(id,document_id,url)
        SELECT a.identity,d.id,a.snapshot->>'url' FROM {_ARCHIVE} a
        JOIN documents d ON d.id=(a.snapshot->>'memory_node_id')::uuid
        WHERE a.source='memory_urls' ON CONFLICT(id) DO NOTHING"""))
    await _transfer_locations(session)
    # Earlier releases had separate grant tables. Copy their identities and
    # effective permissions before those tables can be contracted by Atlas.
    for source, principal in (("memory_item_grants","agent_id"),("document_user_grants","user_id"),("document_team_grants","team_id")):
        await session.execute(text(f"""INSERT INTO share_grants(id,share_id,{principal},can_write)
            SELECT md5(d.share_id::text||':{principal}:'||(grant_row.snapshot->>'{principal}'))::uuid,
                d.share_id,(grant_row.snapshot->>'{principal}')::integer,
                bool_or(coalesce((grant_row.snapshot->>'can_write')::boolean,false))
            FROM {_ARCHIVE} grant_row JOIN documents d ON d.id=(grant_row.snapshot->>'item_id')::uuid
            WHERE grant_row.source=:source GROUP BY d.share_id,grant_row.snapshot->>'{principal}'
            ON CONFLICT(share_id,{principal})
            DO UPDATE SET can_write=share_grants.can_write OR EXCLUDED.can_write"""), {"source":source})
    mismatch = await session.scalar(text(f"""SELECT EXISTS(SELECT 1 FROM {_ARCHIVE} a JOIN documents d ON d.id=a.identity
        WHERE a.source='documents' AND (d.resource_id IS DISTINCT FROM a.snapshot->>'resource_id'
        OR d.content_hash IS DISTINCT FROM a.snapshot->>'content_hash' OR d.revision IS DISTINCT FROM (a.snapshot->>'revision')::integer))"""))
    if mismatch:
        raise RuntimeError("Document body changed after preservation; sources retained")
    # Revision snapshots no longer require a Memory revision row.
    for model, source, parent in ((DocumentRevision,"memory_revisions","item_id"),(DocumentSource,"memory_sources","item_id")):
        columns=[column.name for column in model.__table__.columns if column.computed is None]
        names=",".join(f'"{column}"' for column in columns)
        values=",".join(f'record."{column}"' for column in columns)
        table=model.__tablename__
        extra=",'storage_kind',coalesce(a.snapshot->>'storage_kind','text'),'document_append',coalesce((a.snapshot->>'document_append')::boolean,false) OR coalesce(a.snapshot->>'reason'='Document content appended',false)" if model is DocumentRevision else ""
        conflict=",".join(f'"{column}"=EXCLUDED."{column}"' for column in columns if column!='id')
        await session.execute(text(f"""INSERT INTO {table}({names}) SELECT {values} FROM {_ARCHIVE} a
            JOIN documents d ON d.id=(a.snapshot->>'{parent}')::uuid
            CROSS JOIN LATERAL jsonb_populate_record(NULL::{table},a.snapshot || jsonb_build_object('document_id',d.id{extra})) record
            WHERE a.source=:source ON CONFLICT(id) DO UPDATE SET {conflict}"""),{"source":source})
    # Each folder owns its canonical policy; graph companion creation is optional.
    await session.execute(text(f"""UPDATE dataset_revisions target
        SET document_source_revision_id=(a.snapshot->>'source_revision_id')::uuid
        FROM {_ARCHIVE} a WHERE a.source='dataset_revision_origins' AND a.identity=target.id"""))
    job_columns = [column.name for column in DocumentAutomationJob.__table__.columns if column.computed is None]
    job_names = ",".join(f'"{name}"' for name in job_columns)
    job_values = ",".join(f'record."{name}"' for name in job_columns)
    await session.execute(text(f"""INSERT INTO document_automation_jobs({job_names})
        SELECT {job_values} FROM {_ARCHIVE} a
        CROSS JOIN LATERAL jsonb_populate_record(NULL::document_automation_jobs,
            a.snapshot || CASE WHEN a.snapshot->>'status'='running'
                THEN jsonb_build_object('status','pending','locked_at',NULL) ELSE '{{}}'::jsonb END) record
        WHERE a.source='memory_automation_jobs' ON CONFLICT(id) DO NOTHING"""))
    await session.execute(text(f"""UPDATE document_tags tag SET share_id=(node.snapshot->>'share_id')::uuid,
        share_kind='document',lock_version=coalesce((node.snapshot->>'lock_version')::integer,1)+1
        FROM {_ARCHIVE} node WHERE node.source='memory_items' AND node.identity=tag.memory_item_id
        AND node.snapshot->>'share_id' IS NOT NULL"""))
    await session.execute(text("""WITH pending AS (SELECT id,gen_random_uuid() AS policy FROM document_tags WHERE share_id IS NULL),
        configs AS (INSERT INTO share_configs(id,resource_kind,global_access,group_access,revision)
        SELECT policy,'document',0,0,1 FROM pending RETURNING id)
        UPDATE document_tags tag SET share_id=pending.policy,share_kind='document'
        FROM pending JOIN configs ON configs.id=pending.policy WHERE tag.id=pending.id"""))
    # The old graph companion keeps its identity and searchable reference, never
    # a second authoritative copy of the shared documentary summary.
    await session.execute(text("""UPDATE memory_items SET node_kind='document',provider_code='native',resource_id='',content='',
        content_hash=encode(sha256(''::bytea),'hex'),size_bytes=0,revision=1,lock_version=lock_version+1
        WHERE id IN (SELECT id FROM documents)"""))
    await session.execute(text(f"UPDATE {_MANIFEST} SET transferred=true"))
    if not await transfer_complete(session,delta):
        raise RuntimeError("Document independence postcondition failed")


async def _transfer_locations(session: AsyncSession) -> None:
    # Older interrupted archives predate the location transfer. Their original
    # snapshots stay immutable; the still-retained URL table can be copied
    # transactionally without retiring any source or overwriting a new URL.
    await session.execute(text("""INSERT INTO document_urls(id,document_id,url)
        SELECT source.id,d.id,source.url FROM memory_urls source
        JOIN documents d ON d.id=source.memory_node_id
        ON CONFLICT(document_id,url) DO NOTHING"""))


async def retired_policies(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await _exists(session, _ARCHIVE):
        return True
    if await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM memory_revisions WHERE item_id IN (SELECT id FROM documents))
        OR EXISTS(SELECT 1 FROM memory_sources WHERE item_id IN (SELECT id FROM documents))
        OR EXISTS(SELECT 1 FROM memory_automation_jobs WHERE kind='goal_folder_reconcile')""")):
        return False
    return not bool(await session.scalar(text(f"""SELECT EXISTS(SELECT 1 FROM share_configs cfg WHERE cfg.id IN (
        SELECT (snapshot->>'share_id')::uuid FROM {_ARCHIVE} WHERE source='memory_policies')
        AND NOT EXISTS(SELECT 1 FROM documents WHERE share_id=cfg.id)
        AND NOT EXISTS(SELECT 1 FROM document_tags WHERE share_id=cfg.id)
        AND NOT EXISTS(SELECT 1 FROM datasets WHERE share_id=cfg.id)
        AND NOT EXISTS(SELECT 1 FROM process_definitions WHERE share_id=cfg.id))""")))


async def retire_policies(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    if not await transfer_complete(session, _delta):
        raise RuntimeError("Document state must be verified before retiring its former Memory rows")
    # The old revision identity FK has now contracted. History and provenance
    # belong solely to Document; its optional graph reference has no payload.
    for table in ("memory_revisions", "memory_sources"):
        await session.execute(text(f"DELETE FROM {table} WHERE item_id IN (SELECT id FROM documents)"))
    missing_jobs = await session.scalar(text(f"""SELECT EXISTS(SELECT 1 FROM {_ARCHIVE} a
        LEFT JOIN document_automation_jobs target ON target.id=a.identity
        WHERE a.source='memory_automation_jobs' AND target.id IS NULL)"""))
    if missing_jobs:
        raise RuntimeError("Document automation jobs were not preserved")
    await session.execute(text("DELETE FROM memory_automation_jobs WHERE kind='goal_folder_reconcile'"))
    await session.execute(text(f"""DELETE FROM share_configs cfg WHERE cfg.id IN (
        SELECT (snapshot->>'share_id')::uuid FROM {_ARCHIVE} WHERE source='memory_policies')
        AND NOT EXISTS(SELECT 1 FROM documents WHERE share_id=cfg.id)
        AND NOT EXISTS(SELECT 1 FROM document_tags WHERE share_id=cfg.id)
        AND NOT EXISTS(SELECT 1 FROM datasets WHERE share_id=cfg.id)
        AND NOT EXISTS(SELECT 1 FROM process_definitions WHERE share_id=cfg.id)"""))


def register_independence(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.document.independence_memory_policy_nullable", phase=DbAdminPhase.BEFORE_EXPAND,
        checksum="verified-archive-nullable-retired-memory-policy-columns-v1",
        predicate=needs_nullable_legacy_memory_policy, handler=relax_legacy_memory_policy,
        postcondition=legacy_memory_policy_nullable))
    for key,phase,handler,postcondition in (
        ("preserve",DbAdminPhase.BEFORE_EXPAND,backup,backup_complete),
        ("transfer",DbAdminPhase.AFTER_EXPAND,transfer,transfer_complete),
        ("retire_policies",DbAdminPhase.AFTER_CONTRACT,retire_policies,retired_policies),
    ):
        registry.register_action(DbAdminAction(key=f"app.document.independence_{key}",phase=phase,
            checksum="autonomous-documents-current-summaries-v2" if key == "transfer" else "autonomous-document-resources-and-owned-shared-summaries-v1",
            compatible_checksums=frozenset({"autonomous-document-resources-and-owned-shared-summaries-v1"}) if key == "transfer" else frozenset(),
            predicate=needs_independence,
            handler=handler,postcondition=postcondition))

async def preserved_resource(session: AsyncSession, provider: str, pointer: str) -> bool:
    return pointer in await preserved_resources(session, provider, (pointer,))


async def preserved_resources(session: AsyncSession, provider: str, pointers: Collection[str]) -> set[str]:
    if not await _exists(session,_ARCHIVE):
        return set()
    return set(await session.scalars(text(f"""SELECT snapshot->>'resource_id' FROM {_ARCHIVE}
        WHERE snapshot->>'provider_code'=:provider AND snapshot->>'resource_id'=ANY(CAST(:pointers AS text[]))
        UNION SELECT snapshot->>'summary_resource_id' FROM {_ARCHIVE}
        WHERE snapshot->>'summary_provider_code'=:provider AND snapshot->>'summary_resource_id'=ANY(CAST(:pointers AS text[]))"""),
        {"provider":provider,"pointers":list(pointers)}))
