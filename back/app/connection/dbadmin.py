"""Expand binary function policies without discarding rollback/audit evidence."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet


def _needed(delta: SchemaTransitionSet) -> bool:
    return any(delta.column_added(table, "state") for table in (
        "connection_function_state", "tool_function_state",
    ))


async def _complete(session: AsyncSession, _: SchemaTransitionSet) -> bool:
    marker = await session.scalar(text("SELECT to_regclass('galaris_migration.function_modes_completed')"))
    if marker is None:
        return False
    missing = await session.scalar(text("""
        SELECT (SELECT count(*) FROM connection_function_state WHERE state IS NULL)
             + (SELECT count(*) FROM tool_function_state WHERE state IS NULL)
    """))
    done = await session.scalar(text("SELECT count(*) FROM galaris_migration.function_modes_completed WHERE checksum = 'v1-binary-system-audit-mail'"))
    return missing == 0 and done == 1


async def _convert(session: AsyncSession, _: SchemaTransitionSet) -> None:
    if await _complete(session, _):
        return
    # Previous system rows had no effect. Keep their complete transition audit outside
    # the declarative schema, and restore inheritance instead of activating stale denials.
    await session.execute(text("CREATE SCHEMA IF NOT EXISTS galaris_migration"))
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS galaris_migration.ignored_system_function_policies (
            source_table text NOT NULL, original_key integer NOT NULL, snapshot jsonb NOT NULL,
            PRIMARY KEY (source_table, original_key)
        )
    """))
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS galaris_migration.function_modes_completed (checksum text PRIMARY KEY)
    """))
    for table, join in (
        ("tool_function_state", "JOIN tools t ON t.id = s.tool_id"),
        ("connection_function_state", "JOIN connections c ON c.id = s.connection_id JOIN tools t ON t.id = c.tool_id"),
    ):
        await session.execute(text(f"""
            INSERT INTO galaris_migration.ignored_system_function_policies
            SELECT '{table}', s.id, to_jsonb(s) FROM {table} s {join}
            WHERE s.state IS NULL AND NOT t.can_disable ON CONFLICT DO NOTHING
        """))
        await session.execute(text(f"""
            DELETE FROM {table} WHERE id IN (
                SELECT s.id FROM {table} s {join} WHERE s.state IS NULL AND NOT t.can_disable
            )
        """))
        await session.execute(text(f"""
            UPDATE {table} SET state = CASE WHEN enabled THEN 'enabled' ELSE 'disabled' END
            WHERE state IS NULL
        """))

    # An old Mail opt-in already asked for approval, even with a binary enabled override.
    # False/default is deliberately not migrated to enabled: sensitive defaults now apply.
    await session.execute(text("""
        INSERT INTO connection_function_state (connection_id, function_name, capability_kind, state, enabled)
        SELECT c.id, f.name, 'tool', 'ask', false FROM connections c
        JOIN tools t ON t.id = c.tool_id
        LEFT JOIN connection_params p ON p.connection_id = c.id AND p.param_name = 'approval_required'
        CROSS JOIN (VALUES ('mail_send'), ('mail_reply'), ('mail_forward')) f(name)
        LEFT JOIN connection_function_state l ON l.connection_id = c.id
            AND l.capability_kind = 'tool' AND l.function_name = f.name
        LEFT JOIN tool_function_state g ON g.tool_id = c.tool_id
            AND g.capability_kind = 'tool' AND g.function_name = f.name
        WHERE t.code = 'mail' AND lower(CASE
            WHEN coalesce(t.global_params->'approval_required'->>'forced', 'false') = 'true'
                THEN t.global_params->'approval_required'->>'value'
            ELSE coalesce(nullif(p.param_value, ''), t.global_params->'approval_required'->>'value', 'false')
        END) IN ('true', '1', 'yes', 'on')
          AND coalesce(l.state, g.state, 'enabled') <> 'disabled'
        ON CONFLICT (connection_id, capability_kind, function_name)
        DO UPDATE SET state = 'ask', enabled = false
    """))
    await session.execute(text("""
        INSERT INTO galaris_migration.function_modes_completed VALUES ('v1-binary-system-audit-mail') ON CONFLICT DO NOTHING
    """))


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(
        key="app.connection.function_modes", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="v1-binary-system-audit-mail", predicate=_needed,
        handler=_convert, postcondition=_complete,
    ))
    registry.register_action(DbAdminAction(
        key="app.connection.retire_mail_approval_setting", phase=DbAdminPhase.AFTER_EXPAND,
        checksum="v1-archive-mail-setting-after-function-conversion", predicate=lambda _: True,
        handler=_retire_mail_setting, postcondition=_mail_setting_retired,
    ))


async def _mail_setting_retired(session: AsyncSession, _: SchemaTransitionSet) -> bool:
    remaining = await session.scalar(text("""
        SELECT (SELECT count(*) FROM connection_params p JOIN connections c ON c.id = p.connection_id
            JOIN tools t ON t.id = c.tool_id WHERE t.code = 'mail' AND p.param_name = 'approval_required')
            + (SELECT count(*) FROM tools WHERE code = 'mail' AND global_params ? 'approval_required')
    """))
    return remaining == 0


async def _retire_mail_setting(session: AsyncSession, delta: SchemaTransitionSet) -> None:
    # Also handle an already-expanded schema whose Boolean conversion was interrupted.
    # Its completion marker preserves human choices made after the original conversion.
    await _convert(session, delta)
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS galaris_migration.retired_mail_approval_settings (
            source_table text NOT NULL, original_key integer NOT NULL, snapshot jsonb NOT NULL,
            PRIMARY KEY (source_table, original_key)
        )
    """))
    await session.execute(text("""
        INSERT INTO galaris_migration.retired_mail_approval_settings
        SELECT 'connection_params', p.id, to_jsonb(p) FROM connection_params p
        JOIN connections c ON c.id = p.connection_id JOIN tools t ON t.id = c.tool_id
        WHERE t.code = 'mail' AND p.param_name = 'approval_required' ON CONFLICT DO NOTHING
    """))
    await session.execute(text("""
        INSERT INTO galaris_migration.retired_mail_approval_settings
        SELECT 'tools', id, jsonb_build_object('approval_required', global_params->'approval_required')
        FROM tools WHERE code = 'mail' AND global_params ? 'approval_required' ON CONFLICT DO NOTHING
    """))
    await session.execute(text("""
        DELETE FROM connection_params p USING connections c, tools t
        WHERE p.connection_id = c.id AND c.tool_id = t.id AND t.code = 'mail' AND p.param_name = 'approval_required'
    """))
    await session.execute(text("UPDATE tools SET global_params = global_params - 'approval_required' WHERE code = 'mail'"))
