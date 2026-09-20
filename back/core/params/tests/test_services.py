"""Unit tests for the backend parameter service."""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from pydantic_settings import BaseSettings
from sqlalchemy.ext.asyncio import AsyncSession

from core.params import params_service
from core.params.models import Param
from core.params.consts import DEFAULT_PARAMS, Params
from core.params.runtime_settings import RuntimeSettings, runtime_settings
from core.settings import Settings


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_db_session():
    """Provide a mocked database session."""
    session = AsyncMock(spec=AsyncSession)
    return session


@pytest.fixture
def sample_params():
    """Provide sample parameters."""
    return {
        "ai.model.chatbot": {
            "value": "deepseek/deepseek-v3.2",
            "label": "Chatbot model",
            "description": "LLM used by the chatbot"
        },
        "ai.model.agent": {
            "value": "openai/gpt-4",
            "label": "Agent model",
            "description": "LLM used by the agent"
        },
        "app.timeout": {
            "value": "30",
            "label": "Timeout",
            "description": "Application timeout"
        }
    }


@pytest.fixture
def mock_param_objects():
    """Provide mocked Param objects."""
    param1 = Mock(spec=Param)
    param1.name = "ai.model.chatbot"
    param1.value = "deepseek/deepseek-v3.2"

    param2 = Mock(spec=Param)
    param2.name = "app.timeout"
    param2.value = "30"

    return [param1, param2]


@pytest.fixture(autouse=True)
def reset_params_cache(monkeypatch):
    """Reset the parameter cache around every test."""
    # Reset the global cache.
    import core.params.params_service as ps
    # These cache unit tests provide partial mocked rows. The full internal-secret
    # lifecycle is covered by the database and HTTP integration scenarios.
    monkeypatch.setattr(ps, "load_auth_secret_key", lambda value: None)
    monkeypatch.setattr(ps, "load_web_push_keys", lambda value: None)
    ps._params_cache = {}
    ps._cache_loaded = False
    yield
    # Clean up after the test.
    ps._params_cache = {}
    ps._cache_loaded = False


# =============================================================================
# Lazy-loading tests.
# =============================================================================

class TestLazyLoading:
    """Tests for lazy parameter loading."""

    @pytest.mark.asyncio
    async def test_get_triggers_load(self, mock_param_objects):
        """Test that get loads parameters when necessary."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            # The first call must load the cache.
            result = await params_service.get("ai.model.chatbot")

        assert result == "deepseek/deepseek-v3.2"

    @pytest.mark.asyncio
    async def test_get_all_triggers_load(self, mock_param_objects):
        """Test that get_all loads parameters when necessary."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            # The first call must load the cache.
            result = await params_service.get_all()

        assert "ai.model.chatbot" in result

    @pytest.mark.asyncio
    async def test_no_reload_if_already_loaded(self, mock_param_objects):
        """Test that parameters already in memory are not reloaded."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            # The first call loads the cache.
            await params_service.get("ai.model.chatbot")

            # Reset the mock to count subsequent calls.
            mock_db.execute.reset_mock()

            # The second call must not reload.
            result = await params_service.get("app.timeout")

            # Loading does not call execute again.
            mock_db.execute.assert_not_called()
            assert result == "30"


# =============================================================================
# load_params tests.
# =============================================================================

class TestLoadParams:
    """Tests for loading parameters into memory."""

    @pytest.mark.asyncio
    async def test_load_params_from_db(self, mock_param_objects):
        """Test loading parameters from the database."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            await params_service.load_params()

        # Verify that the cache was loaded.
        all_params = await params_service.get_all()
        assert all_params["ai.model.chatbot"] == "deepseek/deepseek-v3.2"
        assert all_params["app.timeout"] == "30"

    @pytest.mark.asyncio
    async def test_load_params_empty_db(self):
        """Test loading from an empty database."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = []

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            await params_service.load_params()

        all_params = await params_service.get_all()
        assert all_params == {}


# =============================================================================
# get tests.
# =============================================================================

class TestGet:
    """Tests for retrieving parameters."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_param(self, mock_param_objects):
        """Test retrieving a missing parameter."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            result = await params_service.get("nonexistent.param")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_with_default(self, mock_param_objects):
        """Test retrieval with a default value."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            result = await params_service.get("nonexistent.param", default="default_value")

        assert result == "default_value"


# =============================================================================
# has tests.
# =============================================================================

class TestHas:
    """Tests for checking parameter existence."""

    @pytest.mark.asyncio
    async def test_has_existing_param(self, mock_param_objects):
        """Test checking an existing parameter."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            result = await params_service.has("ai.model.chatbot")

        assert result is True

    @pytest.mark.asyncio
    async def test_has_nonexistent_param(self, mock_param_objects):
        """Test checking a missing parameter."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            result = await params_service.has("nonexistent.param")

        assert result is False


# =============================================================================
# get_all tests.
# =============================================================================

class TestGetAll:
    """Tests for retrieving all parameters."""

    @pytest.mark.asyncio
    async def test_get_all_returns_dict(self, mock_param_objects):
        """Test that get_all returns a dictionary."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            result = await params_service.get_all()

        assert isinstance(result, dict)
        assert "ai.model.chatbot" in result
        assert "app.timeout" in result

    @pytest.mark.asyncio
    async def test_get_all_returns_copy(self, mock_param_objects):
        """Test that get_all returns a copy rather than the original reference."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            result1 = await params_service.get_all()
            result2 = await params_service.get_all()

        assert result1 is not result2


# =============================================================================
# set tests.
# =============================================================================

class TestSet:
    """Tests for updating parameters."""

    @pytest.mark.asyncio
    async def test_set_existing_param(self, mock_param_objects):
        """Test updating an existing parameter."""
        mock_select_result = Mock()
        mock_select_result.scalars.return_value.all.return_value = mock_param_objects

        mock_param = Mock(spec=Param)
        mock_param.name = "ai.model.chatbot"
        mock_param.value = "old_value"

        mock_update_result = Mock()
        mock_update_result.scalar_one.return_value = mock_param

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            # The first call loads the cache; the second updates the value.
            mock_db.execute.side_effect = [mock_select_result, mock_update_result]
            mock_get_db.return_value = mock_db

            result = await params_service.set("ai.model.chatbot", "new_value")

        assert result is True
        assert mock_param.value == "new_value"

    @pytest.mark.asyncio
    async def test_set_nonexistent_param(self, mock_param_objects):
        """Test updating a missing parameter."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            result = await params_service.set("nonexistent.param", "value")

        assert result is False

    def test_normalize_runtime_settings(self):
        assert params_service.normalize(Params.VOICE_ENABLED, "0") == "false"
        assert params_service.normalize(Params.SEARCH_TIMEOUT, "0010") == "10"
        assert (
            params_service.normalize(Params.TASK_SCHEDULER_MAX_CONCURRENCY, "08")
            == "8"
        )

        with pytest.raises(ValueError):
            params_service.normalize(Params.MESSENGER_DRIVER, "unsupported")

        assert (
            params_service.normalize(Params.DREAM_TOPIC_CREATION_MODE, "propose")
            == "propose"
        )
        with pytest.raises(ValueError):
            params_service.normalize(
                Params.DREAM_TOPIC_CREATION_MODE, "unsupported"
            )

        assert params_service.normalize(
            Params.MESSENGER_ENABLED_CHANNELS,
            '["matrix", "telegram"]',
        ) == '["matrix","telegram"]'
        assert params_service.normalize(
            Params.MESSENGER_ENABLED_CHANNELS,
            "[]",
        ) == "[]"
        with pytest.raises(ValueError):
            params_service.normalize(
                Params.MESSENGER_ENABLED_CHANNELS,
                '["matrix","matrix"]',
            )
        with pytest.raises(ValueError):
            params_service.normalize(
                Params.MESSENGER_ENABLED_CHANNELS,
                '["matrix","unknown"]',
            )

    def test_runtime_fields_are_exclusively_database_parameters(self):
        declared_fields = {
            str(config["runtime_field"])
            for config in DEFAULT_PARAMS.values()
            if config.get("runtime_field")
        }

        assert declared_fields == set(RuntimeSettings.model_fields)
        assert declared_fields.isdisjoint(Settings.model_fields)
        assert not issubclass(RuntimeSettings, BaseSettings)

        with pytest.raises(ValueError):
            params_service.normalize(Params.TASK_SCHEDULER_MAX_CONCURRENCY, "11")

    def test_runtime_defaults_match_parameter_declarations(self):
        defaults = RuntimeSettings()

        for name, config in DEFAULT_PARAMS.items():
            field_name = config.get("runtime_field")
            if not field_name:
                continue
            assert params_service.normalize(name, config.get("value")) == (
                params_service._serialize_runtime_value(getattr(defaults, field_name))
            )

    def test_process_urls_require_an_http_scheme(self) -> None:
        assert params_service.normalize(
            Params.PROCESS_N8N_BASE_URL,
            " https://n8n.example/ ",
        ) == "https://n8n.example"
        with pytest.raises(ValueError, match="must start with http"):
            params_service.normalize(
                Params.PROCESS_N8N_BASE_URL,
                "admin@example.com",
            )

    def test_dream_learning_is_disabled_by_default(self):
        assert DEFAULT_PARAMS[Params.DREAM_EXPERIENCE_MODE]["value"] == "off"
        assert RuntimeSettings().DREAM_EXPERIENCE_MODE == "off"
        assert DEFAULT_PARAMS[Params.DREAM_SKILL_LEARNING_MODE]["value"] == "off"
        defaults = RuntimeSettings()
        assert defaults.DREAM_SKILL_LEARNING_MODE == "off"
        assert defaults.DREAM_SKILL_ACTIVATION_SCORE == 0.75
        assert defaults.DREAM_SKILL_MIN_EVIDENCE == 3
        assert defaults.DREAM_SKILL_MAX_ACTIVE == 20

    def test_empty_visible_prompt_restores_its_default(self) -> None:
        assert (
            params_service.normalize(
                Params.AI_TOPIC_CONTINUITY_SYSTEM_PROMPT,
                " \n ",
            )
            is None
        )
        assert (
            params_service.normalize(
                Params.AI_TOPIC_RESOLUTION_SYSTEM_PROMPT,
                "Custom resolution prompt",
            )
            == "Custom resolution prompt"
        )
        assert (
            params_service.normalize(
                Params.AUDIO_SUMMARY_MEETING_FINAL_SYSTEM_PROMPT,
                "\n",
            )
            is None
        )

    def test_prompt_declarations_share_the_governed_kind(self) -> None:
        assert Params.AI_TASK_OBJECTIVE_SYSTEM_PROMPT in params_service.prompt_names()
        assert Params.AI_PLANNER_SYSTEM_PROMPT in params_service.prompt_names()
        assert Params.AI_BRIEFING_SYSTEM_PROMPT in params_service.prompt_names()
        assert Params.AI_TOPIC_CLASSIFICATION_SYSTEM_PROMPT in params_service.prompt_names()
        assert Params.AUDIO_SUMMARY_VIDEO_FINAL_SYSTEM_PROMPT in params_service.prompt_names()
        assert all(
            DEFAULT_PARAMS[name].get("empty_uses_default")
            for name in params_service.prompt_names()
        )

    def test_prompt_default_digest_covers_canonical_source(self, monkeypatch) -> None:
        baseline = params_service.prompt_default_digest(
            Params.AI_PLANNER_SYSTEM_PROMPT
        )

        monkeypatch.setattr(
            "core.params.params_service.prompt_default",
            lambda name: "changed canonical prompt",
        )

        assert params_service.prompt_default_digest(
            Params.AI_PLANNER_SYSTEM_PROMPT
        ) != baseline

    @pytest.mark.asyncio
    async def test_saving_a_prompt_acknowledges_the_current_default(self, monkeypatch) -> None:
        name = Params.AI_PLANNER_SYSTEM_PROMPT
        params_service._params_cache = {name: "old customization"}
        params_service._cache_loaded = True
        param = Mock(spec=Param)
        param.name = name
        param.value = "old customization"
        param.default_digest = "old-digest"
        result = Mock()
        result.scalar_one.return_value = param
        db = AsyncMock()
        db.execute.return_value = result
        monkeypatch.setattr(params_service, "get_db", lambda: db)

        assert await params_service.set(name, "kept customization") is True

        assert param.value == "kept customization"
        assert param.default_digest == params_service.prompt_default_digest(name)

    @pytest.mark.asyncio
    async def test_saving_the_effective_default_restores_following(self, monkeypatch) -> None:
        name = Params.AI_PLANNER_SYSTEM_PROMPT
        default = await params_service.declared_default(name)
        params_service._params_cache = {name: "customization"}
        params_service._cache_loaded = True
        param = Mock(spec=Param)
        param.name = name
        param.value = "customization"
        param.default_digest = "old-digest"
        result = Mock()
        result.scalar_one.return_value = param
        db = AsyncMock()
        db.execute.return_value = result
        monkeypatch.setattr(params_service, "get_db", lambda: db)

        assert await params_service.set(name, default) is True

        assert param.value is None
        assert params_service._params_cache[name] is None

    def test_agent_execution_defaults_support_large_runs(self) -> None:
        defaults = RuntimeSettings()

        assert defaults.TASK_AGENT_MAX_REQUESTS == 200
        assert defaults.TASK_AGENT_MAX_TOOL_CALLS == 5_000
        assert defaults.TASK_TOOL_TIMEOUT_SECONDS == 300.0

    def test_content_size_uses_one_decimal_megabyte_parameter(self) -> None:
        defaults = RuntimeSettings()

        assert defaults.MESSENGER_CONTENT_MAX_MB == 1_000
        assert defaults.messenger_content_max_bytes == 1_000_000_000

    def test_voice_note_duration_uses_minutes(self) -> None:
        defaults = RuntimeSettings()

        assert defaults.MESSENGER_VOICE_MAX_DURATION_MINUTES == 15
        assert defaults.messenger_voice_max_duration_seconds == 900

    @pytest.mark.asyncio
    async def test_set_encrypts_and_applies_runtime_secret(self, monkeypatch):
        name = Params.PROCESS_N8N_API_TOKEN
        monkeypatch.setattr(
            runtime_settings,
            name,
            runtime_settings.PROCESS_N8N_API_TOKEN,
        )
        params_service._params_cache = {name: ""}
        params_service._cache_loaded = True
        param = Mock(spec=Param)
        param.name = name
        param.value = ""
        result = Mock()
        result.scalar_one.return_value = param
        db = AsyncMock()
        db.execute.return_value = result
        monkeypatch.setattr(params_service, "get_db", lambda: db)

        assert await params_service.set(name, "replacement-secret") is True

        assert param.value != "replacement-secret"
        assert params_service.reveal(name, param.value) == "replacement-secret"
        assert runtime_settings.PROCESS_N8N_API_TOKEN == "replacement-secret"


# =============================================================================
# refresh tests.
# =============================================================================

class TestRefresh:
    """Tests for reloading parameters."""

    @pytest.mark.asyncio
    async def test_refresh_reloads_params(self, mock_param_objects):
        """Test that refresh reloads parameters."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            # Initial load.
            await params_service.load_params()

            # Reset the mock to count subsequent calls.
            mock_db.execute.reset_mock()

            # Refresh the cache.
            await params_service.refresh()

            # Verify that reloading called execute.
            mock_db.execute.assert_called()


# =============================================================================
# sync tests.
# =============================================================================

class TestGetAllWithMetadata:
    """Tests for retrieving parameters with metadata."""

    @pytest.mark.asyncio
    async def test_get_all_with_metadata(self, mock_param_objects):
        """Test retrieving parameters with metadata."""
        mock_result = Mock()
        mock_result.scalars.return_value.all.return_value = mock_param_objects

        with patch('core.params.params_service.get_db') as mock_get_db:
            mock_db = AsyncMock()
            mock_db.execute.return_value = mock_result
            mock_get_db.return_value = mock_db

            result = await params_service.get_all_with_metadata()

        assert len(result) == 2
        assert result[0].name == "ai.model.chatbot"
