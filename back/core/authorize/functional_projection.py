"""One-time preservation of explicit capabilities for the functional split."""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import SchemaTransitionSet
from core.params import PARAMETER_DOMAINS
from .domain_projection import project_domain_privileges
from .models import Privilege, Role, RolePrivilege


FUNCTIONAL_PROJECTION: dict[str, tuple[str, ...]] = {
    # The earlier split already owned Harness/Profile/Dream writers. Repeating
    # those grants here would undo revocations made between the two upgrades.
    "PARAMS_ACCESS": tuple(dict.fromkeys(pair[0] for name, pair in PARAMETER_DOMAINS.items()
        if name not in {"system", "harnesses", "profiles"})),
    "PARAMS_EDIT": tuple(dict.fromkeys(pair[1] for name, pair in PARAMETER_DOMAINS.items()
        if name not in {"system", "harnesses", "profiles", "dream"})),
    "DREAM_ACCESS": ("DREAM_CONFIG_ACCESS",),
    "CONNECTION_ACCESS": ("MAIL_ACCESS", "CALENDAR_ACCESS"),
    "CONNECTION_EDIT": ("MAIL_EDIT", "CALENDAR_EDIT"),
    "GOAL_ACCESS": ("GOAL_CONFIG_ACCESS",),
    "GOAL_EDIT": ("GOAL_CONFIG_EDIT",),
}


def needs_functional_projection(transitions: SchemaTransitionSet) -> bool:
    return transitions.table_added("roles") or transitions.column_added("roles", "functional_isolation_initialized_at")


async def functional_projection_complete(session: AsyncSession, _transitions: SchemaTransitionSet) -> bool:
    return await session.scalar(select(Role.id).where(Role.functional_isolation_initialized_at.is_(None)).limit(1)) is None


async def project_functional_privileges(session: AsyncSession, transitions: SchemaTransitionSet) -> None:
    # Handles upgrades that cross both splits, regardless of action ordering.
    await project_domain_privileges(session, transitions)
    codes = {code: identity for code, identity in (await session.execute(select(Privilege.code, Privilege.id))).all()}
    required = {code for targets in FUNCTIONAL_PROJECTION.values() for code in targets}
    if required.difference(codes):
        raise RuntimeError("Functional projection requires the complete catalogue")
    pending = list(await session.scalars(select(Role).where(Role.functional_isolation_initialized_at.is_(None)).with_for_update()))
    if not pending:
        return
    grants = (await session.execute(select(RolePrivilege.role_id, Privilege.code)
        .join(Privilege, Privilege.id == RolePrivilege.privilege_id)
        .where(RolePrivilege.role_id.in_([role.id for role in pending])))).all()
    rows = sorted({(role_id, codes[target]) for role_id, source in grants for target in FUNCTIONAL_PROJECTION.get(source, ())})
    for offset in range(0, len(rows), 1000):
        await session.execute(insert(RolePrivilege).values([
            {"role_id": role_id, "privilege_id": privilege_id} for role_id, privilege_id in rows[offset:offset + 1000]
        ]).on_conflict_do_nothing())
    now = datetime.now(timezone.utc)
    for role in pending:
        role.functional_isolation_initialized_at = now
    await session.flush()
