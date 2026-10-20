"""Process-owned BPMN definitions. All launches use the current saved content."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import defer, undefer

from app.agent import Agent, AgentManagementScope
from app.tools import ToolModel
from core.database import get_db
from core.user import get_user_record

from .bpmn import Workflow, compile_bpmn, to_bpmn
from .models import ProcessDefinition, ProcessDefinitionRevision
from .native_access import ProcessActor, accessible_clause
from .query_policy import prepare_process_read


class DefinitionConflictError(Exception):
    """A saved definition changed since the caller's last read."""


async def create(*, actor_agent_id: int, title: str, graph: Workflow | None = None,
                 xml: str | None = None, code: str | None = None,
                 owner_user_id: int | None = None, description: str | None = None) -> ProcessDefinition:
    if (graph is None) == (xml is None):
        raise ValueError("Provide either a graph or BPMN XML")
    title = title.strip()
    if not title or len(title) > 255:
        raise ValueError("A Process title must contain 1 to 255 characters")
    identifier = code or "proc_" + uuid4().hex
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,254}", identifier):
        raise ValueError("Invalid immutable process code")
    existing = await get_db().scalar(select(ProcessDefinition.id).where(ProcessDefinition.code == identifier)
        .execution_options(include_historized=True))
    if existing is not None:
        raise ValueError("This process code has already been used")
    content = to_bpmn(graph, identifier) if graph is not None else str(xml)
    compile_bpmn(content)
    tool = await get_db().scalar(select(ToolModel).where(ToolModel.code == "galaris"))
    if tool is None:
        raise ValueError("The Galaris system Tool is unavailable")
    record = ProcessDefinition(agent_id=actor_agent_id if owner_user_id is None else None,
        owner_user_id=owner_user_id, tool_id=tool.id, engine_process_id=identifier,
        code=identifier, label=title, description=description, bpmn_xml=content, revision=1, lock_version=1)
    get_db().add(record)
    await get_db().flush()
    get_db().add(ProcessDefinitionRevision(process_id=record.id, revision=1, bpmn_xml=content,
        author_agent_id=actor_agent_id if owner_user_id is None else None))
    await get_db().commit()
    return record


async def get(code: str, actor: ProcessActor, *, write: bool = False, lock: bool = False,
              content: bool = True) -> tuple[ProcessDefinition, ProcessActor]:
    content_option = undefer(ProcessDefinition.bpmn_xml) if content else defer(ProcessDefinition.bpmn_xml, raiseload=True)
    query = select(ProcessDefinition).options(content_option).where(
        ProcessDefinition.code == code, ProcessDefinition.bpmn_xml.is_not(None)).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    record = await get_db().scalar(query)
    if record is None:
        raise LookupError("Process not found")
    if not await get_db().scalar(select(ProcessDefinition.id).where(ProcessDefinition.id == record.id,
        accessible_clause(actor, write=write))):
        raise PermissionError("Process edit access denied")
    return record, actor


async def read(code: str, actor: int | AgentManagementScope) -> dict[str, Any]:
    record, _ = await get(code, actor)
    assert record.bpmn_xml is not None
    graph = compile_bpmn(record.bpmn_xml)
    from .program_contracts import program_executor
    from .isolated_code import isolated_code_runner
    diagnostics: list[dict[str, str]] = []
    bodies = [graph]
    while bodies:
        body = bodies.pop()
        for node in body.nodes:
            if isolated_code_runner() is None and (node.kind == "code" or node.kind == "if" and node.config.get("mode") == "code" or any(str(node.config.get(phase, "")).strip() for phase in ("preprocess", "postprocess"))):
                diagnostics.append({"node": node.id, "severity": "warning", "code": "isolated_runner_unavailable",
                    "message": "Python requires a qualified runner on a separate VM or host"})
            if node.kind == "program" and program_executor() is None:
                diagnostics.append({"node": node.id, "severity": "warning", "code": "program_executor_unavailable",
                    "message": "Documentary programs require their separately qualified executor"})
            if node.body:
                bodies.append(node.body)
    try:
        await get(code, actor, write=True)
        can_write = True
    except PermissionError:
        can_write = False
    owner: dict[str, object] | None = None
    if record.agent_id is not None:
        agent = (await get_db().execute(select(Agent.first_name, Agent.last_name, Agent.code, Agent.avatar.is_not(None))
            .where(Agent.id == record.agent_id))).one_or_none()
        owner = {"kind": "agent", "id": record.agent_id, "label": f"{agent.first_name} {agent.last_name}".strip() or agent.code,
            "has_avatar": agent[3]} if agent else {"kind": "agent", "id": record.agent_id, "label": f"#{record.agent_id}", "has_avatar": False}
    elif record.owner_user_id is not None:
        user = await get_user_record(record.owner_user_id)
        owner = {"kind": "user", "id": record.owner_user_id, "label": user.display_name or user.email,
            "avatar_url": user.avatar_url} if user else {"kind": "user", "id": record.owner_user_id, "label": f"#{record.owner_user_id}"}
        owner["is_current_user"] = not isinstance(actor, int) and actor.user_id == record.owner_user_id
    can_manage = bool(await get_db().scalar(select(ProcessDefinition.id).where(
        ProcessDefinition.id == record.id, accessible_clause(actor, manage=True))))
    return {"id": record.id, "code": record.code, "archived": record.archived,
            "owner": owner, "can_manage": can_manage, "lock_version": record.lock_version,
            "title": record.label, "description": record.description, "revision": record.revision, "can_write": can_write,
            "xml": record.bpmn_xml, "graph": graph.model_dump(mode="json"), "diagnostics": diagnostics}


async def update(code: str, actor: int | AgentManagementScope, *, expected_revision: int,
                 graph: Workflow | None = None, xml: str | None = None, title: str | None = None,
                 description: str | None = None) -> dict[str, Any]:
    record, _ = await get(code, actor, write=True, lock=True)
    if (graph is None) == (xml is None):
        raise ValueError("Provide either a graph or BPMN XML")
    content = to_bpmn(graph, code) if graph is not None else str(xml)
    compile_bpmn(content)
    if record.revision != expected_revision:
        raise DefinitionConflictError("Process revision changed; reload before saving")
    normalized = title.strip() if title is not None else None
    if normalized is not None and (not normalized or len(normalized) > 255):
        raise ValueError("A Process title must contain 1 to 255 characters")
    if record.bpmn_xml != content:
        record.bpmn_xml = content
        record.revision += 1
        get_db().add(ProcessDefinitionRevision(process_id=record.id, revision=record.revision, bpmn_xml=content,
            author_agent_id=actor if isinstance(actor, int) else None))
    if normalized is not None:
        record.label = normalized
    if description is not None:
        record.description = description
    record.lock_version += 1
    await get_db().commit()
    return await read(code, actor)


async def list_for(actor: int | AgentManagementScope, *, offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
    await prepare_process_read()
    records = await get_db().scalars(select(ProcessDefinition).where(accessible_clause(actor),
        ProcessDefinition.bpmn_xml.is_not(None)).order_by(ProcessDefinition.label, ProcessDefinition.id).offset(offset).limit(limit))
    return [{"id": record.id, "code": record.code, "title": record.label,
             "archived": record.archived} for record in records]


async def page_for(actor: int | AgentManagementScope, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    await prepare_process_read()
    total = await get_db().scalar(select(func.count()).select_from(ProcessDefinition).where(
        accessible_clause(actor), ProcessDefinition.bpmn_xml.is_not(None)))
    return {"items": await list_for(actor, offset=(page - 1) * page_size, limit=page_size),
        "total": total or 0, "page": page, "page_size": page_size}


async def execution_agents_for(scope: AgentManagementScope) -> list[dict[str, Any]]:
    from app.agent import Agent
    query = select(Agent.id, Agent.code, Agent.first_name, Agent.last_name, Agent.avatar.is_not(None)).order_by(Agent.first_name, Agent.last_name, Agent.id)
    if scope.agent_ids is not None:
        query = query.where(Agent.id.in_(scope.agent_ids))
    return [{"id": identity, "label": f"{first} {last}".strip() or code, "has_avatar": has_avatar}
        for identity, code, first, last, has_avatar in (await get_db().execute(query)).all()]


async def archive(code: str, actor: int | AgentManagementScope, value: bool) -> dict[str, Any]:
    record, _ = await get(code, actor, write=True, lock=True)
    record.archived = value
    await get_db().commit()
    return await read(code, actor)


async def history(code: str, actor: int | AgentManagementScope, *, limit: int = 50, offset: int = 0, exclude_current: bool = False) -> dict[str, Any]:
    record, _ = await get(code, actor, content=False)
    if not 1 <= limit <= 500 or offset < 0:
        raise ValueError("Invalid revision pagination")
    query = select(ProcessDefinitionRevision).where(ProcessDefinitionRevision.process_id == record.id)
    if exclude_current:
        query = query.where(ProcessDefinitionRevision.revision < record.revision)
    total = int(await get_db().scalar(select(func.count()).select_from(query.subquery())) or 0)
    rows = await get_db().scalars(query.order_by(ProcessDefinitionRevision.revision.desc()).offset(offset).limit(limit))
    return {"items": [_revision_metadata(entry) for entry in rows], "total": total,
        "limit": limit, "offset": offset, "has_more": offset + limit < total}


async def restore(code: str, actor: int | AgentManagementScope, revision: int, expected_revision: int) -> dict[str, Any]:
    record, _ = await get(code, actor, write=True, lock=True)
    entry = await _revision(record.id, revision)
    return await update(code, actor, xml=entry.bpmn_xml, expected_revision=expected_revision)


async def revision_detail(code: str, actor: int | AgentManagementScope, revision: int) -> dict[str, Any]:
    record, _ = await get(code, actor)
    entry = await _revision(record.id, revision)
    additions = deletions = 0
    for tag, old_start, old_end, new_start, new_end in SequenceMatcher(None,
        entry.bpmn_xml.splitlines(), (record.bpmn_xml or "").splitlines(), autojunk=False).get_opcodes():
        if tag in {"replace", "delete"}:
            deletions += old_end - old_start
        if tag in {"replace", "insert"}:
            additions += new_end - new_start
    return {"detail": {**_revision_metadata(entry), "content": entry.bpmn_xml},
        "diff": {"revision": revision, "current_revision": record.revision, "additions": additions, "deletions": deletions}}


async def delete_revision(code: str, actor: int | AgentManagementScope, revision: int) -> None:
    record, _ = await get(code, actor, write=True, lock=True)
    if revision >= record.revision:
        raise DefinitionConflictError("The current Process revision cannot be deleted")
    await get_db().delete(await _revision(record.id, revision))
    await get_db().commit()


async def _revision(identity: int, revision: int) -> ProcessDefinitionRevision:
    entry = await get_db().scalar(select(ProcessDefinitionRevision).options(undefer(ProcessDefinitionRevision.bpmn_xml)).where(
        ProcessDefinitionRevision.process_id == identity, ProcessDefinitionRevision.revision == revision))
    if entry is None:
        raise LookupError("Process revision not found")
    return entry


def _revision_metadata(entry: ProcessDefinitionRevision) -> dict[str, Any]:
    return {"revision": entry.revision, "created_at": entry.created_at.isoformat(),
        "author_agent_id": entry.author_agent_id}
