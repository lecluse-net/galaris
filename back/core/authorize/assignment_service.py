"""Transactional role assignment operations."""

from collections.abc import Sequence

from sqlalchemy import select

from core.database import get_db
from core.i18n import tr

from .models import Assignment, Role


async def assign_initial_roles(
    user_id: int, role_ids: Sequence[int], default_role_id: int | None,
) -> None:
    db = get_db()
    roles = set(await db.scalars(
        select(Role.id).where(Role.id.in_(role_ids)).with_for_update(read=True, key_share=True)
    ))
    if roles != set(role_ids):
        raise LookupError(await tr("authorize_api.errors.role_not_found"))
    db.add_all([
        Assignment(user_id=user_id, role_id=role_id, is_default=role_id == default_role_id)
        for role_id in dict.fromkeys(role_ids)
    ])


async def set_default_assignment(target: Assignment) -> None:
    from core.user import UserModel

    db = get_db()
    user_id = target.user_id
    # Serialize default changes per account, including inserts that request a default.
    with db.no_autoflush:
        await db.scalar(select(UserModel.id).where(UserModel.id == user_id).with_for_update(key_share=True))
    assignments = list(await db.scalars(
        select(Assignment).where(Assignment.user_id == user_id).with_for_update()
        .execution_options(populate_existing=True)
    ))
    if target not in assignments:
        raise LookupError(await tr("authorize_api.errors.assignment_not_found"))
    for assignment in assignments:
        assignment.is_default = assignment.id == target.id
