"""Canonical resource references owned by the Messenger domain."""

from __future__ import annotations

import re
from urllib.parse import quote
from uuid import UUID


_TOOL_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*$")
_INVALID_TOOL_CODES = frozenset(
    {"console", "document", "galaris", "memory", "messenger", "workspace"}
)


def attachment_resource_uri(
    tool_code: str,
    room_locator: str,
    attachment_id: UUID | str,
) -> str:
    """Return one attachment URI governed by the exact connected Tool code.

    The room locator is provider-native so the Tool capability can route it without exposing
    a connection identifier. The attachment keeps its durable local UUID.
    """

    scheme = tool_code.strip()
    room = room_locator.strip()
    if (
        not _TOOL_CODE_PATTERN.fullmatch(scheme)
        or scheme in _INVALID_TOOL_CODES
        or not room
    ):
        raise ValueError(
            "Messenger resource URIs require an exact Tool code and provider room locator."
        )
    try:
        canonical_attachment_id = UUID(str(attachment_id))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Messenger resource URIs require a canonical attachment UUID."
        ) from exc
    encoded_room = quote(room, safe="!$&'()*+,-.;=@_~:")
    return f"{scheme}://{encoded_room}/{canonical_attachment_id}"


__all__ = ["attachment_resource_uri"]
