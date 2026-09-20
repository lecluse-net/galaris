"""Preserve a usable administrator while accounts and assignments change."""

from sqlalchemy import func, select

from core.database import get_db
from core.i18n import tr

from .models import Assignment, Role
from .update_admin_role import ADMIN_ROLE_CODE


class AdministratorConflictError(ValueError):
    """The requested change would remove administrative access."""


async def preserve_administrator(
    *, user_id: int | None = None, assignment_id: int | None = None,
) -> None:
    from core.user import UserModel

    db = get_db()
    # Shared by account deactivation/deletion and role-assignment removal.
    await db.execute(select(func.pg_advisory_xact_lock(20_042_655_670_612)))
    admins = list((await db.execute(
        select(Assignment.id, Assignment.user_id)
        .join(Role, Role.id == Assignment.role_id)
        .join(UserModel, UserModel.id == Assignment.user_id)
        .where(Role.code == ADMIN_ROLE_CODE, UserModel.is_active.is_(True), Assignment.deleted_at.is_(None))
    )).all())
    affected = any(row.user_id == user_id or row.id == assignment_id for row in admins)
    remaining = any(row.user_id != user_id and row.id != assignment_id for row in admins)
    if affected and not remaining:
        raise AdministratorConflictError(await tr("user_api.errors.last_administrator"))


async def preserve_admin_role(role: Role) -> None:
    if role.code == ADMIN_ROLE_CODE:
        raise AdministratorConflictError(await tr("user_api.errors.protected_admin_role"))
