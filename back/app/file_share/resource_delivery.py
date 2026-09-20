"""Bounded resource delivery to canonical Messenger attachments."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from core.params import runtime_settings

from .messenger_transport import MessengerFileTransport
from .resource_contracts import DeliveredResource, ResourceContext
from .resource_service import materialize_resource
from .resource_uri import parse_resource_uri


async def deliver_resource_to_messenger(
    ctx: ResourceContext,
    messenger: Any,
    room_id: object,
    uri: object,
) -> DeliveredResource:
    """Copy one authorized resource to a room and return its canonical receipt."""

    with tempfile.TemporaryDirectory(prefix="galaris_messenger_send_") as directory:
        path = Path(directory) / "source"
        materialized = await materialize_resource(
            ctx,
            uri,
            path,
            max_bytes=runtime_settings.messenger_content_max_bytes,
        )
        display = Path(materialized.name.replace("\\", "/")).name or "file"
        location = await MessengerFileTransport(
            messenger,
            language=ctx.language,
        ).upload_from(path, display, target=str(room_id))

    tool_code = str(getattr(messenger, "tool_code", "") or "").strip()
    if not tool_code:
        raise RuntimeError(
            "The Messenger transport did not expose its Tool code; a provider URI cannot "
            "be produced."
        )
    destination_uri = str(parse_resource_uri(f"{tool_code}://{location}"))
    return DeliveredResource(
        source_uri=materialized.uri,
        uri=destination_uri,
        name=display,
        media_type=materialized.media_type,
        size=materialized.size,
    )


__all__ = ["deliver_resource_to_messenger"]
