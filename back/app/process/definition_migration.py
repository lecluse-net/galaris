"""Transfer former BPMN Documents into Process tables, atomically per batch."""

from app.share import ShareGrant

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.document import legacy_process_snapshot, retire_legacy_process_document
from core.dbadmin import SchemaTransitionSet

from .bpmn import compile_bpmn
from .models import ProcessDefinition, ProcessDefinitionRevision


def needs_transfer(delta: SchemaTransitionSet) -> bool:
    return delta.column_added("process_definitions", "bpmn_xml")


async def transfer_complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    return await session.scalar(select(ProcessDefinition.id).where(ProcessDefinition.code.is_not(None),
        ProcessDefinition.document_id.is_not(None)).limit(1).execution_options(include_historized=True)) is None


async def transfer_definitions(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    from app.share import transfer_legacy_sharing as transfer_shares
    await transfer_shares(session)
    while True:
        rows = list(await session.scalars(select(ProcessDefinition).options(undefer(ProcessDefinition.bpmn_xml)).where(ProcessDefinition.code.is_not(None),
            ProcessDefinition.document_id.is_not(None)).order_by(ProcessDefinition.id).limit(50).with_for_update()
            .execution_options(include_historized=True, populate_existing=True)))
        if not rows:
            return
        for record in rows:
            assert record.document_id is not None
            source_id = record.document_id
            source = await legacy_process_snapshot(source_id)
            compile_bpmn(source["content"])
            if record.bpmn_xml is not None:
                raise ValueError("Process already owns content; refusing to overwrite it with a legacy source")
            record.bpmn_xml = source["content"]
            record.label = source["title"]
            record.revision, record.lock_version = source["revision"], source["lock_version"]
            record.agent_id, record.owner_user_id = source["owner_agent_id"], source["owner_user_id"]
            record.global_access, record.group_access = source["global_access"], source["group_access"]
            if source["deleted_at"] is not None:
                record.archived = True
            for entry in source["revisions"]:
                session.add(ProcessDefinitionRevision(id=entry["id"], process_id=record.id, revision=entry["revision"],
                    bpmn_xml=entry["content"], author_agent_id=entry["author_agent_id"], created_at=entry["created_at"]))
            for grant in source["grants"]:
                session.add(ShareGrant(share_id=record.share_id, **grant))
            record.document_id = None
            await session.flush()
            await retire_legacy_process_document(source_id)
        await session.flush()
        await session.commit()
