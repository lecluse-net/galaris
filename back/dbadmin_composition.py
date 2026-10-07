"""Cross-layer DbAdmin composition that must not live inside ``core``."""

import json
import re

from pydantic import JsonValue, TypeAdapter
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
    DbAdminEnumMapping,
    DbAdminPhase,
    DbAdminReconciler,
    DbAdminRegistry,
    SchemaTransitionSet,
)


_MEMORY_SNAPSHOT_FIELDS = frozenset({
    "memory_type", "memory_types", "memoryType", "memoryTypes", "by_memory_type",
})
_MEMORY_SNAPSHOT_LABELS = frozenset({
    "core", "working", "episodic", "semantic", "procedural", "social",
})
_JSON_VALUE = TypeAdapter(JsonValue)


def _normalize_memory_snapshot(
    value: JsonValue, *, record: bool = False, schema: bool = False,
    serialized_results: bool = False,
) -> JsonValue:
    """Normalize known machine paths; authored JSON and strings stay opaque."""
    if isinstance(value, dict):
        memory_hit = record and bool({"memory_id", "memory_item_id", "excerpt"}.intersection(value))
        cleaned: dict[str, JsonValue] = {}
        for key, item in value.items():
            if (record or schema) and key in _MEMORY_SNAPSHOT_FIELDS:
                continue
            if memory_hit and key == "type" and isinstance(item, str) and item in _MEMORY_SNAPSHOT_LABELS:
                continue
            if schema:
                # JSON Schema field names and required lists are machine-owned.
                if key in {"default", "const", "enum", "examples"}:
                    cleaned[key] = item
                    continue
                if key == "required" and isinstance(item, list):
                    item = [entry for entry in item
                            if not (isinstance(entry, str) and entry in _MEMORY_SNAPSHOT_FIELDS)]
                cleaned[key] = _normalize_memory_snapshot(item, schema=True)
            elif key == "schema":
                cleaned[key] = _normalize_memory_snapshot(item, schema=True)
            elif key in {"operations", "memories", "existing_memories"}:
                cleaned[key] = _normalize_memory_snapshot(item, record=True, serialized_results=serialized_results)
            elif key in {"decision", "context", "input_data", "expected_output",
                         "configuration", "parameters"}:
                cleaned[key] = _normalize_memory_snapshot(item, serialized_results=serialized_results)
            elif key == "result" and serialized_results and isinstance(item, str):
                # Only the legacy serialized memory envelope is a JSON snapshot.
                # An arbitrary JSON result remains an authored value.
                try:
                    parsed = _JSON_VALUE.validate_json(item)
                except ValueError:
                    cleaned[key] = item
                    continue
                if isinstance(parsed, dict) and {"memories", "operations"}.intersection(parsed):
                    normalized = _normalize_memory_snapshot(parsed)
                    cleaned[key] = json.dumps(normalized, ensure_ascii=False) if normalized != parsed else item
                else:
                    cleaned[key] = item
            else:
                cleaned[key] = item
        return cleaned
    if isinstance(value, list):
        return [_normalize_memory_snapshot(item, record=record, schema=schema,
                                           serialized_results=serialized_results) for item in value]
    return value


def _needs_memory_snapshot_normalization(transitions: SchemaTransitionSet) -> bool:
    return "memory_items.memory_type" in transitions.removed_columns


async def _memory_snapshot_columns(session: AsyncSession) -> list[tuple[str, str]]:
    rows = await session.execute(text("""
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND data_type = 'jsonb'
          AND ((left(table_name, 7) = 'memory_' AND column_name = 'metadata')
               OR (table_name = 'memory_automation_jobs' AND column_name = 'payload')
               OR (table_name = 'dream_receipts' AND column_name = 'prepared_payload')
               OR (table_name = 'lab_evaluation_datasets'
                   AND column_name IN ('parameters', 'configuration'))
               OR (table_name = 'lab_evaluation_cases'
                   AND column_name IN ('input_data', 'expected_output'))
               OR (table_name = 'lab_evaluation_runs'
                   AND column_name IN ('configuration_snapshot', 'case_snapshots')))
        ORDER BY table_name, column_name
    """))
    return [(str(table), str(column)) for table, column in rows]


def _snapshot_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _memory_snapshot_row_filter(table: str) -> str:
    if table == "dream_receipts":
        return "mechanism_key IN ('memory.extract_task', 'memory.extract_conversation_round', 'memory.reflect_task_outcome')"
    if table == "lab_evaluation_datasets":
        return "mechanism = 'memory_extraction'"
    if table in {"lab_evaluation_cases", "lab_evaluation_runs"}:
        return ("dataset_id IN (SELECT id FROM public.lab_evaluation_datasets "
                "WHERE mechanism = 'memory_extraction')")
    return "true"


def _normalize_memory_column(value: JsonValue, column: str) -> JsonValue:
    if column == "metadata" and isinstance(value, dict):
        # Only these legacy top-level fields belong to the memory contract.
        # Nested metadata may contain an authored schema or arbitrary JSON.
        return {key: item for key, item in value.items() if key not in _MEMORY_SNAPSHOT_FIELDS}
    return _normalize_memory_snapshot(value, record=column == "payload",
                                      serialized_results=column == "prepared_payload")


async def _normalize_memory_snapshots(
    session: AsyncSession, _transitions: SchemaTransitionSet,
) -> None:
    for table, column in await _memory_snapshot_columns(session):
        table_sql, column_sql = "public." + _snapshot_identifier(table), _snapshot_identifier(column)
        # Scope the scan by the owning contract, then update only changed rows.
        rows = await session.stream(text(
            f"SELECT id, {column_sql} FROM {table_sql} "
            f"WHERE {_memory_snapshot_row_filter(table)} AND {column_sql}::text ~ :pattern"
        ), {"pattern": 'memory_type|memoryType|by_memory_type|type'})
        async for row in rows:
            original = _JSON_VALUE.validate_python(row[1])
            cleaned = _normalize_memory_column(original, column)
            if cleaned != original:
                await session.execute(text(
                    f"UPDATE {table_sql} SET {column_sql} = CAST(:value AS jsonb) WHERE id = :id"
                ), {"id": row[0], "value": json.dumps(cleaned, ensure_ascii=False)})


async def _memory_snapshots_normalized(
    session: AsyncSession, _transitions: SchemaTransitionSet,
) -> bool:
    for table, column in await _memory_snapshot_columns(session):
        table_sql, column_sql = "public." + _snapshot_identifier(table), _snapshot_identifier(column)
        rows = await session.stream(text(
            f"SELECT {column_sql} FROM {table_sql} "
            f"WHERE {_memory_snapshot_row_filter(table)} AND {column_sql}::text ~ :pattern"
        ), {"pattern": 'memory_type|memoryType|by_memory_type|type'})
        async for row in rows:
            value = _JSON_VALUE.validate_python(row[0])
            if _normalize_memory_column(value, column) != value:
                return False
    return True


def _retires_execution_preparation(transitions: SchemaTransitionSet) -> bool:
    return "tasks.briefing_result" in transitions.removed_columns


_RETIRED_KEYS = frozenset({
    "briefing", "briefing_result", "briefing_text", "briefing_used",
    "use_briefing", "briefing_efforts", "require_briefing",
})
_PREPARATION_BLOCK = re.compile(r"<execution_briefing>.*?</execution_briefing>\s*", re.DOTALL)


def _without_execution_preparation(value: JsonValue) -> JsonValue:
    """Remove retired machine fields and injected blocks, preserving authored content."""
    if isinstance(value, dict):
        return {
            key: _without_execution_preparation(item)
            for key, item in value.items() if key not in _RETIRED_KEYS
        }
    if isinstance(value, list):
        return [_without_execution_preparation(item) for item in value]
    if isinstance(value, str):
        if value == "BRIEFING":
            return "EXEC"
        return _PREPARATION_BLOCK.sub("", value)
    return value


async def _preparation_snapshots(session: AsyncSession) -> list[tuple[str, str]]:
    # Inspect only execution-owned snapshots; user documents/messages are not configuration.
    rows = await session.execute(text(r"""
        SELECT table_name, column_name FROM information_schema.columns
        WHERE table_schema = 'public' AND data_type = 'jsonb'
          AND column_name <> 'briefing_result'
          AND (table_name IN ('tasks', 'task_attempts', 'harnesses', 'agent_harnesses',
                              'harness_execution_configurations')
               OR left(table_name, 4) IN ('lab_', 'llm_'))
        ORDER BY table_name, column_name
    """))
    return [(str(table), str(column)) for table, column in rows]


async def _purge_execution_preparation(
    session: AsyncSession, _transitions: SchemaTransitionSet,
) -> None:
    """One transactional cutover, explicitly discarding the retired feature's archives."""
    statements = (
        "UPDATE tasks SET forced_route = 'EXEC' WHERE forced_route = 'BRIEFING'",
        "UPDATE task_attempts SET phase = 'DISPATCH' WHERE phase = 'BRIEFING'",
        "DELETE FROM lab_evaluation_datasets WHERE mechanism = 'briefing'",
        # Old structured requests must not be replayed under a different contract.
        """CREATE TEMP TABLE retired_execution_inferences ON COMMIT DROP AS
           SELECT id FROM llm_inferences
           WHERE request::text LIKE '%galaris.briefing/%'
              OR request::text LIKE '%galaris.dispatcher.active/v3%'
              OR request->'context'->>'purpose' = 'agent.briefing'
              OR request->>'purpose' = 'agent.briefing'""",
        """DELETE FROM llm_calls WHERE purpose = 'agent.briefing'
           OR system_prompt ILIKE '%you prepare a concise execution briefing%'
           OR inference_attempt_id IN (
               SELECT id FROM llm_inference_attempts WHERE inference_id IN
                   (SELECT id FROM retired_execution_inferences))""",
        """DELETE FROM llm_call_events WHERE inference_id IN
               (SELECT id FROM retired_execution_inferences)""",
        """DELETE FROM llm_inference_commands WHERE inference_id IN
               (SELECT id FROM retired_execution_inferences)""",
        """UPDATE llm_inference_commands SET replay_id = NULL WHERE replay_id IN
               (SELECT id FROM retired_execution_inferences)""",
        """DELETE FROM llm_inference_attempts WHERE inference_id IN
               (SELECT id FROM retired_execution_inferences)""",
        """UPDATE llm_inferences SET replay_of_id = NULL WHERE replay_of_id IN
               (SELECT id FROM retired_execution_inferences)""",
        "DELETE FROM llm_inferences WHERE id IN (SELECT id FROM retired_execution_inferences)",
        "DROP TABLE retired_execution_inferences",
        """UPDATE llm_calls SET prompt = regexp_replace(
               prompt, '<execution_briefing>.*?</execution_briefing>\\s*', '', 'gs')
           WHERE prompt LIKE '%<execution_briefing>%'""",
    )
    for statement in statements:
        await session.execute(text(statement))
    for table, column in await _preparation_snapshots(session):
        # Identifiers come from PostgreSQL, quoted independently of their values.
        table_sql = '"' + table.replace('"', '""') + '"'
        column_sql = '"' + column.replace('"', '""') + '"'
        rows = await session.stream(text(
            f"SELECT id, {column_sql} FROM {table_sql} "
            f"WHERE {column_sql}::text ILIKE '%briefing%'"
        ))
        async for row in rows:
            cleaned = _without_execution_preparation(row[1])
            if cleaned != row[1]:
                await session.execute(text(
                    f"UPDATE {table_sql} SET {column_sql} = CAST(:value AS jsonb) WHERE id = :id"
                ), {"id": row[0], "value": json.dumps(cleaned)})


async def _execution_preparation_is_purged(
    session: AsyncSession, _transitions: SchemaTransitionSet,
) -> bool:
    remains = await session.scalar(text("""
        SELECT EXISTS(SELECT 1 FROM tasks WHERE forced_route = 'BRIEFING')
            OR EXISTS(SELECT 1 FROM task_attempts WHERE phase = 'BRIEFING')
            OR EXISTS(SELECT 1 FROM lab_evaluation_datasets WHERE mechanism = 'briefing')
            OR EXISTS(SELECT 1 FROM llm_calls WHERE purpose = 'agent.briefing'
                      OR system_prompt ILIKE '%you prepare a concise execution briefing%')
            OR EXISTS(SELECT 1 FROM llm_inferences
                      WHERE request::text LIKE '%galaris.briefing/%'
                         OR request::text LIKE '%galaris.dispatcher.active/v3%'
                         OR request->'context'->>'purpose' = 'agent.briefing'
                         OR request->>'purpose' = 'agent.briefing')
            OR EXISTS(SELECT 1 FROM llm_calls WHERE prompt LIKE '%<execution_briefing>%')
    """))
    if remains:
        return False
    for table, column in await _preparation_snapshots(session):
        table_sql = '"' + table.replace('"', '""') + '"'
        column_sql = '"' + column.replace('"', '""') + '"'
        rows = await session.stream(text(
            f"SELECT {column_sql} FROM {table_sql} WHERE {column_sql}::text ILIKE '%briefing%'"
        ))
        async for row in rows:
            if _without_execution_preparation(row[0]) != row[0]:
                return False
    return True


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
             WHERE task.status IN ('CREATE', 'PAUSE', 'DISPATCH', 'EXEC', 'PLAN')
               AND task.created_at > message.created_at + interval '1 hour'
            UNION
            SELECT link.task_id
              FROM conversation_task_links AS link
              JOIN galaris_replayed_round_ids AS replayed ON replayed.id = link.round_id
              JOIN tasks AS task ON task.id = link.task_id
             WHERE task.status IN ('CREATE', 'PAUSE', 'DISPATCH', 'EXEC', 'PLAN')
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
               AND task.status IN ('CREATE', 'PAUSE', 'DISPATCH', 'EXEC', 'PLAN')
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
             WHERE task.status IN ('CREATE', 'PAUSE', 'DISPATCH', 'EXEC', 'PLAN')
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

    registry.register_action(DbAdminAction(
        key="app.memory.normalize_snapshots",
        phase=DbAdminPhase.BEFORE_EXPAND,
        checksum="content-and-provenance-v1",
        predicate=_needs_memory_snapshot_normalization,
        handler=_normalize_memory_snapshots,
        postcondition=_memory_snapshots_normalized,
    ))

    registry.register_enum_mapping(DbAdminEnumMapping("taskstatus", {"BRIEFING": "DISPATCH"}))
    registry.register_action(DbAdminAction(
        key="app.agent.retire_execution_preparation",
        phase=DbAdminPhase.BEFORE_EXPAND,
        checksum="v1-purge-archives-and-normalize-routing",
        predicate=_retires_execution_preparation,
        handler=_purge_execution_preparation,
        postcondition=_execution_preparation_is_purged,
    ))
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
