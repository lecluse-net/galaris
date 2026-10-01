"""PostgreSQL conversion preserves real denials, historical audit and new choices."""
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.agent import Agent, Title
from app.connection.models import Connection, ConnectionFunctionState, ConnectionParam, ToolFunctionState
from app.connection.dbadmin import _complete, _convert, _retire_mail_setting, _mail_setting_retired
from app.tools import ToolModel
from core.dbadmin import SchemaTransitionSet
from core.database import get_db_session
from core.user import UserModel


@pytest.mark.asyncio
async def test_binary_expansion_and_mail_conversion_are_idempotent_and_transactional(committed_database):
    delta = SchemaTransitionSet(added_columns=frozenset({"connection_function_state.state", "tool_function_state.state"}))
    async with get_db_session() as db:
        # Only this isolated ephemeral test database owns the synthetic migration audit.
        await db.execute(text("DROP SCHEMA IF EXISTS galaris_migration CASCADE"))
        user = UserModel(email=f"migration-{uuid4().hex}@example.test", hashed_password="synthetic")
        title = Title(label="Synthetic", gender="X")
        db.add_all([user, title])
        await db.flush()
        agent = Agent(code=f"migration-{uuid4().hex}", first_name="Synthetic", last_name="Migration", user_id=user.id, title_id=title.id)
        db.add(agent)
        await db.flush()
        mail = await db.scalar(select(ToolModel).where(ToolModel.code == "mail"))
        mail.global_params = {"approval_required": {"value": "true", "forced": False}, "synthetic_keep": {"value": "preserved"}}
        system = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris"))
        ordinary = ToolModel(code=f"legacy-{uuid4().hex}", label="Synthetic third-party Tool")
        db.add(ordinary)
        await db.flush()
        connection = Connection(agent_id=agent.id, tool_id=mail.id, active=False)
        db.add(connection)
        await db.flush()
        db.add(ConnectionParam(connection_id=connection.id, param_name="approval_required", param_value="true"))
        enabled = ToolFunctionState(tool_id=ordinary.id, function_name="legacy_read", enabled=True)
        blocked = ToolFunctionState(tool_id=ordinary.id, function_name="legacy_write", enabled=False)
        ignored = ToolFunctionState(tool_id=system.id, function_name="legacy_ignored", enabled=False)
        mail_enabled = ConnectionFunctionState(connection_id=connection.id, function_name="mail_send", enabled=True)
        mail_blocked = ConnectionFunctionState(connection_id=connection.id, function_name="mail_reply", enabled=False)
        db.add_all([enabled, blocked, ignored, mail_enabled, mail_blocked])
        await db.flush()
        identifiers = enabled.id, blocked.id, ignored.id, mail_enabled.id, mail_blocked.id
        connection_id, agent_id, mail_id = connection.id, agent.id, mail.id
    # Rolling back the action also rolls back its audit and completion marker.
    async with get_db_session() as db:
        await _retire_mail_setting(db, delta)
        await db.rollback()
    async with get_db_session() as db:
        assert (await db.get(ToolFunctionState, identifiers[0])).state is None
        assert (await db.get(ToolFunctionState, identifiers[2])) is not None
        assert not await _complete(db, delta)
        assert not await _mail_setting_retired(db, delta)
        await _retire_mail_setting(db, delta)
    async with get_db_session() as db:
        assert (await db.get(ToolFunctionState, identifiers[0])).state == "enabled"
        assert (await db.get(ToolFunctionState, identifiers[1])).state == "disabled"
        assert await db.get(ToolFunctionState, identifiers[2]) is None
        audit = await db.scalar(text("SELECT snapshot FROM galaris_migration.ignored_system_function_policies WHERE source_table='tool_function_state' AND original_key=:key"), {"key": identifiers[2]})
        assert audit["enabled"] is False
        send = await db.get(ConnectionFunctionState, identifiers[3])
        assert send.state == "ask" and send.enabled is False
        assert (await db.get(ConnectionFunctionState, identifiers[4])).state == "disabled"
        assert (await db.get(Connection, connection_id)).active is False
        assert (await db.get(Agent, agent_id)).yolo is False
        assert await _complete(db, delta)
        assert await _mail_setting_retired(db, delta)
        assert (await db.get(ToolModel, mail_id)).global_params == {"synthetic_keep": {"value": "preserved"}}
        assert await db.scalar(select(ConnectionParam).where(ConnectionParam.connection_id == connection_id, ConnectionParam.param_name == "approval_required")) is None
        archived = (await db.scalars(text("SELECT snapshot FROM galaris_migration.retired_mail_approval_settings"))).all()
        assert any(snapshot.get("param_value") == "true" for snapshot in archived)
        assert any(snapshot.get("approval_required", {}).get("value") == "true" for snapshot in archived)
        send.state, send.enabled = "enabled", True
    async with get_db_session() as db:
        await _convert(db, delta)
        await _retire_mail_setting(db, delta)
        assert (await db.get(ConnectionFunctionState, identifiers[3])).state == "enabled"
        assert await db.scalar(text("SELECT count(*) FROM galaris_migration.function_modes_completed")) == 1
