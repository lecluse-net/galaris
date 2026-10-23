"""Personal memory ownership and live admission of external graph references."""
from collections.abc import Collection
from uuid import UUID
from sqlalchemy import and_, or_, select
from sqlalchemy.sql.elements import ColumnElement
from app.agent import Agent
from app.agent import AgentManagementScope
from app.document import DocumentAttachment, DocumentTag, DocumentTagAssignment
from app.document import interface as documents
from core.database import get_db
from core.user import HumanActor
from .contracts import MemoryAccess
from .models import MemoryItem
from .source_access import source_access_clause, source_is_readable


def _structural_access(direct: ColumnElement[bool], *, user_id: int | None = None) -> ColumnElement[bool]:
    # Companion nodes convey live source visibility, never a copied policy.
    parents=select(MemoryItem.id).where(MemoryItem.node_kind=="document",direct).correlate(None)
    attachments=select(DocumentAttachment.memory_item_id).where(DocumentAttachment.active.is_(True),DocumentAttachment.document_id.in_(parents)).correlate(None)
    if user_id is None:
        from sqlalchemy.orm import aliased
        ancestry=select(DocumentTag.id,DocumentTag.parent_id,DocumentTag.memory_item_id).join(DocumentTagAssignment,DocumentTagAssignment.tag_id==DocumentTag.id).where(DocumentTagAssignment.document_id.in_(parents)).cte(recursive=True)
        parent=aliased(DocumentTag)
        ancestry=ancestry.union(select(parent.id,parent.parent_id,parent.memory_item_id).join(ancestry,parent.id==ancestry.c.parent_id))
        folders=MemoryItem.id.in_(select(ancestry.c.memory_item_id))
    else:
        folders=MemoryItem.id.in_(select(DocumentTag.memory_item_id).where(DocumentTag.user_id==user_id))
    return or_(and_(MemoryItem.node_kind.not_in(("attachment","folder")),direct),and_(MemoryItem.node_kind=="attachment",MemoryItem.id.in_(attachments)),and_(MemoryItem.node_kind=="folder",folders))


def _direct(agent_id: int) -> ColumnElement[bool]:
    return or_(and_(MemoryItem.node_kind!="document",MemoryItem.owner_agent_id==agent_id),and_(MemoryItem.source_managed.is_(True),MemoryItem.visibility=="public"),and_(MemoryItem.node_kind=="document",MemoryItem.id.in_(documents.readable_ids(agent_id))))


def readable_item_clause(agent_id: int) -> ColumnElement[bool]:
    return and_(_structural_access(_direct(agent_id)),source_access_clause())


def readable_item_for_agents_clause(agent_ids: Collection[int] | None) -> ColumnElement[bool]:
    owned=MemoryItem.owner_agent_id.is_not(None) if agent_ids is None else MemoryItem.owner_agent_id.in_(tuple(agent_ids))
    direct=or_(and_(MemoryItem.node_kind!="document",owned),and_(MemoryItem.source_managed.is_(True),MemoryItem.visibility=="public"),and_(MemoryItem.node_kind=="document",MemoryItem.id.in_(documents.readable_ids_for_agents(agent_ids))))
    return and_(_structural_access(direct),source_access_clause())


async def effective_access(item: MemoryItem, agent_id: int | HumanActor, *, evidence_ids: set[UUID] | None = None, team_access: tuple[bool,bool] | None = None, structural_access: bool | None = None) -> MemoryAccess:
    if isinstance(agent_id,HumanActor):
        return await human_item_access(item,agent_id.user_id)
    if (evidence_ids is not None and item.id not in evidence_ids) or not await source_is_readable(item.id,item.managed_source_kind,agent_id,check_evidence=evidence_ids is None and item.metadata_.get("evidence_validator") is not None):
        return MemoryAccess(False,False)
    if item.node_kind=="document":
        result=await documents.document_access(item.id,agent_id)
        return MemoryAccess(result.can_read,result.can_write)
    if item.node_kind in {"attachment","folder"}:
        allowed=structural_access if structural_access is not None else await get_db().scalar(select(MemoryItem.id).where(MemoryItem.id==item.id,readable_item_clause(agent_id))) is not None
        return MemoryAccess(bool(allowed),False)
    if item.owner_agent_id==agent_id:
        return MemoryAccess(True,not item.read_only)
    return MemoryAccess(item.source_managed and item.visibility=="public",False)


async def effective_access_many(items: Collection[MemoryItem],agent_id: int,*,evidence_ids:set[UUID]) -> dict[UUID,MemoryAccess]:
    structural={item.id for item in items if item.node_kind in {"attachment","folder"}}
    visible=set(await get_db().scalars(select(MemoryItem.id).where(MemoryItem.id.in_(structural),readable_item_clause(agent_id)))) if structural else set[UUID]()
    source_access = await documents.document_access_many([item.id for item in items if item.node_kind == "document"], agent_id)
    result: dict[UUID, MemoryAccess] = {}
    for item in items:
        if item.node_kind == "document":
            source = source_access.get(item.id)
            result[item.id] = MemoryAccess(bool(source and source.can_read and item.id in evidence_ids),
                bool(source and source.can_write and item.id in evidence_ids))
        else:
            result[item.id] = await effective_access(item,agent_id,evidence_ids=evidence_ids,
                structural_access=item.id in visible if item.id in structural else None)
    return result


async def managed_item_agent_ids(item: MemoryItem,agent_ids: Collection[int] | None,*,team_access:dict[int,bool] | None=None) -> tuple[tuple[int,...],tuple[int,...]]:
    if item.node_kind=="document":
        return await documents.managed_agents(item.id,agent_ids)
    if item.node_kind not in {"attachment","folder"} and not item.source_managed:
        owner=item.owner_agent_id
        ids=(owner,) if owner is not None and (agent_ids is None or owner in agent_ids) else ()
        return ids,() if item.read_only else ids
    query=select(Agent.id)
    if agent_ids is not None:
        query=query.where(Agent.id.in_(agent_ids))
    readable: list[int] = []
    for identity in await get_db().scalars(query):
        if (await effective_access(item,identity)).can_read:
            readable.append(identity)
    return tuple(readable),()


def human_item_clause(user_id: int,*,write:bool=False) -> ColumnElement[bool]:
    direct=and_(MemoryItem.node_kind=="document",MemoryItem.id.in_(documents.human_ids(user_id,write=write)))
    return direct if write else _structural_access(direct,user_id=user_id)


def human_document_clause(user_id:int,*,write:bool=False) -> ColumnElement[bool]:
    return and_(MemoryItem.node_kind=="document",human_item_clause(user_id,write=write))


async def human_item_access(item:MemoryItem,user_id:int) -> MemoryAccess:
    if item.node_kind=="document":
        result=await documents.document_access(item.id,HumanActor(user_id))
        return MemoryAccess(result.can_read,result.can_write)
    allowed=await get_db().scalar(select(MemoryItem.id).where(MemoryItem.id==item.id,human_item_clause(user_id)))
    return MemoryAccess(allowed is not None,False)


human_document_access=human_item_access

document_team_agent_access=documents.document_team_agent_access


def readable_workflow_document_clause(actor: int | AgentManagementScope) -> ColumnElement[bool]:
    if isinstance(actor, int):
        return MemoryItem.id.in_(documents.readable_ids(actor))
    return or_(MemoryItem.id.in_(documents.readable_ids_for_agents(actor.agent_ids)),
        MemoryItem.id.in_(documents.human_ids(actor.user_id)))
