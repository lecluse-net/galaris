"""Tests for the agent module."""

# pyright: reportPrivateUsage=false

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.agent import agent_service
from app.agent.assertions import AgentOwnerAssertion
from app.agent.models import Agent
from app.agent.schemas import AgentCreate, AgentUpdate
from core.authorize import AssertionContext
from core.user import UserModel
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.parametrize("names", [{}, {"last_name": ""}, {"last_name": None}])
def test_agent_creation_accepts_no_last_name(names: dict[str, object]) -> None:
    agent = AgentCreate.model_validate(
        {"title_id": 1, "code": "lyra", "first_name": "Lyra", **names}
    )
    assert agent.last_name == ""


@pytest.mark.parametrize("schema", [AgentCreate, AgentUpdate])
@pytest.mark.parametrize("first_name", [None, "", " \t\n"])
def test_agent_requires_a_nonblank_first_name(schema, first_name) -> None:
    with pytest.raises(ValidationError):
        schema.model_validate(
            {"title_id": 1, "code": "lyra", "first_name": first_name, "last_name": "Example"}
        )


def test_agent_creation_requires_first_name() -> None:
    with pytest.raises(ValidationError):
        AgentCreate.model_validate({"title_id": 1, "code": "lyra", "last_name": "Example"})


@pytest.mark.parametrize("last_name", [None, ""])
def test_agent_update_can_clear_last_name_without_changing_first_name(last_name) -> None:
    update = AgentUpdate(last_name=last_name)
    assert update.model_dump(exclude_unset=True) == {"last_name": ""}


@pytest.mark.asyncio
async def test_get_all_can_filter_by_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    monkeypatch.setattr(agent_service, "get_db", lambda: db)

    agents = await agent_service.get_all(limit=1, agent_driver="hermes")

    assert agents == []
    statement = db.execute.await_args.args[0]
    compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
    assert "agent_driver = 'hermes'" in compiled
    assert "LIMIT 1" in compiled


@pytest.mark.asyncio
async def test_update_rejects_agent_code_change_before_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agent code is a permanent identity, notably for Hermes runtimes."""
    agent = SimpleNamespace(code="alice")
    result = MagicMock()
    result.scalar_one_or_none.return_value = agent
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    async def translate(key: str) -> str:
        return key

    monkeypatch.setattr(agent_service, "get_db", lambda: db)
    monkeypatch.setattr(agent_service, "tr", translate)

    with pytest.raises(ValueError, match="agent_api.errors.code_immutable"):
        await agent_service.update(1, AgentUpdate(code="bob"))

    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_accepts_echoed_code_without_writing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy clients may echo the unchanged identity during an update."""
    agent = Agent(
        id=1,
        title_id=1,
        code="alice",
        first_name="Alice",
        last_name="Martin",
        agent_driver="internal",
    )
    current_result = MagicMock()
    current_result.scalar_one_or_none.return_value = agent
    refreshed_result = MagicMock()
    refreshed_result.scalar_one.return_value = agent
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[current_result, refreshed_result])
    db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    ensure_skill_assignment_matrix = AsyncMock()

    monkeypatch.setattr(agent_service, "get_db", lambda: db)
    monkeypatch.setattr(
        agent_service,
        "_ensure_skill_assignment_matrix",
        ensure_skill_assignment_matrix,
    )

    updated = await agent_service.update(1, AgentUpdate(code=" alice "))

    assert updated is agent
    assert agent.code == "alice"
    db.commit.assert_awaited_once()
    ensure_skill_assignment_matrix.assert_awaited_once_with(agent.id)


@pytest.mark.asyncio
async def test_voice_selection_validates_the_realtime_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource = SimpleNamespace(
        label="Realtime model",
        resource_type="model",
        service_capabilities=["realtime_conversation"],
    )
    get_llm = AsyncMock(return_value=resource)
    monkeypatch.setattr(agent_service.llm_service, "get_llm", get_llm)

    await agent_service._validate_voice_selection("realtime:12:voice%3Amarin")

    get_llm.assert_awaited_once_with(12)


@pytest.mark.asyncio
async def test_voice_selection_is_normalized() -> None:
    update = AgentUpdate(voice=" realtime:12:voice%3Amarin ")

    assert update.voice == "realtime:12:voice%3Amarin"


def test_agent_update_rejects_removing_the_human_manager() -> None:
    with pytest.raises(ValidationError, match="user_id cannot be null"):
        AgentUpdate(user_id=None)


@pytest.mark.asyncio
async def test_manager_defaults_to_the_authenticated_creator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        agent_service.user_service,
        "get_current_user_id",
        lambda: 17,
    )
    monkeypatch.setattr(
        agent_service.user_service,
        "get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(id=17, is_active=True)),
    )

    assert await agent_service._validate_manager(None) == 17


@pytest.mark.asyncio
async def test_owner_assertion_allows_only_the_human_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assertion = AgentOwnerAssertion()
    db = MagicMock()
    db.scalar = AsyncMock(return_value=7)
    monkeypatch.setattr(
        "app.agent.assertions.check_privilege",
        AsyncMock(return_value=False),
    )

    assert await assertion.assert_route(
        "update_agent",
        {"id": "42"},
        AssertionContext(user=SimpleNamespace(id=7), db=db),
    )
    assert not await assertion.assert_route(
        "update_agent",
        {"id": "42"},
        AssertionContext(user=SimpleNamespace(id=8), db=db),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("last_name", ["Agent", ""])
async def test_agent_persists_its_required_human_manager(
    db: AsyncSession,
    last_name: str,
) -> None:
    manager = UserModel(
        email="agent-manager@example.test",
        hashed_password="not-used",
        display_name="Agent Manager",
        is_active=True,
    )
    from app.agent.models import Title

    title = Title(label="Managed agent", gender="X")
    db.add_all([manager, title])
    await db.flush()
    agent = Agent(
        user_id=manager.id,
        title_id=title.id,
        code="managed-agent-contract",
        first_name="Managed",
        last_name=last_name,
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()

    loaded = await agent_service.get(agent.id)

    assert loaded is not None
    assert loaded.first_name == "Managed"
    assert loaded.last_name == last_name
    assert loaded.user_id == manager.id
    assert loaded.user.display_name == "Agent Manager"
    foreign_key = next(iter(Agent.__table__.c.user_id.foreign_keys))
    assert foreign_key.ondelete == "RESTRICT"
    assert Agent.__table__.c.user_id.nullable is False


@pytest.mark.asyncio
async def test_update_persists_one_voice_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = Agent(
        id=1,
        title_id=1,
        code="alice",
        first_name="Alice",
        last_name="Martin",
        agent_driver="internal",
        voice="tts:8",
    )
    current_result = MagicMock()
    current_result.scalar_one_or_none.return_value = agent
    refreshed_result = MagicMock()
    refreshed_result.scalar_one.return_value = agent
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[current_result, refreshed_result])
    db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    monkeypatch.setattr(agent_service, "get_db", lambda: db)
    monkeypatch.setattr(
        agent_service,
        "_validate_model_selection",
        AsyncMock(),
    )
    monkeypatch.setattr(
        agent_service,
        "_ensure_skill_assignment_matrix",
        AsyncMock(),
    )

    updated = await agent_service.update(
        1,
        AgentUpdate(voice="realtime:12:voice%3Amarin"),
    )

    assert updated is agent
    assert agent.voice == "realtime:12:voice%3Amarin"


@pytest.mark.asyncio
async def test_create_internal_harness_materializes_skill_assignments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    title_result = MagicMock()
    title_result.scalar_one_or_none.return_value = object()
    created_agents: list[Agent] = []
    refreshed_result = MagicMock()
    refreshed_result.scalar_one.side_effect = lambda: created_agents[0]
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[title_result, refreshed_result])
    db.scalars = AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()

    def add_agent(agent: Agent) -> None:
        agent.id = 42
        created_agents.append(agent)

    db.add.side_effect = add_agent
    ensure_skill_assignment_matrix = AsyncMock()

    monkeypatch.setattr(agent_service, "get_db", lambda: db)
    monkeypatch.setattr(
        agent_service.profile_service,
        "ensure_default_profile_id",
        AsyncMock(return_value=42),
    )
    monkeypatch.setattr(
        agent_service.user_service,
        "get_user_by_id",
        AsyncMock(return_value=SimpleNamespace(id=7, is_active=True)),
    )
    monkeypatch.setattr(
        agent_service,
        "_ensure_skill_assignment_matrix",
        ensure_skill_assignment_matrix,
    )

    from app.tools import mandatory_tools

    sync_integrated_tool_connections = AsyncMock(return_value=0)
    monkeypatch.setattr(
        mandatory_tools,
        "sync_integrated_tool_connections",
        sync_integrated_tool_connections,
    )

    created = await agent_service.create(
        AgentCreate(
            user_id=7,
            title_id=1,
            code="internal-matrix",
            first_name="Internal",
            last_name="Matrix",
            agent_driver="internal",
        )
    )

    assert created is created_agents[0]
    ensure_skill_assignment_matrix.assert_awaited_once_with(42)
    sync_integrated_tool_connections.assert_awaited_once_with(42)
