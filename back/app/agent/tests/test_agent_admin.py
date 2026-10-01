"""Synthetic persistence journeys for AgentAdmin and its live delegation."""

import io
import json
from uuid import UUID, uuid4
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select
from fastmcp import Client

from app.agent import mcp as agent_mcp
from app.agent.admin_schemas import AdminAgentCreate, AdminAgentUpdate
from app.agent.avatar_generation import portrait_prompt
from app.agent.avatars import portrait_snapshot, apply_generated_avatar, validate_avatar
from app.agent.models import Agent, Title
from app.agent import agent_service
from app.connection.models import Connection, ConnectionFunctionState, ConnectionParam
from app.connection import mcp as connections_mcp
from app.tools import mandatory_tools, mcp_loader
from app.tools.models import Tool
from core.authorize import Assignment, Privilege, Role
from app.llm import LLM, LLMProvider, LlmProfile
from core.user import UserModel
from core.user import user_service
from app.agent.schemas import AgentGroupCreate, AgentGroupUpdate, TitleCreate, TitleUpdate


def image_bytes(color="blue", size=(24, 24)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, "PNG")
    return output.getvalue()


@pytest_asyncio.fixture
async def admin_fixture(db):
    return await _make_admin_fixture(db)


@pytest_asyncio.fixture
async def durable_admin_fixture(inference_db):
    return await _make_admin_fixture(inference_db)


async def _make_admin_fixture(db):
    owner = UserModel(email=f"admin-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
    other = UserModel(email=f"other-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
    title = Title(label="Synthetic title", gender="F")
    privileges = (await db.scalars(select(Privilege).where(Privilege.code.in_(
        ["AGENT_EDIT", "CONNECTION_EDIT", "TEAM_ACCESS", "TEAM_EDIT", "TEAM_MEMBERS_EDIT", "TASK_EDIT"])))).all()
    role = Role(code=f"agent-admin-{uuid4().hex}", privileges=list(privileges))
    db.add_all([owner, other, title, role])
    await db.flush()
    db.add(Assignment(user_id=owner.id, role_id=role.id))
    caller = Agent(user_id=owner.id, title_id=title.id, code=f"admin-{uuid4().hex}",
                   first_name="Admin", last_name="Synthetic", agent_driver="internal")
    outsider = Agent(user_id=other.id, title_id=title.id, code=f"target-{uuid4().hex}",
                     first_name="Outside", last_name="Synthetic", agent_driver="internal")
    db.add_all([caller, outsider])
    await db.flush()
    profile = LlmProfile(code=f"admin-profile-{uuid4().hex}", label="Synthetic administration profile")
    db.add(profile)
    await db.flush()
    caller.profile_id = profile.id
    await mandatory_tools.sync_integrated_tool_connections(caller.id)
    admin_tool = await db.scalar(select(Tool).where(Tool.code == "agent_admin"))
    connection = await db.scalar(select(Connection).where(Connection.agent_id == caller.id, Connection.tool_id == admin_tool.id))
    assert connection.active is False
    connection.active = True
    # Domain journeys below have a human-enabled function policy. The real MCP
    # one-action suspension is verified in Tools authorization integration tests.
    from app.connection import facade as connections
    for definition in mcp_loader.load_mcp_tools():
        if definition.tool_code == "agent_admin":
            await connections.set_connection_function_state(connection.id, definition.name, "enabled")
    await db.commit()
    return caller, owner, other, outsider, title, role, connection


@pytest.mark.asyncio
async def test_crud_journey_preserves_html_code_and_default_delegation(db, admin_fixture):
    caller, owner, other, outsider, title, _, connection = admin_fixture
    ctx = mcp_loader.McpToolContext(caller.id, "internal")
    user_service.set_current_user(None)
    data = await agent_mcp.agent_create(ctx, AdminAgentCreate(user_id=owner.id, title_id=title.id,
        code=f"created-{uuid4().hex}", first_name="Lyra", personality="<p>Patient <strong>observer</strong>.</p>"))
    target_id = data["id"]
    assert data["resource_uri"] == f"galaris://agent/{target_id}"
    assert "<strong>observer</strong>" in data["personality"]
    target_connections = (await db.scalars(select(Connection).where(Connection.agent_id == target_id))).all()
    admin_tool = await db.scalar(select(Tool).where(Tool.code == "agent_admin"))
    assert not next(c for c in target_connections if c.tool_id == admin_tool.id).active
    details = await agent_mcp.get_agent(ctx, target_id)
    assert "Lyra" in details
    data = await agent_mcp.agent_update(ctx, target_id, AdminAgentUpdate(job_title="Observer", personality=None))
    assert data["personality"] is None and data["job_title"] == "Observer"
    with pytest.raises(PermissionError):
        await agent_mcp.agent_update(ctx, outsider.id, AdminAgentUpdate(job_title="Denied"))
    with pytest.raises(PermissionError):
        await agent_mcp.agent_update(ctx, target_id, AdminAgentUpdate(user_id=other.id))
    with pytest.raises(ValueError):
        await agent_mcp.agent_update(ctx, target_id, AdminAgentUpdate(code="changed"))
    assert (await agent_mcp.agent_delete(ctx, target_id))["deleted"]
    assert await agent_service.get(target_id) is None
    connection.active = False
    await db.commit()
    with pytest.raises(PermissionError):
        await agent_mcp.agent_create(ctx, AdminAgentCreate(user_id=owner.id, title_id=title.id,
            code="denied", first_name="Denied"))


@pytest.mark.asyncio
async def test_real_connection_target_and_system_or_delegation_protections(db, admin_fixture):
    caller, _, _, outsider, _, _, _ = admin_fixture
    ctx = mcp_loader.McpToolContext(caller.id, "internal")
    await mandatory_tools.sync_integrated_tool_connections(outsider.id)
    outsider_connection = await db.scalar(select(Connection).where(Connection.agent_id == outsider.id))
    await db.commit()
    with pytest.raises(PermissionError):
        await connections_mcp.agent_connection_get(ctx, outsider_connection.id)
    for code in ("galaris", "agent_admin"):
        connection = await db.scalar(select(Connection).join(Tool).where(Connection.agent_id == caller.id, Tool.code == code))
        with pytest.raises((ValueError, PermissionError)):
            await connections_mcp.agent_connection_update(ctx, connection.id, False)


@pytest.mark.asyncio
async def test_catalogue_respects_scope_privileges_and_live_revocation(db, admin_fixture):
    caller, owner, _, _, _, role, connection = admin_fixture
    definitions = await mcp_loader.list_enabled_native_mcp_definitions(caller.id, runtime="internal")
    names = {d.name for d in definitions}
    assert "agent_create" in names
    assert "agent_title_create" not in names
    assert "agent_avatar_generate" not in names
    global_privilege = await db.scalar(select(Privilege).where(Privilege.code == "AGENT_MANAGE_ALL"))
    await db.refresh(role, ["privileges"])
    role.privileges.append(global_privilege)
    await db.commit()
    names = {d.name for d in await mcp_loader.list_enabled_native_mcp_definitions(caller.id, runtime="internal")}
    assert "agent_title_create" in names
    await mandatory_tools.sync_integrated_tool_connections(caller.id)
    connection.active = False
    await db.commit()
    await mandatory_tools.sync_integrated_tool_connections(caller.id)
    await db.refresh(connection)
    assert not connection.active
    assert not any(d.tool_code == "agent_admin" for d in await mcp_loader.list_enabled_native_mcp_definitions(caller.id, runtime="internal"))


@pytest.mark.asyncio
async def test_avatar_publication_detects_aba_and_profile_changes(db, admin_fixture):
    caller, *_ = admin_fixture
    caller_id = caller.id
    first, second = image_bytes(), image_bytes("red")
    await agent_service.update_avatar(caller.id, first)
    first_stored = await agent_service.get_avatar(caller_id)
    await db.refresh(caller)
    snapshot = await portrait_snapshot(caller)
    await agent_service.update_avatar(caller.id, second)
    await agent_service.update_avatar(caller.id, first)
    with pytest.raises(ValueError, match="conflict"):
        await apply_generated_avatar(caller.id, second, snapshot)
    await db.rollback()
    await db.refresh(caller)
    snapshot = await portrait_snapshot(caller)
    await agent_service.update(caller.id, AdminAgentUpdate(personality="<p>Changed.</p>"))
    with pytest.raises(ValueError, match="conflict"):
        await apply_generated_avatar(caller.id, second, snapshot)
    await db.rollback()
    assert await agent_service.get_avatar(caller_id) == first_stored


def test_portrait_data_and_decoding_guarantees():
    prompt = portrait_prompt({"first_name": "Lyra", "gender": "F", "personality": "<p>Careful <b>observer</b></p>"}, "neutral background")
    assert "Careful observer" in prompt and "<p>" not in prompt
    assert "neutral background" in prompt
    validate_avatar(image_bytes())
    with pytest.raises(ValueError):
        validate_avatar(b"not an image")
    with pytest.raises(ValueError):
        validate_avatar(image_bytes()[:30])


@pytest.mark.asyncio
async def test_avatar_uri_transfer_validates_bytes_cleans_temporary_and_rechecks_delegation(db, admin_fixture, monkeypatch, tmp_path):
    from app.file_share import resource_service
    from app.file_share.tests.local_file_transport import TemporaryFileTransport

    caller, _, _, _, _, _, connection = admin_fixture
    caller_id = caller.id
    old, new = image_bytes(), image_bytes("red")
    await agent_service.update_avatar(caller_id, old)
    root = tmp_path / "provider"
    transport = TemporaryFileTransport(root)
    (root / "portrait.png").write_bytes(new)
    (root / "invalid.png").write_bytes(b"This is not an image")
    destinations = []
    revoke_during_transfer = False

    class FileProvider(TemporaryFileTransport):
        async def download_to(self, remote, dest, *, target="", max_bytes=512 * 1024 * 1024):
            destinations.append(dest)
            size = await super().download_to(remote, dest, target=target, max_bytes=max_bytes)
            if revoke_during_transfer:
                connection.active = False
                await db.commit()
            return size

    async def resolve(agent_id, scheme, locator, **kwargs):
        assert agent_id == caller_id and scheme == "synthetic-files"
        return FileProvider(root), "synthetic-files"

    # Replace the provider boundary; use the real URI, bounded materialization and storage.
    monkeypatch.setattr(resource_service, "resolve_resource_transport_with_service", resolve)
    ctx = mcp_loader.McpToolContext(caller_id, "internal")
    result = await agent_mcp.agent_avatar_set(ctx, caller_id, "synthetic-files://portrait.png")
    stored = await agent_service.get_avatar(caller_id)
    assert result["has_avatar"]
    with Image.open(io.BytesIO(stored)) as image:
        assert image.format == "JPEG" and image.size == (24, 24)
        assert image.getpixel((12, 12))[0] > 250
    with pytest.raises(ValueError):
        await agent_mcp.agent_avatar_set(ctx, caller_id, "synthetic-files://invalid.png")
    assert await agent_service.get_avatar(caller_id) == stored
    revoke_during_transfer = True
    with pytest.raises(PermissionError):
        await agent_mcp.agent_avatar_set(ctx, caller_id, "synthetic-files://portrait.png")
    assert await agent_service.get_avatar(caller_id) == stored
    assert destinations and all(not path.parent.exists() for path in destinations)


@pytest_asyncio.fixture
async def image_configuration(db, admin_fixture):
    return await _make_image_configuration(db, admin_fixture)


@pytest_asyncio.fixture
async def durable_image_configuration(inference_db, durable_admin_fixture):
    return await _make_image_configuration(inference_db, durable_admin_fixture)


async def _make_image_configuration(db, admin_fixture):
    caller = admin_fixture[0]
    provider = LLMProvider(name=f"Synthetic portraits {uuid4().hex}", base_url="https://portrait.example.test", is_active=True)
    db.add(provider)
    await db.flush()
    image = LLM(llm_provider_id=provider.id, code=f"portraits-{uuid4().hex}", llm_name="synthetic-portraits",
                label="Synthetic portrait model", primary_capability="image_generation", service_capabilities=["image_generation"], output_image=True)
    db.add(image)
    await db.flush()
    profile = await db.get(LlmProfile, caller.profile_id)
    profile.image_llm_id = image.id
    await db.commit()
    return image, profile


@pytest.mark.asyncio
async def test_mounted_catalogue_has_exact_functions_and_rechecks_every_call(db, admin_fixture, image_configuration):
    caller, owner, _, _, _, role, connection = admin_fixture
    image, profile = image_configuration
    await db.refresh(role, ["privileges"])
    role.privileges.append(await db.scalar(select(Privilege).where(Privilege.code == "AGENT_MANAGE_ALL")))
    await db.commit()
    spec = next(s for s in mandatory_tools.INTEGRATED_TOOL_SPECS if s.code == "agent_admin")
    definitions = mcp_loader.load_mcp_tools()
    assert {d.name for d in definitions if d.tool_code == "agent_admin"} == set(spec.mcp_tools)
    assert len(spec.mcp_tools) == 34
    server = await mcp_loader.build_agent_galaris_fastmcp(caller.id)
    async with Client(server) as client:
        assert set(spec.mcp_tools) <= {t.name for t in await client.list_tools()}
        assert not (await client.call_tool("agent_options", {"category": "managers", "limit": 500})).is_error
        # A retained server observes both removal and restoration of image configuration.
        profile.image_llm_id = None
        await db.commit()
        assert "agent_avatar_generate" not in {t.name for t in await client.list_tools()}
        result = await client.call_tool("agent_avatar_generate", {"agent_id": caller.id}, raise_on_error=False)
        assert result.is_error
        assert result.structured_content["error"]["kind"] == "access_denied"
        profile.image_llm_id = image.id
        await db.commit()
        assert "agent_avatar_generate" in {t.name for t in await client.list_tools()}
        from bridge.openrouter import PROFILE
        from app.llm.provider_facade import register_provider
        register_provider(PROFILE)
        provider = await db.get(LLMProvider, image.llm_provider_id)
        # The isolated seed already owns this unique catalogue; transfer it to
        # the synthetic provider used to verify live credential availability.
        seeded_provider = await db.scalar(select(LLMProvider).where(LLMProvider.catalog_code == "openrouter"))
        if seeded_provider is not None and seeded_provider.id != provider.id:
            seeded_provider.catalog_code = None
            await db.flush()
        provider.catalog_code = "openrouter"
        provider.api_key = None
        await db.commit()
        assert "agent_avatar_generate" not in {t.name for t in await client.list_tools()}
        from core.util import get_encryption_service
        provider.api_key = get_encryption_service().encrypt("synthetic-image-key")
        await db.commit()
        assert "agent_avatar_generate" in {t.name for t in await client.list_tools()}
        from app.connection import facade as connections
        await connections.set_connection_function_state(connection.id, "agent_options", "disabled")
        await db.commit()
        assert "agent_options" not in {t.name for t in await client.list_tools()}
        assert (await client.call_tool("agent_options", {"category": "managers"}, raise_on_error=False)).is_error
        owner.is_active = False
        await db.commit()
        assert not set(spec.mcp_tools) & {t.name for t in await client.list_tools()}
        assert (await client.call_tool("agent_title_list", {}, raise_on_error=False)).is_error


@pytest.mark.asyncio
@pytest.mark.parametrize("revoked", [False, True])
async def test_avatar_requires_approval_and_approved_call_completes_without_replay(
    inference_db, durable_admin_fixture, durable_image_configuration, monkeypatch, revoked,
):
    from app.connection import facade as connections
    from app.task.models import Task, TaskStatus
    from app.tools.authorization import AUTHORIZATION_META_KEY, answer_action
    from app.tools.authorization_models import ActionAuthorization
    from app.tools.contracts import ToolExecutionContext, tool_execution
    db = inference_db
    caller, owner, _, _, _, _, connection = durable_admin_fixture
    await connections.set_connection_function_state(connection.id, "agent_avatar_generate", "ask")
    task = Task(agent_id=caller.id, label="Synthetic portrait", objective="<p>Generate a synthetic portrait</p>", status=TaskStatus.EXEC)
    db.add(task)
    await db.commit()
    operation = uuid4()
    async def call():
        with tool_execution(ToolExecutionContext(operation_id=operation, tool_name="agent_avatar_generate")):
            return await mcp_loader.execute_native_mcp_tool(caller.id, runtime="internal", task_id=task.id,
                tool_name="agent_avatar_generate", arguments={"agent_id": caller.id, "instructions": "Synthetic studio background"})
    provider = AsyncMock(return_value=(image_bytes(), "image/png"))
    import app.image
    monkeypatch.setattr(app.image, "generate_image_bytes", provider)
    pending = await call()
    control = pending.meta[AUTHORIZATION_META_KEY]
    assert pending.is_error and control["status"] == "pending"
    request_id = UUID(control["request_id"])
    provider.assert_not_awaited()
    assert await answer_action(request_id, user_id=owner.id, approved=True)
    if revoked:
        await connections.set_connection_function_state(connection.id, "agent_avatar_generate", "disabled")
        with pytest.raises(PermissionError):
            await call()
        provider.assert_not_awaited()
    else:
        result = await call()
        provider.assert_awaited_once()
        assert result["registered"] is True and result["status"] == "success"
        assert (await db.get(ActionAuthorization, request_id)).status == "completed"
        replay = await call()
        assert replay.is_error
        provider.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "invalid", "provider_error", "revoked", "profile_changed", "late_avatar", "deleted"])
async def test_direct_generation_preserves_old_avatar_on_failure(db, admin_fixture, image_configuration, monkeypatch, outcome):
    caller, _, _, _, _, _, connection = admin_fixture
    model, _ = image_configuration
    caller_id, model_id = caller.id, model.id
    old, new, late = image_bytes(), image_bytes("red"), image_bytes("green")
    await agent_service.update_avatar(caller_id, old)
    old = await agent_service.get_avatar(caller_id)
    ctx = mcp_loader.McpToolContext(caller_id, "internal")
    async def provider(prompt, **kwargs):
        nonlocal late
        assert "Admin" in prompt and "gender" in prompt and "personality" in prompt
        assert kwargs["agent_id"] == caller_id and kwargs["model_id"] == model_id
        assert kwargs["task_id"] is None
        if outcome == "provider_error":
            raise TimeoutError("Synthetic ambiguous timeout")
        if outcome == "revoked":
            connection.active = False
            await db.commit()
        if outcome == "profile_changed":
            await agent_service.update(caller_id, AdminAgentUpdate(job_title="Changed during generation"))
        if outcome == "late_avatar":
            await agent_service.update_avatar(caller_id, late)
            late = await agent_service.get_avatar(caller_id)
        if outcome == "deleted":
            await agent_service.delete(caller_id)
        return (b"not an image" if outcome == "invalid" else new), "image/png"

    import app.image
    boundary = AsyncMock(side_effect=provider)
    monkeypatch.setattr(app.image, "generate_image_bytes", boundary)
    if outcome == "success":
        result = await agent_mcp.agent_avatar_generate(ctx, caller_id, "neutral studio background")
        assert result["status"] == "success" and result["registered"] is True
        with Image.open(io.BytesIO(await agent_service.get_avatar(caller_id))) as image:
            assert image.format == "JPEG" and image.size == (24, 24)
            assert image.getpixel((12, 12))[0] > 250
    elif outcome == "deleted":
        with pytest.raises((LookupError, PermissionError)):
            await agent_mcp.agent_avatar_generate(ctx, caller_id)
        assert await agent_service.get(caller_id) is None
    else:
        with pytest.raises((ValueError, PermissionError, TimeoutError)):
            await agent_mcp.agent_avatar_generate(ctx, caller_id)
        assert await agent_service.get_avatar(caller_id) == (late if outcome == "late_avatar" else old)
    boundary.assert_awaited_once()


@pytest.mark.asyncio
async def test_avatar_generation_registers_directly_without_creating_processes(db, admin_fixture, image_configuration, monkeypatch):
    from app.process.models import ProcessDefinition, ProcessRun
    from sqlalchemy import func

    caller = admin_fixture[0]
    caller.personality = "<p>Patient synthetic astronomer</p>"
    await db.commit()
    definitions = await db.scalar(select(func.count()).select_from(ProcessDefinition))
    runs = await db.scalar(select(func.count()).select_from(ProcessRun))
    import app.image
    provider = AsyncMock(return_value=(image_bytes("red", (1200, 800)), "image/png"))
    monkeypatch.setattr(app.image, "generate_image_bytes", provider)
    result = await agent_mcp.agent_avatar_generate(mcp_loader.McpToolContext(caller.id, "internal"), caller.id)
    assert result["registered"] is True and result["status"] == "success"
    provider.assert_awaited_once()
    prompt = provider.await_args.args[0]
    profile = json.loads(prompt.split("\n")[1])
    assert profile == {"first_name": "Admin", "last_name": "Synthetic", "gender": "F",
                       "personality": "Patient synthetic astronomer"}
    with Image.open(io.BytesIO(await agent_service.get_avatar(caller.id))) as avatar:
        assert avatar.format == "JPEG" and avatar.size == (500, 333)
    assert await db.scalar(select(func.count()).select_from(ProcessDefinition)) == definitions
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == runs


@pytest.mark.asyncio
async def test_direct_generation_without_image_model_fails_before_calling_provider(db, admin_fixture):
    caller = admin_fixture[0]
    with pytest.raises(ValueError, match="image generation model"):
        await agent_mcp.agent_avatar_generate(mcp_loader.McpToolContext(caller.id, "internal"), caller.id)


@pytest.mark.asyncio
async def test_connection_parameters_are_atomic_encrypted_and_masked(db, admin_fixture):
    caller = admin_fixture[0]
    ctx = mcp_loader.McpToolContext(caller.id, "internal")
    tool = Tool(code=f"synthetic_{uuid4().hex}", label="Synthetic optional connector",
                connection_schema={"params": {"token": {"type": "password"}, "count": {"type": "integer", "default": "2"}}})
    db.add(tool)
    await db.commit()
    created = await connections_mcp.agent_connection_create(ctx, caller.id, tool.id)
    identifier = created["id"]
    assert created["active"] is False
    with pytest.raises(ValueError, match="already exists"):
        await connections_mcp.agent_connection_create(ctx, caller.id, tool.id)
    secret = "synthetic-secret-never-return"
    updated = await connections_mcp.agent_connection_params_set(ctx, identifier, {"token": secret, "count": "3"})
    assert secret not in repr(updated)
    saved = await db.scalar(select(ConnectionParam).where(ConnectionParam.connection_id == identifier, ConnectionParam.param_name == "token"))
    assert saved.param_value != secret
    from core.util import get_encryption_service
    assert get_encryption_service().decrypt(saved.param_value) == secret
    with pytest.raises(ValueError):
        await connections_mcp.agent_connection_params_set(ctx, identifier, {"token": "must-not-persist", "count": "invalid"})
    await db.refresh(saved)
    assert get_encryption_service().decrypt(saved.param_value) == secret
    inherited = await connections_mcp.agent_connection_param_delete(ctx, identifier, "count")
    assert inherited["effective_params"]["count"]["value"] == "2"
    await connections_mcp.agent_connection_update(ctx, identifier, True)
    assert (await connections_mcp.agent_connection_get(ctx, identifier))["active"]
    await connections_mcp.agent_connection_delete(ctx, identifier)
    assert await db.get(Connection, identifier) is None
    assert await db.scalar(select(ConnectionParam.id).where(ConnectionParam.connection_id == identifier)) is None


@pytest.mark.asyncio
async def test_shared_references_and_membership_preserve_legacy_consistency(db, admin_fixture):
    caller, _, _, _, _, role, _ = admin_fixture
    ctx = mcp_loader.McpToolContext(caller.id, "internal")
    with pytest.raises(PermissionError):
        await agent_mcp.agent_group_create(ctx, AgentGroupCreate(name="Denied"))
    await db.refresh(role, ["privileges"])
    role.privileges.append(await db.scalar(select(Privilege).where(Privilege.code == "AGENT_MANAGE_ALL")))
    await db.commit()
    title = await agent_mcp.agent_title_create(ctx, TitleCreate(label="Synthetic Dr", gender="F"))
    title = await agent_mcp.agent_title_update(ctx, title["id"], TitleUpdate(label="Synthetic Professor"))
    group = await agent_mcp.agent_group_create(ctx, AgentGroupCreate(name="Synthetic astronomy team"))
    group = await agent_mcp.agent_group_update(ctx, group["id"], AgentGroupUpdate(name="Synthetic observers", order=4))
    await agent_mcp.agent_update(ctx, caller.id, AdminAgentUpdate(title_id=title["id"], group_id=group["id"]))
    for _ in range(2):
        member = await agent_mcp.agent_team_set(ctx, caller.id, group["id"], True)
        assert member["team_ids"] == [group["id"]]
    with pytest.raises(ValueError, match="referenced"):
        await agent_mcp.agent_title_delete(ctx, title["id"])
    member = await agent_mcp.agent_team_set(ctx, caller.id, group["id"], False)
    assert member["group_id"] is None and member["team_ids"] == []
    await agent_mcp.agent_team_set(ctx, caller.id, group["id"], True)
    await agent_mcp.agent_group_delete(ctx, group["id"])
    assert (await agent_service.get(caller.id)).team_ids == []
    await agent_mcp.agent_update(ctx, caller.id, AdminAgentUpdate(title_id=admin_fixture[4].id))
    assert (await agent_mcp.agent_title_delete(ctx, title["id"]))["deleted"]


def test_harness_logs_are_bounded_and_remove_credentials_and_host_paths():
    from app.harnesses.sanitizer import redact_logs
    result = redact_logs(['{"api_key": "synthetic-key", "authorization": "Bearer synthetic-token"}',
                          'password=synthetic-password /srv/private/runtime https://host.example.test/log',
                          'sk-syntheticrawcredential', *(['x' * 5000] * 200)])
    assert not any(value in repr(result) for value in ("synthetic-key", "synthetic-token", "synthetic-password", "/srv/private", "https://", "sk-synthetic"))
    assert sum(map(len, result)) <= 200_000 and max(map(len, result)) <= 2000


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup_fails", [False, True])
async def test_harness_mcp_selection_blockers_supervision_and_cleanup(db, admin_fixture, monkeypatch, cleanup_fails):
    from app.harnesses import mcp as harness_mcp, service as harness_service
    from app.harnesses.models import Harness
    from app.harnesses.registry import get_provider
    from app.task.models import Task, TaskStatus
    from core.util import get_encryption_service

    caller, owner, _, _, title, _, _ = admin_fixture
    target = Agent(user_id=owner.id, title_id=title.id, code=f"harness-target-{uuid4().hex}", first_name="Synthetic", last_name="Target")
    harness = Harness(name="Synthetic shared Harness", provider_code="openai_messages", driver_code="openai_messages",
                      enabled=True, base_url="https://harness.example.test/v1", model="synthetic-model",
                      api_token_encrypted=get_encryption_service().encrypt("synthetic-harness-secret"))
    db.add_all([target, harness])
    await db.flush()
    task = Task(label="Synthetic pending work", agent_id=target.id, status=TaskStatus.CREATE)
    db.add(task)
    await db.commit()
    ctx = mcp_loader.McpToolContext(caller.id, "internal")
    assert (await harness_mcp.agent_harness_get(ctx, target.id))["internal"]
    assert (await harness_mcp.agent_harness_status(ctx, target.id))["status"] == "internal"
    blockers = await harness_mcp.agent_harness_blockers(ctx, target.id)
    assert blockers["active_tasks"] == [{"uri": f"galaris://task/{task.id}", "label": task.label}]
    with pytest.raises(harness_service.HarnessConflictError):
        await harness_mcp.agent_harness_set(ctx, target.id, harness.id)
    assert (await harness_mcp.agent_harness_get(ctx, target.id))["internal"]
    task.status = TaskStatus.SUCCESS
    await db.commit()
    selected = await harness_mcp.agent_harness_set(ctx, target.id, harness.id)
    assert selected["operation_status"] == "completed" and selected["lifecycle_status"] == "ready"
    assert selected["model"] == "synthetic-model"
    assert not {"base_url", "token", "api_token_encrypted", "settings", "last_error"} & selected.keys()
    state = await harness_mcp.agent_harness_status(ctx, target.id)
    assert state["status"] == "ready" and state["available_actions"] == []
    with pytest.raises(harness_service.HarnessConflictError):
        await harness_mcp.agent_harness_action(ctx, target.id, "stop")
    with pytest.raises(harness_service.HarnessConflictError):
        await harness_mcp.agent_harness_logs(ctx, target.id)
    if cleanup_fails:
        monkeypatch.setattr(get_provider("openai_messages"), "deprovision",
                            AsyncMock(side_effect=OSError("Synthetic cleanup failure")))
    reset = await harness_mcp.agent_harness_reset(ctx, target.id)
    assert reset["operation_status"] == ("error" if cleanup_fails else "completed")
    assert reset["internal"]
