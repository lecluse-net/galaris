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
async def test_galaris_root_lists_the_supported_business_collections() -> None:
    result = await galaris_provider.galaris_resource_list(
        ResourceContext(agent_id=7, runtime="internal"),
        parse_resource_uri("galaris://", allow_empty=True),
        max_entries=100,
    )

    assert [entry.uri for entry in result.entries] == [
        "galaris://task/",
        "galaris://voice/",
        "galaris://text/",
        "galaris://goal/",
        "galaris://goal_cycle/",
        "galaris://agent/",
        "galaris://process/",
    ]


@pytest.mark.asyncio
async def test_galaris_root_listing_is_paginated() -> None:
    ctx = ResourceContext(agent_id=7, runtime="internal")

    first = await resource_service.resource_list(
        ctx,
        "galaris://",
        max_entries=2,
    )
    second = await resource_service.resource_list(
        ctx,
        "galaris://",
        max_entries=2,
        cursor=first.next_cursor,
    )
    third = await resource_service.resource_list(
        ctx,
        "galaris://",
        max_entries=2,
        cursor=second.next_cursor,
    )

    assert [entry.uri for entry in first.entries] == [
        "galaris://task/",
        "galaris://voice/",
    ]
    assert first.truncated is True
    assert first.next_cursor == "2"
    assert [entry.uri for entry in second.entries] == [
        "galaris://text/",
        "galaris://goal/",
    ]
    assert second.truncated is True
    assert second.next_cursor == "4"
    assert [entry.uri for entry in third.entries] == [
        "galaris://goal_cycle/",
        "galaris://agent/",
    ]
    assert third.truncated is True
    assert third.next_cursor == "6"


@pytest.mark.asyncio
async def test_galaris_root_exposes_skills_only_with_management_access(
) -> None:
    result = await resource_service.resource_list(
        ResourceContext(agent_id=7, runtime="internal", skill_management=True),
        "galaris://",
    )

    assert result.entries[-1].uri == "galaris://skill/"


@pytest.mark.asyncio
async def test_skill_collection_rechecks_management_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.skill as skill

    denied = AsyncMock(side_effect=PermissionError("skill_management required"))
    monkeypatch.setattr(skill, "require_skill_management_access", denied)

    with pytest.raises(PermissionError, match="skill_management"):
        await resource_service.resource_info(
            ResourceContext(agent_id=7, runtime="internal"),
            "galaris://skill/",
        )

    denied.assert_awaited_once_with(7)


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
        }

    monkeypatch.setattr(task, "read_task_resource", read_task_resource)
    ctx = ResourceContext(agent_id=7, runtime="internal")
    uri = f"galaris://task/{identifier}"

    descriptor = await resource_service.resource_info(ctx, uri)
    content = await resource_service.resource_read(ctx, uri, max_chars=10_000)

    assert observed == {"task_id": identifier, "actor_agent_id": 7}
    assert descriptor.uri == uri
    assert descriptor.name == f"task-{identifier}.json"
    assert descriptor.media_type == "application/vnd.galaris.task+json"
    assert descriptor.metadata["label"] == "Prepare release"
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
    assert [entry.uri for entry in result.entries] == [
        f"galaris://{medium}/{identifier}"
    ]


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


@pytest.mark.asyncio
async def test_skill_file_resource_routes_read_and_mutations_through_skill_facade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.skill as skill

    markdown = b"---\nname: research\ndescription: Research.\n---\n# Research\n"
    file_data = SimpleNamespace(
        path="SKILL.md",
        name="SKILL.md",
        content=markdown,
        text=True,
        modified_at=datetime.now(timezone.utc),
        revision=11,
    )
    summary = {
        "code": "research",
        "label": "Research",
        "system": False,
        "available": True,
        "valid": True,
        "description": "Research.",
        "file_count": 1,
        "total_size": len(markdown),
        "modified_at": None,
    }
    monkeypatch.setattr(skill, "get_skill_resource", AsyncMock(return_value=summary))
    monkeypatch.setattr(skill, "read_skill_file", AsyncMock(return_value=file_data))
    write = AsyncMock(return_value=file_data)
    append = AsyncMock(return_value=file_data)
    monkeypatch.setattr(skill, "write_skill_file", write)
    monkeypatch.setattr(skill, "append_skill_file", append)
    ctx = ResourceContext(agent_id=7, runtime="internal")
    uri = "galaris://skill/research/SKILL.md"

    descriptor = await resource_service.resource_info(ctx, uri)
    content = await resource_service.resource_read(ctx, uri)
    written = await resource_service.resource_write(
        ctx,
        uri,
        markdown + b"\nMore.\n",
        expected_revision=11,
    )
    appended = await resource_service.resource_append(ctx, uri, "\nMore.\n")

    assert descriptor.capabilities == ["copy", "info", "read", "write", "append", "edit"]
    assert content.content == markdown.decode("utf-8")
    assert content.revision == 11
    assert written.operation == "write"
    assert appended.operation == "append"
    write.assert_awaited_once_with(
        "research",
        "SKILL.md",
        markdown + b"\nMore.\n",
        actor_agent_id=7,
        expected_revision=11,
    )
    append.assert_awaited_once_with(
        "research",
        "SKILL.md",
        "\nMore.\n",
        actor_agent_id=7,
    )
