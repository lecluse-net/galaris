"""Authorization tests for MCP function exposure and connection-over-tool precedence."""

from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from app.tools import connection_functions
from .. import connection_service
from ..models import Connection, ConnectionFunctionState, ToolFunctionState


class TestFunctionResolution:
    """Resolve the effective cascade using pure functions."""

    def test_connection_wins_over_tool(self):
        assert connection_service.resolve_function_enabled("f", {"f": False}, {"f": True}) is False
        assert connection_service.resolve_function_enabled("f", {"f": True}, {"f": False}) is True

    def test_tool_used_when_no_connection_row(self):
        assert connection_service.resolve_function_enabled("f", {}, {"f": False}) is False
        assert connection_service.resolve_function_enabled("f", {}, {"f": True}) is True

    def test_active_by_default_when_no_row(self):
        assert connection_service.resolve_function_enabled("f", {}, {}) is True

    def test_state_to_label(self):
        assert connection_service.function_state_label(None) == "default"
        assert connection_service.function_state_label(True) == "enabled"
        assert connection_service.function_state_label(False) == "disabled"


class TestDisabledFunctionNames:
    """Build the denylist consumed by the runtime."""

    @pytest.mark.asyncio
    async def test_blacklist_follows_cascade(self, monkeypatch):
        monkeypatch.setattr(connection_service, "tool_can_disable", AsyncMock(return_value=True))
        connection = Connection(id=1, tool_id=7, agent_id=3, active=True)
        conn_rows = [
            # Re-enabled at connection level despite the global block, so it is exposed.
            ConnectionFunctionState(connection_id=1, function_name="a", enabled=True),
        ]
        tool_rows = [
            ToolFunctionState(tool_id=7, function_name="a", enabled=False),
            ToolFunctionState(tool_id=7, function_name="b", enabled=False),  # Blocked via Tool.
        ]
        with patch.object(connection_service, "list_function_states", AsyncMock(return_value=conn_rows)), \
             patch.object(connection_service, "list_tool_function_states", AsyncMock(return_value=tool_rows)):
            disabled = await connection_service.get_disabled_function_names(connection)

        assert disabled == {"b"}


class TestAvailableFunctions:
    """Accumulate local and external functions before resolving their authorization."""

    @pytest.mark.asyncio
    async def test_mixed_tool_lists_every_source_active_by_default(self):
        connection = Connection(id=11, tool_id=35, agent_id=1, active=True)
        tool = SimpleNamespace(
            code="nextcloud",
            can_disable=True,
            mcp=SimpleNamespace(type="http"),
        )

        with (
            patch.object(
                connection_functions,
                "get_connection",
                AsyncMock(return_value=connection),
            ),
            patch(
                "app.tools.tool_service.get_tool_by_id",
                AsyncMock(return_value=tool),
            ),
            patch.object(
                connection_functions,
                "list_function_states",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                connection_functions,
                "list_tool_function_states",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                connection_functions,
                "native_tool_codes_for_tool",
                return_value=frozenset({"messenger", "nextcloud"}),
            ),
            patch.object(
                connection_functions,
                "mcp_tools_by_tool_code",
                return_value={"messenger": []},
            ),
            patch.object(
                connection_functions,
                "_list_internal_functions",
                AsyncMock(return_value=[
                    ("messenger_room_send_message", "Send a message."),
                ]),
            ),
            patch.object(
                connection_functions,
                "get_params_as_dict",
                AsyncMock(return_value=(connection, {"login": "nicolas"})),
            ),
            patch.object(
                connection_functions,
                "_list_external_functions",
                AsyncMock(return_value=[
                    ("nc_webdav_list_directory", "List a WebDAV directory."),
                ]),
            ),
        ):
            result = await connection_functions.list_available_connection_functions(
                connection.id
            )

        assert result["success"] is True
        assert {
            function["name"]: (
                function["connection_state"],
                function["global_state"],
                function["effective"],
            )
            for function in result["functions"]
        } == {
            "messenger_room_send_message": ("default", "default", True),
            "nc_webdav_list_directory": ("default", "default", True),
        }

    @pytest.mark.asyncio
    async def test_local_functions_remain_configurable_when_external_source_fails(self):
        connection = Connection(id=11, tool_id=35, agent_id=1, active=True)
        tool = SimpleNamespace(
            code="nextcloud",
            can_disable=True,
            mcp=SimpleNamespace(type="http"),
        )

        with (
            patch.object(
                connection_functions,
                "get_connection",
                AsyncMock(return_value=connection),
            ),
            patch(
                "app.tools.tool_service.get_tool_by_id",
                AsyncMock(return_value=tool),
            ),
            patch.object(
                connection_functions,
                "list_function_states",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                connection_functions,
                "list_tool_function_states",
                AsyncMock(return_value=[]),
            ),
            patch.object(
                connection_functions,
                "native_tool_codes_for_tool",
                return_value=frozenset({"messenger", "nextcloud"}),
            ),
            patch.object(
                connection_functions,
                "mcp_tools_by_tool_code",
                return_value={"messenger": []},
            ),
            patch.object(
                connection_functions,
                "_list_internal_functions",
                AsyncMock(return_value=[
                    ("messenger_room_send_message", "Send a message."),
                ]),
            ),
            patch.object(
                connection_functions,
                "get_params_as_dict",
                AsyncMock(return_value=(connection, {"login": "nicolas"})),
            ),
            patch.object(
                connection_functions,
                "_list_external_functions",
                AsyncMock(side_effect=RuntimeError("MCP unavailable")),
            ),
        ):
            result = await connection_functions.list_available_connection_functions(
                connection.id
            )

        assert result["success"] is True
        assert [
            function["name"]
            for function in result["functions"]
        ] == ["messenger_room_send_message"]
        assert result["functions"][0]["effective"] is True


class TestSetConnectionFunctionState:
    """Application directe en BDD (insert / upsert / delete)."""

    @pytest.fixture
    def mock_db(self, monkeypatch):
        # Persistence units; immutable system grants are exercised against PostgreSQL.
        monkeypatch.setattr(connection_service, "require_editable_connection", AsyncMock())
        return AsyncMock(spec=AsyncSession)

    @pytest.mark.asyncio
    async def test_default_deletes_existing_row(self, mock_db):
        existing = ConnectionFunctionState(id=1, connection_id=1, function_name="a", enabled=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, "get_db", return_value=mock_db):
            await connection_service.set_connection_function_state(1, "a", "default")

        mock_db.delete.assert_awaited_once_with(existing)
        mock_db.add.assert_not_called()
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disabled_inserts_when_absent(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, "get_db", return_value=mock_db):
            await connection_service.set_connection_function_state(1, "a", "disabled")

        mock_db.add.assert_called_once()
        added = mock_db.add.call_args.args[0]
        assert added.function_name == "a"
        assert added.enabled is False
        mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_enabled_updates_existing_row(self, mock_db):
        existing = ConnectionFunctionState(id=1, connection_id=1, function_name="a", enabled=False)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, "get_db", return_value=mock_db):
            await connection_service.set_connection_function_state(1, "a", "enabled")

        assert existing.enabled is True
        mock_db.add.assert_not_called()
        mock_db.commit.assert_awaited_once()
