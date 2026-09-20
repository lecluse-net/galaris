"""Prevent duplicate agent replies across messaging tools and executor final delivery.

Hermes may send through an MCP messaging tool before its executor attempts final delivery. This
short-lived in-process registry tracks sends by task and room, with an agent fallback outside a
task. Task scoping prevents concurrent runs in the same room from suppressing each other.
"""

from __future__ import annotations

import hashlib
import time
from typing import Dict, List, Optional, Tuple
from uuid import UUID

# Lifetime of a recent send, in seconds.
_TTL = 300.0

# ``(scope, connection_id, room_id)`` maps to recent text hashes. Room IDs are
# opaque only within one provider connection and may collide across platforms.
_sends: Dict[Tuple[str, str, str], List[Tuple[float, str]]] = {}


def _key(
    agent_id: Optional[int],
    room_id: Optional[str],
    task_id: UUID | str | None = None,
    connection_id: int | None = None,
) -> Optional[Tuple[str, str, str]]:
    if not room_id or (task_id is None and agent_id is None):
        return None
    scope = f"task:{task_id}" if task_id is not None else f"agent:{int(agent_id or 0)}"
    return (scope, str(connection_id or 0), str(room_id))


def _hash(text: str) -> str:
    return hashlib.sha1((text or "").strip().encode("utf-8")).hexdigest()


def _prune(entries: List[Tuple[float, str]]) -> List[Tuple[float, str]]:
    now = time.monotonic()
    return [(ts, h) for ts, h in entries if now - ts < _TTL]


def clear_room(
    agent_id: Optional[int],
    room_id: Optional[str],
    *,
    task_id: UUID | str | None = None,
    connection_id: int | None = None,
) -> None:
    """Clear one execution's state without affecting concurrent tasks."""
    key = _key(agent_id, room_id, task_id, connection_id)
    if key is not None:
        _sends.pop(key, None)


def note_reply(
    agent_id: Optional[int],
    room_id: Optional[str],
    text: str = "",
    *,
    task_id: UUID | str | None = None,
    connection_id: int | None = None,
) -> None:
    """Record that the agent sent a reply in a room."""
    key = _key(agent_id, room_id, task_id, connection_id)
    if key is None:
        return
    entries = _prune(_sends.get(key, []))
    entries.append((time.monotonic(), _hash(text)))
    _sends[key] = entries


def replied_recently(
    agent_id: Optional[int],
    room_id: Optional[str],
    *,
    task_id: UUID | str | None = None,
    connection_id: int | None = None,
) -> bool:
    """Return whether a reply was recently sent in the room."""
    key = _key(agent_id, room_id, task_id, connection_id)
    if key is None:
        return False
    entries = _prune(_sends.get(key, []))
    _sends[key] = entries
    return bool(entries)


def text_already_sent(
    agent_id: Optional[int],
    room_id: Optional[str],
    text: str,
    *,
    task_id: UUID | str | None = None,
    connection_id: int | None = None,
) -> bool:
    """Return whether the exact text was recently sent in the room."""
    key = _key(agent_id, room_id, task_id, connection_id)
    if key is None:
        return False
    entries = _prune(_sends.get(key, []))
    _sends[key] = entries
    return _hash(text) in {h for _, h in entries}
