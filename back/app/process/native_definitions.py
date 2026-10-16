"""Document-backed process definitions. All launches use the current saved content."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from sqlalchemy import select, func

from app.agent import AgentManagementScope
from app.memory import (create_workflow_document, read_workflow_document, write_workflow_document,
    workflow_document_actor, workflow_document_readable_ids, workflow_history, restore_workflow_document)
from app.memory import workflow_revision, delete_workflow_revision
from app.memory import workflow_document_titles, prepare_workflow_document_read
from app.tools import ToolModel
from app.memory import MemoryPermissionError, MemoryNotFoundError
from core.database import get_db
from core.user import HumanActor

from .bpmn import Workflow, compile_bpmn, to_bpmn
from .models import ProcessDefinition


async def create(*, actor_agent_id: int, title: str, graph: Workflow | None = None,
                 xml: str | None = None, code: str | None = None,
                 owner_user_id: int | None = None) -> ProcessDefinition:
    if (graph is None) == (xml is None):
        raise ValueError("Provide either a graph or BPMN XML")
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
    document = await create_workflow_document(owner_agent_id=actor_agent_id, title=title,
        content=content, kind="process", command=f"process-definition:{actor_agent_id}:{identifier}", owner_user_id=owner_user_id, process_code=identifier)
    record = ProcessDefinition(agent_id=actor_agent_id if owner_user_id is None else None,
        tool_id=tool.id, engine_process_id=identifier, code=identifier, label=title, document_id=document.id)
    get_db().add(record)
    await get_db().commit()
    return record


async def get(code: str, actor: int | AgentManagementScope, *, write: bool = False) -> tuple[ProcessDefinition, int | HumanActor]:
    record = await get_db().scalar(select(ProcessDefinition).where(ProcessDefinition.code == code,
        ProcessDefinition.document_id.is_not(None)))
    if record is None or record.document_id is None:
        raise LookupError("Process not found")
    try:
        resolved = await workflow_document_actor(record.document_id, actor, write=write) if isinstance(actor, AgentManagementScope) else actor
        document = await read_workflow_document(record.document_id, resolved)
    except MemoryPermissionError as error:
        raise PermissionError("Process access denied") from error
    except MemoryNotFoundError as error:
        if write:
            raise PermissionError("Process edit access denied") from error
        raise LookupError("Process not found") from error
    if write and not document["can_write"]:
        raise PermissionError("Process edit access denied")
    return record, resolved


async def read(code: str, actor: int | AgentManagementScope) -> dict[str, Any]:
    record, resolved = await get(code, actor)
    assert record.document_id is not None
    document = await read_workflow_document(record.document_id, resolved)
    graph = compile_bpmn(document["content"])
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
    return {"id": record.id, "code": record.code, "archived": record.archived,
            "document_id": str(record.document_id), "title": document["title"],
            "revision": document["revision"], "can_write": can_write,
            "xml": document["content"], "graph": graph.model_dump(mode="json"), "diagnostics": diagnostics}


async def update(code: str, actor: int | AgentManagementScope, *, expected_revision: int,
                 graph: Workflow | None = None, xml: str | None = None, title: str | None = None) -> dict[str, Any]:
    record, resolved = await get(code, actor, write=True)
    assert record.document_id is not None
    if (graph is None) == (xml is None):
        raise ValueError("Provide either a graph or BPMN XML")
    content = to_bpmn(graph, code) if graph is not None else str(xml)
    compile_bpmn(content)
    document = await write_workflow_document(record.document_id, resolved, content,
        expected_revision=expected_revision, title=title)
    record.label = document.title
    await get_db().commit()
    return await read(code, actor)


async def list_for(actor: int | AgentManagementScope, *, offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
    await prepare_workflow_document_read()
    documents = workflow_document_titles().subquery()
    records = (await get_db().execute(select(ProcessDefinition, documents.c.title)
        .join(documents, documents.c.id == ProcessDefinition.document_id).where(
        ProcessDefinition.document_id.in_(workflow_document_readable_ids(actor)),
    ).order_by(documents.c.title, ProcessDefinition.id).offset(offset).limit(limit))).all()
    return [{"id": record.id, "code": record.code, "title": title,
             "document_id": str(record.document_id), "archived": record.archived} for record, title in records]


async def page_for(actor: int | AgentManagementScope, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
    await prepare_workflow_document_read()
    total = await get_db().scalar(select(func.count()).select_from(ProcessDefinition).where(
        ProcessDefinition.document_id.in_(workflow_document_readable_ids(actor))))
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
    record, _ = await get(code, actor, write=True)
    record.archived = value
    await get_db().commit()
    return await read(code, actor)


async def history(code: str, actor: int | AgentManagementScope, *, limit: int = 50, offset: int = 0, exclude_current: bool = False) -> dict[str, Any]:
    record, resolved = await get(code, actor)
    assert record.document_id is not None
    before = (await read_workflow_document(record.document_id, resolved))["revision"] if exclude_current else None
    return (await workflow_history(record.document_id, resolved, limit=limit, offset=offset, before_revision=before)).model_dump(mode="json")


async def restore(code: str, actor: int | AgentManagementScope, revision: int, expected_revision: int) -> dict[str, Any]:
    record, resolved = await get(code, actor, write=True)
    assert record.document_id is not None
    await restore_workflow_document(record.document_id, resolved, revision, expected_revision)
    return await read(code, actor)


async def revision_detail(code: str, actor: int | AgentManagementScope, revision: int) -> dict[str, Any]:
    record, resolved = await get(code, actor)
    assert record.document_id is not None
    return await workflow_revision(record.document_id, resolved, revision)


async def delete_revision(code: str, actor: int | AgentManagementScope, revision: int) -> None:
    record, resolved = await get(code, actor, write=True)
    assert record.document_id is not None
    await delete_workflow_revision(record.document_id, resolved, revision)
