"""Present terminal Process variables through canonical conversation resources."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from loguru import logger

from app.file_share import ResourceContext, ResourceUriError, parse_resource_uri
from app.messenger import MessengerFacade
from core.database import get_db
from core.i18n import t


PROCESS_OUTPUT_TIMEOUT_SECONDS = 15


@dataclass(frozen=True, slots=True)
class ProcessOutput:
    label: str
    text: str
    resource_uri: str | None = None


def process_outputs(output: object, *, typed: bool) -> tuple[ProcessOutput, ...]:
    """Unwrap only a frozen v2 contract; ordinary JSON keeps its business keys."""
    rows: list[ProcessOutput] = []

    def visit(label: str, value: object, *, envelope: bool) -> None:
        kind: object = None
        if envelope and isinstance(value, dict):
            item = cast(dict[str, object], value)
            kind, value = item.get("type"), item.get("value")
        resource = isinstance(kind, str) and kind in {"File", "Document", "Dataset"}
        if isinstance(value, dict) and value:
            for key, child in cast(dict[str, object], value).items():
                visit(f"{label}.{key}" if label else key, child, envelope=envelope)
            return
        if isinstance(value, list) and value:
            for index, child in enumerate(cast(list[object], value)):
                visit(f"{label}[{index + 1}]", child, envelope=envelope)
            return
        uri = None
        if isinstance(value, str) and (resource or not typed) and "://" in value:
            try:
                reference = parse_resource_uri(value)
                if not reference.is_collection and str(reference) == value:
                    uri = value
            except ResourceUriError:
                pass
        rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        rows.append(ProcessOutput(label=label, text=rendered, resource_uri=uri))

    if isinstance(output, dict):
        for name, value in cast(dict[str, object], output).items():
            visit(name, value, envelope=typed)
    elif output is not None:
        visit("", output, envelope=False)
    return tuple(rows)


async def present_process_outputs(
    rows: tuple[ProcessOutput, ...],
    *,
    context: ResourceContext,
    messenger: MessengerFacade,
    room_id: UUID,
) -> tuple[str, list[str]]:
    """Attach authorized resources once and preserve values when a provider fails."""
    from app.file_share import deliver_resource_to_messenger, resource_info

    resources = dict.fromkeys(row.resource_uri for row in rows if row.resource_uri)
    names: dict[str, str] = {}
    attachments: list[str] = []
    try:
        # Leave time in the conversation notification lease for its required text.
        async with asyncio.timeout(PROCESS_OUTPUT_TIMEOUT_SECONDS):
            for uri in resources:
                try:
                    if messenger.kind == "internal":
                        descriptor = await resource_info(context, uri)
                        if descriptor.is_collection:
                            continue
                        name, attached_uri = descriptor.name, descriptor.uri
                    else:
                        delivered = await deliver_resource_to_messenger(context, messenger, room_id, uri)
                        name, attached_uri = delivered.name, delivered.uri
                    await get_db().commit()
                    names[uri] = name or uri
                    attachments.append(attached_uri)
                except Exception as exc:
                    await get_db().rollback()
                    logger.warning("Process output attachment unavailable: {}", type(exc).__name__)
    except TimeoutError:
        await get_db().rollback()
        logger.warning("Process output attachment delivery timed out")
    lines: list[str] = []
    for row in rows:
        value = row.text
        if row.resource_uri:
            value = names.get(row.resource_uri) or t("conversation.process_output_unavailable", context.language)
        lines.append(f"{row.label} : {value}" if row.label else value)
    return "\n".join(lines), list(dict.fromkeys(attachments))
