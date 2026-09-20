"""Persistently route Galaris conversations to Hermes sessions."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, cast
from uuid import uuid4

from loguru import logger
from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import get_db
from core.util import as_dict
from app.agent.contracts import AgentRunRequest
from .models import HermesSessionBinding


@dataclass(frozen=True)
class ConversationScope:
    agent_id: int
    platform: str
    key: str
    hash: str


@dataclass(frozen=True)
class SessionBindingRoute:
    """Exact server-side route discovered by the upgrade composition root."""

    agent_id: int
    platform: str
    room_id: str
    connection_id: int


_INVALID_SESSION_ID = re.compile(r"[\x00-\x1f\x7f]")


def _scope_hash(platform: str, key: str) -> str:
    return hashlib.sha256(f"{platform}\0{key}".encode()).hexdigest()


def _new_session_id() -> str:
    return f"galaris_{uuid4().hex}"


def _validated_session_id(value: object) -> str | None:
    session_id = str(value or "").strip()
    if not session_id or len(session_id) > 256 or _INVALID_SESSION_ID.search(session_id):
        return None
    return session_id


def _was_derived_from_conversation_key(binding: HermesSessionBinding) -> bool:
    """Recognize transcript IDs emitted by the two historical room-ID algorithms."""
    key = binding.conversation_key
    _prefix, separator, legacy_tail = key.partition(":")
    candidates = {key.rsplit(":", 1)[-1]}
    if separator:
        candidates.add(legacy_tail)
    _connection_prefix, room_marker, exact_room_id = key.partition(":room:")
    if room_marker:
        candidates.add(exact_room_id)
    return binding.session_id in candidates


def conversation_scope(task: AgentRunRequest) -> ConversationScope | None:
    """Build the persistent logical key for a conversation.

    Messaging is naturally keyed by room. For the OpenAI API, ``conversation_id``
    serves the same purpose. A background task with neither key gets an isolated
    Hermes session.
    """
    platform = (task.message_platform or "task").strip() or "task"
    if task.message_group_id:
        # Tasks and external callers created before the multi-channel contract do not carry
        # this server-only field. Their legacy room scope remains stable during the transition.
        connection = int(getattr(task, "messenger_connection_id", None) or 0)
        key = (
            f"connection:{connection}:room:{task.message_group_id}"
            if connection
            else f"room:{task.message_group_id}"
        )
    else:
        data: dict[str, Any] = task.data if isinstance(task.data, dict) else {}
        conversation_id = data.get("conversation_id")
        if not conversation_id:
            return None
        key = f"conversation:{conversation_id}"

    digest = _scope_hash(platform, key)
    return ConversationScope(task.agent_id, platform, key, digest)


def _initial_session_id(scope: ConversationScope) -> str:
    """Return an opaque transcript ID independent from external room identifiers."""
    del scope
    return _new_session_id()


def stable_session_key(task: AgentRunRequest) -> str:
    """Return the stable, non-reversible Hermes channel key for a task."""
    scope = conversation_scope(task)
    logical_key = (
        f"{scope.agent_id}\0{scope.hash}"
        if scope is not None
        else f"{task.agent_id}\0task\0{task.id}"
    )
    return f"galaris_key_{hashlib.sha256(logical_key.encode()).hexdigest()}"


def effective_session_id(current_id: str, event_name: str, data: Any) -> str:
    """Extract the Hermes tip only from reliable terminal events."""
    if event_name not in {"assistant.completed", "run.completed"} or not isinstance(data, dict):
        return current_id
    returned = _validated_session_id(as_dict(data).get("session_id"))
    return returned or current_id


def _legacy_room_scope(scope: ConversationScope) -> ConversationScope | None:
    """Return the pre-multichannel room scope corresponding to ``scope``."""
    if not scope.key.startswith("connection:"):
        return None
    _prefix, marker, room_id = scope.key.partition(":room:")
    if not marker or not room_id:
        return None
    key = f"room:{room_id}"
    return ConversationScope(
        agent_id=scope.agent_id,
        platform=scope.platform,
        key=key,
        hash=_scope_hash(scope.platform, key),
    )


async def _claim_legacy_binding(scope: ConversationScope) -> str | None:
    """Move one legacy room binding to an exact connection-aware scope.

    Locking and updating the legacy row means that only one connection can inherit its
    transcript. If an old transcript ID was already shared by several logical scopes, the
    claimed row receives a fresh opaque ID and canonical Galaris history repopulates context.
    """
    legacy_scope = _legacy_room_scope(scope)
    if legacy_scope is None:
        return None

    db = get_db()
    legacy = (
        await db.execute(
            select(HermesSessionBinding)
            .where(
                HermesSessionBinding.agent_id == scope.agent_id,
                HermesSessionBinding.scope_hash == legacy_scope.hash,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if legacy is None:
        return None

    exact = await db.scalar(
        select(HermesSessionBinding.session_id).where(
            HermesSessionBinding.agent_id == scope.agent_id,
            HermesSessionBinding.scope_hash == scope.hash,
        )
    )
    if exact is not None:
        return str(exact)

    shared_count = await db.scalar(
        select(func.count(HermesSessionBinding.id)).where(
            HermesSessionBinding.agent_id == scope.agent_id,
            HermesSessionBinding.session_id == legacy.session_id,
        )
    )
    inherited = _validated_session_id(legacy.session_id)
    can_inherit = (
        inherited is not None
        and int(shared_count or 0) == 1
        and not _was_derived_from_conversation_key(legacy)
    )
    legacy.scope_hash = scope.hash
    legacy.message_platform = scope.platform
    legacy.conversation_key = scope.key
    legacy.session_id = cast(str, inherited) if can_inherit else _new_session_id()
    legacy.updated_at = func.now()
    await db.commit()
    logger.info(
        "Hermes legacy session binding migrated to a connection-aware scope: "
        "agent={} platform={} preserved_transcript={}",
        scope.agent_id,
        scope.platform,
        can_inherit,
    )
    return legacy.session_id


async def get_or_create_session_id(task: AgentRunRequest) -> str:
    """Return the active session, atomically creating its binding when needed."""
    scope = conversation_scope(task)
    if scope is None:
        digest = hashlib.sha256(f"{task.agent_id}\0{task.id}".encode()).hexdigest()
        return f"galaris_task_{digest[:32]}"

    db = get_db()
    existing = await db.scalar(
        select(HermesSessionBinding.session_id).where(
            HermesSessionBinding.agent_id == scope.agent_id,
            HermesSessionBinding.scope_hash == scope.hash,
        )
    )
    if existing is not None:
        return str(existing)

    migrated = await _claim_legacy_binding(scope)
    if migrated is not None:
        return migrated

    candidate = _initial_session_id(scope)
    stmt = (
        pg_insert(HermesSessionBinding)
        .values(
            agent_id=scope.agent_id,
            scope_hash=scope.hash,
            message_platform=scope.platform,
            conversation_key=scope.key,
            session_id=candidate,
        )
        .on_conflict_do_nothing(
            index_elements=[HermesSessionBinding.agent_id, HermesSessionBinding.scope_hash]
        )
        .returning(HermesSessionBinding.session_id)
    )
    inserted = (await db.execute(stmt)).scalar_one_or_none()
    if inserted:
        await db.commit()
        return str(inserted)

    existing = await db.scalar(
        select(HermesSessionBinding.session_id).where(
            HermesSessionBinding.agent_id == scope.agent_id,
            HermesSessionBinding.scope_hash == scope.hash,
        )
    )
    if existing is None:
        # This should only happen when the binding is deleted concurrently.
        # A retry recreates the row cleanly without maintaining a local cache.
        return await get_or_create_session_id(task)
    return str(existing)


def _canonical_legacy_platform(platform: str) -> str:
    normalized = platform.strip().lower().replace("-", "_")
    if normalized in {"nextcloud", "talk"}:
        return "nextcloud_talk"
    if normalized == "onebot":
        return "one_bot"
    if normalized == "messenger":
        from core.params import runtime_settings

        configured = str(runtime_settings.MESSENGER_DRIVER or "").strip()
        return configured or normalized
    return normalized or platform


def _canonical_legacy_conversation_key(platform: str, key: str) -> str:
    """Apply bridge-specific room namespace expansions to a stored logical key."""
    if platform != "one_bot":
        return key
    if key.startswith("room:"):
        room_id = key.removeprefix("room:")
        if room_id and not room_id.startswith(("group:", "direct:")):
            return f"room:group:{room_id}"
        return key
    prefix, marker, room_id = key.partition(":room:")
    if marker and room_id and not room_id.startswith(("group:", "direct:")):
        return f"{prefix}:room:group:{room_id}"
    return key


async def migrate_legacy_bindings(
    routes: tuple[SessionBindingRoute, ...] = (),
) -> int:
    """Normalize legacy scopes and eliminate shared transcript pointers idempotently."""
    db = get_db()
    bindings = list(
        (
            await db.execute(
                select(HermesSessionBinding).order_by(
                    HermesSessionBinding.agent_id,
                    HermesSessionBinding.id,
                )
            )
        ).scalars().all()
    )
    derived_binding_ids = {
        binding.id
        for binding in bindings
        if _was_derived_from_conversation_key(binding)
    }
    route_connections: dict[tuple[int, str, str], set[int]] = {}
    for route in routes:
        route_connections.setdefault(
            (
                route.agent_id,
                _canonical_legacy_platform(route.platform),
                route.room_id,
            ),
            set(),
        ).add(route.connection_id)
    changed = 0
    deduplicated_scope_conflicts = 0
    retained_bindings: list[HermesSessionBinding] = []
    for binding in bindings:
        platform = _canonical_legacy_platform(binding.message_platform)
        conversation_key = _canonical_legacy_conversation_key(
            platform, binding.conversation_key
        )
        if conversation_key.startswith("room:"):
            room_id = conversation_key.removeprefix("room:")
            candidates = route_connections.get(
                (binding.agent_id, platform, room_id), set()
            )
            if len(candidates) == 1:
                connection_id = next(iter(candidates))
                conversation_key = f"connection:{connection_id}:room:{room_id}"
        scope_hash = _scope_hash(platform, conversation_key)
        if (
            platform == binding.message_platform
            and conversation_key == binding.conversation_key
            and scope_hash == binding.scope_hash
        ):
            retained_bindings.append(binding)
            continue
        conflict = await db.scalar(
            select(HermesSessionBinding.id).where(
                HermesSessionBinding.agent_id == binding.agent_id,
                HermesSessionBinding.scope_hash == scope_hash,
                HermesSessionBinding.id != binding.id,
            )
        )
        if conflict is not None:
            # The target hash already identifies the binding used by the canonical
            # runtime scope. Keeping the stale alias would leave two pointers for the
            # same logical conversation, so retain the canonical row deterministically.
            await db.delete(binding)
            deduplicated_scope_conflicts += 1
            changed += 1
            continue
        binding.message_platform = platform
        binding.conversation_key = conversation_key
        binding.scope_hash = scope_hash
        binding.updated_at = func.now()
        changed += 1
        retained_bindings.append(binding)

    await db.flush()
    seen_transcripts: set[tuple[int, str]] = set()
    for binding in retained_bindings:
        session_id = _validated_session_id(binding.session_id)
        key = (binding.agent_id, session_id or "")
        if (
            session_id is None
            or key in seen_transcripts
            or binding.id in derived_binding_ids
        ):
            binding.session_id = _new_session_id()
            binding.updated_at = func.now()
            changed += 1
            continue
        seen_transcripts.add(key)

    await db.commit()
    if changed or deduplicated_scope_conflicts:
        logger.info(
            "Hermes session binding upgrade complete: changed={} deduplicated_scope_conflicts={}",
            changed,
            deduplicated_scope_conflicts,
        )
    return changed


async def follow_rotation(
    task: AgentRunRequest,
    previous_id: str,
    effective_id: str,
) -> bool:
    """Advance the pointer to the ID returned by Hermes.

    Comparing against ``previous_id`` prevents an older concurrent request from moving
    the pointer backwards after a recorded rotation.
    """
    scope = conversation_scope(task)
    validated_effective_id = _validated_session_id(effective_id)
    if (
        scope is None
        or validated_effective_id is None
        or validated_effective_id == previous_id
    ):
        return False

    db = get_db()
    conflict = await db.scalar(
        select(HermesSessionBinding.id).where(
            HermesSessionBinding.agent_id == scope.agent_id,
            HermesSessionBinding.session_id == validated_effective_id,
            HermesSessionBinding.scope_hash != scope.hash,
        )
    )
    if conflict is not None:
        logger.error(
            "Hermes session rotation rejected because the returned transcript is already "
            "bound to another scope: agent={} platform={}",
            scope.agent_id,
            scope.platform,
        )
        return False
    result = await db.execute(
        update(HermesSessionBinding)
        .where(
            HermesSessionBinding.agent_id == scope.agent_id,
            HermesSessionBinding.scope_hash == scope.hash,
            HermesSessionBinding.session_id == previous_id,
        )
        .values(session_id=validated_effective_id, updated_at=func.now())
    )
    changed = bool(cast(CursorResult[Any], result).rowcount)
    await db.commit()
    if changed:
        logger.info(
            "Hermes session rotation tracked: agent={} platform={}",
            scope.agent_id,
            scope.platform,
        )
    else:
        logger.warning(
            "Hermes session rotation ignored because the pointer already advanced: "
            "agent={} platform={}",
            scope.agent_id,
            scope.platform,
        )
    return changed
