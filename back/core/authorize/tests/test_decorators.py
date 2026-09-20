"""
Tests for decorators.py - @authorize decorator
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordBearer

from core.authorize import authorize, independent_auth, public
from core.authorize.decorators import _authorize_route, _authorize_resource
from core.authorize import BaseAssertion, AssertionContext


class DummyAssertion(BaseAssertion):
    """Dummy assertion for testing."""
    async def assert_(self, context: AssertionContext) -> bool:
        return True


class TestAuthorizeDecorator:
    """Tests for the main @authorize decorator."""

    def test_authorize_route_target(self):
        """Test that @authorize with target='route' calls _authorize_route."""
        with patch("core.authorize.decorators._authorize_route") as mock_route:
            mock_route.return_value = lambda f: f
            
            decorator = authorize(privileges=["READ"], target="route")
            
            mock_route.assert_called_once()

    def test_authorize_resource_target(self):
        """Test that @authorize with target='resource' calls _authorize_resource."""
        with patch("core.authorize.decorators._authorize_resource") as mock_resource:
            mock_resource.return_value = lambda f: f
            
            decorator = authorize(privileges=["READ"], target="resource")
            
            mock_resource.assert_called_once()

    def test_authorize_default_target_is_route(self):
        """Test that default target is 'route'."""
        with patch("core.authorize.decorators._authorize_route") as mock_route:
            mock_route.return_value = lambda f: f
            
            decorator = authorize(privileges=["READ"])
            
            mock_route.assert_called_once()

    def test_authorize_string_privilege(self):
        """Test that single string privilege is converted to list."""
        with patch("core.authorize.decorators._authorize_route") as mock_route:
            mock_route.return_value = lambda f: f
            
            decorator = authorize(privileges="READ")
            
            # Check that privileges was normalized to list
            call_args = mock_route.call_args
            assert call_args[0][0] == ["READ"]  # privileges as first positional arg

    def test_authorize_list_privilege(self):
        """Test that list privilege stays as list."""
        with patch("core.authorize.decorators._authorize_route") as mock_route:
            mock_route.return_value = lambda f: f
            
            decorator = authorize(privileges=["READ", "WRITE"])
            
            call_args = mock_route.call_args
            assert call_args[0][0] == ["READ", "WRITE"]

    def test_authorize_none_privilege(self):
        """Test that None privilege becomes empty list."""
        with patch("core.authorize.decorators._authorize_route") as mock_route:
            mock_route.return_value = lambda f: f
            
            decorator = authorize()
            
            call_args = mock_route.call_args
            assert call_args[0][0] == []


class TestPublicDecorator:
    """Tests for the explicit RBAC exemption marker."""

    def test_stores_auditable_reason(self):
        async def endpoint():
            return {"ok": True}

        result = public(reason="Health probe")(endpoint)

        assert result._public_route_reason == "Health probe"

    def test_requires_a_reason(self):
        with pytest.raises(ValueError, match="document why"):
            public(reason="   ")

    def test_rejects_public_after_authorize(self):
        async def endpoint():
            return {"ok": True}

        protected = authorize(privileges=["READ"])(endpoint)

        with pytest.raises(ValueError, match="only one authorization classification"):
            public(reason="Invalid overlap")(protected)

    def test_rejects_authorize_after_public(self):
        async def endpoint():
            return {"ok": True}

        exposed = public(reason="Health probe")(endpoint)

        with pytest.raises(ValueError, match="only one authorization classification"):
            authorize(privileges=["READ"])(exposed)


class TestIndependentAuthDecorator:
    """Tests for the non-RBAC authentication marker."""

    def test_stores_auditable_reason(self):
        async def endpoint():
            return {"ok": True}

        result = independent_auth(reason="Signed callback")(endpoint)

        assert result._independent_auth_reason == "Signed callback"

    def test_requires_a_reason(self):
        with pytest.raises(ValueError, match="document its mechanism"):
            independent_auth(reason=" ")

    def test_rejects_overlap_with_public(self):
        async def endpoint():
            return {"ok": True}

        exposed = public(reason="Health probe")(endpoint)

        with pytest.raises(ValueError, match="only one authorization classification"):
            independent_auth(reason="Signed callback")(exposed)


class TestAuthorizeRoute:
    """Tests for _authorize_route function."""

    def test_stores_metadata_on_endpoint(self):
        """Test that metadata is stored on the endpoint."""
        
        async def dummy_endpoint():
            return {"message": "ok"}
        
        decorator = _authorize_route(
            privileges=["READ"],
            assertion=DummyAssertion,
            params={"key": "value"},
        )
        
        result = decorator(dummy_endpoint)
        
        assert hasattr(result, "_authorize_meta")
        assert result._authorize_meta["privileges"] == ["READ"]
        assert result._authorize_meta["assertion"] == DummyAssertion
        assert result._authorize_meta["params"] == {"key": "value"}

class TestAuthorizeResource:
    """Tests for _authorize_resource function."""

    def test_adds_rules_to_class(self):
        """Test that rules are added to class _authorize_rules."""
        
        class DummyClass:
            pass
        
        decorator = _authorize_resource(
            privileges=["READ"],
            assertion=DummyAssertion,
            params={"key": "value"},
        )
        
        result = decorator(DummyClass)
        
        assert hasattr(result, "_authorize_rules")
        assert len(result._authorize_rules) == 1
        
        rule = result._authorize_rules[0]
        assert rule.privileges == ["READ"]
        assert rule.assertion == DummyAssertion
        assert rule.params == {"key": "value"}

    def test_appends_multiple_rules(self):
        """Test that multiple decorators append rules."""
        
        class DummyClass:
            pass
        
        decorator1 = _authorize_resource(privileges=["READ"], assertion=None, params=None)
        decorator2 = _authorize_resource(privileges=["WRITE"], assertion=None, params=None)
        
        DummyClass = decorator1(DummyClass)
        DummyClass = decorator2(DummyClass)
        
        assert len(DummyClass._authorize_rules) == 2
        assert DummyClass._authorize_rules[0].privileges == ["READ"]
        assert DummyClass._authorize_rules[1].privileges == ["WRITE"]

    def test_preserves_existing_rules(self):
        """Test that existing rules are preserved."""
        
        class DummyClass:
            _authorize_rules = ["existing_rule"]
        
        decorator = _authorize_resource(privileges=["READ"], assertion=None, params=None)
        result = decorator(DummyClass)
        
        assert len(result._authorize_rules) == 2
        assert result._authorize_rules[0] == "existing_rule"



class TestIntegrationWithFastAPI:
    """Integration tests with FastAPI router."""

    def test_decorator_order_matters(self):
        """Test that decorator order matters (FastAPI specific)."""
        router = APIRouter()
        
        @router.get("/test")
        @authorize(privileges=["READ"])
        async def test_endpoint():
            return {"message": "ok"}
        
        # Get the route
        route = router.routes[0]
        
        # Check that the endpoint has metadata
        assert hasattr(route.endpoint, "_authorize_meta")
        assert route.endpoint._authorize_meta["privileges"] == ["READ"]

    def test_multiple_privileges(self):
        """Test with multiple privileges (OR logic)."""
        router = APIRouter()
        
        @router.get("/test")
        @authorize(privileges=["READ", "WRITE"])
        async def test_endpoint():
            return {"message": "ok"}
        
        route = router.routes[0]
        assert route.endpoint._authorize_meta["privileges"] == ["READ", "WRITE"]

    def test_with_assertion(self):
        """Test with assertion class."""
        router = APIRouter()
        
        class OwnerAssertion(BaseAssertion):
            async def assert_(self, context):
                return True
        
        @router.get("/test/{id}")
        @authorize(privileges=["READ"], assertion=OwnerAssertion)
        async def test_endpoint(id: int):
            return {"id": id}
        
        route = router.routes[0]
        assert route.endpoint._authorize_meta["assertion"] == OwnerAssertion

    def test_with_params(self):
        """Test with extra params."""
        router = APIRouter()
        
        @router.get("/test")
        @authorize(privileges=["READ"], params={"resource_type": "document"})
        async def test_endpoint():
            return {"message": "ok"}
        
        route = router.routes[0]
        assert route.endpoint._authorize_meta["params"] == {"resource_type": "document"}
