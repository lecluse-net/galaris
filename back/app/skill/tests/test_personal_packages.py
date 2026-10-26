"""Persistence and access guarantees for the new package boundary."""

from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection import Connection, ConnectionParam
from app.skill import interface, skill_service, storage
from app.skill.contracts import SkillPackageCreate, SkillRevisionConflict, SkillScope
from app.skill.models import AgentSkill, Skill
from app.skill.schemas import SkillCreate
from app.tools.models import Tool
from app.tools.contracts import MANAGEMENT_SCOPE_PARAM
from core.database import get_db


async def set_scope(agent_id: int, scope: str) -> None:
    db = get_db()
    connection = await db.scalar(select(Connection).join(Tool).where(Connection.agent_id == agent_id, Tool.code == 'skills'))
    row = await db.scalar(select(ConnectionParam).where(ConnectionParam.connection_id == connection.id,
        ConnectionParam.param_name == MANAGEMENT_SCOPE_PARAM))
    if row is None:
        db.add(ConnectionParam(connection_id=connection.id, param_name=MANAGEMENT_SCOPE_PARAM, param_value=scope))
    else:
        row.param_value = scope
    await db.commit()


def personal(code: str = "shared-name", body: str = "Synthetic procedure") -> SkillPackageCreate:
    return SkillPackageCreate(
        code=code, label="Synthetic skill",
        markdown=f"---\nname: {code}\ndescription: Synthetic procedure.\n---\n{body}\n",
    )


@pytest_asyncio.fixture
async def agents(db: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills"))
    monkeypatch.setattr(storage, "SYSTEM_SKILLS", ())
    title = Title(label="Mx", gender="M")
    db.add(title)
    await db.flush()
    result = [Agent(title_id=title.id, code=f"private-{suffix}", first_name="Synthetic",
                    last_name=suffix, agent_driver="internal") for suffix in ("a", "b", "admin")]
    db.add_all(result)
    tool = await db.scalar(select(Tool).where(Tool.code.in_(("skill_management", "skills"))))
    if tool is None:
        tool = Tool(code="skills", label="Skills")
        db.add(tool)
    else:
        # Exercise the new boundary with the future identity of the same Tool.
        tool.code = "skills"
    await db.flush()
    for agent, scope in zip(result, ("personal", "personal", "all"), strict=True):
        db.add(Connection(agent_id=agent.id, tool_id=tool.id, active=True))
    await db.commit()
    for agent, scope in zip(result, ('personal', 'personal', 'all'), strict=True):
        await set_scope(agent.id, scope)
    return result


@pytest.mark.asyncio
async def test_homonyms_stay_private_across_catalogues_and_rescans(db, agents):
    a, b, admin = agents
    generic = await skill_service.create(SkillCreate(code="shared-name", label="Generic",
                                                     markdown=personal(body="Generic").markdown))
    await skill_service.set_agent_authorization(generic.id, a.id, "enabled")
    first = await interface.create_package(personal(body="Only A"), actor_agent_id=a.id)
    second = await interface.create_package(personal(body="Only B"), actor_agent_id=b.id)
    system_homonym = await interface.create_package(personal("galaris"), actor_agent_id=a.id)
    assert len({generic.id, first.id, second.id}) == 3
    assert first.uri == f"galaris://skill/personnal/{a.id}/shared-name/"
    assert first.kind == "personal"
    assert {item.id for item in await interface.list_packages(actor_agent_id=a.id)} >= {generic.id, first.id}
    assert second.id not in {item.id for item in await interface.list_packages(actor_agent_id=a.id)}
    assert (await interface.read_package_file(first.id, "SKILL.md", actor_agent_id=a.id)).content.endswith(b"Only A\n")
    for actor in (b, admin):
        with pytest.raises(FileNotFoundError):
            await interface.read_package_file(first.id, "SKILL.md", actor_agent_id=actor.id)
    assert b"Only A" in (await interface.read_package_file(
        first.id, "SKILL.md", actor_agent_id=admin.id, administration=True,
    )).content
    with pytest.raises(PermissionError):
        await interface.list_packages(actor_agent_id=a.id, administration=True)

    await skill_service.ensure_assignment_matrix()
    await skill_service.sync_from_disk()
    await skill_service.sync_from_disk()
    assert await skill_service.get(first.id) is None
    assert await skill_service.get_by_code("shared-name") is generic
    assert {item.id for item in await skill_service.get_catalogue()}.isdisjoint({first.id, second.id})
    assert {item.skill_id for item in await skill_service.list_authorizations()}.isdisjoint({first.id, second.id})
    assert [(item.agent_id, item.active) for item in (await db.scalars(
        select(AgentSkill).where(AgentSkill.skill_id == first.id)
    )).all()] == [(a.id, True)]
    assert (await db.get(Skill, first.id)).creator_agent_id == a.id
    assert storage.read_file("shared-name", "SKILL.md").content.endswith(b"Generic\n")
    personal_system = await db.get(Skill, system_homonym.id)
    await db.refresh(personal_system)
    assert personal_system.owner_agent_id == a.id
    assert personal_system.system is False and personal_system.category_id is None
    personal_system.soft_delete()
    await db.commit()
    await skill_service.sync_from_disk()
    assert await db.scalar(select(Skill.id).where(Skill.id == system_homonym.id)) is None


@pytest.mark.asyncio
async def test_scope_is_live_protected_and_does_not_control_ordinary_usage(db, agents):
    a, b, _ = agents
    package = await interface.create_package(personal(), actor_agent_id=a.id)
    await set_scope(a.id, "usage")
    await db.commit()
    assert await interface.get_agent_scope(a.id) == SkillScope.USAGE
    connection = await db.scalar(select(Connection).where(Connection.agent_id == a.id))
    db.add(ConnectionParam(connection_id=connection.id, param_name="scope", param_value="all"))
    await db.commit()
    with pytest.raises(PermissionError):
        await interface.create_package(personal("another"), actor_agent_id=a.id)
    with pytest.raises(PermissionError):
        await interface.set_package_enabled(package.id, False, actor_agent_id=a.id, expected_revision=1)
    assert await interface.read_package_file(package.id, "SKILL.md", actor_agent_id=a.id)
    await set_scope(a.id, "personal")
    connection.active = False
    await db.commit()
    assert await interface.get_agent_scope(a.id) == SkillScope.USAGE
    assert package.id in {item.id for item in await interface.list_packages(actor_agent_id=a.id)}
    with pytest.raises(FileNotFoundError):
        await interface.set_package_enabled(package.id, False, actor_agent_id=b.id, expected_revision=1)


@pytest.mark.asyncio
async def test_personal_activation_is_explicit_revisioned_and_never_distributed(db, agents):
    a, b, admin = agents
    package = await interface.create_package(personal(), actor_agent_id=a.id)
    with pytest.raises(KeyError):
        await skill_service.set_agent_authorization(package.id, b.id, "enabled")
    disabled = await interface.set_package_enabled(package.id, False, actor_agent_id=a.id, expected_revision=1)
    assert disabled.revision == 2
    assert package.id not in {item.id for item in await interface.list_packages(actor_agent_id=a.id)}
    # Management may inspect a disabled own package; usage and projections exclude it.
    assert await interface.read_package_file(package.id, "SKILL.md", actor_agent_id=a.id)
    with pytest.raises(SkillRevisionConflict):
        await interface.set_package_enabled(package.id, True, actor_agent_id=a.id, expected_revision=1)
    enabled = await interface.set_package_enabled(
        package.id, True, actor_agent_id=admin.id, expected_revision=2, administration=True,
    )
    assert enabled.id == package.id and enabled.owner_agent_id == a.id and enabled.revision == 3
    record = await db.get(Skill, package.id)
    await db.refresh(record, attribute_names=["assignments"])
    record.assignments.clear()
    await db.commit()
    await skill_service.ensure_assignment_matrix()
    assert package.id not in {item.id for item in await interface.list_packages(actor_agent_id=a.id)}


@pytest.mark.asyncio
async def test_constraints_prevent_shared_personal_configuration_and_duplicate_codes(db, agents):
    a, _, _ = agents
    await interface.create_package(personal(), actor_agent_id=a.id)
    for attributes in ({"global_enabled": True}, {"system": True}):
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                db.add(Skill(code="invalid-private", label="Invalid", owner_agent_id=a.id, **attributes))
                await db.flush()
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            db.add(Skill(code="shared-name", label="Duplicate", owner_agent_id=a.id))
            await db.flush()
    with pytest.raises(ValidationError):
        SkillPackageCreate(**personal().model_dump(), owner_agent_id=a.id)
    assert SkillScope("team") == SkillScope.TEAM


@pytest.mark.asyncio
async def test_creation_is_bounded_and_rejects_invalid_markdown(db, agents, monkeypatch):
    a, _, _ = agents
    with pytest.raises(ValueError):
        await interface.create_package(personal().model_copy(update={"markdown": "invalid"}), actor_agent_id=a.id)
    assert not (storage.skill_dir("shared-name", owner_agent_id=a.id) / "SKILL.md").exists()
    package = await interface.create_package(personal(), actor_agent_id=a.id)
    with pytest.raises(FileExistsError):
        await interface.create_package(personal(), actor_agent_id=a.id)
    monkeypatch.setattr(interface, "MAX_PERSONAL_PACKAGES", 1)
    with pytest.raises(ValueError, match="budget"):
        await interface.create_package(personal("another"), actor_agent_id=a.id)
    assert {item.id for item in await interface.list_packages(actor_agent_id=a.id)} >= {package.id}


@pytest.mark.asyncio
async def test_failed_creation_rolls_back_index_and_private_files(db, agents, monkeypatch):
    a, _, _ = agents
    actor_id = a.id
    async def fail_commit():
        raise RuntimeError("Synthetic failed commit")

    with monkeypatch.context() as patch:
        patch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="Synthetic failed commit"):
            await interface.create_package(personal(), actor_agent_id=actor_id)
    assert not storage.skill_dir("shared-name", owner_agent_id=actor_id).exists()
    assert await db.scalar(select(Skill.id).where(Skill.owner_agent_id == actor_id)) is None
    assert (await interface.create_package(personal(), actor_agent_id=actor_id)).revision == 1


@pytest.mark.asyncio
async def test_missing_scope_defaults_to_personal_and_explicit_revocation_is_immediate(db, agents):
    a, b, admin = agents
    package = await interface.create_package(personal(), actor_agent_id=a.id)
    await set_scope(admin.id, "personal")
    await db.commit()
    with pytest.raises(FileNotFoundError):
        await interface.set_package_enabled(package.id, False, actor_agent_id=admin.id, expected_revision=1)
    policy = await db.scalar(select(ConnectionParam).join(Connection).where(Connection.agent_id == b.id,
        ConnectionParam.param_name == MANAGEMENT_SCOPE_PARAM))
    await db.delete(policy)
    await db.commit()
    assert await interface.get_agent_scope(b.id) == SkillScope.PERSONAL
    own = await interface.create_package(personal(), actor_agent_id=b.id)
    assert own.owner_agent_id == b.id
    await set_scope(b.id, "usage")
    assert await interface.get_agent_scope(b.id) == SkillScope.USAGE
    with pytest.raises(PermissionError):
        await interface.create_package(personal("another"), actor_agent_id=b.id)


@pytest.mark.asyncio
async def test_team_scope_is_the_live_union_of_all_memberships_and_never_grants_use(db, agents):
    from app.agent import AgentTeamModel
    from core.team import TeamModel
    from app.skill import mcp
    from app.tools.mcp_loader import McpToolContext
    from app.file_share.resource_contracts import ResourceContext
    from app.file_share.skill_provider import info, listing
    from app.file_share.resource_uri import parse_resource_uri
    from uuid import uuid4

    actor, peer, global_admin = agents
    teams = [TeamModel(name=f'Synthetic scope team {index}') for index in range(4)]
    colleagues = [peer, global_admin, *[Agent(title_id=actor.title_id, code=f'scope-peer-{index}',
        first_name='Synthetic', last_name=f'Colleague {index}', agent_driver='internal') for index in range(2)]]
    db.add_all([*teams, *colleagues[2:]])
    await db.flush()
    for team in teams[:3]:
        db.add(AgentTeamModel(agent_id=actor.id, team_id=team.id))
    for colleague, team in zip(colleagues, teams, strict=True):
        db.add(AgentTeamModel(agent_id=colleague.id, team_id=team.id))
    db.add(AgentTeamModel(agent_id=peer.id, team_id=teams[1].id))  # Overlap deduplicates.
    for colleague in colleagues[2:]:
        tool = await db.scalar(select(Tool).where(Tool.code == 'skills'))
        connection = Connection(agent_id=colleague.id, tool_id=tool.id, active=True)
        db.add(connection)
    await db.commit()
    for colleague in colleagues[2:]:
        await set_scope(colleague.id, 'personal')
    packages = [await interface.create_package(personal(), actor_agent_id=colleague.id) for colleague in colleagues]
    generic = await interface.create_package(personal('team-generic'), actor_agent_id=global_admin.id, generic=True)
    await set_scope(actor.id, 'team')
    own = await interface.create_package(personal(), actor_agent_id=actor.id)
    ctx = McpToolContext(agent_id=actor.id, runtime='internal')
    resource_ctx = ResourceContext(agent_id=actor.id, runtime='internal')
    admin_rows = await mcp.mcp_skills_list(ctx, administration=True)
    personal_ids = {item['id'] for item in admin_rows if item['owner_agent_id'] is not None}
    assert personal_ids == {own.id, *(package.id for package in packages[:3])}
    assert {item.id for item in await interface.personal_packages(actor.id)} == {own.id}
    for package in packages[:3]:
        assert await mcp.mcp_skill_read(ctx, skill_id=package.id, administration=True)
        assert await info(resource_ctx, parse_resource_uri(package.uri + 'SKILL.md'))
        with pytest.raises(FileNotFoundError):
            await mcp.mcp_skill_read(ctx, skill_id=package.id)
    owners = await listing(resource_ctx, parse_resource_uri('galaris://skill/personnal/'), max_entries=50, cursor=None)
    assert len(owners.entries) == 4
    outside = packages[-1]
    with pytest.raises(FileNotFoundError):
        await mcp.mcp_skill_read(ctx, skill_id=outside.id, administration=True)
    with pytest.raises(FileNotFoundError):
        await info(resource_ctx, parse_resource_uri(outside.uri + 'SKILL.md'))
    await mcp.mcp_skill_set_authorization(ctx, generic.id, peer.id, 'enabled')
    with pytest.raises(PermissionError):
        await mcp.mcp_skill_set_authorization(ctx, generic.id, colleagues[-1].id, 'enabled')
    with pytest.raises(PermissionError):
        await interface.update_package(generic.id, 'Forbidden', actor_agent_id=actor.id, expected_revision=1, administration=True)
    with pytest.raises(PermissionError):
        await interface.release_ownership(packages[0].id, actor_agent_id=actor.id, expected_revision=1, operation_id=uuid4())
    from app.file_share import mcp as files
    await files.create_file(ctx, packages[2].uri + 'references/team.md', 'Synthetic team procedure')
    assert storage.read_text(packages[2].code, 'references/team.md', owner_agent_id=colleagues[2].id) == 'Synthetic team procedure'
    changed = await interface.update_package(packages[2].id, 'Team-managed', actor_agent_id=actor.id,
        expected_revision=2, administration=True)
    membership = await db.scalar(select(AgentTeamModel).where(AgentTeamModel.agent_id == actor.id,
        AgentTeamModel.team_id == teams[2].id))
    await db.delete(membership)
    await db.commit()
    with pytest.raises(FileNotFoundError):
        await interface.update_package(changed.id, 'Revoked', actor_agent_id=actor.id,
            expected_revision=changed.revision, administration=True)
    assert await mcp.mcp_skill_read(ctx, skill_id=packages[0].id, administration=True)
    teams[0].soft_delete()
    teams[1].soft_delete()
    await db.commit()
    assert await interface.manageable_agents(actor.id) == frozenset({actor.id})


@pytest.mark.asyncio
async def test_connection_scope_is_local_and_cannot_be_written_through_agent_parameter_services(db, agents):
    from app.connection import connection_service
    from app.tools import tool_service
    from app.tools.schemas import ToolGlobalParamsUpdate, ToolGlobalParamUpdate
    a, _, _ = agents
    connection = await db.scalar(select(Connection).join(Tool).where(Connection.agent_id == a.id, Tool.code == 'skills'))
    for call in (
        lambda: connection_service.set_param(connection.id, MANAGEMENT_SCOPE_PARAM, 'all'),
        lambda: connection_service.set_params_bulk(connection.id, {MANAGEMENT_SCOPE_PARAM: 'all'}),
        lambda: connection_service.delete_param(connection.id, MANAGEMENT_SCOPE_PARAM),
    ):
        with pytest.raises(PermissionError):
            await call()
    assert await interface.get_agent_scope(a.id) == SkillScope.PERSONAL
    with pytest.raises(ValueError, match='per connection'):
        await tool_service.update_global_params(connection.tool_id,
            ToolGlobalParamsUpdate(params={MANAGEMENT_SCOPE_PARAM: ToolGlobalParamUpdate(value='all')}))
    # Even a historical or forged global value must never override a local scope.
    record = await db.get(Tool, connection.tool_id)
    record.global_params = {MANAGEMENT_SCOPE_PARAM: {'value': 'all', 'forced': True}}
    await db.commit()
    assert MANAGEMENT_SCOPE_PARAM not in (await tool_service.get_runtime_global_params(record.id))[0]
    assert await interface.get_agent_scope(a.id) == SkillScope.PERSONAL
