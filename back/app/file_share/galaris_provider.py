"""Read-only virtual provider for canonical Galaris business resources."""

from __future__ import annotations

import base64
import json
import mimetypes
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class _Route:
    kind: GalarisResourceKind | None
    identifier: UUID | str | None = None
    goal_cycles_for: UUID | None = None
    skill_code: str | None = None
    skill_path: str | None = None

    @property
    def is_collection(self) -> bool:
        if self.kind == "skill":
            return self.skill_path is None
        return self.identifier is None


def _route(reference: ResourceUri) -> _Route:
    if reference.scheme != "galaris":
        raise ResourceUriError("Expected a galaris:// resource URI.")
    segments = reference.segments
    if not segments:
        return _Route(kind=None)
    raw_kind = segments[0]
    if raw_kind not in _KINDS:
        raise ResourceUriError(
            "galaris:// supports task, voice, text, goal, goal_cycle, process, and skill."
        )
    kind = raw_kind
    if len(segments) == 1 and reference.is_collection:
        return _Route(kind=kind)
    if kind == "skill":
        from app.skill import storage

        if len(segments) == 2 and reference.is_collection:
            return _Route(kind=kind, skill_code=storage.validate_code(segments[1]))
        if len(segments) >= 3 and not reference.is_collection:
            return _Route(
                kind=kind,
                skill_code=storage.validate_code(segments[1]),
                skill_path="/".join(segments[2:]),
            )
        raise ResourceUriError(
            "galaris://skill/ requires a skill collection or one exact file path."
        )
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
    if kind == "task":
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
        )
        if payload.get(key) is not None
    }
    metadata["label"] = label
    return ResourceDescriptor(
        uri=f"galaris://{kind}/{encoded_identifier}",
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
        "skill": "Skills",
    }
    return ResourceDescriptor(
        uri=f"galaris://{kind}/",
        name=labels[kind],
        is_collection=True,
        media_type="application/vnd.galaris.collection+json",
        capabilities=list(_COLLECTION_CAPABILITIES),
    )


def _skill_directory_descriptor(payload: dict[str, Any]) -> ResourceDescriptor:
    code = str(payload["code"])
    return ResourceDescriptor(
        uri=f"galaris://skill/{quote(code, safe='-')}/",
        name=str(payload.get("label") or code),
        is_collection=True,
        media_type="application/vnd.galaris.skill+directory",
        modified_at=cast(str | None, payload.get("modified_at")),
        capabilities=["info", "list", "search", "create"],
        metadata={
            key: payload[key]
            for key in (
                "code",
                "label",
                "system",
                "available",
                "valid",
                "description",
                "file_count",
                "total_size",
            )
        },
    )


def _skill_file_descriptor(
    code: str,
    payload: dict[str, Any],
    *,
    system: bool,
    modified_at: str | None = None,
    revision: int | None = None,
) -> ResourceDescriptor:
    path = str(payload["path"])
    encoded_path = "/".join(quote(part, safe="!$&'()*+,-.;=@_~:") for part in path.split("/"))
    capabilities: list[ResourceCapability] = ["copy", "info", "read"]
    if not system:
        capabilities.append("write")
        if bool(payload.get("text")):
            capabilities.extend(("append", "edit"))
        if path != "SKILL.md":
            capabilities.extend(("delete", "move"))
    return ResourceDescriptor(
        uri=f"galaris://skill/{quote(code, safe='-')}/{encoded_path}",
        name=str(payload.get("name") or path.rsplit("/", 1)[-1]),
        media_type=mimetypes.guess_type(path)[0] or "application/octet-stream",
        size=int(payload["size"]),
        modified_at=modified_at,
        revision=revision,
        capabilities=capabilities,
        metadata={"skill_code": code, "path": path, "system": system},
    )


async def _skill_summary(ctx: ResourceContext, code: str) -> dict[str, Any]:
    from app.skill import get_skill_resource

    payload = await get_skill_resource(code, actor_agent_id=ctx.agent_id)
    if payload is None:
        raise FileNotFoundError(code)
    return dict(payload)


async def _can_access_skills(ctx: ResourceContext) -> bool:
    return ctx.skill_management


async def _read_payload(
    ctx: ResourceContext,
    kind: GalarisResourceKind,
    identifier: UUID | str,
) -> dict[str, Any] | None:
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
    route = _route(reference)
    if route.kind is None:
        capabilities = list(_COLLECTION_CAPABILITIES)
        if await _can_access_skills(ctx):
            capabilities.append("create")
        return ResourceDescriptor(
            uri="galaris://",
            name="Galaris",
            is_collection=True,
            media_type="application/vnd.galaris.collection+json",
            capabilities=capabilities,
        )
    if route.kind == "skill":
        if route.skill_code is None:
            if not await _can_access_skills(ctx):
                from app.skill import require_skill_management_access

                await require_skill_management_access(ctx.agent_id)
            descriptor = _collection_descriptor("skill")
            descriptor.capabilities.append("create")
            return descriptor
        summary = await _skill_summary(ctx, route.skill_code)
        if route.skill_path is None:
            return _skill_directory_descriptor(summary)
        from app.skill import read_skill_file

        file_data = await read_skill_file(
            route.skill_code,
            route.skill_path,
            actor_agent_id=ctx.agent_id,
        )
        return _skill_file_descriptor(
            route.skill_code,
            {
                "path": file_data.path,
                "name": file_data.name,
                "size": len(file_data.content),
                "text": file_data.text,
            },
            system=bool(summary["system"]),
            modified_at=file_data.modified_at.isoformat(),
            revision=file_data.revision,
        )
    if route.is_collection:
        descriptor = _collection_descriptor(route.kind)
        if route.goal_cycles_for is not None:
            descriptor.uri = f"galaris://goal/{route.goal_cycles_for}/cycles/"
            descriptor.name = "Goal cycles"
        return descriptor
    assert route.identifier is not None
    payload = await _read_payload(ctx, route.kind, route.identifier)
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
    route = _route(reference)
    offset = _listing_offset(cursor)
    if route.kind is None:
        skill_access = await _can_access_skills(ctx)
        visible_kinds: tuple[GalarisResourceKind, ...] = (
            _KINDS
            if skill_access
            else tuple(kind for kind in _KINDS if kind != "skill")
        )
        selected_kinds = visible_kinds[offset : offset + max_entries]
        next_offset = offset + len(selected_kinds)
        truncated = next_offset < len(visible_kinds)
        return ResourceListing(
            uri="galaris://",
            entries=[_collection_descriptor(kind) for kind in selected_kinds],
            truncated=truncated,
            next_cursor=str(next_offset) if truncated else None,
        )
    if route.kind == "skill":
        limit = max(1, min(max_entries, 500))
        if route.skill_code is None:
            from app.skill import list_skill_resources

            payloads = await list_skill_resources(
                actor_agent_id=ctx.agent_id,
                offset=offset,
                limit=limit + 1,
            )
            return ResourceListing(
                uri="galaris://skill/",
                entries=[_skill_directory_descriptor(dict(item)) for item in payloads[:limit]],
                truncated=len(payloads) > limit,
                next_cursor=str(offset + limit) if len(payloads) > limit else None,
            )
        if route.skill_path is not None:
            raise ResourceUriError("file_list requires a galaris://skill/ collection URI.")
        from app.skill import list_skill_files

        summary = await _skill_summary(ctx, route.skill_code)
        files = await list_skill_files(route.skill_code, actor_agent_id=ctx.agent_id)
        selected = files[offset : offset + limit]
        return ResourceListing(
            uri=str(reference),
            entries=[
                _skill_file_descriptor(
                    route.skill_code,
                    dict(item),
                    system=bool(summary["system"]),
                )
                for item in selected
            ],
            truncated=offset + limit < len(files),
            next_cursor=str(offset + limit) if offset + limit < len(files) else None,
        )
    if not route.is_collection:
        raise ResourceUriError("file_list requires a galaris:// collection URI.")
    limit = max(1, min(max_entries, 500))
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
    route = _route(reference)
    if route.kind == "skill":
        if route.skill_code is None or route.skill_path is None:
            raise ResourceUriError("file_read requires one exact skill file URI.")
        from app.skill import read_skill_file

        file_data = await read_skill_file(
            route.skill_code,
            route.skill_path,
            actor_agent_id=ctx.agent_id,
        )
        media_type = mimetypes.guess_type(file_data.name)[0] or "application/octet-stream"
        if not file_data.text:
            if offset:
                raise ValueError("Binary skill files do not support paginated offsets.")
            if len(file_data.content) > 1_048_576:
                raise ValueError(
                    "Binary skill files larger than 1 MiB must be copied to another provider."
                )
            return ResourceRead(
                uri=str(reference),
                content=base64.b64encode(file_data.content).decode("ascii"),
                encoding="base64",
                media_type=media_type,
                start=0,
                end=len(file_data.content),
                total=len(file_data.content),
                revision=file_data.revision,
            )
        try:
            content = file_data.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("The skill file is not valid UTF-8 text.") from exc
        start = max(0, min(offset, len(content)))
        end = min(len(content), start + max_chars)
        return ResourceRead(
            uri=str(reference),
            content=content[start:end],
            media_type=media_type,
            start=start,
            end=end,
            total=len(content),
            next_offset=end if end < len(content) else None,
            revision=file_data.revision,
        )
    if route.kind is None or route.is_collection or route.identifier is None:
        raise ResourceUriError("file_read requires one exact galaris:// resource.")
    payload = await _read_payload(ctx, route.kind, route.identifier)
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

    route = _route(reference)
    if route.kind != "skill" or route.skill_code is None or route.skill_path is None:
        raise ResourceUriError("Expected one exact galaris://skill/ file URI.")
    from app.skill import read_skill_file

    data = await read_skill_file(
        route.skill_code,
        route.skill_path,
        actor_agent_id=ctx.agent_id,
    )
    return data.content


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
    if mode == "semantic":
        raise NotImplementedError("galaris:// does not expose semantic search.")
    route = _route(reference)
    if not route.is_collection:
        raise ResourceUriError("file_search requires a galaris:// collection URI.")
    offset = max(0, int(cursor or "0"))
    limit = max(1, min(max_results, 500))
    if route.kind == "skill":
        from app.skill import list_skill_files, list_skill_resources, read_skill_file

        hits: list[ResourceSearchHit] = []
        if route.skill_code is None:
            summaries = await list_skill_resources(
                actor_agent_id=ctx.agent_id,
                query=query,
                offset=offset,
                limit=limit + 1,
            )
            selected_summaries = summaries[:limit]
            return ResourceSearchResult(
                uri=str(reference),
                query=query,
                mode=mode,
                hits=[
                    ResourceSearchHit(resource=_skill_directory_descriptor(dict(item)))
                    for item in selected_summaries
                ],
                truncated=len(summaries) > limit,
                next_cursor=str(offset + limit) if len(summaries) > limit else None,
            )
        summary = await _skill_summary(ctx, route.skill_code)
        files = await list_skill_files(route.skill_code, actor_agent_id=ctx.agent_id)
        folded = query.casefold()
        for item in files:
            matched = folded in item["path"].casefold()
            excerpt = ""
            if mode == "text" and item["text"]:
                data = await read_skill_file(
                    route.skill_code,
                    item["path"],
                    actor_agent_id=ctx.agent_id,
                )
                text = data.content.decode("utf-8")
                position = text.casefold().find(folded)
                matched = position >= 0
                if matched:
                    start = max(0, position - 120)
                    excerpt = text[start : position + len(query) + 240]
            if matched:
                hits.append(
                    ResourceSearchHit(
                        resource=_skill_file_descriptor(
                            route.skill_code,
                            dict(item),
                            system=bool(summary["system"]),
                        ),
                        excerpt=excerpt,
                    )
                )
        selected_hits = hits[offset : offset + limit]
        truncated = offset + limit < len(hits)
        return ResourceSearchResult(
            uri=str(reference),
            query=query,
            mode=mode,
            hits=selected_hits,
            truncated=truncated,
            next_cursor=str(offset + limit) if truncated else None,
        )
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
    route = _route(reference)
    if route.kind != "skill" or route.skill_code is None or route.skill_path is None:
        raise PermissionError(
            "Only galaris://skill/<skill-code>/<path> supports generic file creation."
        )
    from app.skill import create_skill_file

    data = await create_skill_file(
        route.skill_code,
        route.skill_path,
        content,
        actor_agent_id=ctx.agent_id,
    )
    return ResourceMutation(
        uri=str(reference),
        operation="create",
        state="created",
        size=len(data.content),
        revision=data.revision,
    )


async def galaris_resource_write(
    ctx: ResourceContext,
    reference: ResourceUri,
    content: bytes,
    *,
    expected_revision: int | None = None,
) -> ResourceMutation:
    route = _route(reference)
    if route.kind != "skill" or route.skill_code is None or route.skill_path is None:
        raise PermissionError(
            "galaris:// business snapshots are read-only; only "
            "galaris://skill/<skill-code>/<path> supports generic file writes."
        )
    from app.skill import write_skill_file

    data = await write_skill_file(
        route.skill_code,
        route.skill_path,
        content,
        actor_agent_id=ctx.agent_id,
        expected_revision=expected_revision,
    )
    return ResourceMutation(
        uri=str(reference),
        operation="write",
        state="written",
        size=len(data.content),
        revision=data.revision,
    )


async def galaris_resource_append(
    ctx: ResourceContext,
    reference: ResourceUri,
    content: str,
) -> ResourceMutation:
    route = _route(reference)
    if route.kind != "skill" or route.skill_code is None or route.skill_path is None:
        raise PermissionError(
            "Only galaris://skill/<skill-code>/<path> supports generic text append."
        )
    from app.skill import append_skill_file

    data = await append_skill_file(
        route.skill_code,
        route.skill_path,
        content,
        actor_agent_id=ctx.agent_id,
    )
    return ResourceMutation(
        uri=str(reference),
        operation="append",
        state="appended",
        size=len(data.content),
        revision=data.revision,
    )


async def galaris_resource_delete(
    ctx: ResourceContext,
    reference: ResourceUri,
) -> ResourceMutation:
    route = _route(reference)
    if route.kind != "skill" or route.skill_code is None or route.skill_path is None:
        raise PermissionError(
            "Only auxiliary galaris://skill/<skill-code>/<path> files can be deleted."
        )
    from app.skill import delete_skill_file

    data = await delete_skill_file(
        route.skill_code,
        route.skill_path,
        actor_agent_id=ctx.agent_id,
    )
    return ResourceMutation(
        uri=str(reference),
        operation="delete",
        state="deleted",
        size=len(data.content),
        revision=data.revision,
    )


async def galaris_resource_move(
    ctx: ResourceContext,
    source: ResourceUri,
    destination: ResourceUri,
    *,
    overwrite: bool,
) -> ResourceMutation:
    source_route = _route(source)
    destination_route = _route(destination)
    if (
        source_route.kind != "skill"
        or destination_route.kind != "skill"
        or source_route.skill_code is None
        or destination_route.skill_code != source_route.skill_code
        or source_route.skill_path is None
    ):
        raise PermissionError(
            "Skill files can only be moved within the same galaris://skill/<skill-code>/ directory."
        )
    destination_path = destination_route.skill_path
    if destination_path is None and destination_route.skill_code is not None:
        destination_path = source_route.skill_path.rsplit("/", 1)[-1]
    if destination_path is None:
        raise ResourceUriError("A skill file move requires an exact destination path.")
    from app.skill import move_skill_file

    data = await move_skill_file(
        source_route.skill_code,
        source_route.skill_path,
        destination_path,
        actor_agent_id=ctx.agent_id,
        overwrite=overwrite,
    )
    encoded_path = "/".join(
        quote(part, safe="!$&'()*+,-.;=@_~:") for part in data.path.split("/")
    )
    return ResourceMutation(
        uri=f"galaris://skill/{quote(source_route.skill_code, safe='-')}/{encoded_path}",
        operation="move",
        state="moved",
        source_uri=str(source),
        size=len(data.content),
        revision=data.revision,
    )


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
