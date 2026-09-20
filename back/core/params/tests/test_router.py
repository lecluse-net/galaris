"""Unit tests for the backend parameter router.

This module tests the public parameter-router endpoints.
"""

import pytest
from unittest.mock import Mock, patch, AsyncMock
from sqlalchemy.ext.asyncio import AsyncSession

from core.params import router, params_service
from core.params.router import read_params, update_param
from core.params.schemas import ParamUpdate
from core.params.consts import Params


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_db():
    """Provide a mocked database session."""
    return AsyncMock(spec=AsyncSession)


@pytest.fixture
def mock_params_dict():
    """Provide parameters in dictionary form."""
    return {
        "ai.model.chatbot": "deepseek/deepseek-v3.2",
        "ai.model.agent": "openai/gpt-4",
        "app.timeout": "30"
    }


@pytest.fixture
def mock_params_list():
    """Provide parameters as a list of names and values."""
    param1 = Mock()
    param1.name = "ai.model.chatbot"
    param1.value = "deepseek/deepseek-v3.2"

    param2 = Mock()
    param2.name = "app.timeout"
    param2.value = "30"

    return [param1, param2]


# =============================================================================
# Router-function tests without HTTP.
# =============================================================================

class TestRouterFunctions:
    """Tests for router functions called directly."""

    @pytest.mark.asyncio
    async def test_read_params_logic(self, mock_db, mock_params_list):
        """Test la logique de read_params."""
        with patch.object(params_service, 'get_all_with_metadata', new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_params_list

            result = await read_params()

            # The result is a Pydantic ParamsListResponse object.
            assert hasattr(result, 'params')
            assert len(result.params) == 2
            assert result.params[0].name == "ai.model.chatbot"

    @pytest.mark.asyncio
    async def test_update_param_success_logic(self, mock_db):
        """Test a successful update_param call."""
        with patch.object(params_service, 'has', new_callable=AsyncMock) as mock_has:
            mock_has.return_value = True

            with patch.object(params_service, 'set', new_callable=AsyncMock) as mock_set:
                mock_set.return_value = True

                param_update = ParamUpdate(value="new-model")
                result = await update_param(
                    name="ai.model.chatbot",
                    param_update=param_update
                )

                assert result.status == "success"
                assert result.name == "ai.model.chatbot"
                assert result.value == "new-model"

    @pytest.mark.asyncio
    async def test_read_params_masks_configured_secrets(self):
        secret = Mock()
        secret.name = Params.PROCESS_N8N_API_TOKEN
        secret.value = "legacy-plaintext-secret"

        with patch.object(
            params_service,
            "get_all_with_metadata",
            new=AsyncMock(return_value=[secret]),
        ):
            result = await read_params()

        assert result.params[0].value is None
        assert result.params[0].secret is True
        assert result.params[0].configured is True

    @pytest.mark.asyncio
    async def test_read_params_displays_the_effective_sequential_topic_prompt(self):
        prompt = Mock()
        prompt.name = Params.AI_TOPIC_CONTINUITY_SYSTEM_PROMPT
        prompt.value = None

        with patch.object(
            params_service,
            "get_all_with_metadata",
            new=AsyncMock(return_value=[prompt]),
        ):
            result = await read_params()

        assert result.params[0].value is not None
        assert "weak, revisable evidence" in result.params[0].value
        assert result.params[0].configured is False
        assert result.params[0].prompt is not None
        assert result.params[0].prompt.customized is False
        assert result.params[0].prompt.default_changed is False

    @pytest.mark.asyncio
    async def test_read_params_marks_a_custom_prompt_based_on_an_old_default(self):
        prompt = Mock()
        prompt.name = Params.AI_TOPIC_CONTINUITY_SYSTEM_PROMPT
        prompt.value = "Instance customization"
        prompt.default_digest = "old-default"

        with patch.object(
            params_service,
            "get_all_with_metadata",
            new=AsyncMock(return_value=[prompt]),
        ):
            result = await read_params()

        metadata = result.params[0].prompt
        assert metadata is not None
        assert metadata.customized is True
        assert metadata.default_changed is True
        assert metadata.default_value

    @pytest.mark.asyncio
    async def test_keep_custom_prompt_acknowledges_the_new_default(self):
        name = Params.AI_TOPIC_CONTINUITY_SYSTEM_PROMPT
        with (
            patch.object(params_service, "has", new=AsyncMock(return_value=True)),
            patch.object(
                params_service,
                "get",
                new=AsyncMock(return_value="Custom prompt"),
            ),
            patch.object(params_service, "set", new=AsyncMock(return_value=True)) as set_param,
        ):
            result = await update_param(
                name,
                ParamUpdate(prompt_action="keep_custom"),
            )

        set_param.assert_awaited_once_with(name, "Custom prompt")
        assert result.prompt is not None
        assert result.prompt.customized is True
        assert result.prompt.default_changed is False

    @pytest.mark.asyncio
    async def test_update_secret_never_echoes_plaintext(self):
        with (
            patch.object(params_service, "has", new=AsyncMock(return_value=True)),
            patch.object(params_service, "set", new=AsyncMock(return_value=True)),
        ):
            result = await update_param(
                Params.PROCESS_N8N_API_TOKEN,
                ParamUpdate(value="replacement-secret"),
            )

        assert result.value is None
        assert result.secret is True
        assert result.configured is True


# =============================================================================
# Router structure tests.
# =============================================================================

class TestRouterStructure:
    """Tests for router structure."""
    
    def test_router_prefix(self):
        """Test that the router uses the expected prefix."""
        assert router.router.prefix == "/params"
    
    def test_router_tags(self):
        """Test that the router has the expected tags."""
        assert "params" in router.router.tags
    
    def test_router_has_routes(self):
        """Test that the router exposes the expected routes."""
        routes = [route.path for route in router.router.routes]
        assert "/params" in routes or "" in routes  # GET /
        assert "/params/{name}" in routes or "/{name}" in routes  # PUT /{name}
