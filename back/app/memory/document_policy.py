"""Format policies complement Documents' shared ACL, on every access surface."""

from sqlalchemy import exists, or_, and_, select, false
from sqlalchemy.sql.elements import ColumnElement

from app.agent import Agent
from core.authorize import privilege_clause
from core.user import UserModel

from .models import Document, MemoryItem


def orphan_process_clause() -> ColumnElement[bool]:
    process = exists(select(Document.id).where(Document.id == MemoryItem.id, Document.document_type == "process").correlate(MemoryItem))
    owned = or_(
        exists(select(Agent.id).where(Agent.id == MemoryItem.owner_agent_id, Agent.deleted_at.is_(None)).correlate(MemoryItem)),
        exists(select(UserModel.id).where(UserModel.id == MemoryItem.owner_user_id, UserModel.is_active.is_(True)).correlate(MemoryItem)),
    )
    return and_(process, ~owned)


def document_policy_clause(user_id: int | None = None) -> ColumnElement[bool]:
    admin = privilege_clause(user_id, "PROCESS_ADMIN") if user_id is not None else false()
    return or_(~orphan_process_clause(), admin)
