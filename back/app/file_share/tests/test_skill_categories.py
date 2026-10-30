"""Virtual category navigation preserves package identities and live resource policy."""

import pytest

from app.file_share.resource_contracts import ResourceContext
from app.file_share.resource_service import resource_info, resource_list, resource_read, resource_search
from app.skill import interface, skill_service
from app.skill.schemas import SkillCategoryCreate, SkillCategoryUpdate
from app.skill.tests.test_personal_packages import agents, personal, set_scope


@pytest.mark.asyncio
async def test_category_folders_paginate_and_keep_canonical_skill_files_and_live_classification(db, agents):
    actor, _, admin = agents
    ctx = ResourceContext(agent_id=admin.id, runtime='internal')
    root = 'galaris://skill/'
    existing = {entry.uri for entry in (await resource_list(ctx, root, max_entries=500)).entries}
    category = await skill_service.create_category(SkillCategoryCreate(label='Synthetic procedures'))
    other = await skill_service.create_category(SkillCategoryCreate(label='Synthetic reference'))
    first = await interface.create_package(personal('guide-alpha'), actor_agent_id=admin.id, generic=True)
    second = await interface.create_package(personal('guide-beta'), actor_agent_id=admin.id, generic=True)
    outside = await interface.create_package(personal('guide-other'), actor_agent_id=admin.id, generic=True)
    loose = await interface.create_package(personal('guide-loose'), actor_agent_id=admin.id, generic=True)
    await skill_service.set_skill_category(first.id, category.id)
    await skill_service.set_skill_category(second.id, category.id)
    await skill_service.set_skill_category(outside.id, other.id)
    await interface.create_package(personal('guide-alpha'), actor_agent_id=actor.id)
    category_uri = root + f'_category-{category.id}/'
    other_uri = root + f'_category-{other.id}/'
    loose_uri = root + '_uncategorized/'
    locations, cursor = [], None
    for _ in range(10):
        page = await resource_list(ctx, root, max_entries=1, cursor=cursor)
        locations.extend(page.entries)
        cursor = page.next_cursor
        if not cursor:
            break
    assert cursor is None
    assert locations[0].uri == root + 'personnal/'
    assert len(locations) == len({entry.uri for entry in locations})
    assert {entry.uri for entry in locations} == existing | {category_uri, other_uri, loose_uri}
    assert all(entry.is_collection for entry in locations)
    names = {entry.uri: entry.name for entry in locations}
    assert [names[uri] for uri in [category_uri, other_uri, loose_uri]] == ['Synthetic procedures', 'Synthetic reference', 'Uncategorized']
    page = await resource_list(ctx, category_uri, max_entries=1)
    following = await resource_list(ctx, category_uri, max_entries=1, cursor=page.next_cursor)
    assert [entry.uri for entry in [*page.entries, *following.entries]] == [first.uri, second.uri]
    assert page.truncated and not following.truncated
    assert [entry.uri for entry in page.ancestors] == ['galaris://', root, category_uri]
    assert page.ancestors[-1].name == 'Synthetic procedures'
    assert (await resource_info(ctx, category_uri)).capabilities == ['info', 'list', 'search']
    assert [entry.uri for entry in (await resource_list(ctx, loose_uri)).entries] == [loose.uri]
    hits = await resource_search(ctx, category_uri, 'guide', mode='name')
    assert {hit.resource.uri for hit in hits.hits} == {first.uri + 'SKILL.md', second.uri + 'SKILL.md'}
    original = (await resource_read(ctx, first.uri + 'SKILL.md')).content
    await skill_service.update_category(category.id, SkillCategoryUpdate(label='Synthetic renamed category'))
    assert (await resource_info(ctx, category_uri)).name == 'Synthetic renamed category'
    await skill_service.set_skill_category(first.id, other.id)
    assert [entry.uri for entry in (await resource_list(ctx, category_uri)).entries] == [second.uri]
    assert (await resource_read(ctx, first.uri + 'SKILL.md')).content == original
    await skill_service.delete_category(category.id)
    with pytest.raises(FileNotFoundError):
        await resource_list(ctx, category_uri)
    assert {entry.uri for entry in (await resource_list(ctx, loose_uri)).entries} == {second.uri, loose.uri}


@pytest.mark.asyncio
async def test_category_navigation_and_search_do_not_reveal_unassigned_packages(db, agents):
    actor, _, admin = agents
    visible = await skill_service.create_category(SkillCategoryCreate(label='Synthetic allowed category'))
    hidden = await skill_service.create_category(SkillCategoryCreate(label='Synthetic denied category'))
    allowed = await interface.create_package(personal('allowed-guide'), actor_agent_id=admin.id, generic=True)
    denied = await interface.create_package(personal('denied-guide'), actor_agent_id=admin.id, generic=True)
    await skill_service.set_skill_category(allowed.id, visible.id)
    await skill_service.set_skill_category(denied.id, hidden.id)
    await skill_service.set_agent_authorization(allowed.id, actor.id, 'enabled')
    await set_scope(actor.id, 'usage')
    ctx = ResourceContext(agent_id=actor.id, runtime='internal')
    root = 'galaris://skill/'
    allowed_uri = root + f'_category-{visible.id}/'
    denied_uri = root + f'_category-{hidden.id}/'
    assert {entry.uri for entry in (await resource_list(ctx, root)).entries} == {root + 'personnal/', allowed_uri}
    assert [entry.uri for entry in (await resource_list(ctx, allowed_uri)).entries] == [allowed.uri]
    for uri in [denied_uri, root + '_uncategorized/']:
        with pytest.raises(FileNotFoundError):
            await resource_info(ctx, uri)
        with pytest.raises(FileNotFoundError):
            await resource_list(ctx, uri)
        with pytest.raises(FileNotFoundError):
            await resource_search(ctx, uri, 'guide', mode='name')
    await skill_service.set_agent_authorization(allowed.id, actor.id, 'disabled')
    with pytest.raises(FileNotFoundError):
        await resource_list(ctx, allowed_uri)
    assert [entry.uri for entry in (await resource_list(ctx, root)).entries] == [root + 'personnal/']
