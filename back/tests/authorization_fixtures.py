"""Explicit functional grants for synthetic actors in integration journeys."""

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.authorize import Assignment, Privilege, Role


async def grant_privileges(db: AsyncSession, user_id: int, *codes: str) -> None:
    privileges = list(await db.scalars(select(Privilege).where(Privilege.code.in_(codes))))
    assert {privilege.code for privilege in privileges} == set(codes)
    role = Role(code=f"synthetic-grants-{uuid4().hex}", privileges=privileges)
    db.add(role)
    await db.flush()
    db.add(Assignment(user_id=user_id, role_id=role.id))
    await db.flush()
