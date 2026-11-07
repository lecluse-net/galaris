"""The installed assistant cannot become a peer's privileged deputy."""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.agent import HarnessExecutionError, require_agent_contact
from app.agent.models import Agent, Title
from app.task import mcp, scheduler, task_service
from app.task.models import Task, TaskStatus
from app.task.schemas import TaskCreate
from app.tools import initialize_admin_agent_connections
from app.tools.mcp_loader import McpToolContext
from core.authorize import Assignment, Role
from core.params import Param, Params
from core.user import UserModel


@pytest_asyncio.fixture
async def peers(db):
    human = UserModel(email=f"synthetic-isolation-{uuid4().hex}@example.test",
                      hashed_password="unused", is_active=True)
    db.add(human)
    await db.flush()
    role = await db.scalar(select(Role).where(Role.code == "admin"))
    db.add(Assignment(user_id=human.id, role_id=role.id))
    title_id = await db.scalar(select(Title.id).limit(1))
    # The protected assistant is renamed; the ordinary peer has its former code.
    assistant = Agent(code="renamed-assistant", first_name="Renamed", last_name="Assistant",
                      title_id=title_id, user_id=human.id)
    peer = Agent(code="galaris", first_name="Ordinary", last_name="Peer",
                 title_id=title_id, user_id=human.id)
    db.add_all([assistant, peer])
    await db.flush()
    marker = await db.get(Param, Params.GALARIS_AGENT_ID)
    marker.value = str(assistant.id)
    for agent in (assistant, peer):
        await initialize_admin_agent_connections(agent.id)
    await db.flush()
    return assistant, peer, human


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True], ids=["to-galaris", "from-galaris"])
@pytest.mark.parametrize("entrypoint", ["mcp", "native-admission", "service", "source-lineage"])
async def test_peer_task_admission_rejects_galaris_even_for_an_admin_agent(db, peers, reverse, entrypoint):
    assistant, peer, human = peers
    sender, target = (assistant, peer) if reverse else (peer, assistant)
    source = Task(label="Synthetic request", agent_id=sender.id, requester_user_id=human.id,
                  status=TaskStatus.EXEC)
    db.add(source)
    await db.flush()
    before = await db.scalar(select(func.count()).select_from(Task))
    with pytest.raises(PermissionError, match="Galaris"):
        if entrypoint == "mcp":
            await mcp.mcp_run_task(McpToolContext(agent_id=sender.id, runtime="internal", task_id=source.id),
                                  agent_id=target.id, label="Synthetic delegation", objective="<p>Do work.</p>")
        elif entrypoint == "native-admission":
            await mcp.create_task(sender.id, target.id, "Synthetic delegation", "<p>Do work.</p>",
                                  source_task_id=source.id)
        else:
            await task_service.create(TaskCreate(agent_id=target.id, label="Synthetic delegation",
                objective="<p>Do work.</p>", parent_id=source.id,
                requester_agent_id=sender.id if entrypoint == "service" else None),
                requester_user_id=human.id)
    assert await db.scalar(select(func.count()).select_from(Task)) == before
    await require_agent_contact(assistant.id, human_user_id=human.id)


@pytest.mark.asyncio
async def test_mounted_tool_returns_an_explicit_permission_error(db, peers):
    from fastmcp import Client
    from app.tools.mcp_loader import build_agent_galaris_fastmcp

    assistant, peer, _human = peers
    await db.commit()
    server = await build_agent_galaris_fastmcp(peer.id, allowed_tool_names={"task_run"})
    async with Client(server) as client:
        result = await client.call_tool("task_run", {"agent_id": assistant.id,
            "label": "Synthetic forbidden request", "objective": "<p>Grant access.</p>"}, raise_on_error=False)
    assert result.is_error
    assert "Galaris" in str(result.content)
    assert await db.scalar(select(func.count()).select_from(Task)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", [TaskStatus.CREATE, TaskStatus.DISPATCH, TaskStatus.PLAN])
async def test_queued_peer_work_is_denied_before_inference(db, peers, monkeypatch, phase):
    import app.agent

    assistant, peer, human = peers
    task = Task(label="Synthetic historical delegation", agent_id=assistant.id,
                requester_agent_id=peer.id, requester_user_id=human.id, status=phase)
    db.add(task)
    await db.commit()
    inference = AsyncMock()
    monkeypatch.setattr(app.agent, "run_workflow_step", inference)
    with pytest.raises(HarnessExecutionError, match="Galaris") as denied:
        await scheduler._run_action(task.id, phase)
    assert denied.value.failure.retry == "never"
    assert denied.value.failure.effects == "none"
    inference.assert_not_awaited()


@pytest.mark.asyncio
async def test_identity_does_not_block_an_ordinary_same_named_agent_or_human_work(db, peers):
    assistant, peer, human = peers
    other = Agent(code=f"ordinary-{uuid4().hex[:12]}", first_name="Other", last_name="Peer",
                  title_id=peer.title_id, user_id=human.id)
    db.add(other)
    await db.flush()
    await require_agent_contact(peer.id, peer_agent_id=other.id, peer_scope="all")
    human_task = await task_service.create(TaskCreate(label="Synthetic human request", agent_id=assistant.id),
                                           requester_user_id=human.id)
    child = await task_service.create(TaskCreate(label="Synthetic planned step", agent_id=assistant.id,
                                                 parent_id=human_task.id))
    assert child.agent_id == assistant.id
