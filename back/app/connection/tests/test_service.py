"""Tests for the asynchronous EAV connection service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.ext.asyncio import AsyncSession

from .. import connection_service
from ..models import Connection, ConnectionParam


class TestConnectionService:
    """Tests for the EAV connection service."""

    @pytest.fixture
    def mock_db(self, monkeypatch):
        """Isolate persistence; system-service refusals use PostgreSQL in test_system_tools."""
        monkeypatch.setattr(connection_service, "require_editable_connection", AsyncMock())
        monkeypatch.setattr(connection_service, "require_editable_tool", AsyncMock())
        return AsyncMock(spec=AsyncSession)

    # ==========================================================================
    # Connection-management tests.
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_get_or_create_connection_create_new(self, mock_db):
        """Test creating a new connection."""
        # Arrange: no connection exists.
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, 'get_db', return_value=mock_db):
            # Act
            connection = await connection_service.get_or_create_connection(
                tool_id=1, agent_id=1
            )

        # Assert
        assert connection.tool_id == 1
        assert connection.agent_id == 1
        assert connection.active is True
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_or_create_connection_get_existing(self, mock_db):
        """Test retrieving an existing connection."""
        # Arrange: an existing connection.
        existing = Connection(id=1, tool_id=1, agent_id=1, active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, 'get_db', return_value=mock_db):
            # Act
            connection = await connection_service.get_or_create_connection(
                tool_id=1, agent_id=1
            )

        # Assert
        assert connection.id == 1
        assert connection.tool_id == 1
        mock_db.add.assert_not_called()  # No creation.

    @pytest.mark.asyncio
    async def test_get_connection_by_id(self, mock_db):
        """Test retrieving a connection by ID."""
        # Arrange
        existing = Connection(id=42, tool_id=1, agent_id=1, active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, 'get_db', return_value=mock_db):
            # Act
            connection = await connection_service.get_connection(connection_id=42)

        # Assert
        assert connection is not None
        assert connection.id == 42

    @pytest.mark.asyncio
    async def test_get_connection_by_agent_tool(self, mock_db):
        """Test retrieving a connection by agent and tool."""
        # Arrange
        existing = Connection(id=1, tool_id=1, agent_id=5, active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, 'get_db', return_value=mock_db):
            # Act
            connection = await connection_service.get_connection_by_agent_tool(
                tool_id=1, agent_id=5
            )

        # Assert
        assert connection is not None
        assert connection.agent_id == 5
        assert connection.tool_id == 1

    @pytest.mark.asyncio
    async def test_has_active_tool_connection_returns_database_result(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 42
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, "get_db", return_value=mock_db):
            active = await connection_service.has_active_tool_connection(
                agent_id=5,
                tool_code="messenger",
                connection_id=42,
            )

        assert active is True
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_has_active_tool_connection_returns_false_when_missing(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, "get_db", return_value=mock_db):
            active = await connection_service.has_active_tool_connection(
                agent_id=5,
                tool_code="voice",
            )

        assert active is False

    @pytest.mark.asyncio
    async def test_has_any_active_tool_connection_returns_database_result(self, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = 42
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, "get_db", return_value=mock_db):
            active = await connection_service.has_any_active_tool_connection("mail")

        assert active is True
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_connection_active(self, mock_db):
        """Test enabling and disabling a connection."""
        # Arrange
        existing = Connection(id=1, tool_id=1, agent_id=1, active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, 'get_db', return_value=mock_db):
            # Act
            connection = await connection_service.set_connection_active(
                connection_id=1, active=False
            )

        # Assert
        assert connection.active is False
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_connection(self, mock_db):
        """Test deleting a connection."""
        # Arrange
        existing = Connection(id=1, tool_id=1, agent_id=1, active=True)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, 'get_db', return_value=mock_db):
            # Act
            result = await connection_service.delete_connection(connection_id=1)

        # Assert
        assert result is True
        mock_db.delete.assert_called_once_with(existing)
        mock_db.commit.assert_called_once()

    # ==========================================================================
    # EAV parameter-management tests.
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_global_values_are_inherited_and_local_values_override(self):
        global_values = {"host": "shared.example.test", "port": "22"}
        with patch(
            'app.tools.tool_service.get_runtime_global_params',
            new=AsyncMock(return_value=(global_values, set())),
        ):
            resolved = await connection_service.merge_with_global_params(
                7,
                {"host": "exception.example.test", "username": "agent"},
            )

        assert resolved == {
            "host": "exception.example.test",
            "port": "22",
            "username": "agent",
        }

    @pytest.mark.asyncio
    async def test_forced_global_value_ignores_local_override(self):
        with patch(
            'app.tools.tool_service.get_runtime_global_params',
            new=AsyncMock(return_value=({"host": "forced.example.test"}, {"host"})),
        ):
            resolved = await connection_service.merge_with_global_params(
                7,
                {"host": "ignored.example.test"},
            )

        assert resolved == {"host": "forced.example.test"}

    @pytest.mark.asyncio
    async def test_forced_global_value_rejects_new_local_override(self, mock_db):
        connection = Connection(id=1, tool_id=7, agent_id=1, active=True)
        with patch.object(connection_service, 'get_db', return_value=mock_db), \
             patch.object(connection_service, 'get_connection', new=AsyncMock(return_value=connection)), \
             patch(
                 'app.tools.tool_service.get_runtime_global_params',
                 new=AsyncMock(return_value=({"host": "forced.example.test"}, {"host"})),
             ):
            with pytest.raises(ValueError, match="imposed globally"):
                await connection_service.set_param(1, "host", "other.example.test")

    @pytest.mark.asyncio
    async def test_get_params_as_dict(self, mock_db):
        """Test retrieving parameters as a dictionary."""
        # Arrange
        connection = Connection(id=1, tool_id=1, agent_id=1, active=True)

        # Mock get_connection
        mock_conn_result = MagicMock()
        mock_conn_result.scalar_one_or_none.return_value = connection

        # Mock the parameters.
        param1 = ConnectionParam(id=1, connection_id=1, param_name="user_id", param_value="123")
        param2 = ConnectionParam(id=2, connection_id=1, param_name="login", param_value="john")

        mock_params_result = MagicMock()
        mock_params_result.scalars.return_value.all.return_value = [param1, param2]

        # Configure execute to return different results.
        call_count = 0
        async def side_effect(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_conn_result
            return mock_params_result

        mock_db.execute.side_effect = side_effect

        with patch.object(connection_service, 'get_db', return_value=mock_db), \
             patch.object(connection_service, '_get_tool_schema', new=AsyncMock(return_value=None)), \
             patch('app.tools.tool_service.get_runtime_global_params', new=AsyncMock(return_value=({}, set()))):
            # Act
            conn, params = await connection_service.get_params_as_dict(connection=1)

        # Assert
        assert conn is not None
        assert params["user_id"] == "123"
        assert params["login"] == "john"

    @pytest.mark.asyncio
    async def test_set_param_create_new(self, mock_db):
        """Test creating a new parameter."""
        # Arrange
        connection = Connection(id=1, tool_id=1, agent_id=1, active=True)

        mock_conn_result = MagicMock()
        mock_conn_result.scalar_one_or_none.return_value = connection

        mock_param_result = MagicMock()
        mock_param_result.scalar_one_or_none.return_value = None  # No existing parameter.

        call_count = 0
        async def side_effect(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_conn_result
            return mock_param_result

        mock_db.execute.side_effect = side_effect

        with patch.object(connection_service, 'get_db', return_value=mock_db), \
             patch.object(connection_service, '_get_tool_schema', new=AsyncMock(return_value=None)), \
             patch('app.tools.tool_service.get_runtime_global_params', new=AsyncMock(return_value=({}, set()))):
            # Act
            param = await connection_service.set_param(
                connection_id=1, param_name="api_key", param_value="secret123"
            )

        # Assert
        assert param.param_name == "api_key"
        assert param.param_value == "secret123"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_param_update_existing(self, mock_db):
        """Test updating an existing parameter."""
        # Arrange
        connection = Connection(id=1, tool_id=1, agent_id=1, active=True)
        existing_param = ConnectionParam(id=1, connection_id=1, param_name="api_key", param_value="old_value")

        mock_conn_result = MagicMock()
        mock_conn_result.scalar_one_or_none.return_value = connection

        mock_param_result = MagicMock()
        mock_param_result.scalar_one_or_none.return_value = existing_param

        call_count = 0
        async def side_effect(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_conn_result
            return mock_param_result

        mock_db.execute.side_effect = side_effect

        with patch.object(connection_service, 'get_db', return_value=mock_db), \
             patch.object(connection_service, '_get_tool_schema', new=AsyncMock(return_value=None)), \
             patch('app.tools.tool_service.get_runtime_global_params', new=AsyncMock(return_value=({}, set()))):
            # Act
            param = await connection_service.set_param(
                connection_id=1, param_name="api_key", param_value="new_value"
            )

        # Assert
        assert param.param_value == "new_value"
        mock_db.add.assert_not_called()  # Update only; do not create.

    @pytest.mark.asyncio
    async def test_delete_param(self, mock_db):
        """Test deleting a parameter."""
        # Arrange
        mock_result = MagicMock()
        mock_result.rowcount = 1
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, 'get_db', return_value=mock_db):
            # Act
            result = await connection_service.delete_param(
                connection_id=1, param_name="api_key"
            )

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_all_params(self, mock_db):
        """Test deleting every parameter for a connection."""
        # Arrange
        mock_result = MagicMock()
        mock_result.rowcount = 3
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, 'get_db', return_value=mock_db):
            # Act
            count = await connection_service.delete_all_params(connection_id=1)

        # Assert
        assert count == 3

    @pytest.mark.asyncio
    async def test_get_param(self, mock_db):
        """Test retrieving a specific parameter."""
        # Arrange
        connection = Connection(id=1, tool_id=1, agent_id=1, active=True)
        param = ConnectionParam(id=1, connection_id=1, param_name="user_id", param_value="123")

        mock_conn_result = MagicMock()
        mock_conn_result.scalar_one_or_none.return_value = connection

        mock_param_result = MagicMock()
        mock_param_result.scalar_one_or_none.return_value = param
        mock_param_result.scalars.return_value.all.return_value = [param]

        call_count = 0
        async def side_effect(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_conn_result
            return mock_param_result

        mock_db.execute.side_effect = side_effect

        with patch.object(connection_service, 'get_db', return_value=mock_db), \
             patch.object(connection_service, '_get_tool_schema', new=AsyncMock(return_value=None)), \
             patch('app.tools.tool_service.get_runtime_global_params', new=AsyncMock(return_value=({}, set()))):
            # Act
            value = await connection_service.get_param(
                connection_id=1, param_name="user_id"
            )

        # Assert
        assert value == "123"

    # ==========================================================================
    # Parameter-query tests.
    # ==========================================================================

    @pytest.mark.asyncio
    async def test_find_agents_by_param(self, mock_db):
        """Test finding agents by parameter value."""
        # Arrange
        connections = [
            Connection(id=index, tool_id=1, agent_id=index, active=True)
            for index in (1, 2, 3)
        ]

        with patch.object(
            connection_service,
            'get_connections_by_param',
            new=AsyncMock(return_value=connections),
        ):
            # Act
            agent_ids = await connection_service.find_agents_by_param(
                tool_id=1, param_name="user_id", param_value="123"
            )

        # Assert
        assert agent_ids == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_get_connections_by_param(self, mock_db):
        """Test finding connections by parameter value."""
        # Arrange
        conn1 = Connection(id=1, tool_id=1, agent_id=1, active=True)
        conn2 = Connection(id=2, tool_id=1, agent_id=2, active=True)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [conn1, conn2]
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, 'get_db', return_value=mock_db), \
             patch(
                 'app.tools.tool_service.get_runtime_global_params',
                 new=AsyncMock(return_value=({}, set())),
             ):
            # Act
            connections = await connection_service.get_connections_by_param(
                tool_id=1, param_name="user_id", param_value="123"
            )

        # Assert
        assert len(connections) == 2
        assert connections[0].agent_id == 1
        assert connections[1].agent_id == 2

    @pytest.mark.asyncio
    async def test_get_connections_by_param_accepts_inherited_global(self, mock_db):
        """A matching global value also selects connections without a local override."""
        connection = Connection(id=1, tool_id=1, agent_id=1, active=True)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [connection]
        mock_db.execute.return_value = mock_result

        with patch.object(connection_service, 'get_db', return_value=mock_db), \
             patch(
                 'app.tools.tool_service.get_runtime_global_params',
                 new=AsyncMock(return_value=({"user_id": "123"}, set())),
             ):
            connections = await connection_service.get_connections_by_param(
                tool_id=1, param_name="user_id", param_value="123"
            )

        assert connections == [connection]
        mock_db.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_connections_by_param_rejects_nonmatching_forced_global(self, mock_db):
        """A forced global value makes every conflicting local value inactive."""
        with patch.object(connection_service, 'get_db', return_value=mock_db), \
             patch(
                 'app.tools.tool_service.get_runtime_global_params',
                 new=AsyncMock(
                     return_value=({"user_id": "global"}, {"user_id"})
                 ),
             ):
            connections = await connection_service.get_connections_by_param(
                tool_id=1, param_name="user_id", param_value="local"
            )

        assert connections == []
        mock_db.execute.assert_not_awaited()

    # ==========================================================================
    # Encryption tests.
    # ==========================================================================

    def test_is_password_field(self):
        """Test password-field detection."""
        schema = {
            "properties": {
                "username": {"type": "string"},
                "password": {"type": "password"},
                "api_key": {"type": "password"}
            }
        }

        assert connection_service._is_password_field("password", schema) is True
        assert connection_service._is_password_field("api_key", schema) is True
        assert connection_service._is_password_field("username", schema) is False
        assert connection_service._is_password_field("unknown", schema) is False
