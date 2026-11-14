"""An in-place PostgreSQL rename retains identities, credentials and delegation."""

import pytest
from sqlalchemy import text
from app.agent.models import Agent, Title
from app.connection import Connection, ConnectionParam, ServiceFunctionState

from app.services.naming_migration import rename_services, service_names_complete, needs_service_names
from core.dbadmin import SchemaTransitionSet


@pytest.mark.asyncio
async def test_upgrade_renames_populated_legacy_tables_and_is_idempotent(db):
    # Synthetic legacy identity and foreign-key consumers, using the real schema.
    identifier = await db.scalar(text("INSERT INTO services(code,label,description,capabilities,connection_schema,global_params) "
        "VALUES ('synthetic-rename','Synthetic rename','', '[]', '{\"params\":{\"tools.management_scope\":{\"type\":\"string\"}}}', "
        "'{\"tools.file_indexing_mode\":{\"value\":\"excluded\"}}') RETURNING id"))
    title = Title(label="Synthetic migration", gender="N")
    db.add(title)
    await db.flush()
    agent = Agent(code="synthetic-migration", first_name="Synthetic", last_name="Migration", title_id=title.id)
    db.add(agent)
    await db.flush()
    connection = Connection(service_id=identifier, agent_id=agent.id, active=False)
    db.add(connection)
    await db.flush()
    db.add(ConnectionParam(connection_id=connection.id, param_name="token", param_value="synthetic-encrypted-value"))
    db.add(ConnectionParam(connection_id=connection.id, param_name="tools.management_scope", param_value="team"))
    db.add(ServiceFunctionState(service_id=identifier, function_name="tools_list", enabled=False, state="disabled"))
    await db.flush()
    connection_id = connection.id
    privilege_id = await db.scalar(text("SELECT id FROM privileges WHERE code='SERVICE_ACCESS'"))
    grants = await db.scalar(text("SELECT count(*) FROM role_privileges WHERE privilege_id=:id"), {"id": privilege_id})
    await db.execute(text("UPDATE privileges SET code='TOOL_ACCESS' WHERE id=:id"), {"id": privilege_id})
    for current, legacy in (("services", "tools"), ("service_function_state", "tool_function_state"),
                            ("service_action_authorizations", "tool_action_authorizations")):
        await db.execute(text(f'ALTER TABLE public."{current}" RENAME TO "{legacy}"'))
    await db.execute(text('ALTER TABLE public.connections RENAME COLUMN service_id TO tool_id'))
    transition = SchemaTransitionSet(removed_tables=frozenset({"tools", "tool_function_state", "tool_action_authorizations"}),
        added_tables=frozenset({"services", "service_function_state", "service_action_authorizations"}))
    assert needs_service_names(transition)
    assert not await service_names_complete(db, transition)
    await rename_services(db, transition)
    assert await service_names_complete(db, transition)
    row = (await db.execute(text("SELECT id,code,connection_schema,global_params FROM services WHERE id=:id"), {"id": identifier})).one()
    assert row[0] == identifier and row[1] == "synthetic-rename"
    assert "services.management_scope" in row[2]["params"]
    assert "services.file_indexing_mode" in row[3]
    assert (await db.execute(text("SELECT service_id,active FROM connections WHERE id=:id"), {"id": connection_id})).one() == (identifier, False)
    params = dict((await db.execute(text("SELECT param_name,param_value FROM connection_params WHERE connection_id=:id"), {"id": connection_id})).all())
    assert params == {"token": "synthetic-encrypted-value", "services.management_scope": "team"}
    assert await db.scalar(text("SELECT state FROM service_function_state WHERE service_id=:id AND function_name='services_list'"), {"id": identifier}) == "disabled"
    assert await db.scalar(text("SELECT code FROM privileges WHERE id=:id"), {"id": privilege_id}) == "SERVICE_ACCESS"
    assert await db.scalar(text("SELECT count(*) FROM role_privileges WHERE privilege_id=:id"), {"id": privilege_id}) == grants
    await rename_services(db, transition)
    assert await service_names_complete(db, transition)


def test_naming_migration_does_not_run_for_unrelated_schema_changes():
    assert not needs_service_names(SchemaTransitionSet(added_tables=frozenset({"unrelated"})))


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupted", [False, True])
async def test_legacy_schema_converges_through_atlas_and_recovers_after_rollback(committed_database, monkeypatch, interrupted):
    from dataclasses import replace
    from core import settings
    from core.dbadmin import DbAdminRegistry, DbAdminVerdict
    from core.dbadmin import orchestrator
    from core.dbadmin._internal import atlas
    from app.services.naming_migration import register_naming_migration

    engine = committed_database.kw["bind"]
    monkeypatch.setattr(orchestrator, "engine", engine)
    monkeypatch.setattr(atlas, "engine", engine)
    monkeypatch.setattr(settings, "POSTGRES_DB", engine.url.database)
    monkeypatch.setattr(orchestrator, "_load_contributions", lambda registry: None)
    async with engine.begin() as connection:
        identifier = await connection.scalar(text("INSERT INTO services(code,label,description,capabilities,connection_schema) "
            "VALUES ('synthetic-atlas-upgrade','Synthetic retained','', '[]', '{}') RETURNING id"))
        columns = (await connection.execute(text("SELECT table_name FROM information_schema.columns WHERE table_schema='public' AND column_name='service_id'"))).scalars().all()
        for table in columns:
            await connection.execute(text(f'ALTER TABLE public."{table}" RENAME COLUMN service_id TO tool_id'))
        for current, legacy in (("services", "tools"), ("service_function_state", "tool_function_state"),
                                ("service_action_authorizations", "tool_action_authorizations")):
            await connection.execute(text(f'ALTER TABLE public."{current}" RENAME TO "{legacy}"'))
            sequence = await connection.scalar(text("SELECT to_regclass(:name)"), {"name": f"public.{current}_id_seq"})
            if sequence:
                await connection.execute(text(f'ALTER SEQUENCE public."{current}_id_seq" RENAME TO "{legacy}_id_seq"'))
        await connection.execute(text("ALTER TABLE public.tools DROP COLUMN icon, DROP COLUMN catalog"))
    registry = DbAdminRegistry()
    register_naming_migration(registry)
    if interrupted:
        broken = DbAdminRegistry()
        original = registry.actions[0]

        async def fail_before_commit(session, transitions):
            await original.handler(session, transitions)
            raise RuntimeError("Synthetic interruption before naming transaction commit")

        broken.register_action(replace(original, handler=fail_before_commit))
        result = await orchestrator.synchronize_database(target_registry=broken)
        assert result.verdict is DbAdminVerdict.FATAL
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT to_regclass('public.tools') IS NOT NULL"))
            assert await connection.scalar(text("SELECT label FROM tools WHERE id=:id"), {"id": identifier}) == "Synthetic retained"
    for _ in range(2):
        result = await orchestrator.synchronize_database(target_registry=registry)
        assert result.verdict is DbAdminVerdict.CONVERGED, result.issues
        async with engine.connect() as connection:
            assert await connection.scalar(text("SELECT label FROM services WHERE id=:id"), {"id": identifier}) == "Synthetic retained"
            assert await connection.scalar(text("SELECT to_regclass('public.tools') IS NULL"))
