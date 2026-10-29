"""Only the model is scripted: Chat, MCP, approvals, Tasks and Documents stay real."""

import json

from fastapi import APIRouter
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall
from sqlalchemy import select

from core.database import get_db, get_db_session
from tests.e2e_conversation_control import ControlledModel

router = APIRouter(prefix="/api/__test/document-authorization")
states = {}
INITIAL = "<h1>Synthetic authorization report</h1><p>Initial content preserved.</p>"
UPDATED = INITIAL + "<p>Background task contribution.</p>"


async def seed(agent_id):
    from app.connection import Connection, facade as connections
    from app.tools import ToolModel, sync_integrated_tool_connections

    await sync_integrated_tool_connections(agent_id)
    db = get_db()
    rows = (await db.execute(select(Connection, ToolModel.code).join(ToolModel).where(
        Connection.agent_id == agent_id, ToolModel.code.in_(("file_sharing", "conversation")),
    ))).all()
    assert len(rows) == 2
    for connection, code in rows:
        for name, mode in ({"file_create": "ask", "file_write": "ask", "file_read": "enabled"}
                           if code == "file_sharing" else {"conversation_task_submit": "enabled"}).items():
            await connections.set_connection_function_state(connection.id, name, mode)
    states[agent_id] = {"calls": [], "uri": None}


def objects(value):
    """MCP results can contain JSON inside text content blocks."""
    if isinstance(value, str):
        try:
            yield from objects(json.loads(value))
        except (ValueError, TypeError):
            return
    elif isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from objects(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from objects(nested)


async def build_model(_llm, *, agent_id, purpose=None, **_kwargs):
    state = states[agent_id]
    task = str(purpose) == "agent.exec"

    def answer(messages, info):
        state["calls"].append(str(purpose))
        assert len(state["calls"]) < 40, "Unexpected model/tool loop"
        if str(purpose) == "agent.dispatch":
            return ModelResponse(parts=[TextPart('{"route":"EXEC","effort":"standard","language":"fr"}')])
        if str(purpose) == "conversation.task_objective":
            fields = {"label": "Synthetic document continuation",
                      "objective": f"<p>Compléter le document {state['uri']} en conservant son contenu initial.</p>",
                      "write_targets": [{"target": state["uri"],
                                         "request_quote": "lance une tâche de fond pour le compléter",
                                         "context_quote": state["uri"]}]}
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, fields)])
        returns = [part for message in messages for part in message.parts if isinstance(part, ToolReturnPart)]
        relevant = [part for part in returns if part.tool_name in {
            "file_create", "file_read", "file_write", "conversation_task_submit"}]
        latest = relevant[-1] if relevant else None
        if latest is not None and latest.outcome != "success":
            return ModelResponse(parts=[TextPart("Action interdite : aucun changement effectué après le refus.")])
        if latest is None:
            name, args = ("file_read", {"uri": state["uri"]}) if task else (
                "file_create", {"path": "document://", "name": "Synthetic authorization report", "content": INITIAL})
        elif latest.tool_name == "file_create":
            state["uri"] = next(item["uri"] for item in objects(latest.content) if "uri" in item)
            name, args = "conversation_task_submit", {
                "label": "Synthetic document continuation",
                "objective": f"<p>Compléter le document {state['uri']} en conservant son contenu initial.</p>",
                "mode": "exec",
            }
        elif latest.tool_name == "conversation_task_submit":
            receipt = list(objects(latest.content))
            assert any(item.get("created") for item in receipt), receipt
            return ModelResponse(parts=[TextPart("Document créé ; modification confiée à une tâche de fond.")])
        elif latest.tool_name == "file_read":
            receipt = next(item for item in objects(latest.content) if "revision" in item)
            name, args = "file_write", {"uri": state["uri"], "content": UPDATED,
                                       "expected_revision": receipt["revision"]}
        else:
            return ModelResponse(parts=[TextPart("Document complété par la tâche de fond.")])
        if name not in {tool.name for tool in info.function_tools}:
            return ModelResponse(parts=[ToolCallPart("search_tools", {"queries": [name]})])
        return ModelResponse(parts=[ToolCallPart(name, args)])

    async def stream(messages, info):
        for part in answer(messages, info).parts:
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {0: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args),
                                       tool_call_id=part.tool_call_id)}

    return ControlledModel(function=answer, stream_function=stream)


@router.get("/{agent_id}")
async def snapshot(agent_id: int):
    from app.document.models import Document, DocumentRevision
    from app.task.models import Task, TaskAttempt
    from app.tools.authorization_models import ActionAuthorization

    async with get_db_session() as db:
        documents = list(await db.scalars(select(Document).where(Document.owner_agent_id == agent_id)))
        tasks = list(await db.scalars(select(Task).where(Task.agent_id == agent_id).order_by(Task.created_at)))
        approvals = list(await db.scalars(select(ActionAuthorization).where(
            ActionAuthorization.agent_id == agent_id).order_by(ActionAuthorization.created_at)))
        revisions = list(await db.scalars(select(DocumentRevision).where(
            DocumentRevision.document_id.in_([document.id for document in documents]))))
        attempts = list(await db.scalars(select(TaskAttempt).where(TaskAttempt.task_id.in_([task.id for task in tasks]))))
        return {"calls": states[agent_id]["calls"], "documents": [
            {"uri": f"document://{document.id}", "content": document.content, "revision": document.revision}
            for document in documents], "revisions": [revision.revision for revision in revisions],
            "tasks": [{"uri": f"galaris://task/{task.id}", "status": task.status.value, "paused": task.paused,
                       "lease": str(task.lease_token) if task.lease_token else None, "data": task.data,
                       "result": task.execution_result} for task in tasks],
            "attempts": [{"status": attempt.status, "finished": attempt.finished_at is not None} for attempt in attempts],
            "approvals": [{"id": str(row.id), "function": row.capability_name, "status": row.status,
                           "context": row.context_key, "interaction_id": str(row.interaction_id) if row.interaction_id else None}
                          for row in approvals]}
