"""Explicit policies for synthetic bulk-loaded shared resource corpora."""

from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.share import ShareConfig, ShareKind


async def bind_private_shares(
    session: AsyncSession, rows: list[dict[str, object]], *, kind: ShareKind | None = None,
) -> None:
    # Personal memories have ownership, never a ShareConfig. Existing private
    # bulk fixtures therefore need no policy rows or sharing columns.
    if kind is None:
        return
    for row in rows:
        row["share_id"], row["share_kind"] = uuid4(), kind
    if rows:
        await session.execute(ShareConfig.__table__.insert(), [
            {"id": row["share_id"], "resource_kind": kind} for row in rows
        ])
