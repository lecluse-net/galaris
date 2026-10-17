"""Explicit private policies for synthetic bulk-loaded resource corpora."""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.share import ShareConfig, ShareKind


async def bind_private_shares(
    session: AsyncSession, rows: list[dict[str, object]], *, kind: ShareKind = "memory",
) -> None:
    for row in rows:
        row["share_id"], row["share_kind"] = uuid4(), kind
    if rows:
        await session.execute(ShareConfig.__table__.insert(), [
            {"id": row["share_id"], "resource_kind": kind} for row in rows
        ])
