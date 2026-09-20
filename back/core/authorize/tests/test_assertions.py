"""
Tests for assertions.py - AssertionContext, BaseAssertion, EntityAssertion, CompositeAssertion
"""
import pytest
from typing import Any, Dict, Optional
from unittest.mock import Mock, AsyncMock

from core.authorize import (
    AssertionContext,
    BaseAssertion,
    EntityAssertion,
    CompositeAssertion,
    OwnUserOrPrivilegeAssertion,
    RequireAllPrivilegesAssertion,
)


class TestAssertionContext:
    """Tests for AssertionContext dataclass."""

    def test_default_initialization(self):
        """Test that AssertionContext can be initialized with defaults."""
        context = AssertionContext()
        assert context.user is None
        assert context.request is None
        assert context.db is None
        assert context.resource is None
        assert context.privilege is None
        assert context.params == {}

    def test_full_initialization(self):
        """Test that AssertionContext can be initialized with all fields."""
        mock_user = Mock()
        mock_request = Mock()
        mock_db = Mock()
        
        context = AssertionContext(
            user=mock_user,
            request=mock_request,
            db=mock_db,
            resource={"id": 1},
            privilege="READ_DATA",
            params={"key": "value"},
        )
        
        assert context.user == mock_user
        assert context.request == mock_request
        assert context.db == mock_db
        assert context.resource == {"id": 1}
        assert context.privilege == "READ_DATA"
        assert context.params == {"key": "value"}


class ConcreteAssertion(BaseAssertion):
    """Concrete implementation for testing BaseAssertion."""
    
    async def assert_(self, context: AssertionContext) -> bool:
        return True


class TestBaseAssertion:
    """Tests for BaseAssertion abstract class."""

    def test_initialization_without_service(self):
        """Test BaseAssertion initialization without authorize_service."""
        assertion = ConcreteAssertion()
        assert assertion._authorize is None
        assert assertion._params == {}

    def test_initialization_with_service(self):
        """Test BaseAssertion initialization with authorize_service."""
        mock_service = Mock()
        assertion = ConcreteAssertion(authorize_service=mock_service)
        assert assertion._authorize == mock_service

    def test_set_params(self):
        """Test set_params method."""
        assertion = ConcreteAssertion()
        params = {"key1": "value1", "key2": "value2"}
        
        assertion.set_params(params)
        
        assert assertion._params == params

    def test_get_param_existing(self):
        """Test get_param with existing key."""
        assertion = ConcreteAssertion()
        assertion.set_params({"key": "value"})
        
        result = assertion.get_param("key")
        
        assert result == "value"

    def test_get_param_missing_with_default(self):
        """Test get_param with missing key and default value."""
        assertion = ConcreteAssertion()
        
        result = assertion.get_param("missing", default="default_value")
        
        assert result == "default_value"

    def test_get_param_missing_without_default(self):
        """Test get_param with missing key and no default."""
        assertion = ConcreteAssertion()
        
        result = assertion.get_param("missing")
        
        assert result is None

    def test_get_params(self):
        """Test get_params method."""
        assertion = ConcreteAssertion()
        params = {"key": "value"}
        assertion.set_params(params)
        
        result = assertion.get_params()
        
        assert result == params

    @pytest.mark.asyncio
    async def test_is_allowed_without_service(self):
        """Test is_allowed returns False when no service is set."""
        assertion = ConcreteAssertion()
        
        result = await assertion.is_allowed("resource", "privilege")
        
        assert result is False

    @pytest.mark.asyncio
    async def test_is_allowed_with_service(self):
        """Test is_allowed delegates to service when set."""
        mock_service = Mock()
        mock_service.is_allowed = AsyncMock(return_value=True)
        
        assertion = ConcreteAssertion(authorize_service=mock_service)
        result = await assertion.is_allowed("resource", "privilege")
        
        assert result is True
        mock_service.is_allowed.assert_called_once()

    def test_asserts_all_true(self):
        """Test asserts with all True values."""
        assertion = ConcreteAssertion()
        
        result = assertion.asserts(True, True, True)
        
        assert result is True

    def test_asserts_one_false(self):
        """Test asserts with one False value."""
        assertion = ConcreteAssertion()
        
        result = assertion.asserts(True, False, True)
        
        assert result is False

    def test_asserts_with_list(self):
        """Test asserts with a single list argument."""
        assertion = ConcreteAssertion()
        
        result = assertion.asserts([True, True, True])
        
        assert result is True

    def test_asserts_with_list_one_false(self):
        """Test asserts with a single list containing one False."""
        assertion = ConcreteAssertion()
        
        result = assertion.asserts([True, False, True])
        
        assert result is False


class TestEntityAssertion:
    """Tests for EntityAssertion class."""

    @pytest.mark.asyncio
    async def test_assert_with_resource_calls_assert_entity(self):
        """Test that assert_ calls assert_entity when resource is present."""
        
        class TestEntityAssertion(EntityAssertion):
            async def assert_entity(self, entity, privilege, context):
                return entity.get("allowed", False)
        
        assertion = TestEntityAssertion()
        context = AssertionContext(resource={"id": 1, "allowed": True})
        
        result = await assertion.assert_(context)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_assert_without_resource_calls_assert_other(self):
        """Test that assert_ calls assert_other when no resource."""
        
        class TestEntityAssertion(EntityAssertion):
            async def assert_other(self, context):
                return True
        
        assertion = TestEntityAssertion()
        context = AssertionContext()
        
        result = await assertion.assert_(context)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_default_assert_entity_returns_true(self):
        """Test default assert_entity returns True."""
        assertion = EntityAssertion()
        context = AssertionContext(resource={"id": 1})
        
        result = await assertion.assert_entity({"id": 1}, "privilege", context)
        
        assert result is True


class TestRequireAllPrivilegesAssertion:
    @pytest.mark.asyncio
    async def test_requires_every_configured_privilege(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        check = AsyncMock(side_effect=[True, False])
        monkeypatch.setattr("core.authorize.logic.check_privilege", check)
        assertion = RequireAllPrivilegesAssertion()
        assertion.set_params({"required_privileges": ["EDIT", "API"]})
        context = AssertionContext(user=Mock(), db=Mock())

        assert await assertion.assert_(context) is False
        assert check.await_count == 2

    @pytest.mark.asyncio
    async def test_rejects_missing_configuration(self) -> None:
        assertion = RequireAllPrivilegesAssertion()

        assert await assertion.assert_(AssertionContext()) is False


class TestOwnUserOrPrivilegeAssertion:
    @pytest.mark.asyncio
    async def test_allows_own_user_without_fallback_check(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        check = AsyncMock()
        monkeypatch.setattr("core.authorize.logic.check_privilege", check)
        assertion = OwnUserOrPrivilegeAssertion()
        assertion.set_params(
            {
                "owner_param": "user_id",
                "fallback_privilege": "MANAGE",
                "user_id": "7",
                "__route_name__": "own_user",
            }
        )
        context = AssertionContext(
            user=Mock(id=7),
            db=Mock(),
            params=assertion.get_params(),
        )

        assert await assertion.assert_(context) is True
        check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_requires_fallback_privilege_for_another_user(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        check = AsyncMock(return_value=False)
        monkeypatch.setattr("core.authorize.logic.check_privilege", check)
        assertion = OwnUserOrPrivilegeAssertion()
        assertion.set_params(
            {
                "owner_param": "user_id",
                "fallback_privilege": "MANAGE",
                "user_id": 8,
                "__route_name__": "other_user",
            }
        )
        user = Mock(id=7)
        db = Mock()
        context = AssertionContext(
            user=user,
            db=db,
            params=assertion.get_params(),
        )

        assert await assertion.assert_(context) is False
        check.assert_awaited_once_with(user, "MANAGE", db)


class TestCompositeAssertion:
    """Tests for CompositeAssertion class."""

    @pytest.mark.asyncio
    async def test_all_mode_all_true(self):
        """Test 'all' mode with all assertions returning True."""
        assertion1 = ConcreteAssertion()
        assertion2 = ConcreteAssertion()
        
        composite = CompositeAssertion(
            assertions=[assertion1, assertion2],
            mode="all"
        )
        context = AssertionContext()
        
        result = await composite.assert_(context)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_all_mode_one_false(self):
        """Test 'all' mode with one assertion returning False."""
        
        class FalseAssertion(BaseAssertion):
            async def assert_(self, context):
                return False
        
        assertion1 = ConcreteAssertion()
        assertion2 = FalseAssertion()
        
        composite = CompositeAssertion(
            assertions=[assertion1, assertion2],
            mode="all"
        )
        context = AssertionContext()
        
        result = await composite.assert_(context)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_any_mode_one_true(self):
        """Test 'any' mode with one assertion returning True."""
        
        class FalseAssertion(BaseAssertion):
            async def assert_(self, context):
                return False
        
        assertion1 = FalseAssertion()
        assertion2 = ConcreteAssertion()
        
        composite = CompositeAssertion(
            assertions=[assertion1, assertion2],
            mode="any"
        )
        context = AssertionContext()
        
        result = await composite.assert_(context)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_any_mode_all_false(self):
        """Test 'any' mode with all assertions returning False."""
        
        class FalseAssertion(BaseAssertion):
            async def assert_(self, context):
                return False
        
        assertion1 = FalseAssertion()
        assertion2 = FalseAssertion()
        
        composite = CompositeAssertion(
            assertions=[assertion1, assertion2],
            mode="any"
        )
        context = AssertionContext()
        
        result = await composite.assert_(context)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_empty_assertions_all_mode(self):
        """Test with empty assertions list in 'all' mode."""
        composite = CompositeAssertion(assertions=[], mode="all")
        context = AssertionContext()
        
        result = await composite.assert_(context)
        
        assert result is True  # all([]) returns True

    @pytest.mark.asyncio
    async def test_empty_assertions_any_mode(self):
        """Test with empty assertions list in 'any' mode."""
        composite = CompositeAssertion(assertions=[], mode="any")
        context = AssertionContext()
        
        result = await composite.assert_(context)
        
        assert result is False  # any([]) returns False

    @pytest.mark.asyncio
    async def test_assert_route_delegates(self):
        """Test assert_route delegates to assert_."""
        composite = CompositeAssertion(assertions=[ConcreteAssertion()], mode="all")
        context = AssertionContext()
        
        result = await composite.assert_route("route_name", {}, context)
        
        assert result is True

    @pytest.mark.asyncio
    async def test_assert_entity_delegates(self):
        """Test assert_entity delegates to assert_."""
        composite = CompositeAssertion(assertions=[ConcreteAssertion()], mode="all")
        context = AssertionContext()
        
        result = await composite.assert_entity({"id": 1}, "privilege", context)
        
        assert result is True
