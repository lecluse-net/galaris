"""Real MCP/domain/file workflow; replaces the former selector-only MCP doubles."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from app.file_share import mcp as files
from app.file_share.resource_contracts import ResourceContext
from app.file_share.resource_service import resource_copy, resource_move
from app.harness.skills import build_internal_skill_capabilities
from app.skill import interface, skill_service, storage
from app.skill import mcp
from app.skill.contracts import SkillScope, SkillRevisionConflict
from app.skill.models import Skill, AgentSkill
from app.skill.projection import build_skill_projection
from app.skill.schemas import SkillCreate, SkillCategoryCreate
from app.tools.mcp_loader import McpToolContext
from .test_personal_packages import agents, personal, set_scope


@pytest.mark.asyncio
@pytest.mark.parametrize('system', [False, True])
async def test_generic_disable_overrides_grants_and_preserves_mcp_management(db, agents, system):
    a, b, admin = agents
    package = await interface.create_package(personal('global-guide'), actor_agent_id=admin.id, generic=True)
    record = await skill_service.get(package.id)
    record.system = system
    await db.commit()
    category = await skill_service.create_category(SkillCategoryCreate(label='Synthetic procedures'))
    await skill_service.set_skill_category(package.id, category.id)
    await skill_service.set_global_authorization(package.id, admin.id, 'enabled')
    await skill_service.set_category_authorization(category.id, b.id, 'enabled')
    await skill_service.set_agent_authorization(package.id, a.id, 'enabled')
    ctx = McpToolContext(agent_id=admin.id, runtime='internal')
    original = await build_skill_projection(a.id)
    capabilities = await build_internal_skill_capabilities(a.id)
    assert 'global-guide' in original.skill_codes
    assert 'global-guide' in {item.id for item in capabilities}
    assert skill_service.to_public(await skill_service.get(package.id)).enabled
    for scope in ('usage', 'personal', 'team'):
        await set_scope(a.id, scope)
        with pytest.raises(PermissionError):
            await mcp.mcp_skill_set_enabled(McpToolContext(agent_id=a.id, runtime='internal'),
                                            package.id, False, package.revision, administration=True)
    with pytest.raises(PermissionError):
        await mcp.mcp_skill_set_enabled(ctx, package.id, False, package.revision)
    disabled = await mcp.mcp_skill_set_enabled(ctx, package.id, False, package.revision, administration=True)
    assert disabled['revision'] == package.revision + 1
    with pytest.raises(SkillRevisionConflict):
        await mcp.mcp_skill_set_enabled(ctx, package.id, True, package.revision, administration=True)
    for agent in agents:
        assert 'global-guide' not in await skill_service.get_assigned_codes(agent.id)
        assert package.id not in {item['id'] for item in await mcp.mcp_skills_list(
            McpToolContext(agent_id=agent.id, runtime='internal'))}
        assert 'global-guide' not in (await build_skill_projection(agent.id)).skill_codes
        assert 'global-guide' not in {item.id for item in await build_internal_skill_capabilities(agent.id)}
    assert (await build_skill_projection(a.id)).revision != original.revision
    capability = next(item for item in capabilities if item.id == 'global-guide')
    with pytest.raises(PermissionError):
        await next(iter(capability.get_toolset().tools.values())).function(path='SKILL.md')
    with pytest.raises(FileNotFoundError):
        await mcp.mcp_skill_read(ctx, skill_id=package.id)
    assert 'Synthetic procedure' in await mcp.mcp_skill_read(ctx, skill_id=package.id, administration=True)
    summary = next(item for item in await mcp.mcp_skills_list(ctx, administration=True) if item['id'] == package.id)
    assert summary['enabled'] is False
    assert 'Synthetic procedure' in json.loads(await files.read_file(ctx, package.uri + 'SKILL.md'))['content']
    assert all(not row.effective and not row.enabled for row in await skill_service.list_authorizations(skill_id=package.id))
    # Neither grants nor rescans can undo global suspension.
    assert not (await skill_service.set_agent_authorization(package.id, a.id, 'enabled')).effective
    await skill_service.set_category_authorization(category.id, b.id, 'enabled')
    await skill_service.sync_from_disk()
    assert not (await skill_service.get(package.id)).enabled
    assert 'global-guide' not in await skill_service.get_assigned_codes(a.id)
    revision = (await skill_service.get(package.id)).revision
    await mcp.mcp_skill_set_enabled(ctx, package.id, True, revision, administration=True)
    for agent in agents:
        assert 'global-guide' in await skill_service.get_assigned_codes(agent.id)
    assert (await build_skill_projection(a.id)).revision == original.revision


@pytest.mark.asyncio
async def test_mcp_personal_skill_lifecycle_is_private_and_reaches_next_runtime(db, agents):
    a, b, admin = agents
    ctx = McpToolContext(agent_id=a.id, runtime='internal')
    other = McpToolContext(agent_id=b.id, runtime='internal')
    admin_ctx = McpToolContext(agent_id=admin.id, runtime='internal')
    await interface.create_package(personal('unassigned-generic'), actor_agent_id=admin.id, generic=True)
    await skill_service.ensure_assignment_matrix()
    await db.execute(update(AgentSkill).where(AgentSkill.agent_id.in_((a.id, b.id))).values(active=False))
    await db.commit()
    uri = f'galaris://skill/personnal/{a.id}/shared-name/SKILL.md'
    created = json.loads(await files.create_file(ctx, uri, personal(body='Only A instructions').markdown))
    package = (await mcp.mcp_skills_list(ctx))[0]
    assert package['owner_agent_id'] == a.id and package['uri'] + 'SKILL.md' == created['uri']
    package_id = package['id']
    assert 'Only A instructions' in await mcp.mcp_skill_read(ctx, skill_id=package_id)
    for call in (
        lambda: mcp.mcp_skill_read(other, skill_id=package_id),
        lambda: files.read_file(other, uri),
        lambda: files.file_info(other, uri),
    ):
        with pytest.raises(FileNotFoundError):
            await call()
    with pytest.raises(PermissionError):
        await mcp.mcp_skills_list(ctx, agent_id=b.id)
    assert not await mcp.mcp_skills_list(other)
    assert not await mcp.mcp_skills_list(admin_ctx)
    assert package_id in {item['id'] for item in await mcp.mcp_skills_list(admin_ctx, administration=True)}
    # Target availability is filtered before pagination; an unrelated generic
    # inserted first must not hide the owner's package on a one-item page.
    assert [item['id'] for item in await mcp.mcp_skills_list(
        admin_ctx, agent_id=a.id, administration=True, limit=1)] == [package_id]
    assert not await mcp.mcp_skills_list(admin_ctx, agent_id=b.id, administration=True)
    assert 'Only A' in await mcp.mcp_skill_read(admin_ctx, skill_id=package_id, administration=True)
    aux = uri.replace('SKILL.md', 'references/notes.md')
    await files.create_file(ctx, aux, 'Private reference')
    read = json.loads(await files.read_file(ctx, aux))
    await files.write_file(ctx, aux, 'Updated reference', expected_revision=read['revision'])
    with pytest.raises(RuntimeError):
        await files.write_file(ctx, aux, 'Lost update', expected_revision=read['revision'])
    await files.append_file(ctx, aux, '\nMore context')
    await files.edit_file(ctx, aux, start_line=1, end_line=1, content='Edited reference',
                          expected_revision=json.loads(await files.read_file(ctx, aux))['revision'])
    for actor in (a, admin):
        resource_ctx = ResourceContext(agent_id=actor.id, runtime='internal')
        with pytest.raises(PermissionError):
            await resource_copy(resource_ctx, aux, 'file://')
        with pytest.raises(PermissionError):
            await resource_move(resource_ctx, aux, 'galaris://skill/exported/notes.md')
    with pytest.raises(KeyError):
        await mcp.mcp_skill_set_authorization(admin_ctx, package_id, b.id, 'enabled')
    snapshot = await build_skill_projection(a.id)
    assert len(snapshot.files) == 2
    assert any(b'Only A instructions' in item.source.read_bytes() for item in snapshot.files)
    assert not (await build_skill_projection(b.id)).files
    capabilities = await build_internal_skill_capabilities(a.id)
    assert len(capabilities) == 1
    assert not await build_internal_skill_capabilities(b.id)
    before = await interface.resolve_package('shared-name', owner_agent_id=a.id, actor_agent_id=a.id)
    await mcp.mcp_skill_set_enabled(ctx, package_id, False, before.revision)
    assert not (await build_skill_projection(a.id)).files
    tool = next(iter(capabilities[0].get_toolset().tools.values()))
    with pytest.raises(PermissionError):
        await tool.function(path='SKILL.md')
    await set_scope(a.id, 'usage')
    await db.commit()
    with pytest.raises(PermissionError):
        await files.write_file(ctx, aux, 'Forbidden')


@pytest.mark.asyncio
async def test_global_release_is_explicit_collision_safe_and_replay_does_not_reset_grants(db, agents):
    a, b, admin = agents
    package = await interface.create_package(personal(), actor_agent_id=a.id)
    await skill_service.create(SkillCreate(code=package.code, label='Generic collision', markdown=personal().markdown))
    ctx = McpToolContext(agent_id=admin.id, runtime='internal')
    operation = uuid4()
    with pytest.raises(FileExistsError):
        await mcp.mcp_skill_release_ownership(ctx, package.id, 1, operation)
    result = await mcp.mcp_skill_release_ownership(ctx, package.id, 1, operation, new_code='released-guide')
    assert result['uri'] == 'galaris://skill/released-guide/'
    record = await skill_service.get(package.id)
    assert record.id == package.id and record.creator_agent_id == a.id
    assert record.owner_agent_id is None and record.global_enabled is False and record.category_id is None
    settings = (await db.scalars(select(AgentSkill).where(AgentSkill.skill_id == package.id))).all()
    assert all(item.active is None for item in settings)
    with pytest.raises(FileNotFoundError):
        await interface.resolve_package(package.code, owner_agent_id=a.id, actor_agent_id=a.id)
    await mcp.mcp_skill_set_authorization(ctx, package.id, b.id, 'enabled')
    assert result == await mcp.mcp_skill_release_ownership(ctx, package.id, 1, operation, new_code='released-guide')
    assert 'released-guide' in await skill_service.get_assigned_codes(b.id)
    assert 'released-guide' not in await skill_service.get_assigned_codes(a.id)
    assert 'name: released-guide' in storage.read_text('released-guide', 'SKILL.md')
    assert len((await build_skill_projection(b.id)).files) == 1
    assert not storage.pending_ownership_releases()


@pytest.mark.asyncio
async def test_actual_fastmcp_server_enforces_live_scope_after_tool_discovery(db, agents):
    from fastmcp import Client
    from app.connection import Connection, ConnectionFunctionState
    from app.tools import ToolModel, build_agent_galaris_fastmcp
    a, _, _ = agents
    functions = {'skills': ['skills_list', 'skill_read', 'skill_set_enabled'],
                 'file_sharing': ['file_create', 'file_read', 'file_write']}
    for code, names in functions.items():
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == code))
        connection = await db.scalar(select(Connection).where(Connection.tool_id == tool.id, Connection.agent_id == a.id))
        if connection is None:
            connection = Connection(agent_id=a.id, tool_id=tool.id, active=True)
            db.add(connection)
            await db.flush()
        for name in names:
            db.add(ConnectionFunctionState(connection_id=connection.id, function_name=name, state='enabled', enabled=True))
    await db.commit()
    actor_id = a.id
    server = await build_agent_galaris_fastmcp(actor_id, runtime='internal',
        allowed_tool_names=set(sum(functions.values(), [])))
    uri = f'galaris://skill/personnal/{actor_id}/protocol-guide/SKILL.md'
    async with Client(server) as client:
        names = {tool.name for tool in await client.list_tools()}
        assert {'file_create', 'skills_list', 'skill_read'} <= names
        created = await client.call_tool('file_create', {'path': uri, 'content': personal('protocol-guide').markdown}, raise_on_error=False)
        assert not created.is_error, created
        discovered = await client.call_tool('skills_list', {}, raise_on_error=False)
        assert not discovered.is_error
        package = await interface.resolve_package('protocol-guide', owner_agent_id=actor_id, actor_agent_id=actor_id)
        read = await client.call_tool('skill_read', {'skill_id': package.id}, raise_on_error=False)
        assert not read.is_error
        await set_scope(actor_id, SkillScope.USAGE)
        refused = await client.call_tool('file_write', {'uri': uri, 'content': personal('protocol-guide', body='Forbidden').markdown,
            'expected_revision': package.revision}, raise_on_error=False)
        assert refused.is_error
        assert b'Forbidden' not in (await interface.read_package_file(package.id, 'SKILL.md', actor_agent_id=actor_id)).content


@pytest.mark.asyncio
@pytest.mark.parametrize('scope', ['usage', 'personal', 'team', 'all'])
@pytest.mark.parametrize('target', ['self', 'teammate', 'outside'])
async def test_fastmcp_scope_matrix_preserves_private_usage_and_bounds_every_mutation(db, agents, scope, target):
    from fastmcp import Client
    from app.agent import AgentTeamModel
    from app.connection import Connection, ConnectionFunctionState
    from app.tools import ToolModel, build_agent_galaris_fastmcp
    from core.team import TeamModel

    actor, teammate, outside = agents
    owners = {'self': actor, 'teammate': teammate, 'outside': outside}
    owner = owners[target]
    team, other_team = TeamModel(name='Synthetic shared team'), TeamModel(name='Synthetic outside team')
    db.add_all([team, other_team])
    await db.flush()
    db.add_all([
        AgentTeamModel(agent_id=actor.id, team_id=team.id),
        AgentTeamModel(agent_id=teammate.id, team_id=team.id),
        AgentTeamModel(agent_id=outside.id, team_id=other_team.id),
    ])
    await db.commit()
    package = await interface.create_package(personal('matrix-guide'), actor_agent_id=owner.id)
    await interface.mutate_file(package.id, 'references/existing.md', actor_agent_id=owner.id,
        operation='create', content=b'Original reference', expected_revision=package.revision)
    generic = await interface.create_package(personal('matrix-generic'), actor_agent_id=outside.id, generic=True)
    functions = {
        'skills': ['skills_list', 'skill_read', 'skill_update', 'skill_set_enabled', 'skill_delete', 'skill_set_authorization'],
        'file_sharing': ['file_read', 'file_create', 'file_write', 'file_delete'],
    }
    for code, names in functions.items():
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == code))
        connection = await db.scalar(select(Connection).where(Connection.tool_id == tool.id, Connection.agent_id == actor.id))
        if connection is None:
            connection = Connection(agent_id=actor.id, tool_id=tool.id, active=True)
            db.add(connection)
            await db.flush()
        db.add_all([ConnectionFunctionState(connection_id=connection.id, function_name=name, state='enabled', enabled=True)
                    for name in names])
    await db.commit()
    server = await build_agent_galaris_fastmcp(actor.id, runtime='internal', allowed_tool_names=set(sum(functions.values(), [])))
    permitted = scope != 'usage' and (target == 'self' or scope == 'all' or (scope == 'team' and target == 'teammate'))
    administrative = target != 'self'
    record = await db.get(Skill, package.id)

    async with Client(server) as client:
        assert set(sum(functions.values(), [])) <= {tool.name for tool in await client.list_tools()}
        # Change the real connection policy after discovery, keeping the MCP session open.
        await set_scope(actor.id, scope)
        ordinary = await client.call_tool('skill_read', {'skill_id': package.id}, raise_on_error=False)
        assert ordinary.is_error == (target != 'self')
        managed = await client.call_tool('skill_read', {'skill_id': package.id, 'administration': administrative}, raise_on_error=False)
        assert managed.is_error == (target != 'self' and not permitted)
        file_read = await client.call_tool('file_read', {'uri': package.uri + 'references/existing.md'}, raise_on_error=False)
        assert file_read.is_error == (target != 'self' and not permitted)
        catalogue = await client.call_tool('skills_list', {}, raise_on_error=False)
        assert not catalogue.is_error
        if target != 'self':
            assert package.id not in {item['id'] for item in catalogue.data}
        targeted = await client.call_tool('skills_list', {'agent_id': owner.id, 'administration': administrative}, raise_on_error=False)
        assert targeted.is_error == (target != 'self' and not permitted)
        if not targeted.is_error:
            assert package.id in {item['id'] for item in targeted.data}

        for name, arguments in [
            ('skill_update', {'skill_id': package.id, 'label': 'Managed synthetic guide', 'administration': administrative}),
            ('file_create', {'path': package.uri + 'references/new.md', 'content': 'New reference'}),
            ('file_write', {'uri': package.uri + 'references/existing.md', 'content': 'Changed reference'}),
            ('file_delete', {'uri': package.uri + 'references/existing.md'}),
            ('skill_set_enabled', {'skill_id': package.id, 'enabled': False, 'administration': administrative}),
            ('skill_set_enabled', {'skill_id': package.id, 'enabled': True, 'administration': administrative}),
            ('skill_delete', {'skill_id': package.id, 'administration': administrative}),
        ]:
            await db.refresh(record)
            before = (record.revision, record.label)
            if name not in ('file_create', 'file_delete'):
                arguments = {**arguments, 'expected_revision': record.revision}
            result = await client.call_tool(name, arguments, raise_on_error=False)
            assert result.is_error == (not permitted), f'{scope}/{target}/{name}: {result}'
            if not permitted:
                await db.refresh(record)
                assert (record.revision, record.label) == before
                assert storage.read_text(package.code, 'references/existing.md', owner_agent_id=owner.id) == 'Original reference'
                assert not storage.skill_dir(package.code, owner_agent_id=owner.id).joinpath('references/new.md').exists()
            elif name == 'skill_delete':
                assert await db.scalar(select(Skill.id).where(Skill.id == package.id)) is None
                assert not storage.skill_dir(package.code, owner_agent_id=owner.id).exists()
            else:
                await db.refresh(record)
                assert record.revision == before[0] + 1
                if name == 'skill_update':
                    assert record.label == arguments['label']
                elif name == 'skill_set_enabled':
                    assert await db.scalar(select(AgentSkill.active).where(
                        AgentSkill.skill_id == package.id, AgentSkill.agent_id == owner.id)) is arguments['enabled']
                elif name == 'file_create':
                    assert storage.read_text(package.code, 'references/new.md', owner_agent_id=owner.id) == 'New reference'
                elif name == 'file_write':
                    assert storage.read_text(package.code, 'references/existing.md', owner_agent_id=owner.id) == 'Changed reference'
                elif name == 'file_delete':
                    assert not storage.skill_dir(package.code, owner_agent_id=owner.id).joinpath('references/existing.md').exists()

        grant = await client.call_tool('skill_set_authorization', {
            'skill_id': generic.id, 'agent_id': owner.id, 'state': 'enabled',
        }, raise_on_error=False)
        may_distribute = scope == 'all' or (scope == 'team' and target != 'outside')
        assert grant.is_error == (not may_distribute)
        assignment = await db.scalar(select(AgentSkill.active).where(AgentSkill.skill_id == generic.id, AgentSkill.agent_id == owner.id))
        assert (assignment is True) == may_distribute
        if permitted:
            assert await db.scalar(select(Skill.id).where(Skill.id == package.id)) is None
        else:
            assert await db.scalar(select(AgentSkill.active).where(AgentSkill.skill_id == package.id, AgentSkill.agent_id == owner.id)) is True
