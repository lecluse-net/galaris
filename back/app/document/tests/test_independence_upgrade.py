"""The real DbAdmin/Atlas pipeline preserves a populated pre-separation schema."""
from dataclasses import replace
from hashlib import sha256
from uuid import uuid4
import pytest
from sqlalchemy import select,text
from app.agent.models import Agent,Title
from app.document import Document,DocumentRevision,DocumentSummaryRevision,DocumentTag,DocumentTagAssignment,DocumentURL
from app.memory.models import MemoryItem,MemoryRevision,MemoryURL
from app.share import ShareConfig,ShareGrant
from app.document.independence import register_independence,transfer_complete
from core import settings
from core.dbadmin import DbAdminReconciler,DbAdminRegistry,DbAdminVerdict,SchemaTransitionSet,orchestrator
from core.dbadmin._internal import atlas
from core.user import UserModel


def digest(body: str) -> str:
    return sha256(body.encode()).hexdigest()


async def old_schema(session):
    manager=UserModel(email="synthetic-document-upgrade-owner@example.test",hashed_password="unused",is_active=True)
    recipient=UserModel(email="synthetic-document-upgrade-reader@example.test",hashed_password="unused",is_active=True)
    title=Title(label="Synthetic document migration",gender="X")
    owner=Agent(user=manager,title=title,code="synthetic-document-migration-owner",first_name="Synthetic",last_name="Owner",agent_driver="internal")
    reader=Agent(user=recipient,title=title,code="synthetic-document-migration-reader",first_name="Synthetic",last_name="Reader",agent_driver="internal")
    session.add_all([owner,reader]);await session.flush()
    identity,folder_node,private_id=uuid4(),uuid4(),uuid4()
    content,summary="<p>Preserved source body.</p>","<p>Preserved shared abstract.</p>"
    body_pointer,summary_pointer=str(uuid4()),str(uuid4())
    document=Document(id=identity,owner_agent_id=owner.id,title="Synthetic durable document",provider_code="native",resource_id=body_pointer,content=content,revision=2,content_hash=digest(content),size_bytes=len(content),keywords=["retained"],metadata_={"synthetic":True},content_type="text",media_type="text/html",content_profile_version=1)
    folder=DocumentTag(user_id=manager.id,name="Synthetic retained folder",position=1)
    session.add_all([document,folder]);await session.flush()
    node=MemoryItem(id=identity,node_kind="document",owner_agent_id=owner.id,memory_provider_code="native",memory_resource_id=summary_pointer,memory_content=summary,memory_content_hash=digest(summary),memory_size_bytes=len(summary),memory_revision=3,memory_content_type="text",memory_media_type="text/html",memory_content_profile_version=1,search_title=document.title,search_text="Preserved source body. Preserved shared abstract.",keywords=["retained"],metadata_={"synthetic":True},summary_document_revision=2)
    folder_memory=MemoryItem(id=folder_node,node_kind="folder",owner_user_id=manager.id,memory_provider_code="native",memory_resource_id=str(uuid4()),memory_content="",memory_content_hash=digest(""),memory_size_bytes=0,memory_content_type="text",memory_media_type="text/html",memory_content_profile_version=1,search_title=folder.name,search_text="",source_managed=True,managed_source_kind="folder",managed_source_ref=str(folder.id),memory_read_only=True,deletion_protected=True)
    personal=MemoryItem(id=private_id,node_kind="memory",owner_agent_id=owner.id,memory_provider_code="native",memory_resource_id=str(uuid4()),memory_content="<p>Private synthetic memory.</p>",memory_content_hash=digest("<p>Private synthetic memory.</p>"),memory_size_bytes=32,memory_content_type="text",memory_media_type="text/html",memory_content_profile_version=1,search_title="Private synthetic memory",search_text="Private synthetic memory")
    session.add_all([node,folder_memory,personal]);await session.flush()
    location=MemoryURL(memory_node_id=identity,url="https://example.test/synthetic-source")
    session.add(location);await session.flush()
    folder.memory_item_id=folder_node
    session.add(DocumentTagAssignment(tag_id=folder.id,document_id=identity,position=1))
    session.add(ShareGrant(share_id=document.share_id,agent_id=reader.id,can_write=False))
    session.add(ShareGrant(share_id=folder.share_id,agent_id=reader.id,can_write=True))
    revisions=[]
    for version in (1,2):
        rev_id=uuid4();revisions.append(rev_id)
        body=f"<p>Preserved source version {version}.</p>"
        pointer=str(uuid4())
        common=dict(id=rev_id,revision=version,provider_code="native",resource_id=pointer,content=body,content_hash=digest(body),content_type="text",media_type="text/html",content_profile_version=1,title=document.title,keywords=["retained"],metadata_={"synthetic":True},author_agent_id=owner.id,document_content_version=True)
        session.add(DocumentRevision(document_id=identity,**common))
        session.add(MemoryRevision(item_id=identity,**common))
    summary_revision=uuid4()
    session.add(DocumentSummaryRevision(id=summary_revision,document_id=identity,revision=3,provider_code="native",resource_id=summary_pointer,content=summary,content_hash=digest(summary),source_document_revision=2,keywords=["retained"],author_agent_id=reader.id))
    await session.commit()
    expected={"id":identity,"owner":owner.id,"reader":reader.id,"folder":folder.id,"folder_node":folder_node,"private":private_id,"content":content,"summary":summary,"body_pointer":body_pointer,"summary_pointer":summary_pointer,"revisions":revisions,"summary_revision":summary_revision,"document_policy":document.share_id,"folder_policy":folder.share_id,"url":location.id}
    # Recreate only the source representation. All data is synthetic, in this test's
    # committed PostgreSQL database; no development schema or data is touched.
    await session.execute(text("DROP TABLE IF EXISTS galaris_migration.document_independence_rows,galaris_migration.document_independence_manifest"))
    await session.execute(text("ALTER TABLE memory_items ADD COLUMN share_id uuid, ADD COLUMN share_kind varchar(30)"))
    await session.execute(text("ALTER TABLE documents ADD COLUMN memory_item_id uuid"))
    await session.execute(text("UPDATE documents SET memory_item_id=id"))
    await session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await session.execute(text("ALTER TABLE documents ALTER COLUMN memory_item_id SET NOT NULL"))
    await session.execute(text("ALTER TABLE share_configs DROP CONSTRAINT ck_share_configs_kind"))
    personal_policy=ShareConfig(resource_kind="memory",global_access=0,group_access=0)
    session.add(personal_policy);await session.flush()
    for node_id,policy,kind in ((identity,document.share_id,"document"),(folder_node,folder.share_id,"memory"),(private_id,personal_policy.id,"memory")):
        await session.execute(text("UPDATE memory_items SET share_id=:policy,share_kind=:kind WHERE id=:id"),{"policy":policy,"kind":kind,"id":node_id})
    await session.execute(text("ALTER TABLE memory_items ALTER COLUMN share_id SET NOT NULL, ALTER COLUMN share_kind SET NOT NULL"))
    from app.connection import Connection
    from app.messenger import Message
    from app.tools import ToolModel
    tool = ToolModel(code="synthetic-upgrade-mail", label="Synthetic upgrade Mail",
        messenger_config={"service": "mail"}, connection_schema={})
    session.add(tool)
    await session.flush()
    connection = Connection(agent_id=owner.id, tool_id=tool.id, active=True)
    session.add(connection)
    await session.flush()
    message = Message(connection_id=connection.id, tool_id=tool.id, platform="mail",
        user_id="synthetic-sender@example.org", remote_message_id="synthetic-upgrade-message",
        direction="inbound", text="Entirely synthetic upgrade input",
        metadata_={"sender_display_name": "Synthetic upgrade sender"})
    session.add(message)
    await session.flush()
    expected["message"] = message.id
    await session.execute(text("ALTER TABLE document_tags DROP COLUMN share_id CASCADE, DROP COLUMN share_kind CASCADE, DROP COLUMN lock_version"))
    await session.execute(text("UPDATE share_configs SET resource_kind='memory' WHERE id=:policy"),{"policy":folder.share_id})
    await session.execute(text("ALTER TABLE memory_items ADD UNIQUE(id,share_id)"))
    await session.execute(text("ALTER TABLE documents ADD CONSTRAINT synthetic_legacy_document_identity FOREIGN KEY(memory_item_id,share_id) REFERENCES memory_items(id,share_id) DEFERRABLE INITIALLY DEFERRED"))
    await session.execute(text("CREATE TABLE memory_summary_revisions (LIKE document_summary_revisions INCLUDING DEFAULTS)"))
    await session.execute(text("INSERT INTO memory_summary_revisions SELECT * FROM document_summary_revisions"))
    await session.execute(text("ALTER TABLE memory_summary_revisions RENAME COLUMN document_id TO item_id"))
    await session.execute(text("DROP TABLE document_summary_revisions"))
    legacy_columns={"id","document_id","revision"}
    for column in DocumentRevision.__table__.columns:
        if column.name not in legacy_columns:
            await session.execute(text(f'ALTER TABLE document_revisions DROP COLUMN "{column.name}" CASCADE'))
    await session.execute(text("ALTER TABLE document_revisions ADD CONSTRAINT synthetic_legacy_revision_resource FOREIGN KEY(id) REFERENCES memory_revisions(id) ON DELETE CASCADE"))
    moved=("owner_agent_id","owner_user_id","lock_version","keywords","metadata","deletion_protected","valid_from","valid_until","temporal","last_accessed_at","access_count","search_text","summary_revision","summary_provider_code","summary_resource_id","summary_content","summary_content_hash","summary_size_bytes","summary_document_revision")
    # The generated search column depends on the fields that used to live in Memory.
    await session.execute(text("ALTER TABLE documents DROP COLUMN search_vector"))
    for column in moved:
        await session.execute(text(f'ALTER TABLE documents DROP COLUMN "{column}" CASCADE'))
    await session.commit()
    return expected


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted",[False,True,"reconciler"])
async def test_real_upgrade_preserves_document_summary_history_policies_and_replay(committed_database,monkeypatch,interrupted):
    engine=committed_database.kw["bind"]
    monkeypatch.setattr(orchestrator,"engine",engine)
    monkeypatch.setattr(atlas,"engine",engine)
    monkeypatch.setattr(settings,"POSTGRES_DB",engine.url.database)
    monkeypatch.setattr(orchestrator,"_load_contributions",lambda registry:None)
    async with committed_database() as session:
        expected=await old_schema(session)
    registry=DbAdminRegistry();register_independence(registry)
    from app.messenger.dbadmin import _reconcile_contacts
    registry.register_reconciler(DbAdminReconciler(key="synthetic.upgrade_contacts", handler=_reconcile_contacts))
    if interrupted is True:
        interrupted_registry=DbAdminRegistry()
        for action in registry.actions:
            if action.key=="app.document.independence_transfer":
                original=action.handler
                async def fail_after_copy(session,delta):
                    await original(session,delta)
                    raise RuntimeError("Synthetic failure after transfer, before commit")
                action=replace(action,handler=fail_after_copy)
            interrupted_registry.register_action(action)
        result=await orchestrator.synchronize_database(target_registry=interrupted_registry)
        assert result.verdict is DbAdminVerdict.FATAL
        async with committed_database() as session:
            assert await session.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='memory_items' AND column_name='share_id')"))
            assert await session.scalar(text("SELECT resource_id FROM memory_items WHERE id=:id"),{"id":expected["id"]})==expected["summary_pointer"]
    elif interrupted == "reconciler":
        previous_registry = DbAdminRegistry()
        for action in registry.actions:
            if action.key != "app.document.independence_memory_policy_nullable":
                previous_registry.register_action(action)
        previous_registry.register_reconciler(DbAdminReconciler(
            key="synthetic.upgrade_contacts", handler=_reconcile_contacts))
        result = await orchestrator.synchronize_database(target_registry=previous_registry)
        assert result.verdict is DbAdminVerdict.FATAL
        async with committed_database() as session:
            assert await transfer_complete(session, SchemaTransitionSet())
            assert await session.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_schema='public' AND table_name='memory_items' AND column_name IN ('share_id','share_kind') AND is_nullable='NO'")) == 2
    for _ in range(2):
        result=await orchestrator.synchronize_database(target_registry=registry)
        assert result.verdict is DbAdminVerdict.CONVERGED
        async with committed_database() as session:
            document=await session.get(Document,expected["id"])
            assert document is not None
            assert (document.content,document.resource_id,document.revision)==(expected["content"],expected["body_pointer"],2)
            assert (document.owner_agent_id,document.keywords,document.metadata_)==(expected["owner"],["retained"],{"synthetic":True})
            assert (document.summary_content,document.summary_resource_id,document.summary_revision,document.summary_document_revision)==(expected["summary"],expected["summary_pointer"],3,2)
            assert document.share_id==expected["document_policy"]
            assert await session.scalar(select(DocumentTag.share_id).where(DocumentTag.id==expected["folder"]))==expected["folder_policy"]
            assert set(await session.scalars(select(DocumentRevision.id).where(DocumentRevision.document_id==document.id)))==set(expected["revisions"])
            assert await session.scalar(select(DocumentSummaryRevision.content).where(DocumentSummaryRevision.id==expected["summary_revision"]))==expected["summary"]
            assert await session.scalar(select(MemoryItem.memory_content).where(MemoryItem.id==expected["private"]))=="<p>Private synthetic memory.</p>"
            assert not await session.scalar(text("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='memory_items' AND column_name IN ('share_id','share_kind'))"))
            assert await transfer_complete(session,SchemaTransitionSet())
            assert await session.scalar(select(DocumentURL.url).where(DocumentURL.id==expected["url"]))=="https://example.test/synthetic-source"
            assert await session.scalar(select(ShareGrant.can_write).where(ShareGrant.share_id==document.share_id,ShareGrant.agent_id==expected["reader"])) is False
            from app.messenger import Message
            contact_id = await session.scalar(select(Message.contact_memory_item_id).where(Message.id == expected["message"]))
            assert contact_id is not None
            contact = await session.get(MemoryItem, contact_id)
            assert contact.owner_agent_id == expected["owner"] and contact.node_kind == "memory"
