"""Upgrade preservation, homonyms and injected failures against the real database."""

from uuid import uuid4
import pytest
from sqlalchemy import select
from app.connection import Connection, ConnectionParam, ConnectionFunctionState
from app.tools import ToolModel
from core.dbadmin import SchemaTransitionSet
from app.skill import dbadmin, interface, storage
from app.skill.contracts import SkillScope
from app.skill.models import Skill, AgentSkill, SkillOwnershipRelease, LearnedSkill
from app.skill.projection import build_skill_projection
from app.harness.skills import build_internal_skill_capabilities
from .test_personal_packages import agents, personal, set_scope


@pytest.mark.asyncio
async def test_upgrade_preserves_the_single_tool_connections_settings_and_delegation(db, agents):
    a, b, _ = agents
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == 'skills'))
    original_id = tool.id
    tool.code = 'skill_management'
    connections = list((await db.scalars(select(Connection).where(Connection.tool_id == original_id))).all())
    active = next(item for item in connections if item.agent_id == a.id)
    inactive = next(item for item in connections if item.agent_id == b.id)
    inactive.active = False
    for policy in (await db.scalars(select(ConnectionParam).where(ConnectionParam.param_name == 'tools.management_scope'))).all():
        await db.delete(policy)
    db.add(ConnectionParam(connection_id=active.id, param_name='synthetic', param_value='preserved'))
    db.add(ConnectionFunctionState(connection_id=active.id, function_name='skill_read', state='ask', enabled=False))
    await db.commit()
    assert not await dbadmin._tool_renamed(db, SchemaTransitionSet())
    await dbadmin._rename_tool(db, SchemaTransitionSet())
    await db.commit()
    await dbadmin._rename_tool(db, SchemaTransitionSet())
    assert await dbadmin._tool_renamed(db, SchemaTransitionSet())
    assert (await db.scalar(select(ToolModel).where(ToolModel.code == 'skills'))).id == original_id
    assert await interface.get_agent_scope(a.id) == SkillScope.ALL
    assert await interface.get_agent_scope(b.id) == SkillScope.USAGE
    assert not inactive.active
    assert (await db.scalar(select(ConnectionParam).where(ConnectionParam.connection_id == active.id))).param_value == 'preserved'
    assert (await db.scalar(select(ConnectionFunctionState).where(ConnectionFunctionState.connection_id == active.id))).state == 'ask'
    assert len((await db.scalars(select(ToolModel).where(ToolModel.code.in_(('skills', 'skill_management'))))).all()) == 1


@pytest.mark.asyncio
async def test_generic_personal_and_learned_homonyms_all_reach_the_runtime_without_source_rewrites(db, agents):
    a, b, admin = agents
    generic = await interface.create_package(personal(), actor_agent_id=admin.id, generic=True)
    from app.skill import skill_service
    await skill_service.set_agent_authorization(generic.id, a.id, 'enabled')
    private = await interface.create_package(personal(body='Private source'), actor_agent_id=a.id)
    learned = LearnedSkill(agent_id=a.id, code='shared-name', label='Learned procedure', description='Synthetic learned procedure',
        markdown=personal(body='Learned source').markdown, evidence_count=100, score=1)
    db.add(learned)
    await db.commit()
    before = storage.read_file('shared-name', 'SKILL.md', owner_agent_id=a.id).content
    snapshot = await build_skill_projection(a.id)
    files = [item for item in snapshot.files if item.relative_path == 'SKILL.md']
    assert len(files) == 3 and len({item.skill_code for item in files}) == 3
    for item in files:
        assert storage.metadata_from_markdown(item.source.read_text(), expected_code=item.skill_code)
    assert storage.read_file('shared-name', 'SKILL.md', owner_agent_id=a.id).content == before
    capabilities = await build_internal_skill_capabilities(a.id)
    assert {item.id for item in capabilities} == {item.skill_code for item in files}
    assert not (await build_skill_projection(b.id)).files
    assert any(item.package_id == private.id for item in files)


@pytest.mark.asyncio
@pytest.mark.parametrize('stage', ['publish', 'commit', 'cleanup', 'cleanup_then_delete'])
async def test_ownership_release_recovers_failures_without_publication_or_lost_grants(db, agents, monkeypatch, stage):
    a, _, admin = agents
    actor = admin.id
    package = await interface.create_package(personal(), actor_agent_id=a.id)
    operation = uuid4()
    original_recover = storage.recover_ownership_release
    original_prepare = storage.prepare_ownership_release
    async def failed_commit():
        raise RuntimeError('Synthetic commit failure')
    def failed_publish(*args, **kwargs):
        original_prepare(*args, **kwargs)
        raise RuntimeError('Synthetic publish failure')
    def failed_cleanup(operation_id, *, committed, deleted=False):
        if committed:
            raise OSError('Synthetic cleanup failure')
        return original_recover(operation_id, committed=committed, deleted=deleted)
    with monkeypatch.context() as patch:
        if stage == 'commit':
            patch.setattr(db, 'commit', failed_commit)
        elif stage == 'publish':
            patch.setattr(storage, 'prepare_ownership_release', failed_publish)
        else:
            patch.setattr(storage, 'recover_ownership_release', failed_cleanup)
        if stage.startswith('cleanup'):
            result = await interface.release_ownership(package.id, actor_agent_id=actor, expected_revision=1,
                                                       operation_id=operation)
            assert result['cleanup_pending'] is True
        else:
            with pytest.raises(RuntimeError, match='Synthetic'):
                await interface.release_ownership(package.id, actor_agent_id=actor, expected_revision=1,
                                                   operation_id=operation)
    if stage.startswith('cleanup'):
        assert await db.get(SkillOwnershipRelease, operation) is not None
        if stage == 'cleanup_then_delete':
            await interface.delete_package(package.id, actor_agent_id=actor, expected_revision=2, administration=True)
            await dbadmin._recover_releases(db)
            assert not storage.skill_dir(package.code).exists()
        result = await interface.release_ownership(package.id, actor_agent_id=actor, expected_revision=1, operation_id=operation)
        assert result['cleanup_pending'] is False
    else:
        record = await db.scalar(select(Skill).where(Skill.id == package.id))
        assert record.owner_agent_id == package.owner_agent_id and record.revision == 1
        assert not storage.skill_dir('shared-name').exists()
        assert storage.read_file('shared-name', 'SKILL.md', owner_agent_id=package.owner_agent_id).content
        assert await db.get(SkillOwnershipRelease, operation) is None
    assert not storage.pending_ownership_releases()


@pytest.mark.asyncio
async def test_crashed_uncommitted_release_is_hidden_from_rescan_and_recovered(db, agents):
    a, _, _ = agents
    package = await interface.create_package(personal(), actor_agent_id=a.id)
    operation = uuid4()
    storage.prepare_ownership_release(str(operation), package.id, a.id, package.code, package.code)
    system, installed, _ = dbadmin.compile_skill_rows()
    assert not any(item['code'] == package.code for item in (*system, *installed))
    await dbadmin._recover_releases(db)
    assert storage.read_file(package.code, 'SKILL.md', owner_agent_id=a.id).content
    assert not storage.skill_dir(package.code).exists()
    assert not storage.pending_ownership_releases()


@pytest.mark.asyncio
async def test_agent_deletion_retains_private_ownership_and_restoration_stays_disabled(db, agents):
    from app.agent import agent_service
    a, _, _ = agents
    owner = a.id
    package = await interface.create_package(personal(), actor_agent_id=owner)
    assert await agent_service.delete(owner)
    record = await db.scalar(select(Skill).where(Skill.id == package.id))
    assert record.owner_agent_id == owner and record.creator_agent_id == owner
    assert not await interface.personal_packages(owner)
    await db.refresh(a)
    a.restore()
    await db.commit()
    assert not await interface.personal_packages(owner)
    assert not (await build_skill_projection(owner)).files


@pytest.mark.asyncio
async def test_concurrent_creations_and_same_operation_release_share_database_locks(committed_database, tmp_path, monkeypatch):
    import asyncio
    from app.agent import Agent, Title
    from app.connection import Connection
    from core.user import UserModel
    from core.database import get_db_session
    from app.skill.contracts import SkillPackageRef
    monkeypatch.setattr(type(storage.settings), 'GALARIS_SKILLS_ROOT', str(tmp_path / 'skills'))
    monkeypatch.setattr(storage, 'SYSTEM_SKILLS', ())
    async with get_db_session() as db:
        user = UserModel(email='synthetic-skill-lock@example.test', hashed_password='unused')
        title = Title(label='Synthetic lock test', gender='X')
        db.add_all([user, title])
        await db.flush()
        agent = Agent(user_id=user.id, title_id=title.id, code='synthetic-skill-lock', first_name='Synthetic', last_name='Lock')
        db.add(agent)
        await db.flush()
        actor = agent.id
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == 'skills'))
        connection = Connection(agent_id=actor, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        db.add(ConnectionParam(connection_id=connection.id, param_name='tools.management_scope', param_value='all'))
    async def create():
        async with get_db_session():
            return await interface.create_package(personal(), actor_agent_id=actor)
    results = await asyncio.wait_for(asyncio.gather(create(), create(), return_exceptions=True), 10)
    created = [item for item in results if isinstance(item, SkillPackageRef)]
    assert len(created) == 1 and sum(isinstance(item, FileExistsError) for item in results) == 1
    package = created[0]
    operation = uuid4()
    async def release():
        async with get_db_session():
            return await interface.release_ownership(package.id, actor_agent_id=actor,
                expected_revision=1, operation_id=operation)
    first, second = await asyncio.wait_for(asyncio.gather(release(), release()), 10)
    assert first == second
    async with get_db_session() as db:
        assert len((await db.scalars(select(SkillOwnershipRelease))).all()) == 1
        assert len((await db.scalars(select(Skill).where(Skill.code == package.code))).all()) == 1
        with pytest.raises(RuntimeError, match='identity changed'):
            await interface.mutate_file(package.id, 'SKILL.md', actor_agent_id=actor, operation='append',
                content=b'Forbidden stale write', administration=True, expected_identity=package)
    assert b'Forbidden stale write' not in storage.read_file(package.code, 'SKILL.md').content
