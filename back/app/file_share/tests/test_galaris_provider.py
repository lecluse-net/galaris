from typing import Any
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.file_share import galaris_provider, resource_service
from app.file_share.resource_contracts import ResourceContext
from app.file_share.resource_uri import parse_resource_uri


@pytest.mark.asyncio
async def test_galaris_root_lists_the_supported_business_collections(db) -> None:
    result = await galaris_provider.galaris_resource_list(
        ResourceContext(agent_id=7, runtime="internal"),
        parse_resource_uri("galaris://", allow_empty=True),
        max_entries=100,
    )

    assert {entry.uri for entry in result.entries} == {
        "galaris://task/",
        "galaris://voice/",
        "galaris://text/",
        "galaris://goal/",
        "galaris://agent/",
        "galaris://processes/",
        "galaris://code/",
        "galaris://skill/",
    }
    for entry in result.entries:
        kind = entry.uri.removeprefix("galaris://").strip("/")
        code = f"collection_{'process' if kind == 'processes' else kind}"
        assert entry.label_code == code
    info = await resource_service.resource_info(ResourceContext(agent_id=7, runtime="internal"), "galaris://task/")
    assert info.label_code == "collection_task"


@pytest.mark.asyncio
async def test_galaris_root_listing_is_paginated(db) -> None:
    ctx = ResourceContext(agent_id=7, runtime="internal")

    complete = await resource_service.resource_list(ctx, "galaris://", max_entries=100)
    entries = []
    cursors = set()
    cursor = None
    while True:
        page = await resource_service.resource_list(ctx, "galaris://", max_entries=2, cursor=cursor)
        assert 0 < len(page.entries) <= 2
        entries.extend(page.entries)
        if not page.truncated:
            assert page.next_cursor is None
            break
        assert page.next_cursor is not None and page.next_cursor not in cursors
        cursors.add(page.next_cursor)
        cursor = page.next_cursor
    assert [entry.uri for entry in entries] == [entry.uri for entry in complete.entries]
    assert len({entry.uri for entry in entries}) == len(entries)


@pytest.mark.asyncio
async def test_galaris_root_exposes_the_skills_usage_collection(
    db,
) -> None:
    result = await resource_service.resource_list(
        ResourceContext(agent_id=7, runtime="internal", skill_management=True),
        "galaris://",
    )

    assert result.entries[-1].uri == "galaris://skill/"



@pytest.mark.asyncio
async def test_large_galaris_task_collection_uses_bounded_cursor_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.task as task

    identifiers = [uuid4() for _ in range(1_201)]
    observed: list[tuple[int, int]] = []

    async def list_tasks(**kwargs: object) -> list[dict[str, Any]]:
        offset = int(kwargs["offset"])
        limit = int(kwargs["limit"])
        observed.append((offset, limit))
        return [
            {
                "id": str(identifier),
                "label": f"Task {offset + index}",
                "status": "SUCCESS",
            }
            for index, identifier in enumerate(identifiers[offset : offset + limit])
        ]

    monkeypatch.setattr(task, "list_task_resources", list_tasks)
    ctx = ResourceContext(agent_id=17, runtime="internal")
    pages = []
    cursor: str | None = None
    while True:
        page = await resource_service.resource_list(
            ctx,
            "galaris://task/",
            max_entries=500,
            cursor=cursor,
        )
        pages.append(page)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    uris = [entry.uri for page in pages for entry in page.entries]
    assert len(uris) == 1_201
    assert len(set(uris)) == 1_201
    assert [len(page.entries) for page in pages] == [500, 500, 201]
    assert [page.next_cursor for page in pages] == ["500", "1000", None]
    assert observed == [(0, 501), (500, 501), (1000, 501)]


@pytest.mark.asyncio
async def test_galaris_listing_rejects_invalid_cursor() -> None:
    with pytest.raises(ValueError, match="cursor"):
        await resource_service.resource_list(
            ResourceContext(agent_id=7, runtime="internal"),
            "galaris://task/",
            cursor="not-a-cursor",
        )


@pytest.mark.asyncio
async def test_galaris_task_is_a_scoped_read_only_json_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.task as task

    identifier = uuid4()
    observed: dict[str, object] = {}

    async def read_task_resource(
        task_id: object,
        *,
        actor_agent_id: int,
    ) -> dict[str, Any]:
        observed.update(task_id=task_id, actor_agent_id=actor_agent_id)
        return {
            "id": str(identifier),
            "revision": 3,
            "label": "Prepare release",
            "status": "SUCCESS",
            "created_at": "2026-01-02T03:04:05+00:00",
            "updated_at": "2026-01-03T04:05:06+00:00",
        }

    monkeypatch.setattr(task, "read_task_resource", read_task_resource)
    ctx = ResourceContext(agent_id=7, runtime="internal")
    uri = f"galaris://task/{identifier}"

    descriptor = await resource_service.resource_info(ctx, uri)
    content = await resource_service.resource_read(ctx, uri, max_chars=10_000)

    assert observed == {"task_id": identifier, "actor_agent_id": 7}
    assert descriptor.uri == uri
    assert descriptor.name == f"task-{identifier}.json"
    assert descriptor.label_code is None  # Resource titles are never system labels.
    assert descriptor.media_type == "application/vnd.galaris.task+json"
    assert descriptor.metadata["label"] == "Prepare release"
    assert descriptor.metadata["created_at"] == "2026-01-02T03:04:05+00:00"
    assert descriptor.modified_at == "2026-01-03T04:05:06+00:00"
    assert descriptor.capabilities == ["copy", "info", "read"]
    assert '"status": "SUCCESS"' in content.content
    assert content.revision == 3


@pytest.mark.asyncio
async def test_galaris_process_uses_the_assigned_workflow_id_and_cursor_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.process as process

    workflow_id = "Kw70xUO8uRWkXvtX"
    observed: dict[str, object] = {}

    async def read_process(
        requested_workflow_id: str,
        *,
        actor_agent_id: int,
    ) -> dict[str, Any]:
        observed.update(
            requested_workflow_id=requested_workflow_id,
            read_agent_id=actor_agent_id,
        )
        return {
            "workflow_id": workflow_id,
            "label": "Météo du jour → Aster",
            "description": "Météo test",
            "tool_code": "n8n",
        }

    async def list_processes(**kwargs: object) -> list[dict[str, Any]]:
        observed.update(kwargs)
        return [
            {
                "workflow_id": workflow_id,
                "label": "Météo du jour → Aster",
                "description": "Météo test",
                "tool_code": "n8n",
            }
        ]

    monkeypatch.setattr(process, "read_process_resource", read_process)
    monkeypatch.setattr(process, "list_process_resources", list_processes)
    ctx = ResourceContext(agent_id=23, runtime="internal")
    uri = f"galaris://process/{workflow_id}"

    descriptor = await resource_service.resource_info(ctx, uri)
    content = await resource_service.resource_read(ctx, uri)
    listing = await resource_service.resource_list(
        ctx,
        "galaris://process/",
        max_entries=50,
        cursor="100",
    )

    assert observed == {
        "requested_workflow_id": workflow_id,
        "read_agent_id": 23,
        "actor_agent_id": 23,
        "query": "",
        "offset": 100,
        "limit": 51,
    }
    assert descriptor.uri == uri
    assert descriptor.name == f"process-{workflow_id}.json"
    assert descriptor.metadata["tool_code"] == "n8n"
    assert '"workflow_id": "Kw70xUO8uRWkXvtX"' in content.content
    assert [entry.uri for entry in listing.entries] == [uri]


@pytest.mark.asyncio
async def test_browser_lists_and_searches_goals_without_loading_their_cycles(monkeypatch):
    import app.goal as goal

    identity = uuid4()
    payload = {"id": str(identity), "title": "Synthetic objective", "status": "ACTIVE"}
    monkeypatch.setattr(goal, "list_goal_resources", AsyncMock(return_value=[payload]))
    monkeypatch.setattr(goal, "read_goal_resource", AsyncMock(return_value=payload))
    cycles = AsyncMock(side_effect=AssertionError("File browsing must not load Goal cycles"))
    monkeypatch.setattr(goal, "list_goal_cycle_resources", cycles)
    ctx = ResourceContext(agent_id=11, runtime="internal", browser_navigation=True)
    canonical = f"galaris://goal/{identity}"
    listing = await resource_service.resource_list(ctx, "galaris://goal/")
    assert [(entry.uri, entry.name, entry.is_collection) for entry in listing.entries] == [
        (canonical, payload["title"], False)]
    legacy = await resource_service.resource_list(ctx, canonical + "/")
    assert [entry.uri for entry in legacy.entries] == [canonical]
    assert not legacy.truncated and legacy.next_cursor is None
    search = await resource_service.resource_search(ctx, "galaris://goal/", "Synthetic")
    assert [hit.resource.uri for hit in search.hits] == [canonical]
    for uri in ["galaris://goal_cycle/", canonical + "/cycles/"]:
        assert not (await resource_service.resource_list(ctx, uri)).entries
        assert not (await resource_service.resource_search(ctx, uri, "Synthetic")).hits
    cycles.assert_not_called()


@pytest.mark.asyncio
async def test_nested_goal_cycle_collection_preserves_goal_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.goal as goal

    goal_id = uuid4()
    cycle_id = uuid4()
    observed: dict[str, object] = {}

    async def list_cycles(**kwargs: object) -> list[dict[str, Any]]:
        observed.update(kwargs)
        return [
            {
                "id": str(cycle_id),
                "goal_id": str(goal_id),
                "sequence": 4,
                "status": "COMPLETED",
            }
        ]

    monkeypatch.setattr(goal, "list_goal_cycle_resources", list_cycles)

    result = await resource_service.resource_list(
        ResourceContext(agent_id=11, runtime="internal"),
        f"galaris://goal/{goal_id}/cycles/",
    )

    assert observed["actor_agent_id"] == 11
    assert observed["goal_id"] == goal_id
    assert [entry.uri for entry in result.entries] == [
        f"galaris://goal_cycle/{cycle_id}"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("medium", ["text", "voice"])
async def test_conversation_collections_route_to_the_canonical_medium(
    monkeypatch: pytest.MonkeyPatch,
    medium: str,
) -> None:
    import app.conversation as conversation

    identifier = uuid4()
    observed: dict[str, object] = {}

    async def list_rounds(**kwargs: object) -> list[dict[str, Any]]:
        observed.update(kwargs)
        return [
            {
                "id": str(identifier),
                "room_label": "Support",
                "medium": medium,
                "status": "COMPLETED",
                "created_at": "2026-01-02T03:04:05+00:00",
                "finished_at": "2026-01-03T04:05:06+00:00",
            }
        ]

    monkeypatch.setattr(
        conversation,
        "list_conversation_round_resources",
        list_rounds,
    )

    result = await resource_service.resource_list(
        ResourceContext(agent_id=13, runtime="internal"),
        f"galaris://{medium}/",
    )

    assert observed["actor_agent_id"] == 13
    assert observed["medium"] == medium
    assert result.entries[0].metadata["created_at"] == "2026-01-02T03:04:05+00:00"
    assert result.entries[0].modified_at == "2026-01-03T04:05:06+00:00"
    assert [entry.uri for entry in result.entries] == [
        f"galaris://{medium}/{identifier}"
    ]

    async def read_round(*args: object, **kwargs: object) -> dict[str, Any]:
        return {
            "round": {
                "id": str(identifier),
                "created_at": "2026-01-02T03:04:05+00:00",
                "finished_at": "2026-01-03T04:05:06+00:00",
            }
        }

    monkeypatch.setattr(conversation, "read_conversation_round_resource", read_round)
    detail = await resource_service.resource_info(
        ResourceContext(agent_id=13, runtime="internal"), result.entries[0].uri
    )
    assert detail.metadata["created_at"] == result.entries[0].metadata["created_at"]


@pytest.mark.asyncio
async def test_galaris_resources_reject_generic_mutations() -> None:
    ctx = ResourceContext(agent_id=7, runtime="internal")
    identifier = uuid4()
    uri = f"galaris://task/{identifier}"

    with pytest.raises(PermissionError, match="read-only"):
        await resource_service.resource_write_text(ctx, uri, "changed")
    with pytest.raises(PermissionError, match="read-only business snapshots"):
        await resource_service.resource_delete(ctx, uri)
    with pytest.raises(PermissionError, match="cannot be moved"):
        await resource_service.resource_move(ctx, uri, "console://task.json")



# The old mocked facade-call assertions are replaced by real package persistence;
# the private MCP/FS workflow is covered by app.skill.tests.test_mcp.
from app.skill.tests.test_personal_packages import agents, personal


@pytest.mark.asyncio
async def test_generic_skill_reads_and_writes_use_live_domain_policy(db, agents):
    from app.skill import interface
    _, _, admin = agents
    package = await interface.create_package(personal('research'), actor_agent_id=admin.id, generic=True)
    ctx = ResourceContext(agent_id=admin.id, runtime='internal')
    uri = package.uri + 'SKILL.md'
    descriptor = await resource_service.resource_info(ctx, uri)
    content = await resource_service.resource_read(ctx, uri)
    assert {'copy', 'info', 'read', 'write', 'append', 'edit'} <= set(descriptor.capabilities)
    written = await resource_service.resource_write(ctx, uri, (content.content + '\nUpdated.\n').encode(),
                                                      expected_revision=content.revision)
    await resource_service.resource_append(ctx, uri, '\nAppended.\n')
    assert written.operation == 'write'
    assert 'Updated.\n\nAppended.' in (await resource_service.resource_read(ctx, uri)).content


@pytest.mark.asyncio
async def test_skill_collection_discovery_does_not_grant_management(monkeypatch):
    from app.skill import interface
    from app.skill.contracts import SkillScope
    monkeypatch.setattr(interface, 'get_agent_scope', AsyncMock(return_value=SkillScope.USAGE))
    descriptor = await resource_service.resource_info(
        ResourceContext(agent_id=7, runtime='internal', skill_management=True), 'galaris://skill/')
    assert descriptor.is_collection and 'create' not in descriptor.capabilities
