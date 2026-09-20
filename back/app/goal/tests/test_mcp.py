"""Contract tests for self-service and administrative Goal MCP functions."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, AsyncIterator
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.tools.mcp_loader import McpToolContext, build_galaris_fastmcp
from app.tools.models import Tool

from .. import mcp
from ..models import Goal, GoalStatus
from ..schemas import GoalMessengerReferrerInput
from .factories import make_goal


@asynccontextmanager
async def _session() -> AsyncIterator[None]:
    yield


class _Response:
    def __init__(
        self,
        *,
        agent_id: int = 12,
        identifier: str = "goal-1",
        revision: int = 1,
    ) -> None:
        self.agent_id = agent_id
        self.identifier = identifier
        self.revision = revision

    def model_dump(self, *, mode: str) -> dict[str, object]:
        assert mode == "json"
        return {
            "id": self.identifier,
            "revision": self.revision,
            "agent_id": self.agent_id,
        }


async def _new_agent(db: Any, prefix: str) -> Agent:
    title_id = await db.scalar(select(Title.id).limit(1))
    if title_id is None:
        title = Title(label="Test", gender="M")
        db.add(title)
        await db.flush()
        title_id = title.id
    agent = Agent(
        title_id=title_id,
        code=f"{prefix}-{uuid4().hex[:10]}",
        first_name="Goal",
        last_name="Tester",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    return agent


@pytest.mark.asyncio
async def test_goal_self_service_tool_schemas_are_exposed_by_galaris() -> None:
    server = build_galaris_fastmcp(
        90,
        runtime="internal",
        enabled_tool_codes={"galaris", "file_sharing"},
    )
    tools = {tool.name: tool for tool in await server.list_tools()}

    assert {"goal_list", "goal_get", "goal_get_suivi"}.isdisjoint(tools)
    assert {"file_list", "file_search", "file_read"} <= tools.keys()
    assert tools["goal_update_suivi"].parameters["required"] == [
        "goal_id",
        "expected_revision",
        "tracking_content",
    ]
    assert tools["goal_run_now"].parameters["required"] == [
        "goal_id",
        "expected_revision",
    ]


@pytest.mark.asyncio
async def test_goal_create_selects_owner_and_human_referrer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = AsyncMock(return_value=_Response())
    monkeypatch.setattr(mcp.goal_service, "create", create)
    monkeypatch.setattr(
        mcp,
        "_require_goal_management_access",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    result = await mcp.mcp_goal_create(
        McpToolContext(agent_id=90, runtime="internal"),
        agent_id=12,
        referrer_connection_id=34,
        referrer_user_id="human-34",
        referrer_display_name="Human supervisor",
        title="Développer l'équipe",
        description="Accompagner la progression de l'équipe dans la durée.",
        cycle_delay_seconds=7200,
    )

    data = create.await_args.args[0]
    assert data.agent_id == 12
    assert isinstance(data.referrer, GoalMessengerReferrerInput)
    assert data.referrer.connection_id == 34
    assert data.referrer.user_id == "human-34"
    assert data.cycle_delay_seconds == 7200
    assert result == {"id": "goal-1", "revision": 1, "agent_id": 12}


@pytest.mark.asyncio
async def test_goal_list_normalizes_status(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _Response()
    list_page = AsyncMock(return_value=page)
    monkeypatch.setattr(mcp.goal_service, "list_page", list_page)
    monkeypatch.setattr(mcp, "_has_goal_management_access", AsyncMock(return_value=False))
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    await mcp.mcp_goal_list(
        McpToolContext(agent_id=90, runtime="internal"),
        status="paused",
    )

    assert list_page.await_args.kwargs["agent_id"] == 90
    assert list_page.await_args.kwargs["status"] == mcp.GoalStatus.PAUSED


@pytest.mark.asyncio
async def test_goal_list_rejects_another_owner_without_management(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    list_page = AsyncMock()
    monkeypatch.setattr(mcp.goal_service, "list_page", list_page)
    monkeypatch.setattr(mcp, "_has_goal_management_access", AsyncMock(return_value=False))
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    with pytest.raises(ValueError, match="current agent"):
        await mcp.mcp_goal_list(
            McpToolContext(agent_id=90, runtime="internal"),
            agent_id=12,
        )

    list_page.assert_not_awaited()


@pytest.mark.asyncio
async def test_goal_list_management_scope_can_list_every_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _Response()
    list_page = AsyncMock(return_value=page)
    monkeypatch.setattr(mcp.goal_service, "list_page", list_page)
    monkeypatch.setattr(mcp, "_has_goal_management_access", AsyncMock(return_value=True))
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    await mcp.mcp_goal_list(McpToolContext(agent_id=90, runtime="internal"))

    assert list_page.await_args.kwargs["agent_id"] is None


@pytest.mark.asyncio
async def test_goal_management_access_requires_the_active_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_connection = AsyncMock(side_effect=[False, True])
    monkeypatch.setattr(
        "app.connection.connection_service.has_active_tool_connection",
        active_connection,
    )
    ctx = McpToolContext(agent_id=90, runtime="internal")

    assert await mcp._has_goal_management_access(  # pyright: ignore[reportPrivateUsage]
        ctx
    ) is False
    assert await mcp._has_goal_management_access(  # pyright: ignore[reportPrivateUsage]
        ctx
    ) is True
    assert active_connection.await_args_list[0].kwargs == {
        "agent_id": 90,
        "tool_code": "goal_management",
    }


@pytest.mark.asyncio
async def test_goal_visibility_is_owner_scoped_unless_management_is_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = uuid4()
    own_goal = _Response(agent_id=90, identifier=str(identifier))
    foreign_goal = _Response(
        agent_id=12,
        identifier=str(identifier),
    )
    get_detail = AsyncMock(side_effect=[own_goal, None, foreign_goal])
    owner_scope = AsyncMock(side_effect=[90, 90, None])
    monkeypatch.setattr(mcp.goal_service, "get_detail", get_detail)
    monkeypatch.setattr(mcp, "_goal_owner_scope", owner_scope)

    assert await mcp._goal_visible_to_caller(  # pyright: ignore[reportPrivateUsage]
        McpToolContext(agent_id=90, runtime="internal"), identifier
    ) is own_goal
    assert get_detail.await_args.kwargs == {"owner_agent_id": 90}

    with pytest.raises(ValueError, match="Goal not found"):
        await mcp._goal_visible_to_caller(  # pyright: ignore[reportPrivateUsage]
            McpToolContext(agent_id=90, runtime="internal"), identifier
        )

    assert await mcp._goal_visible_to_caller(  # pyright: ignore[reportPrivateUsage]
        McpToolContext(agent_id=90, runtime="internal"), identifier
    ) is foreign_goal
    assert get_detail.await_args.kwargs == {"owner_agent_id": None}


@pytest.mark.parametrize(
    ("function_name", "kwargs", "service_name"),
    [
        (
            "mcp_goal_create",
            {
                "agent_id": 12,
                "referrer_connection_id": 34,
                "referrer_user_id": "human-34",
                "referrer_display_name": "Human supervisor",
                "title": "Restricted Goal",
                "description": "Must not be created without the admin witness.",
            },
            "create",
        ),
        (
            "mcp_goal_update",
            {
                "goal_id": str(uuid4()),
                "expected_revision": 1,
                "title": "Restricted update",
            },
            "update",
        ),
        (
            "mcp_goal_pause",
            {"goal_id": str(uuid4()), "expected_revision": 1},
            "pause",
        ),
        (
            "mcp_goal_resume",
            {"goal_id": str(uuid4()), "expected_revision": 1},
            "resume",
        ),
        (
            "mcp_goal_complete",
            {"goal_id": str(uuid4()), "expected_revision": 1},
            "complete",
        ),
        (
            "mcp_goal_delete",
            {"goal_id": str(uuid4())},
            "delete",
        ),
    ],
)
@pytest.mark.asyncio
async def test_every_goal_admin_tool_revalidates_the_live_management_witness(
    function_name: str,
    kwargs: dict[str, Any],
    service_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    denied = AsyncMock(
        side_effect=PermissionError("goal_management connection is inactive")
    )
    service = AsyncMock()
    monkeypatch.setattr(mcp, "_require_goal_management_access", denied)
    monkeypatch.setattr(mcp.goal_service, service_name, service)
    monkeypatch.setattr("core.database.database.get_db_session", _session)
    ctx = McpToolContext(agent_id=90, runtime="internal")

    function = getattr(mcp, function_name)
    with pytest.raises(PermissionError, match="inactive"):
        await function(ctx, **kwargs)

    denied.assert_awaited_once_with(ctx)
    service.assert_not_awaited()


@pytest.mark.asyncio
async def test_live_management_connection_controls_cross_owner_goal_access(db: Any) -> None:
    caller = await _new_agent(db, "goal-caller")
    owner = await _new_agent(db, "goal-owner")
    own_goal = await make_goal(
        title="Caller's Goal",
        description="Visible without administration.",
        tracking_content="# Own tracking",
        agent_id=caller.id,
        cycle_delay_seconds=3600,
        status=GoalStatus.PAUSED,
    )
    foreign_goal = await make_goal(
        title="Another agent's Goal",
        description="Hidden unless the live admin witness is active.",
        tracking_content="<h1>Foreign tracking</h1>",
        agent_id=owner.id,
        cycle_delay_seconds=3600,
        status=GoalStatus.PAUSED,
    )
    db.add_all([own_goal, foreign_goal])

    management_tool = await db.scalar(
        select(Tool).where(Tool.code == "goal_management")
    )
    if management_tool is None:
        management_tool = Tool(
            code="goal_management",
            label="Goal management",
            description="",
            connection_schema={},
        )
        db.add(management_tool)
        await db.flush()
    connection = Connection(
        tool_id=management_tool.id,
        agent_id=caller.id,
        active=False,
    )
    db.add(connection)
    await db.commit()

    ctx = McpToolContext(agent_id=caller.id, runtime="internal")
    own = await mcp.mcp_goal_get(ctx, str(own_goal.id))
    assert own["agent_id"] == caller.id
    with pytest.raises(ValueError, match="Goal not found"):
        await mcp.mcp_goal_get(ctx, str(foreign_goal.id))
    with pytest.raises(ValueError, match="Goal not found"):
        await mcp.mcp_goal_update_suivi(
            ctx,
            str(foreign_goal.id),
            expected_revision=foreign_goal.revision,
            tracking_content="# Unauthorized change",
        )

    await db.refresh(foreign_goal)
    assert (await mcp.goal_service.read_markdown(foreign_goal)).tracking == "<h1>Foreign tracking</h1>"

    connection.active = True
    await db.commit()
    foreign = await mcp.mcp_goal_get(ctx, str(foreign_goal.id))
    assert foreign["agent_id"] == owner.id
    administered = await mcp.mcp_goal_update(
        ctx,
        str(foreign_goal.id),
        expected_revision=int(foreign["revision"]),
        title="Authorized administrative update",
    )
    assert administered["title"] == "Authorized administrative update"
    updated = await mcp.mcp_goal_update_suivi(
        ctx,
        str(foreign_goal.id),
        expected_revision=int(administered["revision"]),
        tracking_content="<h1>Authorized admin change</h1>",
    )
    assert updated["tracking_content"] == "<h1>Authorized admin change</h1>"

    connection.active = False
    await db.commit()
    with pytest.raises(ValueError, match="Goal not found"):
        await mcp.mcp_goal_get(ctx, str(foreign_goal.id))


@pytest.mark.asyncio
async def test_goal_get_returns_goal_without_cycles(monkeypatch: pytest.MonkeyPatch) -> None:
    identifier = uuid4()
    goal = _Response(agent_id=90, identifier=str(identifier), revision=3)
    visible = AsyncMock(return_value=goal)
    monkeypatch.setattr(mcp, "_goal_visible_to_caller", visible)
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    result = await mcp.mcp_goal_get(
        McpToolContext(agent_id=90, runtime="internal"),
        str(identifier),
    )

    assert result == {"id": str(identifier), "revision": 3, "agent_id": 90}
    visible.assert_awaited_once_with(
        McpToolContext(agent_id=90, runtime="internal"), identifier
    )


@pytest.mark.asyncio
async def test_goal_get_suivi_returns_bounded_newest_cycles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = uuid4()
    ctx = McpToolContext(agent_id=90, runtime="internal")
    cycle = _Response(agent_id=90, identifier="cycle-1")
    list_cycles = AsyncMock(return_value=SimpleNamespace(items=[cycle]))
    owner_scope = AsyncMock(return_value=90)
    monkeypatch.setattr(mcp, "_goal_owner_scope", owner_scope)
    monkeypatch.setattr(mcp.goal_service, "list_cycles", list_cycles)
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    result = await mcp.mcp_goal_get_suivi(ctx, str(identifier), limit=7)

    assert result == [{"id": "cycle-1", "revision": 1, "agent_id": 90}]
    owner_scope.assert_awaited_once_with(ctx)
    list_cycles.assert_awaited_once_with(
        identifier,
        page=1,
        page_size=7,
        owner_agent_id=90,
    )


@pytest.mark.asyncio
async def test_goal_update_suivi_updates_only_tracking_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = uuid4()
    ctx = McpToolContext(agent_id=90, runtime="internal")
    owner_scope = AsyncMock(return_value=90)
    update = AsyncMock(
        return_value=_Response(agent_id=90, identifier=str(identifier), revision=5)
    )
    monkeypatch.setattr(mcp, "_goal_owner_scope", owner_scope)
    monkeypatch.setattr(mcp.goal_service, "update", update)
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    result = await mcp.mcp_goal_update_suivi(
        ctx,
        str(identifier),
        expected_revision=4,
        tracking_content="<h1>Suivi courant</h1>",
    )

    data = update.await_args.args[1]
    assert update.await_args.kwargs == {"owner_agent_id": 90}
    assert data.expected_revision == 4
    assert data.tracking_content == "<h1>Suivi courant</h1>"
    assert data.model_fields_set == {"expected_revision", "tracking_content"}
    assert result["revision"] == 5


@pytest.mark.asyncio
async def test_goal_run_now_checks_visibility_before_lifecycle_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identifier = uuid4()
    ctx = McpToolContext(agent_id=90, runtime="internal")
    owner_scope = AsyncMock(return_value=90)
    run_now = AsyncMock(
        return_value=_Response(agent_id=90, identifier=str(identifier), revision=8)
    )
    monkeypatch.setattr(mcp, "_goal_owner_scope", owner_scope)
    monkeypatch.setattr(mcp.goal_service, "run_now", run_now)
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    result = await mcp.mcp_goal_run_now(ctx, str(identifier), expected_revision=7)

    called_identifier, command = run_now.await_args.args
    assert run_now.await_args.kwargs == {"owner_agent_id": 90}
    assert called_identifier == identifier
    assert command.expected_revision == 7
    assert result["revision"] == 8


@pytest.mark.asyncio
async def test_goal_ask_referrer_uses_current_task_and_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    ask = AsyncMock(return_value="Question envoyée")
    monkeypatch.setattr(mcp, "ask_human_referrer", ask)
    monkeypatch.setattr(mcp, "context_language", AsyncMock(return_value="fr"))
    monkeypatch.setattr("core.database.database.get_db_session", _session)

    result = await mcp.mcp_goal_ask_referrer(
        McpToolContext(agent_id=90, runtime="internal", task_id=task_id),
        "Quelle option choisir ?",
    )

    assert result == "Question envoyée"
    ask.assert_awaited_once_with(
        task_id=task_id,
        agent_id=90,
        question="Quelle option choisir ?",
        language="fr",
    )
