"""Additive Dataset transfer, committed before changing its consumers' FKs."""

from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet

_ARCHIVE = "galaris_migration.typed_document_sources"
_TRANSFERS = "galaris_migration.typed_document_transfers"
_STATE = "galaris_migration.typed_document_state"
_ROLES = "galaris_migration.typed_document_roles"
_SOURCES = ("datasets", "dataset_revisions", "dataset_tags", "dataset_tag_assignments",
            "dataset_appearances", "dataset_attachments", "dataset_app_consents",
            "dataset_write_budgets", "dataset_aliases")
_DOCUMENT_PLACEMENTS = ("document_tag_assignments", "document_nesting", "document_icons", "document_list_positions")


def needed(delta: SchemaTransitionSet) -> bool:
    return delta.table_added("documents") or delta.column_added("documents", "storage_kind")


async def exists(session: AsyncSession, table: str) -> bool:
    return bool(await session.scalar(text("SELECT to_regclass(:name) IS NOT NULL"), {"name": table}))


async def preserve(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await session.execute(text("CREATE SCHEMA IF NOT EXISTS galaris_migration"))
    await session.execute(text(f"CREATE TABLE IF NOT EXISTS {_ARCHIVE} (source text NOT NULL, identity uuid NOT NULL, snapshot jsonb NOT NULL, digest text NOT NULL, PRIMARY KEY(source,identity))"))
    await session.execute(text(f"CREATE TABLE IF NOT EXISTS {_TRANSFERS} (identity uuid PRIMARY KEY, finalized boolean NOT NULL DEFAULT false)"))
    await session.execute(text(f"CREATE TABLE IF NOT EXISTS {_STATE} (singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton), classified boolean NOT NULL DEFAULT false)"))
    await session.execute(text(f"INSERT INTO {_STATE}(singleton) VALUES(true) ON CONFLICT DO NOTHING"))
    await session.execute(text(f"CREATE TABLE IF NOT EXISTS {_ROLES} (role_id integer NOT NULL, code text NOT NULL, applied boolean NOT NULL DEFAULT false, PRIMARY KEY(role_id,code))"))
    if await exists(session, "public.role_privileges"):
        await session.execute(text(f"""INSERT INTO {_ROLES}(role_id,code)
            SELECT rp.role_id,CASE p.code WHEN 'DATASET_READ' THEN 'DOCUMENT_ACCESS'
                WHEN 'DATASET_EDIT' THEN 'DOCUMENT_EDIT' ELSE 'DOCUMENT_ADMIN' END
            FROM role_privileges rp JOIN privileges p ON p.id=rp.privilege_id
            WHERE p.code IN ('DATASET_READ','DATASET_EDIT','DATASET_ADMIN') ON CONFLICT DO NOTHING"""))
    if not await exists(session, "public.datasets") or not await exists(session, "public.documents"):
        return
    # One transaction locks the complete source set, verifies every copy and
    # publishes its marker. A failure rolls back both rows and markers.
    for table in (*_SOURCES, *_DOCUMENT_PLACEMENTS, "documents", "document_revisions", "share_configs", "share_grants"):
        if await exists(session, f"public.{table}"):
            await session.execute(text(f"LOCK TABLE public.{table} IN SHARE MODE"))
    for table in _SOURCES:
        if await exists(session, f"public.{table}"):
            await session.execute(text(f"INSERT INTO {_ARCHIVE} SELECT :source,id,to_jsonb(r),encode(sha256(convert_to(to_jsonb(r)::text,'UTF8')),'hex') FROM public.{table} r ON CONFLICT DO NOTHING"), {"source": table})
    # Also preserve documentary projections and their historical bytes before
    # merging a verified shared identity.
    for table, condition in (("documents", "id"), ("document_revisions", "document_id"),
                             *((table, "document_id") for table in _DOCUMENT_PLACEMENTS)):
        await session.execute(text(f"INSERT INTO {_ARCHIVE} SELECT :source,id,to_jsonb(r),encode(sha256(convert_to(to_jsonb(r)::text,'UTF8')),'hex') FROM public.{table} r WHERE {condition} IN (SELECT id FROM datasets) ON CONFLICT DO NOTHING"), {"source": table})
    cursor: UUID | None = None
    while rows := (await session.execute(text(f"SELECT id FROM datasets WHERE (CAST(:cursor AS uuid) IS NULL OR id>CAST(:cursor AS uuid)) AND NOT EXISTS(SELECT 1 FROM {_TRANSFERS} t WHERE t.identity=datasets.id) ORDER BY id LIMIT 100"), {"cursor": cursor})).scalars().all():
        for identity in rows:
            collision = await session.scalar(text("SELECT document_type NOT IN ('dataset','data') FROM documents WHERE id=:id"), {"id": identity})
            if collision:
                raise ValueError("Dataset transfer conflicts with an unrelated Document identity")
            share_id = uuid5(NAMESPACE_URL, f"galaris:typed-document:{identity}")
            await session.execute(text("""INSERT INTO share_configs(id,resource_kind,global_access,group_access,revision)
                SELECT :share,'document',s.global_access,s.group_access,s.revision FROM datasets d JOIN share_configs s ON s.id=d.share_id WHERE d.id=:id
                ON CONFLICT DO NOTHING"""), {"id": identity, "share": share_id})
            grants = (await session.execute(text("SELECT agent_id,user_id,team_id,can_write FROM share_grants WHERE share_id=(SELECT share_id FROM datasets WHERE id=:id)"), {"id": identity})).mappings()
            for grant in grants:
                key = next(f"{k}:{v}" for k, v in grant.items() if k.endswith("_id") and v is not None)
                await session.execute(text("INSERT INTO share_grants(id,share_id,agent_id,user_id,team_id,can_write) VALUES(:grant,:share,:agent_id,:user_id,:team_id,:can_write) ON CONFLICT DO NOTHING"), {"grant": uuid5(share_id, key), "share": share_id, **grant})
            await session.execute(text("""INSERT INTO documents(id,title,owner_agent_id,owner_user_id,topic_id,
                provider_code,resource_id,content,revision,lock_version,document_type,content_type,media_type,
                content_hash,size_bytes,keywords,metadata,read_only,visibility,share_id,share_kind,summary_content,
                summary_generated,summary_pending,summary_source_text,search_text,
                created_at,created_by,updated_at,updated_by,deleted_at,deleted_by)
                SELECT id,title,owner_agent_id,owner_user_id,topic_id,'native',id::text,content,revision,lock_version,
                'dataset','text','application/json',encode(sha256(convert_to(content,'UTF8')),'hex'),octet_length(content),
                keywords,metadata,read_only,CASE WHEN EXISTS(SELECT 1 FROM share_configs cfg WHERE cfg.id=:share
                    AND (cfg.global_access>0 OR cfg.group_access>0)) OR EXISTS(SELECT 1 FROM share_grants WHERE share_id=:share)
                    THEN 'shared' ELSE 'private' END,:share,'document',summary_content,summary_generated,summary_pending,
                summary_source_text,content,created_at,created_by,updated_at,updated_by,deleted_at,deleted_by FROM datasets WHERE id=:id
                ON CONFLICT(id) DO UPDATE SET title=excluded.title,owner_agent_id=excluded.owner_agent_id,
                owner_user_id=excluded.owner_user_id,topic_id=excluded.topic_id,provider_code='native',resource_id=excluded.resource_id,
                content=excluded.content,revision=excluded.revision,lock_version=excluded.lock_version,document_type='dataset',
                content_type='text',media_type='application/json',content_profile_version=NULL,
                content_hash=excluded.content_hash,size_bytes=excluded.size_bytes,keywords=excluded.keywords,
                metadata=excluded.metadata,read_only=excluded.read_only,visibility=excluded.visibility,share_id=excluded.share_id,share_kind='document',
                summary_content=excluded.summary_content,summary_generated=excluded.summary_generated,
                summary_pending=excluded.summary_pending,summary_source_text=excluded.summary_source_text,
                search_text=excluded.search_text,created_at=excluded.created_at,created_by=excluded.created_by,
                updated_at=excluded.updated_at,updated_by=excluded.updated_by,deleted_at=excluded.deleted_at,deleted_by=excluded.deleted_by"""), {"id": identity, "share": share_id})
            await session.execute(text("""INSERT INTO document_revisions(id,document_id,revision,provider_code,resource_id,content,
                content_hash,content_type,media_type,title,metadata,author_agent_id,created_at,document_content_version)
                SELECT r.id,r.dataset_id,r.revision,'native',r.id::text,r.content,
                encode(sha256(convert_to(r.content,'UTF8')),'hex'),'text','application/json',d.title,'{}',
                r.author_agent_id,r.created_at,true FROM dataset_revisions r JOIN datasets d ON d.id=r.dataset_id WHERE d.id=:id
                ON CONFLICT(document_id,revision) DO UPDATE SET content=excluded.content,resource_id=excluded.resource_id,
                provider_code='native',content_hash=excluded.content_hash,content_type='text',media_type='application/json',
                content_profile_version=NULL,author_agent_id=excluded.author_agent_id,
                created_at=excluded.created_at,document_content_version=true"""), {"id": identity})
            invalid = await session.scalar(text("""SELECT EXISTS(SELECT 1 FROM datasets s JOIN documents d ON d.id=s.id
                WHERE s.id=:id AND (s.content IS DISTINCT FROM d.content OR s.revision<>d.revision OR s.keywords<>d.keywords
                OR s.summary_content IS DISTINCT FROM d.summary_content OR s.owner_agent_id IS DISTINCT FROM d.owner_agent_id
                OR s.owner_user_id IS DISTINCT FROM d.owner_user_id OR s.topic_id IS DISTINCT FROM d.topic_id
                OR s.metadata IS DISTINCT FROM d.metadata OR s.read_only<>d.read_only OR s.lock_version<>d.lock_version
                OR s.created_at IS DISTINCT FROM d.created_at OR s.deleted_at IS DISTINCT FROM d.deleted_at)) OR EXISTS(SELECT 1 FROM dataset_revisions s
                LEFT JOIN document_revisions d ON d.document_id=s.dataset_id AND d.revision=s.revision
                WHERE s.dataset_id=:id AND (d.id IS NULL OR s.content IS DISTINCT FROM d.content))"""), {"id": identity})
            if invalid:
                raise ValueError("Dataset content or revision transfer verification failed")
            await session.execute(text(f"INSERT INTO {_TRANSFERS}(identity) VALUES(:id)"), {"id": identity})
        cursor = rows[-1]


async def preserved(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    if not await exists(session, _TRANSFERS):
        return False
    if await session.scalar(text(f"SELECT EXISTS(SELECT 1 FROM {_ARCHIVE} WHERE digest<>encode(sha256(convert_to(snapshot::text,'UTF8')),'hex'))")):
        return False
    if not await exists(session, "public.datasets"):
        return True
    return not await session.scalar(text(f"SELECT EXISTS(SELECT 1 FROM datasets s WHERE NOT EXISTS(SELECT 1 FROM {_TRANSFERS} t WHERE t.identity=s.id))"))


async def finalize(session: AsyncSession, delta: SchemaTransitionSet) -> None:
    if not await exists(session, _TRANSFERS):
        await preserve(session, delta)
    await session.execute(text("UPDATE documents SET document_type='text' WHERE document_type IN ('html','form')"))
    await session.execute(text(f"""UPDATE documents d SET document_type='data',creation_key=s.creation_key,
        summary_media_type='text/plain',
        summary_resource_id=md5('summary:' || d.id::text)::uuid::text,
        summary_size_bytes=octet_length(coalesce(d.summary_content,'')),
        summary_content_hash=encode(sha256(convert_to(coalesce(d.summary_content,''),'UTF8')),'hex'),
        creation_fingerprint=s.creation_fingerprint FROM datasets s JOIN {_TRANSFERS} t ON t.identity=s.id
        WHERE d.id=s.id AND NOT t.finalized"""))
    await session.execute(text(f"""UPDATE document_revisions d SET author_user_id=s.author_user_id
        FROM dataset_revisions s JOIN {_TRANSFERS} t ON t.identity=s.dataset_id
        WHERE d.document_id=s.dataset_id AND d.revision=s.revision AND NOT t.finalized"""))
    if not await session.scalar(text(f"SELECT classified FROM {_STATE}")):
        await _classification(session)
        await session.execute(text(f"UPDATE {_STATE} SET classified=true"))
    await session.execute(text(f"UPDATE {_TRANSFERS} SET finalized=true WHERE NOT finalized"))


async def _classification(session: AsyncSession) -> None:
    # Folder UUID collisions are mapped deterministically; personal placements
    # remain independent of ownership and never widen source permissions.
    # Old documentary projections were not the live Dataset classification.
    # Keeping their incoming placements could silently inherit a shared folder's
    # rights. Their snapshots remain in the archive; Dataset placements win.
    for table in _DOCUMENT_PLACEMENTS:
        await session.execute(text(f"DELETE FROM {table} WHERE document_id IN (SELECT identity FROM {_TRANSFERS})"))
    tags = (await session.execute(text("SELECT * FROM dataset_tags ORDER BY id"))).mappings().all()
    for tag in tags:
        identity = uuid5(NAMESPACE_URL, f"galaris:data-folder:{tag['id']}")
        share = uuid5(identity, "sharing")
        await session.execute(text("INSERT INTO share_configs(id,resource_kind,global_access,group_access,revision) VALUES(:id,'document',0,0,1) ON CONFLICT DO NOTHING"), {"id": share})
        await session.execute(text("""INSERT INTO document_tags(id,user_id,name,icon,position,share_id,share_kind,
            created_at,created_by,updated_at,updated_by,deleted_at,deleted_by)
            VALUES(:id,:user_id,:name,:icon,:position,:share,'document',:created_at,:created_by,:updated_at,:updated_by,:deleted_at,:deleted_by)
            ON CONFLICT DO NOTHING"""), {**tag, "id": identity, "share": share})
    for tag in tags:
        if tag["parent_id"]:
            await session.execute(text("UPDATE document_tags SET parent_id=:parent WHERE id=:id AND parent_id IS NULL"), {"id": uuid5(NAMESPACE_URL, f"galaris:data-folder:{tag['id']}"), "parent": uuid5(NAMESPACE_URL, f"galaris:data-folder:{tag['parent_id']}")})
    for tag in tags:
        target = uuid5(NAMESPACE_URL, f"galaris:data-folder:{tag['id']}")
        await session.execute(text("""INSERT INTO document_tag_assignments(id,tag_id,document_id,position)
            SELECT id,:tag,dataset_id,position FROM dataset_tag_assignments WHERE tag_id=:source
            ON CONFLICT DO NOTHING"""), {"tag": target, "source": tag["id"]})
    await session.execute(text("""INSERT INTO document_icons(id,user_id,document_id,icon)
        SELECT id,user_id,dataset_id,icon FROM dataset_appearances WHERE icon IS NOT NULL
        ON CONFLICT(user_id,document_id) DO UPDATE SET icon=excluded.icon"""))
    await session.execute(text("""INSERT INTO document_list_positions(id,user_id,document_id,position,at_root)
        SELECT id,user_id,dataset_id,position,at_root FROM dataset_appearances
        ON CONFLICT(user_id,document_id) DO UPDATE SET position=excluded.position,at_root=excluded.at_root"""))


async def complete(session: AsyncSession, delta: SchemaTransitionSet) -> bool:
    return (await preserved(session, delta) and await exists(session, _STATE)
        and bool(await session.scalar(text(f"SELECT classified FROM {_STATE}")))
        and not await session.scalar(text("SELECT EXISTS(SELECT 1 FROM documents WHERE document_type IN ('html','form'))"))
        and not await session.scalar(text(f"SELECT EXISTS(SELECT 1 FROM {_TRANSFERS} WHERE NOT finalized)")))


async def restore_roles(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await session.execute(text(f"""INSERT INTO role_privileges(role_id,privilege_id)
        SELECT old.role_id,p.id FROM {_ROLES} old JOIN roles r ON r.id=old.role_id
        JOIN privileges p ON p.code=old.code WHERE NOT old.applied ON CONFLICT DO NOTHING"""))
    missing = await session.scalar(text(f"""SELECT EXISTS(SELECT 1 FROM {_ROLES} old JOIN roles r ON r.id=old.role_id
        LEFT JOIN privileges p ON p.code=old.code WHERE p.id IS NULL AND NOT old.applied)"""))
    if missing:
        raise ValueError("Common Document privileges have not been initialized")
    await session.execute(text(f"UPDATE {_ROLES} SET applied=true"))


async def roles_complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    return await exists(session, _ROLES) and not await session.scalar(text(f"SELECT EXISTS(SELECT 1 FROM {_ROLES} WHERE NOT applied)"))


def register(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(key="app.document.typed_sources", phase=DbAdminPhase.BEFORE_EXPAND,
        checksum="preserve-and-verify-dataset-content-history-acls-v1", predicate=needed,
        handler=preserve, postcondition=preserved))
    registry.register_action(DbAdminAction(key="app.document.typed_documents", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="typed-documents-and-personal-classification-v1", predicate=needed,
        handler=finalize, postcondition=complete))
    registry.register_action(DbAdminAction(key="app.document.typed_role_capabilities", phase=DbAdminPhase.AFTER_DATASET,
        checksum="dataset-roles-retain-equivalent-document-capabilities-v1", predicate=needed,
        handler=restore_roles, postcondition=roles_complete))
