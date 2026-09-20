"""
Fixtures for authorize module tests.
"""
import pytest
from unittest.mock import Mock, AsyncMock

from core.authorize import AuthorizeService
from core.authorize import GuardProvider
from core.authorize import RuleProvider


@pytest.fixture
def guard_provider():
    """Provide a fresh GuardProvider instance."""
    return GuardProvider()


@pytest.fixture
def rule_provider():
    """Provide a fresh RuleProvider instance."""
    return RuleProvider()


@pytest.fixture
def authorize_service(guard_provider, rule_provider, mock_db):
    """Provide an AuthorizeService with fresh providers."""
    return AuthorizeService(
        guard_provider=guard_provider,
        rule_provider=rule_provider,
        db=mock_db,
    )


@pytest.fixture
def mock_user():
    """Provide a mock User."""
    user = Mock()
    user.id = 1
    user.email = "test@example.com"
    user.is_active = True
    return user


@pytest.fixture
def mock_db():
    """Provide a mock database session."""
    db = AsyncMock()
    return db


@pytest.fixture
def mock_request():
    """Provide a mock FastAPI Request."""
    request = Mock()
    request.path_params = {}
    request.query_params = {}
    request.scope = {"route": Mock(name="test_route")}
    return request
