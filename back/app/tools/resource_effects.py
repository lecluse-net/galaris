"""Promote successful native-tool effects into the Task working set."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any, cast

from app.agent.contracts import WorkingResource
from app.agent.task_port import task_port
from app.file_share import ResourceUriError, parse_resource_uri

from .mcp_loader import McpToolContext


def _result_mapping(result: Any) -> Mapping[str, Any]:
    if isinstance(result, Mapping):
        return cast(Mapping[str, Any], result)
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, Mapping):
        return cast(Mapping[str, Any], structured)
    if not isinstance(result, str) or not result.lstrip().startswith("{"):
        return {}
    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        return {}
    return cast(Mapping[str, Any], parsed) if isinstance(parsed, Mapping) else {}


def _text(arguments: Mapping[str, Any], key: str) -> str:
    return str(arguments.get(key) or "").strip()


def _file_role(path: str) -> str:
    return f"file:{path}"[:160]


def _resource_uri(value: object, *, allow_empty: bool = False) -> str:
    try:
        parsed = parse_resource_uri(value, allow_empty=allow_empty)
        if parsed.scheme in {"http", "https"} and "?" in parsed.locator:
            return f"{parsed.scheme}://{parsed.locator.partition('?')[0]}"
        return str(parsed)
    except ResourceUriError:
        return ""


def _resource_type(uri: str) -> str:
    scheme = uri.partition("://")[0]
    return {
        "document": "memory_document",
        "memory": "memory",
    }.get(scheme, "artifact")


async def _record(ctx: McpToolContext, resource: WorkingResource) -> None:
    if ctx.task_id is None:
        return
    await task_port.upsert_working_resource(ctx.task_id, resource)


async def record_tool_resources(
    ctx: McpToolContext,
    tool_name: str,
    arguments: Mapping[str, Any],
    result: Any,
) -> None:
    """Record exact references only after the underlying tool returned successfully."""

    if ctx.task_id is None:
        return
    payload = _result_mapping(result)
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))

    if tool_name == "process_get_run" and payload.get("status") == "success" and payload.get("tool_code") == "multimedia":
        output = _result_mapping(payload.get("output"))
        files = output.get("files")
        if isinstance(files, list):
            for item in cast(list[Any], files):
                file = _result_mapping(item)
                uri = _resource_uri(file.get("uri"))
                if uri:
                    await _record(ctx, WorkingResource(
                        resource_type="artifact", role=_file_role(uri), reference=uri,
                        label=PurePosixPath(uri).name, producer_task_id=ctx.task_id,
                        metadata={"tool": "multimedia", "process_run_id": payload.get("id"),
                                  "media_type": file.get("media_type")},
                    ))
        return

    if tool_name == "console_exec":
        # Shell text and exit status do not prove which remote ref/content was published.
        # Even a read-only grep may mention "git push". Keep only the execution journal.
        return

    if tool_name.startswith("document_"):
        document_id = str(
            payload.get("document_id") or arguments.get("document_id") or ""
        ).strip()
        if not document_id:
            return
        requested_role = _text(arguments, "role")
        working_set = await task_port.get_working_set(ctx.task_id)
        existing = next(
            (
                item
                for item in working_set.active()
                if item.resource_type == "memory_document"
                and item.reference in {document_id, f"document://{document_id}"}
            ),
            None,
        )
        role = requested_role or (
            existing.role
            if existing is not None
            else f"referenced_document:{document_id[:8]}"
        )
        revision_raw = payload.get("revision")
        revision = (
            int(revision_raw)
            if isinstance(revision_raw, int) and not isinstance(revision_raw, bool)
            else existing.revision if existing is not None else None
        )
        await _record(
            ctx,
            WorkingResource(
                resource_type="memory_document",
                role=role,
                reference=f"document://{document_id}",
                label=str(payload.get("title") or arguments.get("title") or ""),
                revision=revision,
                producer_task_id=ctx.task_id,
                metadata={
                    "folder": str(payload.get("folder") or arguments.get("folder") or ""),
                    "last_operation": tool_name,
                },
            ),
        )
        return

    resource_reference = ""
    if tool_name in {
        "file_create",
        "file_write",
        "file_append",
        "file_edit",
        "file_read",
        "file_info",
    }:
        resource_reference = str(payload.get("uri") or "").strip() or _resource_uri(
            arguments.get("uri") or arguments.get("path")
        )
    elif tool_name in {"file_copy", "file_move"}:
        resource_reference = str(payload.get("uri") or "").strip() or _resource_uri(
            arguments.get("destination")
        )
    elif tool_name == "file_delete":
        resource_reference = str(payload.get("uri") or "").strip() or _resource_uri(
            arguments.get("uri") or arguments.get("path")
        )
    elif tool_name == "file_download":
        resource_reference = _resource_uri(arguments.get("destination"))
    if resource_reference:
        normalized = _resource_uri(resource_reference)
        scheme = normalized.partition("://")[0]
        is_delivery = (
            tool_name in {"file_copy", "file_move"}
            and scheme not in {"console", "document", "memory"}
        )
        label = PurePosixPath(normalized.partition("://")[2].rstrip("/")).name
        role = "final_artifact" if is_delivery else _file_role(normalized)
        if scheme == "document":
            working_set = await task_port.get_working_set(ctx.task_id)
            existing = next(
                (
                    item
                    for item in working_set.active()
                    if item.reference == normalized
                ),
                None,
            )
            if existing is not None:
                role = existing.role
            elif tool_name == "file_create" and not working_set.active(
                "primary_working_document"
            ):
                role = "primary_working_document"
            else:
                role = f"referenced_document:{label[:8]}"
            label = str(arguments.get("name") or label)
        await _record(
            ctx,
            WorkingResource(
                resource_type=_resource_type(normalized),
                role=role,
                reference=normalized,
                label=label,
                revision=(
                    int(payload["revision"])
                    if isinstance(payload.get("revision"), int)
                    else None
                ),
                producer_task_id=ctx.task_id,
                state="stale" if tool_name == "file_delete" else "active",
                metadata={
                    "runtime": ctx.runtime,
                    "last_operation": tool_name,
                    **(
                        {"produced": True}
                        if tool_name
                        in {
                            "file_create",
                            "file_write",
                            "file_append",
                            "file_edit",
                            "file_copy",
                            "file_move",
                            "file_download",
                        }
                        else {}
                    ),
                    **({"delivered": True} if is_delivery else {}),
                },
            ),
        )

    if tool_name == "file_move":
        source_uri = str(payload.get("source_uri") or "").strip() or _resource_uri(
            arguments.get("source")
        )
        if source_uri:
            normalized_source = _resource_uri(source_uri)
            await _record(
                ctx,
                WorkingResource(
                    resource_type=_resource_type(normalized_source),
                    role=_file_role(normalized_source),
                    reference=normalized_source,
                    label=PurePosixPath(
                        normalized_source.partition("://")[2].rstrip("/")
                    ).name,
                    producer_task_id=ctx.task_id,
                    state="stale",
                    metadata={
                        "runtime": ctx.runtime,
                        "last_operation": tool_name,
                        "moved_to": resource_reference,
                    },
                ),
            )

    if tool_name in {"file_copy", "file_move"} and resource_reference:
        destination_uri = _resource_uri(resource_reference)
        destination_scheme = destination_uri.partition("://")[0]
        if destination_scheme not in {"console", "document", "memory"}:
            source_uri = str(payload.get("source_uri") or "").strip() or _resource_uri(
                arguments.get("source")
            )
            label = PurePosixPath(destination_uri.partition("://")[2]).name
            await _record(
                ctx,
                WorkingResource(
                    resource_type="delivery_receipt",
                    role=f"delivery_receipt:{destination_uri}"[:160],
                    reference=f"{tool_name}:{destination_uri}",
                    label=label,
                    producer_task_id=ctx.task_id,
                    metadata={
                        "source": source_uri,
                        "destination": destination_uri,
                        "tool": tool_name,
                        "delivered": True,
                    },
                ),
            )

    if tool_name == "messenger_send_audio_message":
        destination = str(payload.get("destination") or "").strip()
        connection_id = str(payload.get("connection_id") or "").strip()
        if not destination:
            return
        reference = f"messenger-audio:{connection_id}:{destination}"
        await _record(
            ctx,
            WorkingResource(
                resource_type="artifact",
                role="final_artifact",
                reference=reference,
                label="message-audio.mp3",
                producer_task_id=ctx.task_id,
                metadata={
                    "delivery_destination": destination,
                    "provider": str(payload.get("provider") or ""),
                    "size": payload.get("size"),
                    "delivered": True,
                },
            ),
        )
        await _record(
            ctx,
            WorkingResource(
                resource_type="delivery_receipt",
                role=f"delivery_receipt:{reference}"[:160],
                reference=reference,
                label="message-audio.mp3",
                producer_task_id=ctx.task_id,
                metadata={
                    "destination": destination,
                    "connection_id": connection_id,
                    "tool": tool_name,
                },
            ),
        )
    elif tool_name in {"messenger_room_send_file", "messenger_send_file_to_user"}:
        source = str(payload.get("source_uri") or "").strip()
        if not source:
            source = _text(arguments, "resource_uri") or _text(arguments, "filename")
        if not source:
            return
        normalized = _resource_uri(source)
        if not normalized:
            return
        delivered_uri = str(payload.get("uri") or "").strip()
        label = str(payload.get("name") or "").strip() or PurePosixPath(
            normalized.partition("://")[2]
        ).name
        destination = _text(arguments, "room_id") or _text(arguments, "user_id")
        await _record(
            ctx,
            WorkingResource(
                resource_type=_resource_type(normalized),
                role=_file_role(normalized),
                reference=normalized,
                label=label,
                producer_task_id=ctx.task_id,
                metadata={
                    "runtime": ctx.runtime,
                    "delivered_copy": True,
                    "last_delivery_tool": tool_name,
                },
            ),
        )
        await _record(
            ctx,
            WorkingResource(
                resource_type="artifact",
                role="final_artifact",
                reference=_resource_uri(delivered_uri) if delivered_uri else normalized,
                label=label,
                producer_task_id=ctx.task_id,
                metadata={
                    "source": normalized,
                    "delivery_destination": destination,
                    "delivered": True,
                },
            ),
        )
        await _record(
            ctx,
            WorkingResource(
                resource_type="delivery_receipt",
                role=f"delivery_receipt:{normalized}"[:160],
                reference=f"{tool_name}:{destination}:{normalized}",
                label=label,
                producer_task_id=ctx.task_id,
                metadata={
                    "destination": destination,
                    "filename": normalized,
                    **({"uri": _resource_uri(delivered_uri)} if delivered_uri else {}),
                    "tool": tool_name,
                },
            ),
        )
    elif tool_name == "file_upload":
        source = _text(arguments, "source")
        if not source:
            return
        normalized = _resource_uri(source)
        if not normalized:
            return
        label = PurePosixPath(normalized.partition("://")[2]).name
        tool_code = _text(arguments, "tool_code")
        destination = _text(arguments, "destination")
        delivery_reference = _resource_uri(
            f"{tool_code}://{destination or label}"
        )
        await _record(
            ctx,
            WorkingResource(
                resource_type="artifact",
                role="final_artifact",
                reference=delivery_reference,
                label=label,
                producer_task_id=ctx.task_id,
                metadata={
                    "source": normalized,
                    "file_share_tool": tool_code,
                    "destination": destination,
                    "delivered": True,
                },
            ),
        )
        await _record(
            ctx,
            WorkingResource(
                resource_type="delivery_receipt",
                role=f"delivery_receipt:{normalized}"[:160],
                reference=f"file_upload:{delivery_reference}",
                label=label,
                producer_task_id=ctx.task_id,
                metadata={
                    "source": normalized,
                    "destination": destination,
                    "tool_code": tool_code,
                    "tool": tool_name,
                },
            ),
        )
    elif tool_name in {"messenger_room_send_message", "messenger_send_message_to_user"}:
        destination = _text(arguments, "room_id") or _text(arguments, "user_id")
        if destination:
            await _record(
                ctx,
                WorkingResource(
                    resource_type="messenger_destination",
                    role="conversation_destination",
                    reference=destination,
                    producer_task_id=ctx.task_id,
                    metadata={"tool": tool_name},
                ),
            )


__all__ = ["record_tool_resources"]
