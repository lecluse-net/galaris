"""Cross-layer DbAdmin composition that must not live inside ``core``."""

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.connection.models import Connection
from app.messenger.models import Message
from app.task.models import Task
from bridge.hermes.config_service import (
    backfill_legacy_configs,
    encrypt_persisted_data_env,
)
from bridge.hermes.session_binding import SessionBindingRoute, migrate_legacy_bindings
from core.dbadmin import (
    DbAdminAction,
    DbAdminPhase,
    DbAdminReconciler,
    DbAdminRegistry,
    SchemaTransitionSet,
)


def _adds_durable_messenger_task_key(transitions: SchemaTransitionSet) -> bool:
    return transitions.column_added("tasks", "messenger_message_id")


async def _backfill_messenger_admissions(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> None:
    """Close the legacy admission cutover before any listener can start.

    Older releases persisted inbound messages as ``received`` even after their business effect
    completed. They must be treated as admitted at the schema cutover; replaying them is less safe
    than accepting the historical receipt because the old workflow had no durable effect key.
    UUID-shaped Task snapshots are also linked to one canonical message, preferring the oldest
    Task when historical duplicates exist.
    """

    # Repair the rollout incident before listeners start. A Task or conversation round created
    # more than one hour after its canonical input is not a delayed worker attempt: admission is
    # synchronous, so this gap proves that a provider history item was replayed as new work. Keep
    # terminal outcomes for audit, but quarantine unfinished effects and their live attempts.
    await session.execute(
        text("DROP TABLE IF EXISTS pg_temp.galaris_replayed_task_ids")
    )
    await session.execute(
        text("DROP TABLE IF EXISTS pg_temp.galaris_replayed_round_ids")
    )
    await session.execute(
        text(
            """
            CREATE TEMP TABLE galaris_replayed_round_ids ON COMMIT DROP AS
            SELECT DISTINCT round_.id
              FROM conversation_rounds AS round_
              JOIN conversation_round_messages AS membership
                ON membership.round_id = round_.id
               AND membership.role = 'input'
              JOIN messenger_messages AS message
                ON message.id = membership.message_id
             WHERE round_.status IN ('FROZEN', 'CLAIMED', 'RUNNING')
               AND round_.created_at > message.created_at + interval '1 hour'
            """
        )
    )
    await session.execute(
        text(
            """
            CREATE TEMP TABLE galaris_replayed_task_ids ON COMMIT DROP AS
            SELECT DISTINCT task.id
              FROM tasks AS task
              JOIN messenger_messages AS message
                ON (task.data ->> 'message_id')
                   ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
               AND message.id = (task.data ->> 'message_id')::uuid
             WHERE task.status IN ('CREATE', 'PAUSE', 'DISPATCH', 'BRIEFING', 'EXEC', 'PLAN')
               AND task.created_at > message.created_at + interval '1 hour'
            UNION
            SELECT link.task_id
              FROM conversation_task_links AS link
              JOIN galaris_replayed_round_ids AS replayed ON replayed.id = link.round_id
              JOIN tasks AS task ON task.id = link.task_id
             WHERE task.status IN ('CREATE', 'PAUSE', 'DISPATCH', 'BRIEFING', 'EXEC', 'PLAN')
            """
        )
    )
    await session.execute(
        text(
            """
            UPDATE task_attempts AS attempt
               SET status = 'CANCELLED',
                   retryable = false,
                   error = COALESCE(attempt.error, 'Quarantined historical Messenger replay.'),
                   finished_at = COALESCE(attempt.finished_at, now())
              FROM galaris_replayed_task_ids AS replayed
             WHERE attempt.task_id = replayed.id
               AND attempt.status IN ('CLAIMED', 'RETRY', 'WAITING_CHILDREN')
            """
        )
    )
    await session.execute(
        text(
            """
            UPDATE tasks AS task
               SET status = 'ERROR',
                   paused = false,
                   cancel_requested = true,
                   lease_token = NULL,
                   lease_owner = NULL,
                   lease_expires_at = NULL,
                   next_attempt_at = NULL,
                   last_error = 'Quarantined historical Messenger replay during idempotency cutover.',
                   feedback = COALESCE(
                       task.feedback,
                       'Historical Messenger replay quarantined before execution.'
                   ),
                   data = COALESCE(task.data, '{}'::jsonb)
                       || jsonb_build_object('quarantined_messenger_replay', true),
                   revision = task.revision + 1,
                   updated_at = now()
              FROM galaris_replayed_task_ids AS replayed
             WHERE task.id = replayed.id
               AND task.status IN ('CREATE', 'PAUSE', 'DISPATCH', 'BRIEFING', 'EXEC', 'PLAN')
            """
        )
    )
    await session.execute(
        text(
            """
            UPDATE conversation_round_attempts AS attempt
               SET status = 'CANCELLED',
                   error = COALESCE(attempt.error, 'Quarantined historical Messenger replay.'),
                   finished_at = COALESCE(attempt.finished_at, now())
              FROM galaris_replayed_round_ids AS replayed
             WHERE attempt.round_id = replayed.id
               AND attempt.status IN ('CLAIMED', 'RUNNING')
            """
        )
    )
    await session.execute(
        text(
            """
            UPDATE conversation_round_messages AS membership
               SET consumed_at = COALESCE(membership.consumed_at, now())
              FROM galaris_replayed_round_ids AS replayed
             WHERE membership.round_id = replayed.id
               AND membership.role = 'input'
            """
        )
    )
    await session.execute(
        text(
            """
            UPDATE conversation_rounds AS round_
               SET status = 'CANCELLED',
                   delivery_state = 'SKIPPED',
                   lease_token = NULL,
                   lease_owner = NULL,
                   lease_expires_at = NULL,
                   last_error = 'Quarantined historical Messenger replay during idempotency cutover.',
                   finished_at = COALESCE(round_.finished_at, now())
              FROM galaris_replayed_round_ids AS replayed
             WHERE round_.id = replayed.id
               AND round_.status IN ('FROZEN', 'CLAIMED', 'RUNNING')
            """
        )
    )

    await session.execute(
        text(
            """
            WITH ranked AS (
                SELECT
                    task.id AS task_id,
                    message.id AS message_id,
                    row_number() OVER (
                        PARTITION BY message.id
                        ORDER BY
                            (task.messenger_message_id IS NOT NULL) DESC,
                            task.created_at ASC,
                            task.id ASC
                    ) AS ordinal
                FROM tasks AS task
                JOIN messenger_messages AS message
                  ON (task.data ->> 'message_id')
                     ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
                 AND message.id = (task.data ->> 'message_id')::uuid
                WHERE task.deleted_at IS NULL
            )
            UPDATE tasks AS task
               SET messenger_message_id = ranked.message_id,
                   revision = task.revision + 1,
                   updated_at = now()
              FROM ranked
             WHERE task.id = ranked.task_id
               AND ranked.ordinal = 1
               AND task.messenger_message_id IS NULL
            """
        )
    )
    await session.execute(
        text(
            """
            UPDATE messenger_messages
               SET status = 'admitted',
                   last_error = NULL,
                   updated_at = now()
             WHERE direction = 'inbound'
               AND status = 'received'
            """
        )
    )


async def _legacy_messenger_admissions_are_closed(
    session: AsyncSession,
    _transitions: SchemaTransitionSet,
) -> bool:
    pending = await session.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.direction == "inbound", Message.status == "received")
    )
    active_replays = await session.scalar(
        text(
            """
            SELECT count(*)
              FROM tasks AS task
              JOIN messenger_messages AS message
                ON (task.data ->> 'message_id')
                   ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'
               AND message.id = (task.data ->> 'message_id')::uuid
             WHERE task.status IN ('CREATE', 'PAUSE', 'DISPATCH', 'BRIEFING', 'EXEC', 'PLAN')
               AND task.created_at > message.created_at + interval '1 hour'
            """
        )
    )
    active_replayed_rounds = await session.scalar(
        text(
            """
            SELECT count(DISTINCT round_.id)
              FROM conversation_rounds AS round_
              JOIN conversation_round_messages AS membership
                ON membership.round_id = round_.id
               AND membership.role = 'input'
              JOIN messenger_messages AS message ON message.id = membership.message_id
             WHERE round_.status IN ('FROZEN', 'CLAIMED', 'RUNNING')
               AND round_.created_at > message.created_at + interval '1 hour'
            """
        )
    )
    return (
        int(pending or 0) == 0
        and int(active_replays or 0) == 0
        and int(active_replayed_rounds or 0) == 0
    )


async def _encrypt_hermes_data_env(_session: AsyncSession) -> None:
    await encrypt_persisted_data_env()


async def _reconcile_hermes_configs(_session: AsyncSession) -> None:
    await backfill_legacy_configs()


async def _legacy_session_binding_routes(
    session: AsyncSession,
) -> tuple[SessionBindingRoute, ...]:
    """Collect exact routes from durable Tasks and the canonical message journal."""

    routes: set[SessionBindingRoute] = set()
    task_rows = (
        await session.execute(
            select(
                Task.agent_id,
                Task.message_platform,
                Task.message_group_id,
                Task.messenger_connection_id,
            )
            .where(
                Task.agent_id.is_not(None),
                Task.message_platform.is_not(None),
                Task.message_group_id.is_not(None),
                Task.messenger_connection_id.is_not(None),
            )
            .execution_options(include_historized=True)
        )
    ).all()
    for agent_id, platform, room_id, connection_id in task_rows:
        routes.add(
            SessionBindingRoute(
                agent_id=int(agent_id),
                platform=str(platform),
                room_id=str(room_id),
                connection_id=int(connection_id),
            )
        )

    journal_rows = (
        await session.execute(
            select(
                Connection.agent_id,
                Message.platform,
                Message.room_id,
                Message.connection_id,
            )
            .join(Connection, Connection.id == Message.connection_id)
            .where(Message.room_id.is_not(None))
        )
    ).all()
    for agent_id, platform, room_id, connection_id in journal_rows:
        routes.add(
            SessionBindingRoute(
                agent_id=int(agent_id),
                platform=str(platform),
                room_id=str(room_id),
                connection_id=int(connection_id),
            )
        )
    return tuple(routes)


async def _reconcile_hermes_session_bindings(session: AsyncSession) -> None:
    await migrate_legacy_bindings(await _legacy_session_binding_routes(session))


def register_dbadmin(registry: DbAdminRegistry) -> None:
    """Register transitional Hermès work without changing the in-progress bridge."""

    registry.register_action(
        DbAdminAction(
            key="app.messenger.close_legacy_inbound_admissions",
            phase=DbAdminPhase.AFTER_EXPAND,
            checksum="v1-quarantine-replays-and-durable-task-key",
            predicate=_adds_durable_messenger_task_key,
            handler=_backfill_messenger_admissions,
            postcondition=_legacy_messenger_admissions_are_closed,
        )
    )

    registry.register_reconciler(
        DbAdminReconciler(
            key="bridge.hermes.data_env_encryption",
            handler=_encrypt_hermes_data_env,
            depends_on=("core.params.declarations",),
        )
    )
    registry.register_reconciler(
        DbAdminReconciler(
            key="bridge.hermes.config_reconciliation",
            handler=_reconcile_hermes_configs,
            depends_on=("bridge.hermes.data_env_encryption",),
        )
    )
    registry.register_reconciler(
        DbAdminReconciler(
            key="bridge.hermes.session_bindings",
            handler=_reconcile_hermes_session_bindings,
            depends_on=(
                "app.messenger.contact_memory",
                "bridge.hermes.config_reconciliation",
            ),
        )
    )
