"""One-time preservation of capabilities when broad grants become domain grants."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import SchemaTransitionSet

from .models import Privilege, Role, RolePrivilege


# Explicitly approved capability mapping. Never applied to roles created after
# the split, nor reapplied after a grant has been deliberately revoked.
DOMAIN_PROJECTION: dict[str, tuple[str, ...]] = {
    "MEMORY_ACCESS": ("CONTACT_ACCESS", "FILE_ACCESS", "FILE_INDEX_ACCESS"),
    "MEMORY_EDIT": ("CONTACT_EDIT", "FILE_EDIT", "FILE_INDEX_RUN"),
    "MEMORY_ADMIN": ("CONTACT_ACCESS",),
    "TASK_ACCESS": (
        "CONVERSATION_ACCESS",
        "VOICE_HISTORY_ACCESS",
        "LLM_CALL_ACCESS",
        "DASHBOARD_ACCESS",
        "DREAM_ACCESS",
    ),
    "TASK_EDIT": (
        "CONVERSATION_CONTROL",
        "VOICE_HISTORY_CONTROL",
        "LLM_CALL_CONTROL",
        "DASHBOARD_ACCESS",
    ),
    "CONNECTION_ACCESS": ("PERMISSION_ACCESS",),
    "CONNECTION_EDIT": ("PERMISSION_ACCESS", "PERMISSION_DECIDE", "PERMISSION_REVOKE"),
    "LLM_PROVIDER_ACCESS": ("LLM_MODEL_ACCESS",),
    "LLM_PROVIDER_EDIT": ("LLM_MODEL_EDIT",),
    "PARAMS_ACCESS": ("LLM_PROFILE_ACCESS", "HARNESS_CONFIG_ACCESS"),
    "PARAMS_EDIT": ("LLM_PROFILE_EDIT", "HARNESS_CONFIG_EDIT", "DREAM_EDIT"),
}


def needs_domain_projection(transitions: SchemaTransitionSet) -> bool:
    return transitions.table_added("roles") or transitions.column_added(
        "roles", "domain_privileges_initialized_at"
    )


async def domain_projection_complete(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> bool:
    return (
        await session.scalar(
            select(Role.id).where(Role.domain_privileges_initialized_at.is_(None)).limit(1)
        )
        is None
    )


async def project_domain_privileges(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> None:
    privileges = {
        code: identifier
        for code, identifier in (await session.execute(select(Privilege.code, Privilege.id))).all()
    }
    targets = {code for values in DOMAIN_PROJECTION.values() for code in values}
    if targets.difference(privileges):
        raise RuntimeError("Domain privilege projection requires the complete target catalogue")
    roles = list(
        await session.scalars(
            select(Role).where(Role.domain_privileges_initialized_at.is_(None)).with_for_update()
        )
    )
    if not roles:
        return
    role_ids = [role.id for role in roles]
    grants = (
        await session.execute(
            select(RolePrivilege.role_id, Privilege.code)
            .join(Privilege, Privilege.id == RolePrivilege.privilege_id)
            .where(RolePrivilege.role_id.in_(role_ids))
        )
    ).all()
    projected = {
        (role_id, privileges[target])
        for role_id, code in grants
        for target in DOMAIN_PROJECTION.get(code, ())
    }
    if projected:
        rows = [
            {"role_id": role_id, "privilege_id": privilege_id}
            for role_id, privilege_id in sorted(projected)
        ]
        for offset in range(0, len(rows), 1000):
            await session.execute(
                insert(RolePrivilege).values(rows[offset : offset + 1000]).on_conflict_do_nothing()
            )
    now = datetime.now(timezone.utc)
    for role in roles:
        role.domain_privileges_initialized_at = now
    await session.flush()
