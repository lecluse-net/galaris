from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from loguru import logger

from core.user.models import User
from .models import Assignment, Privilege, RolePrivilege
from .cache import cached_privileges
from .context import role_id_ctx


async def check_privilege(
    user: User | None,
    privilege_code: str | list[str],
    db: AsyncSession,
    role_id: int | None = None,
) -> bool:
    """Check OR privileges for the active role, or all assignments without a role.

    Active users have the special ``user`` privilege; anonymous callers have
    ``guest``. HTTP callers share role codes within the request, invalidated on
    database mutations and transaction boundaries. Other callers always query.
    """
    requested = {privilege_code} if isinstance(privilege_code, str) else set(privilege_code)
    if not requested:
        return False
    if user is None:
        return "guest" in requested
    if not user.is_active:
        return False
    if "user" in requested:
        return True

    effective_role = role_id if role_id is not None else role_id_ctx.get()
    key = (user.id, effective_role)
    cache = cached_privileges(db.sync_session)
    effective = cache.get(key) if cache is not None else None
    if effective is None:
        # Fetch immutable codes directly, avoiding repeated ORM relationship
        # loading and stale identity-map collections after a role mutation.
        statement = (
            select(Privilege.code)
            .join(RolePrivilege, RolePrivilege.privilege_id == Privilege.id)
            .join(Assignment, Assignment.role_id == RolePrivilege.role_id)
            .where(Assignment.user_id == user.id, Assignment.deleted_at.is_(None))
        )
        if effective_role is not None:
            statement = statement.where(Assignment.role_id == effective_role)
        effective = frozenset(await db.scalars(statement))
        # The SELECT may have autoflushed, which invalidates the earlier cache.
        cache = cached_privileges(db.sync_session)
        if cache is not None:
            cache[key] = effective

    allowed = not requested.isdisjoint(effective)
    if not allowed:
        logger.debug("User {} denied access to {}", user.id, privilege_code)
    return allowed
