"""Resolve budget attribution from persisted, server-owned inference provenance."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from .models import LLMCall
    from .subscription_policy import LLMExecutionAuthority


# Both admission and DbAdmin run this projection. Read only identifiers and
# include archived rows. See docs/fr/dev/llm-attribution.md for the precedence.
_SOURCES = """
, evidence AS (
    SELECT c.*,
           inference.requester_user_id AS inference_user,
           media.task_id AS media_task,
           CASE WHEN pg_input_is_valid(media.authority->>'requester_user_id', 'integer')
                THEN (media.authority->>'requester_user_id')::integer END AS media_user,
           COALESCE(c.source_kind, inference.authority->>'source_kind',
                    media.authority->>'source_kind', receipt.subject_kind, discovery.source_kind) AS kind,
           COALESCE(c.source_ref, inference.authority->>'source_id',
                    media.authority->>'source_id', receipt.subject_id, discovery.source_ref) AS ref
    FROM selected_calls c
    LEFT JOIN llm_inference_attempts attempt ON attempt.id = c.inference_attempt_id
    LEFT JOIN llm_inferences inference ON inference.id = attempt.inference_id
    LEFT JOIN multimedia_generations media ON media.id = c.media_generation_id
    -- A standalone durable API client can set correlation_ref. Its frozen
    -- authority, rather than that label, supplies the attribution evidence.
    LEFT JOIN dream_receipts receipt ON inference.id IS NULL AND c.authenticated_user IS NULL
        AND receipt.id = CASE
            WHEN split_part(c.correlation_ref, ':', 1) = 'dream-receipt'
                 AND pg_input_is_valid(split_part(c.correlation_ref, ':', 2), 'uuid')
            THEN split_part(c.correlation_ref, ':', 2)::uuid END
    LEFT JOIN contact_discovery_jobs discovery ON inference.id IS NULL AND c.authenticated_user IS NULL
        AND discovery.id = CASE
            WHEN split_part(c.correlation_ref, ':', 1) = 'contact-discovery'
                 AND pg_input_is_valid(split_part(c.correlation_ref, ':', 2), 'uuid')
            THEN split_part(c.correlation_ref, ':', 2)::uuid END
), sources AS (
    SELECT evidence.*,
           CASE WHEN pg_input_is_valid(split_part(ref, ':', 1), 'uuid')
                THEN split_part(ref, ':', 1)::uuid END AS subject
    FROM evidence
), attributed AS (
    SELECT c.id, account.id AS user_id
    FROM sources c
    LEFT JOIN lab_evaluation_runs lab ON c.kind = 'lab_run' AND lab.id = c.subject
    LEFT JOIN process_runs run ON run.id = COALESCE(
        c.process_run_id, CASE WHEN c.kind = 'process_projection' THEN c.subject END)
    LEFT JOIN process_runs root_run ON root_run.id = run.root_run_id
    LEFT JOIN tasks task ON task.id = COALESCE(
        lab.requester_task_id, c.task_id, run.task_id, root_run.task_id, c.media_task,
        CASE WHEN c.kind IN ('task', 'task_outcome', 'task_skill_learning') THEN c.subject END)
    LEFT JOIN LATERAL (
        WITH RECURSIVE lineage(id, parent, requester, depth, path) AS (
            SELECT task.id, COALESCE(task.parent_id, task.source_task_id),
                   task.requester_user_id, 0, ARRAY[task.id]
            WHERE task.id IS NOT NULL
            UNION ALL
            SELECT ancestor.id, COALESCE(ancestor.parent_id, ancestor.source_task_id),
                   ancestor.requester_user_id, lineage.depth + 1, lineage.path || ancestor.id
            FROM lineage JOIN tasks ancestor ON ancestor.id = lineage.parent
            WHERE ancestor.id <> ALL(lineage.path)
        )
        SELECT requester FROM lineage
        WHERE requester IS NOT NULL
        ORDER BY (parent IS NULL) DESC, depth ASC
        LIMIT 1
    ) mission ON true
    LEFT JOIN goals goal ON goal.id = task.goal_id
    LEFT JOIN deep_sessions deep ON deep.id = c.deep_session_id
    LEFT JOIN conversation_task_links task_link ON task_link.task_id = task.id
    LEFT JOIN conversation_rounds round ON round.id = COALESCE(
        c.conversation_round_id, task_link.round_id,
        CASE WHEN c.kind = 'conversation_round' THEN c.subject END)
    LEFT JOIN voice_sessions voice ON c.kind = 'voice_session' AND voice.id = c.subject
    LEFT JOIN messenger_messages message ON message.id = COALESCE(
        CASE WHEN c.kind = 'message' THEN c.subject END, task.messenger_message_id)
    JOIN users account ON account.id = CASE
        WHEN lab.created_by IS NOT NULL THEN lab.created_by
        WHEN root_run.requester_user_id IS NOT NULL THEN root_run.requester_user_id
        WHEN run.requester_user_id IS NOT NULL THEN run.requester_user_id
        WHEN mission.requester IS NOT NULL THEN mission.requester
        WHEN goal.requester_user_id IS NOT NULL THEN goal.requester_user_id
        WHEN c.deep_session_id IS NOT NULL THEN deep.requester_user_id
        WHEN round.id IS NOT NULL OR c.kind = 'conversation_round' THEN round.requester_user_id
        WHEN c.kind = 'voice_session' THEN voice.requester_user_id
        WHEN message.id IS NOT NULL OR c.kind = 'message' THEN
            CASE WHEN message.direction = 'inbound' THEN message.requester_user_id END
        WHEN run.id IS NOT NULL OR c.kind IN ('task', 'task_outcome', 'task_skill_learning', 'process_projection')
            THEN NULL
        WHEN split_part(c.correlation_ref, ':', 1) IN ('dream-receipt', 'contact-discovery')
            AND c.authenticated_user IS NULL
            AND (c.kind IS NOT NULL OR c.inference_user IS NULL) THEN NULL
        ELSE COALESCE(c.authenticated_user, c.inference_user, c.requester_user_id, c.media_user)
    END
)
"""

_LIVE_CALL = text("""
WITH selected_calls AS (
    SELECT CAST(NULL AS uuid) AS id, CAST(:task AS uuid) AS task_id,
           CAST(:round AS uuid) AS conversation_round_id, CAST(:process AS uuid) AS process_run_id,
           CAST(:deep AS uuid) AS deep_session_id, CAST(:media AS uuid) AS media_generation_id,
           CAST(:attempt AS uuid) AS inference_attempt_id, CAST(:requester AS integer) AS requester_user_id,
           CAST(:authenticated AS integer) AS authenticated_user, CAST(:correlation AS text) AS correlation_ref,
           CAST(:source_kind AS text) AS source_kind, CAST(:source_ref AS text) AS source_ref
)
""" + _SOURCES + "SELECT user_id FROM attributed")


async def resolve_call_user(
    session: AsyncSession, call: LLMCall, authenticated_user: int | None, authority: LLMExecutionAuthority | None,
) -> int | None:
    return await session.scalar(_LIVE_CALL, {
        "task": call.task_id, "round": call.conversation_round_id, "process": call.process_run_id,
        "deep": call.deep_session_id, "media": call.media_generation_id, "attempt": call.inference_attempt_id,
        "requester": call.requester_user_id, "authenticated": authenticated_user,
        "correlation": call.correlation_ref, "source_kind": authority.source_kind if authority else None,
        "source_ref": authority.source_id if authority else None,
    })


_UNATTRIBUTED = """
    SELECT id, task_id, conversation_round_id, process_run_id, deep_session_id,
           media_generation_id, inference_attempt_id, requester_user_id,
           created_by AS authenticated_user, correlation_ref,
           CAST(NULL AS text) AS source_kind, CAST(NULL AS text) AS source_ref
    FROM llm_calls WHERE user_id IS NULL
"""
_HISTORICAL_CALLS = "WITH selected_calls AS (" + _UNATTRIBUTED + ")\n" + _SOURCES
_BACKFILL_BATCH = text("WITH selected_calls AS (" + _UNATTRIBUTED + """
    AND id = ANY(CAST(:ids AS uuid[]))
)
""" + _SOURCES + """
    UPDATE llm_calls c SET user_id = attributed.user_id FROM attributed
    WHERE c.id = attributed.id AND c.user_id IS NULL
""")

async def backfill_call_users(session: AsyncSession) -> None:
    """Bound each update by a range of call IDs and leave assigned rows unchanged."""
    after: UUID | None = None
    while True:
        query = "SELECT id FROM llm_calls WHERE user_id IS NULL"
        if after is not None:
            query += " AND id > CAST(:after AS uuid)"
        ids = (await session.execute(text(query + " ORDER BY id LIMIT 2000"), {"after": after})).scalars().all()
        if not ids:
            return
        await session.execute(_BACKFILL_BATCH, {"ids": ids})
        after = ids[-1]


async def call_users_backfilled(session: AsyncSession) -> bool:
    return not await session.scalar(text(_HISTORICAL_CALLS + "SELECT EXISTS (SELECT 1 FROM attributed)"))
