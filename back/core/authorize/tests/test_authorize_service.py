"""
Tests for authorize_service.py - AuthorizeService with polymorphic is_allowed()
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from core.authorize import (
    AuthorizeService,
)
from core.authorize import GuardProvider, GuardConfig
from core.authorize import RuleProvider, ResourceRule
from core.authorize import BaseAssertion, AssertionContext
from core.user import User


class DummyAssertion(BaseAssertion):
    """Dummy assertion for testing."""
    async def assert_(self, context: AssertionContext) -> bool:
        return True


class TestAuthorizeServiceInitialization:
    """Tests for AuthorizeService initialization."""

    def test_default_initialization(self):
        """Test initialization with default providers."""
        service = AuthorizeService()
        
        assert isinstance(service.guard_provider, GuardProvider)
        assert isinstance(service.rule_provider, RuleProvider)
        assert service._started is False
        assert service.db is None

    def test_custom_providers(self):
        """Test initialization with custom providers."""
        guard_provider = GuardProvider()
        rule_provider = RuleProvider()
        mock_db = Mock()
        
        service = AuthorizeService(
            guard_provider_instance=guard_provider,
            rule_provider=rule_provider,
            db=mock_db,
        )
        
        assert service.guard_provider is guard_provider
        assert service.rule_provider is rule_provider
        assert service.db is mock_db


class TestAuthorizeServiceSyntaxConstants:
    """Tests for syntax constants."""

    def test_syntax_constants(self):
        """Test that syntax constants are defined correctly."""
        service = AuthorizeService()
        
        assert service.SYNTAX_PRIVILEGE == "privilege/"
        assert service.SYNTAX_ROUTE == "route/"


class TestIsAllowedPrivilege:
    """Tests for is_allowed_privilege method."""

    @pytest.mark.asyncio
    async def test_with_user_and_db(self):
        """Test privilege check with user and db."""
        mock_db = Mock()
        service = AuthorizeService(db=mock_db)
        mock_user = Mock(spec=User)
        
        with patch("core.authorize.authorize_service.check_privilege", new_callable=AsyncMock) as mock_check:
            mock_check.return_value = True
            
            result = await service.is_allowed_privilege("READ", mock_user, mock_db)
            
            assert result is True
            mock_check.assert_called_once_with(mock_user, "READ", mock_db)

    @pytest.mark.asyncio
    async def test_without_user(self):
        """Test privilege check without user returns False."""
        mock_db = Mock()
        service = AuthorizeService(db=mock_db)
        
        result = await service.is_allowed_privilege("READ", None)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_without_db(self):
        """Test privilege check without db returns False."""
        service = AuthorizeService()  # No db provided
        mock_user = Mock(spec=User)
        
        result = await service.is_allowed_privilege("READ", mock_user)
        
        assert result is False


class TestIsAllowedRoute:
    """Tests for is_allowed_route method."""

    @pytest.mark.asyncio
    async def test_existing_guard_allowed(self):
        """Test route check when guard exists and allows access."""
        mock_db = Mock()
        service = AuthorizeService(db=mock_db)
        
        # Add a guard
        guard = GuardConfig(
            route_name="test_route",
            privileges=["READ"],
        )
        service.guard_provider.add(guard)
        
        mock_user = Mock(spec=User)
        
        with patch.object(service, "is_allowed_privilege", new_callable=AsyncMock) as mock_priv:
            mock_priv.return_value = True
            
            result = await service.is_allowed_route("test_route", {}, mock_user, mock_db)
            
            assert result is True

    @pytest.mark.asyncio
    async def test_missing_guard(self):
        """Test route check when no guard exists (deny by default)."""
        mock_db = Mock()
        service = AuthorizeService(db=mock_db)
        mock_user = Mock(spec=User)
        
        result = await service.is_allowed_route("missing_route", {}, mock_user)
        
        assert result is False


class TestIsAllowedPolymorphic:
    """Tests for polymorphic is_allowed method."""

    @pytest.mark.asyncio
    async def test_privilege_syntax(self):
        """Test is_allowed with privilege/ syntax."""
        mock_db = Mock()
        service = AuthorizeService(db=mock_db)
        mock_user = Mock(spec=User)
        
        with patch.object(service, "is_allowed_privilege", new_callable=AsyncMock) as mock_priv:
            mock_priv.return_value = True
            
            result = await service.is_allowed("privilege/READ", user=mock_user, db=mock_db)
            
            assert result is True
            mock_priv.assert_called_once_with("READ", mock_user, mock_db)

    @pytest.mark.asyncio
    async def test_route_syntax(self):
        """Test is_allowed with route/ syntax."""
        mock_db = Mock()
        service = AuthorizeService(db=mock_db)
        mock_user = Mock(spec=User)
        
        with patch.object(service, "is_allowed_route", new_callable=AsyncMock) as mock_route:
            mock_route.return_value = True
            
            result = await service.is_allowed("route/test_route", params={"id": 1}, user=mock_user, db=mock_db)
            
            assert result is True
            mock_route.assert_called_once_with("test_route", {"id": 1}, mock_user, mock_db)

    @pytest.mark.asyncio
    async def test_resource_fallback(self):
        """Test is_allowed falls back to resource check for non-string."""
        mock_db = Mock()
        service = AuthorizeService(db=mock_db)
        resource = {"id": 1}
        mock_user = Mock(spec=User)
        
        with patch.object(service, "is_allowed_resource", new_callable=AsyncMock) as mock_res:
            mock_res.return_value = True
            
            result = await service.is_allowed(resource, "READ", user=mock_user)
            
            assert result is True


class TestStaticResourceBuilders:
    """Tests for static resource builder methods."""

    def test_privilege_resource(self):
        """Test privilege_resource static method."""
        result = AuthorizeService.privilege_resource("READ")
        assert result == "privilege/READ"

    def test_route_resource(self):
        """Test route_resource static method."""
        result = AuthorizeService.route_resource("test_route")
        assert result == "route/test_route"


