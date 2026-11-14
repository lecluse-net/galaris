"""Reusable runtime consent; Galaris keeps control of every individual dispatch."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select, update

from app.agent import AgentManagementScope, authorization_policy, configured_harness_selection, get_agent_record
from core.database import get_db

from .authorization_models import ActionAuthorization, RuntimeActionPermission


async def configuration_fingerprint(agent_id: int, runtime: str) -> str | None:
    if runtime == "internal":
        return None
    from .authorization import fingerprint
    from .runtime_authorization import runtime_authorization_configuration
    agent = await get_agent_record(agent_id)
    target = await configured_harness_selection(agent) if agent else None
    if (target is None or target.provider_code != runtime or target.status != "ready"
            or target.metadata.get("authorization_enabled") is not True):
        return None
    return fingerprint({"target": str(target.id), "revision": target.revision,
        "configuration": await runtime_authorization_configuration(agent_id, runtime)})


async def matching_permission(agent_id: int, runtime: str, name: str,
                              configuration: str | None) -> RuntimeActionPermission | None:
    if configuration is None:
        return None
    policy = await authorization_policy(agent_id)
    return await get_db().scalar(select(RuntimeActionPermission).where(
        RuntimeActionPermission.agent_id == agent_id, RuntimeActionPermission.runtime == runtime,
        RuntimeActionPermission.capability_name == name, RuntimeActionPermission.revoked_at.is_(None),
        RuntimeActionPermission.configuration_fingerprint == configuration,
        RuntimeActionPermission.approver_user_id == policy.manager_user_id,
        RuntimeActionPermission.policy_version == policy.version,
    ).order_by(RuntimeActionPermission.created_at.desc()).limit(1))


async def permission_still_valid(row: ActionAuthorization) -> bool:
    if row.runtime_permission_id is None:
        return True
    configuration = await configuration_fingerprint(row.agent_id, row.runtime)
    permission = await matching_permission(row.agent_id, row.runtime, row.capability_name, configuration)
    return permission is not None and permission.allowed and permission.id == row.runtime_permission_id


async def remember_permission(row: ActionAuthorization, *, allowed: bool) -> None:
    """Caller holds the agent policy lock and has validated the human and snapshot."""
    db = get_db()
    assert row.remember_configuration_fingerprint is not None
    await db.execute(update(RuntimeActionPermission).where(
        RuntimeActionPermission.agent_id == row.agent_id, RuntimeActionPermission.runtime == row.runtime,
        RuntimeActionPermission.capability_name == row.capability_name,
        RuntimeActionPermission.revoked_at.is_(None),
    ).values(revoked_at=datetime.now(timezone.utc)))
    permission = RuntimeActionPermission(agent_id=row.agent_id, approver_user_id=row.approver_user_id,
        runtime=row.runtime, capability_name=row.capability_name, allowed=allowed,
        configuration_fingerprint=row.remember_configuration_fingerprint,
        policy_version=row.policy_version)
    db.add(permission)
    await db.flush()
    row.runtime_permission_id = permission.id


async def revoke_permission(identifier: UUID, *, user_id: int) -> bool:
    db = get_db()
    agent_id = await db.scalar(select(RuntimeActionPermission.agent_id).where(RuntimeActionPermission.id == identifier))
    if agent_id is None:
        return False
    try:
        policy = await authorization_policy(agent_id, lock=True)
    except PermissionError:
        policy = None
    row = await db.get(RuntimeActionPermission, identifier, populate_existing=True)
    if row is None or (user_id != row.approver_user_id and (policy is None or user_id != policy.manager_user_id)):
        return False
    now = datetime.now(timezone.utc)
    row.revoked_at = row.revoked_at or now
    await db.execute(update(ActionAuthorization).where(
        ActionAuthorization.runtime_permission_id == identifier,
        ActionAuthorization.status.in_(("pending", "approved")),
    ).values(status="invalidated", encrypted_arguments=None, notification_due_at=None,
        wake_due_at=now, finished_at=now))
    await db.commit()
    return True


async def list_permissions(scope: AgentManagementScope, *, agent_id: int | None,
                           offset: int, limit: int) -> dict[str, object]:
    db = get_db()
    query = select(RuntimeActionPermission).where(RuntimeActionPermission.revoked_at.is_(None))
    if scope.agent_ids is not None:
        query = query.where(or_(RuntimeActionPermission.agent_id.in_(scope.agent_ids),
            RuntimeActionPermission.approver_user_id == scope.user_id))
    if agent_id is not None:
        query = query.where(RuntimeActionPermission.agent_id == agent_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (await db.scalars(query.order_by(RuntimeActionPermission.created_at.desc())
        .offset(offset).limit(limit))).all()
    items: list[dict[str, object]] = []
    configurations: dict[tuple[int, str], str | None] = {}
    policies: dict[int, tuple[int, int] | None] = {}
    for row in rows:
        key = (row.agent_id, row.runtime)
        if row.agent_id not in policies:
            try:
                policy = await authorization_policy(row.agent_id)
                policies[row.agent_id] = (policy.manager_user_id, policy.version)
            except PermissionError:
                policies[row.agent_id] = None
        if key not in configurations:
            try:
                configurations[key] = await configuration_fingerprint(*key)
            except (PermissionError, ValueError, LookupError):
                configurations[key] = None
        identity = policies[row.agent_id]
        active = (identity == (row.approver_user_id, row.policy_version)
            and configurations[key] == row.configuration_fingerprint)
        items.append({"id": str(row.id), "agent_id": row.agent_id, "runtime": row.runtime,
            "capability_name": row.capability_name, "allowed": row.allowed, "created_at": row.created_at, "active": active,
            "can_revoke": scope.user_id == row.approver_user_id or (identity is not None and scope.user_id == identity[0])})
    return {"items": items, "total": total or 0}


async def list_policies(scope: AgentManagementScope, agent_id: int) -> list[dict[str, object]]:
    """Known action types include observed requests without a permanent decision."""
    if not scope.allows(agent_id):
        raise LookupError("Agent not found")
    observed = {(runtime, name) for runtime, name in (await get_db().execute(select(ActionAuthorization.runtime, ActionAuthorization.capability_name).where(
        ActionAuthorization.agent_id == agent_id, ActionAuthorization.source == "runtime",
        ActionAuthorization.capability_kind == "tool", ActionAuthorization.connection_id.is_(None),
        ActionAuthorization.runtime != "internal",
    ).distinct())).all()}
    permissions = (await get_db().scalars(select(RuntimeActionPermission).where(
        RuntimeActionPermission.agent_id == agent_id, RuntimeActionPermission.revoked_at.is_(None)))).all()
    policy = await authorization_policy(agent_id)
    current = {(row.runtime, row.capability_name): row for row in permissions}
    keys = observed | set(current)
    configurations = {runtime: await configuration_fingerprint(agent_id, runtime) for runtime, _ in keys}
    result: list[dict[str, object]] = []
    for runtime, name in sorted(keys):
        row = current.get((runtime, name))
        active = bool(row and configurations[runtime] == row.configuration_fingerprint
            and row.approver_user_id == policy.manager_user_id and row.policy_version == policy.version)
        ready = configurations[runtime] is not None
        result.append({"id": str(row.id) if row else f"{runtime}:{name}", "agent_id": agent_id,
            "runtime": runtime, "capability_name": name, "allowed": row.allowed if row and active else None,
            "remembered_allowed": row.allowed if row else None, "active": active, "remembered": row is not None,
            "can_decide": ready and scope.user_id == policy.manager_user_id,
            "can_revoke": bool(row and scope.user_id in (row.approver_user_id, policy.manager_user_id))})
    return result


async def set_policy(agent_id: int, runtime: str, name: str, *, allowed: bool | None, user_id: int) -> bool:
    db = get_db()
    policy = await authorization_policy(agent_id, lock=True)
    if policy.manager_user_id != user_id:
        return False
    configuration = await configuration_fingerprint(agent_id, runtime)
    if allowed is not None and configuration is None:
        return False
    old = await db.scalar(select(RuntimeActionPermission).where(RuntimeActionPermission.agent_id == agent_id,
        RuntimeActionPermission.runtime == runtime, RuntimeActionPermission.capability_name == name,
        RuntimeActionPermission.revoked_at.is_(None)).with_for_update())
    known = old is not None or await db.scalar(select(ActionAuthorization.id).where(
        ActionAuthorization.agent_id == agent_id, ActionAuthorization.runtime == runtime,
        ActionAuthorization.capability_name == name, ActionAuthorization.source == "runtime",
        ActionAuthorization.capability_kind == "tool", ActionAuthorization.connection_id.is_(None)).limit(1)) is not None
    if not known:
        return False
    now = datetime.now(timezone.utc)
    if old is not None:
        old.revoked_at = now
        await db.execute(update(ActionAuthorization).where(ActionAuthorization.runtime_permission_id == old.id,
            ActionAuthorization.status.in_(("pending", "approved"))).values(status="invalidated", encrypted_arguments=None,
                notification_due_at=None, finished_at=now, wake_due_at=now))
        await db.flush()
    if allowed is not None and configuration is not None:
        db.add(RuntimeActionPermission(agent_id=agent_id, approver_user_id=user_id, runtime=runtime,
            capability_name=name, allowed=allowed, configuration_fingerprint=configuration, policy_version=policy.version))
    await db.commit()
    return True
