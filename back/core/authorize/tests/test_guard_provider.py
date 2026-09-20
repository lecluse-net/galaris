"""
Tests for guard_provider.py - GuardProvider and GuardConfig
"""
import pytest
from unittest.mock import AsyncMock, Mock
from fastapi import APIRouter, FastAPI, HTTPException, Request

from core.authorize import GuardProvider, GuardConfig
from core.authorize import guard_provider as guard_provider_module
from core.authorize import (
    BaseAssertion,
    AssertionContext,
    authorize,
    independent_auth,
    public,
)


class DummyAssertion(BaseAssertion):
    """Dummy assertion for testing."""
    async def assert_(self, context: AssertionContext) -> bool:
        return True


class TestGuardConfig:
    """Tests for GuardConfig dataclass."""

    def test_default_initialization(self):
        """Test GuardConfig with default values."""
        config = GuardConfig(route_name="test_route")
        
        assert config.route_name == "test_route"
        assert config.privileges == []
        assert config.assertion is None
        assert config.params == {}
        assert config.methods is None

    def test_full_initialization(self):
        """Test GuardConfig with all fields."""
        config = GuardConfig(
            route_name="test_route",
            privileges=["READ", "WRITE"],
            assertion=DummyAssertion,
            params={"key": "value"},
            methods=["GET", "POST"],
        )
        
        assert config.route_name == "test_route"
        assert config.privileges == ["READ", "WRITE"]
        assert config.assertion == DummyAssertion
        assert config.params == {"key": "value"}
        assert config.methods == ["GET", "POST"]


class TestGuardProvider:
    """Tests for GuardProvider class."""

    def test_initialization(self):
        """Test GuardProvider initialization."""
        provider = GuardProvider()
        assert provider._guards == {}

    def test_add_and_get(self):
        """Test adding and retrieving a guard."""
        provider = GuardProvider()
        config = GuardConfig(route_name="test_route", privileges=["READ"])
        
        provider.add(config)
        retrieved = provider.get("test_route")
        
        assert retrieved == config

    def test_has_existing(self):
        """Test has() with existing guard."""
        provider = GuardProvider()
        provider.add(GuardConfig(route_name="test_route"))
        
        result = provider.has("test_route")
        
        assert result is True

    def test_has_missing(self):
        """Test has() with missing guard."""
        provider = GuardProvider()
        
        result = provider.has("missing_route")
        
        assert result is False

    def test_get_missing(self):
        """Test get() with missing guard."""
        provider = GuardProvider()
        
        result = provider.get("missing_route")
        
        assert result is None

    def test_get_all(self):
        """Test get_all() returns all guards."""
        provider = GuardProvider()
        config1 = GuardConfig(route_name="route1")
        config2 = GuardConfig(route_name="route2")
        
        provider.add(config1)
        provider.add(config2)
        all_guards = provider.get_all()
        
        assert len(all_guards) == 2
        assert all_guards["route1"] == config1
        assert all_guards["route2"] == config2

    def test_remove_existing(self):
        """Test remove() with existing guard."""
        provider = GuardProvider()
        provider.add(GuardConfig(route_name="test_route"))
        
        result = provider.remove("test_route")
        
        assert result is True
        assert provider.has("test_route") is False

    def test_remove_missing(self):
        """Test remove() with missing guard."""
        provider = GuardProvider()
        
        result = provider.remove("missing_route")
        
        assert result is False

    def test_to_rule_existing(self):
        """Test to_rule() with existing guard."""
        provider = GuardProvider()
        config = GuardConfig(
            route_name="test_route",
            privileges=["READ"],
            params={"key": "value"},
        )
        provider.add(config)
        
        rule = provider.to_rule("test_route")
        
        assert rule is not None
        assert rule.privileges == ["READ"]
        assert rule.params == {"key": "value"}

    def test_to_rule_missing(self):
        """Test to_rule() with missing guard."""
        provider = GuardProvider()
        
        rule = provider.to_rule("missing_route")
        
        assert rule is None

    def test_multiple_guards(self):
        """Test managing multiple guards."""
        provider = GuardProvider()
        
        for i in range(10):
            provider.add(GuardConfig(route_name=f"route_{i}"))
        
        assert len(provider.get_all()) == 10
        assert provider.has("route_5") is True

    def test_overwrite_guard(self):
        """Test that adding a guard with same name overwrites."""
        provider = GuardProvider()
        config1 = GuardConfig(route_name="test_route", privileges=["READ"])
        config2 = GuardConfig(route_name="test_route", privileges=["WRITE"])
        
        provider.add(config1)
        provider.add(config2)
        
        retrieved = provider.get("test_route")
        assert retrieved.privileges == ["WRITE"]

    def test_scan_app_unwraps_lazy_included_routers(self):
        """FastAPI 0.139 stores include_router calls in lazy _IncludedRouter objects."""
        nested = APIRouter()

        @nested.get("/protected", name="lazy_protected")
        @authorize(privileges=["READ"])
        async def protected():
            return {"ok": True}

        api = APIRouter(prefix="/api")
        api.include_router(nested)
        app = FastAPI()
        app.include_router(api)

        provider = GuardProvider()
        provider.scan_app(app)

        guard = provider.get("lazy_protected")
        assert guard is not None
        assert guard.privileges == ["READ"]

    def test_scan_app_accepts_explicit_public_route(self):
        app = FastAPI()

        @app.get("/health")
        @public(reason="Health probe")
        async def health():
            return {"ok": True}

        GuardProvider().scan_app(app)

    def test_scan_app_accepts_independently_authenticated_route(self):
        app = FastAPI()

        @app.post("/callback")
        @independent_auth(reason="Signed callback")
        async def callback():
            return {"ok": True}

        GuardProvider().scan_app(app)

    def test_scan_app_rejects_unclassified_route(self):
        app = FastAPI()

        @app.get("/forgotten")
        async def forgotten():
            return {"ok": True}

        with pytest.raises(
            RuntimeError,
            match=r"unclassified routes: GET /forgotten",
        ):
            GuardProvider().scan_app(app)

    def test_scan_app_rejects_duplicate_guarded_route_names(self):
        app = FastAPI()

        @app.get("/first", name="duplicate")
        @authorize(privileges=["READ"])
        async def first():
            return {"ok": True}

        @app.get("/second", name="duplicate")
        @authorize(privileges=["WRITE"])
        async def second():
            return {"ok": True}

        with pytest.raises(
            RuntimeError,
            match=r"Routes sharing an RBAC name must have the same policy; 'duplicate'",
        ):
            GuardProvider().scan_app(app)


@pytest.mark.asyncio
async def test_global_guard_rejects_missing_privilege_without_reading_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body_read = False

    async def receive() -> dict[str, object]:
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"large", "more_body": False}

    async def endpoint() -> None:
        return None

    endpoint._authorize_meta = {}  # type: ignore[attr-defined]
    route = Mock(name="large_upload", endpoint=endpoint)
    route.name = "large_upload"
    route.endpoint = endpoint
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/large-upload",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "route": route,
            "path_params": {},
        },
        receive,
    )
    guard = GuardConfig(route_name="large_upload", privileges=["UPLOAD"])
    monkeypatch.setattr(guard_provider_module.guard_provider, "get", lambda _name: guard)
    monkeypatch.setattr(guard_provider_module, "get_db", Mock())
    monkeypatch.setattr(
        guard_provider_module,
        "check_privilege",
        AsyncMock(return_value=False),
    )
    user = Mock(id=7, is_active=True)

    with pytest.raises(HTTPException) as raised:
        await guard_provider_module.global_authorization_guard(request, user)

    assert raised.value.status_code == 403
    assert body_read is False
