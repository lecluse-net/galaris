"""Read-only virtual provider for canonical Galaris business resources."""

from __future__ import annotations

import json
from dataclasses import dataclass
from collections.abc import Awaitable, Callable
from typing import Any, Literal, cast
from urllib.parse import quote
from uuid import UUID

from fastapi.encoders import jsonable_encoder

from .resource_contracts import (
    ResourceCapability,
    ResourceContext,
    ResourceDescriptor,
    ResourceListing,
    ResourceMutation,
    ResourceSearchHit,
    ResourceSearchResult,
    ResourceRead,
)
from .resource_uri import ResourceUri, ResourceUriError


GalarisResourceKind = Literal[
    "code",
    "task",
    "voice",
    "text",
    "goal",
    "goal_cycle",
    "agent",
    "process",
    "skill",
]
_KINDS: tuple[GalarisResourceKind, ...] = (
    "code",
    "task",
    "voice",
    "text",
    "goal",
    "goal_cycle",
    "agent",
    "process",
    "skill",
)
_COLLECTION_CAPABILITIES: list[ResourceCapability] = ["info", "list", "search"]
_ITEM_CAPABILITIES: list[ResourceCapability] = ["copy", "info", "read"]
_code_reader: Callable[[UUID, int], Awaitable[dict[str, object] | None]] | None = None
_code_lister: Callable[[int, str, int, int], Awaitable[list[dict[str, object]]]] | None = None


def register_code_resource_provider(
    reader: Callable[[UUID, int], Awaitable[dict[str, object] | None]],
    lister: Callable[[int, str, int, int], Awaitable[list[dict[str, object]]]],
) -> None:
    global _code_reader, _code_lister
    _code_reader, _code_lister = reader, lister


@dataclass(frozen=True, slots=True)
class _Route:
    kind: GalarisResourceKind | None
    identifier: UUID | str | None = None
    goal_cycles_for: UUID | None = None

    @property
    def is_collection(self) -> bool:
        return self.identifier is None


def _route(reference: ResourceUri) -> _Route:
    if reference.scheme != "galaris":
        raise ResourceUriError("Expected a galaris:// resource URI.")
    segments = reference.segments
    if not segments:
        return _Route(kind=None)
    raw_kind = "process" if segments[0] == "processes" else segments[0]
    if raw_kind == "documentation":
        raise PermissionError("Official Galaris documentation is read-only; use documentation_search or file_read.")
    if raw_kind not in _KINDS:
        raise ResourceUriError(
            "galaris:// supports task, voice, text, goal, goal_cycle, process, and skill."
        )
    kind = raw_kind
    if len(segments) == 1 and reference.is_collection:
        return _Route(kind=kind)
    if (
        kind == "goal"
        and len(segments) == 3
        and segments[2] == "cycles"
        and reference.is_collection
    ):
        try:
            return _Route(kind="goal_cycle", goal_cycles_for=UUID(segments[1]))
        except ValueError as exc:
            raise ResourceUriError("galaris://goal/<uuid>/cycles/ requires a UUID.") from exc
    if len(segments) != 2 or reference.is_collection:
        raise ResourceUriError(
            f"galaris://{kind}/ requires a collection or one exact identifier."
        )
    if kind == "agent":
        if not segments[1].isdecimal() or int(segments[1]) < 1:
            raise ResourceUriError("galaris://agent/ requires a positive integer.")
        return _Route(kind=kind, identifier=segments[1])
    if kind == "process":
        workflow_id = segments[1].strip()
        if not workflow_id or len(workflow_id) > 255:
            raise ResourceUriError(
                "galaris://process/ requires a workflow ID of at most 255 characters."
            )
        return _Route(kind=kind, identifier=workflow_id)
    try:
        return _Route(kind=kind, identifier=UUID(segments[1]))
    except ValueError as exc:
        raise ResourceUriError(f"galaris://{kind}/ requires a valid UUID.") from exc


def _json(payload: object) -> str:
    return json.dumps(
        jsonable_encoder(payload, exclude_none=True),
        ensure_ascii=False,
        indent=2,
        default=str,
    )


def _listing_offset(cursor: str | None) -> int:
    if cursor is None or not cursor.strip():
        return 0
    try:
        offset = int(cursor)
    except ValueError as exc:
        raise ResourceUriError("Invalid galaris:// listing cursor.") from exc
    if offset < 0:
        raise ResourceUriError("Invalid galaris:// listing cursor.")
    return offset


def _item_name(kind: GalarisResourceKind, payload: dict[str, Any]) -> str:
    identifier = str(
        (
            payload.get("workflow_id")
            if kind == "process"
            else payload.get("id")
        )
        or "resource"
    )
    if kind == "task" or kind == "code":
        return str(payload.get("label") or f"Task {identifier}")
    if kind == "text" or kind == "voice":
        round_payload = payload.get("round")
        room_payload = payload.get("room")
        medium = "Voice" if kind == "voice" else "Text"
        if isinstance(room_payload, dict):
            typed_room_payload = cast(dict[str, Any], room_payload)
            if typed_room_payload.get("label"):
                return f"{medium} conversation — {typed_room_payload['label']}"
        if payload.get("room_label"):
            return f"{medium} conversation — {payload['room_label']}"
        if isinstance(round_payload, dict):
            identifier = str(
                cast(dict[str, Any], round_payload).get("id") or identifier
            )
        return f"{medium} conversation round {identifier}"
    if kind in {"goal", "agent"}:
        return str(payload.get("title") or f"Goal {identifier}")
    if kind == "process":
        return str(payload.get("label") or f"Process {identifier}")
    sequence = payload.get("sequence")
    task_label = str(payload.get("task_label") or "").strip()
    return task_label or (
        f"Goal cycle {sequence}" if sequence is not None else f"Goal cycle {identifier}"
    )


def _item_id(kind: GalarisResourceKind, payload: dict[str, Any]) -> str:
    if kind == "process":
        return str(payload.get("workflow_id") or "")
    if kind in {"text", "voice"} and isinstance(payload.get("round"), dict):
        return str(cast(dict[str, Any], payload["round"]).get("id") or "")
    return str(payload.get("id") or "")


def _item_modified_at(kind: GalarisResourceKind, payload: dict[str, Any]) -> str | None:
    if kind in {"text", "voice"} and isinstance(payload.get("round"), dict):
        round_payload = cast(dict[str, Any], payload["round"])
        return cast(
            str | None,
            round_payload.get("finished_at") or round_payload.get("created_at"),
        )
    return cast(
        str | None,
        payload.get("updated_at")
        or payload.get("finished_at")
        or payload.get("created_at"),
    )


def _descriptor(
    kind: GalarisResourceKind,
    payload: dict[str, Any],
    *,
    include_size: bool = False,
) -> ResourceDescriptor:
    identifier = _item_id(kind, payload)
    if kind == "process" and "/" in identifier:
        raise ResourceUriError(
            "A process workflow ID containing '/' cannot be represented as galaris://."
        )
    encoded_identifier = quote(identifier, safe="!$&'()*+,-.;=@_~:")
    content = _json(payload) if include_size else ""
    label = _item_name(kind, payload)
    metadata = {
        key: payload[key]
        for key in (
            "status",
            "agent_id",
            "requester_agent_id",
            "goal_id",
            "task_id",
            "tool_code",
            "native_code",
        )
        if payload.get(key) is not None
    }
    metadata["label"] = label
    return ResourceDescriptor(
        uri=f"galaris://{'processes' if kind == 'process' and payload.get('native_code') else kind}/{encoded_identifier}",
        name=f"{kind}-{identifier}.json",
        media_type=f"application/vnd.galaris.{kind}+json",
        size=len(content.encode("utf-8")) if include_size else None,
        modified_at=_item_modified_at(kind, payload),
        revision=(
            int(payload["revision"])
            if isinstance(payload.get("revision"), int)
            else None
        ),
        capabilities=list(_ITEM_CAPABILITIES),
        metadata=metadata,
    )


def _collection_descriptor(kind: GalarisResourceKind) -> ResourceDescriptor:
    labels = {
        "task": "Tasks",
        "voice": "Voice conversations",
        "text": "Text conversations",
        "goal": "Goals",
        "agent": "Agent profiles",
        "goal_cycle": "Goal cycles",
        "process": "Processes",
        "code": "Code repositories",
        "skill": "Skills",
    }
    return ResourceDescriptor(
        uri=f"galaris://{'processes' if kind == 'process' else kind}/",
        name=labels[kind],
        is_collection=True,
        media_type="application/vnd.galaris.collection+json",
        capabilities=list(_COLLECTION_CAPABILITIES),
    )


async def _can_access_skills(ctx: ResourceContext) -> bool:
    return True  # Usage reads are independent of management delegation.


async def _read_payload(
    ctx: ResourceContext,
    kind: GalarisResourceKind,
    identifier: UUID | str,
    *, native_process: bool = False,
) -> dict[str, Any] | None:
    if kind == "code":
        assert isinstance(identifier, UUID)
        return await _code_reader(identifier, ctx.agent_id) if _code_reader is not None else None
    if kind == "agent":
        from app.agent import read_agent_resource
        return await read_agent_resource(int(str(identifier)), actor_agent_id=ctx.agent_id)
    if kind == "task":
        from app.task import read_task_resource

        assert isinstance(identifier, UUID)
        return await read_task_resource(identifier, actor_agent_id=ctx.agent_id)
    if kind == "text" or kind == "voice":
        from app.conversation import read_conversation_round_resource

        assert isinstance(identifier, UUID)
        return await read_conversation_round_resource(
            identifier,
            actor_agent_id=ctx.agent_id,
            medium=kind,
        )
    if kind == "goal":
        from app.goal import read_goal_resource

        assert isinstance(identifier, UUID)
        return await read_goal_resource(identifier, actor_agent_id=ctx.agent_id)
    if kind == "process":
        from app.process import read_process_resource

        assert isinstance(identifier, str)
        if native_process:
            return await read_process_resource(identifier, actor_agent_id=ctx.agent_id, native=True,
                management_scope=ctx.management_scope)
        return await read_process_resource(
            identifier,
            actor_agent_id=ctx.agent_id,
        )
    from app.goal import read_goal_cycle_resource

    assert isinstance(identifier, UUID)
    return await read_goal_cycle_resource(identifier, actor_agent_id=ctx.agent_id)


async def _list_payloads(
    ctx: ResourceContext,
    kind: GalarisResourceKind,
    *,
    query: str = "",
    offset: int = 0,
    limit: int = 100,
    goal_id: UUID | None = None,
) -> list[dict[str, Any]]:
    if kind == "code":
        return await _code_lister(ctx.agent_id, query, offset, limit) if _code_lister is not None else []
    if kind == "agent":
        from app.agent import list_agent_resources
        return await list_agent_resources(actor_agent_id=ctx.agent_id, query=query, offset=offset, limit=limit)
    if kind == "task":
        from app.task import list_task_resources

        return await list_task_resources(
            actor_agent_id=ctx.agent_id,
            query=query,
            offset=offset,
            limit=limit,
        )
    if kind == "text" or kind == "voice":
        from app.conversation import list_conversation_round_resources

        return await list_conversation_round_resources(
            actor_agent_id=ctx.agent_id,
            medium=kind,
            query=query,
            offset=offset,
            limit=limit,
        )
    if kind == "goal":
        from app.goal import list_goal_resources

        return await list_goal_resources(
            actor_agent_id=ctx.agent_id,
            query=query,
            offset=offset,
            limit=limit,
        )
    if kind == "process":
        from app.process import list_process_resources

        if ctx.management_scope is not None:
            return await list_process_resources(actor_agent_id=ctx.agent_id, query=query, offset=offset,
                limit=limit, management_scope=ctx.management_scope)
        return await list_process_resources(
            actor_agent_id=ctx.agent_id,
            query=query,
            offset=offset,
            limit=limit,
        )
    from app.goal import list_goal_cycle_resources

    return await list_goal_cycle_resources(
        actor_agent_id=ctx.agent_id,
        goal_id=goal_id,
        query=query,
        offset=offset,
        limit=limit,
    )


async def galaris_resource_info(
    ctx: ResourceContext,
    reference: ResourceUri,
) -> ResourceDescriptor:
    if reference.segments[:1] == ("skill",):
        from . import skill_provider
        return await skill_provider.info(ctx, reference)
    if reference.segments[:1] == ("documentation",):
        from . import documentation_provider
        return await documentation_provider.info(ctx, reference)
    route = _route(reference)
    if route.kind is None:
        capabilities = list(_COLLECTION_CAPABILITIES)
        from app.skill import can_manage_skill_resources
        if await can_manage_skill_resources(ctx.agent_id):
            capabilities.append("create")
        return ResourceDescriptor(
            uri="galaris://",
            name="Galaris",
            is_collection=True,
            media_type="application/vnd.galaris.collection+json",
            capabilities=capabilities,
        )
    if route.is_collection:
        descriptor = _collection_descriptor(route.kind)
        if route.goal_cycles_for is not None:
            descriptor.uri = f"galaris://goal/{route.goal_cycles_for}/cycles/"
            descriptor.name = "Goal cycles"
        return descriptor
    assert route.identifier is not None
    payload = await _read_payload(ctx, route.kind, route.identifier, native_process=reference.segments[:1] == ("processes",))
    if payload is None:
        raise FileNotFoundError(str(reference))
    return _descriptor(route.kind, payload, include_size=True)


async def galaris_resource_list(
    ctx: ResourceContext,
    reference: ResourceUri,
    *,
    max_entries: int,
    cursor: str | None = None,
) -> ResourceListing:
    if reference.segments[:1] == ("skill",):
        from . import skill_provider
        return await skill_provider.listing(ctx, reference, max_entries=max_entries, cursor=cursor)
    if reference.segments[:1] == ("documentation",):
        from . import documentation_provider
        return await documentation_provider.list_pages(ctx, reference, max_entries=max_entries, cursor=cursor)
    route = _route(reference)
    offset = _listing_offset(cursor)
    if route.kind is None:
        skill_access = await _can_access_skills(ctx)
        visible_kinds: tuple[GalarisResourceKind, ...] = (
            _KINDS
            if skill_access
            else tuple(kind for kind in _KINDS if kind != "skill")
        )
        from app.tools import has_documentation_access
        from .documentation_provider import collection_descriptor
        entries = [_collection_descriptor(kind) for kind in visible_kinds]
        if await has_documentation_access(ctx.agent_id):
            entries.append(collection_descriptor())
        selected = entries[offset : offset + max_entries]
        next_offset = offset + len(selected)
        truncated = next_offset < len(entries)
        return ResourceListing(
            uri="galaris://",
            entries=selected,
            truncated=truncated,
            next_cursor=str(next_offset) if truncated else None,
        )
    if not route.is_collection:
        raise ResourceUriError("file_list requires a galaris:// collection URI.")
    limit = max(1, min(max_entries, 500))
    if route.kind == "process" and reference.segments[:1] == ("processes",):
        # The first row is a real subcollection; subsequent cursors address definitions.
        available = limit - (1 if offset == 0 else 0)
        payloads = await _list_payloads(ctx, "process", offset=max(0, offset - 1), limit=available + 1)
        entries = ([ResourceDescriptor(uri="galaris://processes/runs/", name="Runs", is_collection=True,
            capabilities=["info", "list"])] if offset == 0 else [])
        entries.extend(_descriptor("process", item) for item in payloads[:available])
        return ResourceListing(uri=str(reference), entries=entries, truncated=len(payloads) > available,
            next_cursor=str(offset + len(entries)) if len(payloads) > available else None)
    payloads = await _list_payloads(
        ctx,
        route.kind,
        offset=offset,
        limit=limit + 1,
        goal_id=route.goal_cycles_for,
    )
    uri = str(reference)
    return ResourceListing(
        uri=uri,
        entries=[_descriptor(route.kind, item) for item in payloads[:limit]],
        truncated=len(payloads) > limit,
        next_cursor=str(offset + limit) if len(payloads) > limit else None,
    )


async def galaris_resource_read(
    ctx: ResourceContext,
    reference: ResourceUri,
    *,
    offset: int,
    max_chars: int,
) -> ResourceRead:
    if reference.segments[:1] == ("skill",):
        from . import skill_provider
        return await skill_provider.read(ctx, reference, offset=offset, max_chars=max_chars)
    if reference.segments[:1] == ("documentation",):
        from . import documentation_provider
        return await documentation_provider.read(ctx, reference, offset=offset, max_chars=max_chars)
    route = _route(reference)
    if route.kind is None or route.is_collection or route.identifier is None:
        raise ResourceUriError("file_read requires one exact galaris:// resource.")
    payload = await _read_payload(ctx, route.kind, route.identifier, native_process=reference.segments[:1] == ("processes",))
    if payload is None:
        raise FileNotFoundError(str(reference))
    content = _json(payload)
    start = max(0, min(offset, len(content)))
    end = min(len(content), start + max_chars)
    return ResourceRead(
        uri=str(reference),
        content=content[start:end],
        start=start,
        end=end,
        total=len(content),
        next_offset=end if end < len(content) else None,
        revision=(
            int(payload["revision"])
            if isinstance(payload.get("revision"), int)
            else None
        ),
        media_type=f"application/vnd.galaris.{route.kind}+json",
    )


async def galaris_skill_file_bytes(
    ctx: ResourceContext,
    reference: ResourceUri,
) -> bytes:
    """Return authorized skill-file bytes for bounded server-side transfers."""

    from . import skill_provider
    return await skill_provider.file_bytes(ctx, reference)
def _excerpt(payload: dict[str, Any], query: str) -> str:
    text = _json(payload)
    position = text.casefold().find(query.casefold())
    if position < 0:
        return text[:360]
    start = max(0, position - 120)
    return text[start : position + len(query) + 240]


async def galaris_resource_search(
    ctx: ResourceContext,
    reference: ResourceUri,
    query: str,
    *,
    mode: Literal["name", "text", "semantic"],
    max_results: int,
    cursor: str | None,
) -> ResourceSearchResult:
    if reference.segments[:1] == ("skill",):
        from . import skill_provider
        return await skill_provider.search(ctx, reference, query, mode=mode, max_results=max_results, cursor=cursor)
    if reference.segments[:1] == ("documentation",):
        from app.tools import require_documentation_access
        await require_documentation_access(ctx.agent_id)
        raise NotImplementedError("Use documentation_search for the versioned Galaris documentation corpus.")
    if mode == "semantic":
        raise NotImplementedError("galaris:// does not expose semantic search.")
    route = _route(reference)
    if not route.is_collection:
        raise ResourceUriError("file_search requires a galaris:// collection URI.")
    offset = max(0, int(cursor or "0"))
    limit = max(1, min(max_results, 500))
    if route.kind is None:
        kinds: tuple[GalarisResourceKind, ...] = tuple(
            kind for kind in _KINDS if kind != "skill"
        )
    else:
        kinds = (route.kind,)
    payloads: list[tuple[GalarisResourceKind, dict[str, Any]]] = []
    for kind in kinds:
        remaining = limit + 1 - len(payloads)
        if remaining <= 0:
            break
        items = await _list_payloads(
            ctx,
            kind,
            query=query,
            offset=offset if len(kinds) == 1 else 0,
            limit=remaining,
            goal_id=route.goal_cycles_for if kind == "goal_cycle" else None,
        )
        payloads.extend((kind, item) for item in items)
    selected = payloads[:limit]
    truncated = len(payloads) > limit
    return ResourceSearchResult(
        uri=str(reference),
        query=query,
        mode=mode,
        hits=[
            ResourceSearchHit(
                resource=_descriptor(kind, payload),
                excerpt=_excerpt(payload, query),
            )
            for kind, payload in selected
        ],
        truncated=truncated,
        next_cursor=str(offset + limit) if truncated and len(kinds) == 1 else None,
    )


async def galaris_resource_create(
    ctx: ResourceContext,
    reference: ResourceUri,
    content: bytes,
) -> ResourceMutation:
    from . import skill_provider
    return await skill_provider.mutate(ctx, reference, content, operation="create")
async def galaris_resource_write(
    ctx: ResourceContext,
    reference: ResourceUri,
    content: bytes,
    *,
    expected_revision: int | None = None,
) -> ResourceMutation:
    from . import skill_provider
    return await skill_provider.mutate(ctx, reference, content, operation="write", expected_revision=expected_revision)
async def galaris_resource_append(
    ctx: ResourceContext,
    reference: ResourceUri,
    content: str,
) -> ResourceMutation:
    from . import skill_provider
    return await skill_provider.mutate(ctx, reference, content.encode("utf-8"), operation="append")
async def galaris_resource_delete(
    ctx: ResourceContext,
    reference: ResourceUri,
) -> ResourceMutation:
    from . import skill_provider
    return await skill_provider.mutate(ctx, reference, operation="delete")
async def galaris_resource_move(
    ctx: ResourceContext,
    source: ResourceUri,
    destination: ResourceUri,
    *,
    overwrite: bool,
) -> ResourceMutation:
    from . import skill_provider
    return await skill_provider.move(ctx, source, destination, overwrite=overwrite)
__all__ = [
    "galaris_resource_append",
    "galaris_resource_create",
    "galaris_resource_delete",
    "galaris_resource_info",
    "galaris_resource_list",
    "galaris_resource_move",
    "galaris_resource_read",
    "galaris_resource_search",
    "galaris_resource_write",
    "galaris_skill_file_bytes",
]
