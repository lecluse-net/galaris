"""Expand current documentary sharing rules into individual beneficiaries."""

from collections.abc import Collection
from typing import Literal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import TextClause

from core.database import get_db, lock_resource_sharing
from core.team import TeamMember


_DOCUMENT_POLICIES = """
        SELECT id FROM share_configs
        WHERE resource_kind = 'document'
          AND (CAST(:share_ids AS uuid[]) IS NULL OR id = ANY(CAST(:share_ids AS uuid[])))
"""
_TEAM_POLICIES = """
        SELECT d.share_id AS id FROM share_grants g JOIN documents d ON d.share_id = g.share_id
        WHERE g.team_id = :team_id
        UNION
        SELECT d.share_id FROM documents d JOIN share_configs c ON c.id = d.share_id
        WHERE c.group_access > 0 AND (
            d.owner_agent_id IN (SELECT agent_id FROM agent_teams WHERE team_id = :team_id)
            OR d.owner_user_id IN (SELECT user_id FROM team_users WHERE team_id = :team_id)
        )
"""
_USER_POLICIES = """
        WITH memberships AS (SELECT team_id FROM team_users WHERE user_id = :member_id)
        SELECT id FROM share_configs WHERE resource_kind = 'document' AND global_access > 0
        UNION
        SELECT share_id FROM documents WHERE owner_user_id = :member_id
        UNION
        SELECT d.share_id FROM documents d JOIN share_grants g USING (share_id)
        WHERE g.user_id = :member_id OR g.team_id IN (SELECT team_id FROM memberships)
        UNION
        SELECT d.share_id FROM documents d JOIN share_configs c ON c.id = d.share_id
        WHERE c.group_access > 0 AND (
            d.owner_agent_id IN (SELECT agent_id FROM agent_teams JOIN memberships USING (team_id))
            OR d.owner_user_id IN (SELECT user_id FROM team_users JOIN memberships USING (team_id))
        )
        UNION
        SELECT e.share_id FROM share_effective_access e JOIN share_configs c ON c.id = e.share_id
        WHERE e.user_id = :member_id AND c.resource_kind = 'document'
"""


def _sync_statement(policies: str, *, beneficiary: Literal["agent_id", "user_id"] | None = None) -> TextClause:
    # Both fragments come exclusively from the fixed statements below. The
    # caller binds identities. Filter source AND target for a member update.
    source_scope = f"c.{beneficiary} = :member_id" if beneficiary else "true"
    target_scope = f"e.{beneficiary} = :member_id" if beneficiary else "true"
    return text(f"""
    WITH policies AS MATERIALIZED (
        {policies}
    ), docs AS MATERIALIZED (
        SELECT d.share_id, d.owner_agent_id, d.owner_user_id, c.global_access, c.group_access
        FROM documents d JOIN policies p ON p.id = d.share_id
        JOIN share_configs c ON c.id = p.id
        WHERE d.deleted_at IS NULL AND c.deleted_at IS NULL
    ), team_rules AS (
        SELECT g.share_id, g.team_id, g.can_write
        FROM share_grants g JOIN docs d USING (share_id) WHERE g.team_id IS NOT NULL
        UNION ALL
        SELECT d.share_id, m.team_id, d.group_access = 2
        FROM docs d JOIN agent_teams m ON m.agent_id = d.owner_agent_id WHERE d.group_access > 0
        UNION ALL
        SELECT d.share_id, m.team_id, d.group_access = 2
        FROM docs d JOIN team_users m ON m.user_id = d.owner_user_id WHERE d.group_access > 0
    ), live_teams AS (
        SELECT r.share_id, r.team_id, bool_or(r.can_write) AS can_write
        FROM team_rules r JOIN agent_groups t ON t.id = r.team_id AND t.deleted_at IS NULL
        GROUP BY r.share_id, r.team_id
    ), contributions(share_id, agent_id, user_id, can_write) AS (
        SELECT share_id, owner_agent_id, NULL::integer, true FROM docs WHERE owner_agent_id IS NOT NULL
        UNION ALL
        SELECT share_id, NULL, owner_user_id, true FROM docs WHERE owner_user_id IS NOT NULL
        UNION ALL
        SELECT g.share_id, g.agent_id, g.user_id, g.can_write
        FROM share_grants g JOIN docs d USING (share_id) WHERE g.team_id IS NULL
        UNION ALL
        SELECT t.share_id, a.agent_id, NULL, t.can_write FROM live_teams t JOIN agent_teams a USING (team_id)
        UNION ALL
        SELECT t.share_id, NULL, u.user_id, t.can_write FROM live_teams t JOIN team_users u USING (team_id)
        UNION ALL
        SELECT d.share_id, a.id, NULL, d.global_access = 2 FROM docs d CROSS JOIN agents a
        WHERE d.global_access > 0 AND a.deleted_at IS NULL
        UNION ALL
        SELECT d.share_id, NULL, u.id, d.global_access = 2 FROM docs d CROSS JOIN users u
        WHERE d.global_access > 0 AND u.is_active
    ), effective AS (
        SELECT c.share_id, c.agent_id, c.user_id, bool_or(c.can_write) AS can_write
        FROM contributions c
        WHERE {source_scope} AND (
            EXISTS (SELECT FROM agents a WHERE a.id = c.agent_id AND a.deleted_at IS NULL)
            OR EXISTS (SELECT FROM users u WHERE u.id = c.user_id AND u.is_active)
        )
        GROUP BY c.share_id, c.agent_id, c.user_id
    ), stored AS (
        SELECT e.* FROM share_effective_access e JOIN policies p ON p.id = e.share_id
        WHERE {target_scope}
    ), delta AS (
        SELECT e.id, s.share_id, s.agent_id, s.user_id, s.can_write
        FROM effective s FULL JOIN stored e
          ON e.share_id = s.share_id AND (e.agent_id IS NULL) = (s.agent_id IS NULL)
           AND coalesce(e.agent_id, e.user_id) = coalesce(s.agent_id, s.user_id)
        WHERE e.can_write IS DISTINCT FROM s.can_write
    )
    MERGE INTO share_effective_access e USING delta s ON e.id = s.id
    WHEN MATCHED AND s.share_id IS NULL THEN DELETE
    WHEN MATCHED THEN UPDATE SET can_write = s.can_write
    WHEN NOT MATCHED BY TARGET THEN INSERT (share_id, agent_id, user_id, can_write)
        VALUES (s.share_id, s.agent_id, s.user_id, s.can_write)
    """)


_SYNC = _sync_statement(_DOCUMENT_POLICIES)
_ARCHIVE_TEAM = _sync_statement(_TEAM_POLICIES)
_ACTIVATE_USER = _sync_statement(_USER_POLICIES, beneficiary="user_id")
_MEMBER_SYNC = {
    "agent": _sync_statement(_TEAM_POLICIES, beneficiary="agent_id"),
    "user": _sync_statement(_TEAM_POLICIES, beneficiary="user_id"),
}


async def project_document_access(session: AsyncSession, share_ids: Collection[UUID] | None = None) -> None:
    """Repair the documentary projection within the caller's sharing transaction."""
    if share_ids is not None and not share_ids:
        return
    if share_ids is None:
        # Serialize a full maintenance rebuild with live ACL edits.
        await lock_resource_sharing(session)
    await session.flush()
    await session.execute(_SYNC, {"share_ids": list(share_ids) if share_ids is not None else None})


async def project_team_access(session: AsyncSession, team_id: int, member: TeamMember | None) -> None:
    """Apply the effective delta for policies referencing the changed team."""
    await session.flush()
    if member is None:
        await session.execute(_ARCHIVE_TEAM, {"team_id": team_id})
        return
    kind, identity = member
    await session.execute(_MEMBER_SYNC[kind], {"team_id": team_id, "member_id": identity})


async def project_user_document_access(user_id: int, active: bool) -> None:
    """Synchronize just this account using its freshly persisted eligibility."""
    db = get_db()
    if active:
        await db.execute(_ACTIVATE_USER, {"member_id": user_id})
    else:
        await db.execute(text("""
            DELETE FROM share_effective_access e USING share_configs c
            WHERE e.user_id = :member_id AND e.share_id = c.id AND c.resource_kind = 'document'
        """), {"member_id": user_id})


async def initialize_agent_document_access(agent_id: int) -> None:
    """A new identity can already have team or owner rows from its initializers."""
    await get_db().execute(text("""
        INSERT INTO share_effective_access AS e (share_id, agent_id, can_write)
        SELECT d.share_id, :agent_id, c.global_access = 2
        FROM documents d JOIN share_configs c ON c.id = d.share_id
        WHERE d.deleted_at IS NULL AND c.deleted_at IS NULL AND c.global_access > 0
        ON CONFLICT (agent_id, share_id) DO UPDATE SET can_write = true
        WHERE excluded.can_write AND NOT e.can_write
    """), {"agent_id": agent_id})
