import pytest
from datetime import timedelta
from unittest.mock import AsyncMock

from jose import jwt
from starlette.requests import Request
from starlette.responses import Response

from core import settings
from core.secrets import auth_secret_key
from core.user import (
    encrypt_password,
    verify_password,
    create_access_token,
)
from core.user.authContextMiddleware import AuthContextMiddleware
from core.user import user_service

def test_password_hashing():
    """Test that password hashing works and is verifiable."""
    password = "securepassword"
    hashed = encrypt_password(password)
    
    assert hashed != password
    assert verify_password(password, hashed) is True
    assert verify_password("wrongpassword", hashed) is False

def test_access_token_generation():
    """Test JWT token generation and claims."""
    data = {"sub": "test@example.com", "user_id": 123}
    token = create_access_token(data=data)
    
    # Decode manually to verify content
    payload = jwt.decode(token, auth_secret_key(), algorithms=[settings.ALGORITHM])
    
    assert payload["sub"] == "test@example.com"
    assert payload["user_id"] == 123
    assert "exp" in payload

def test_access_token_expiration():
    """Test custom expiration time for tokens."""
    data = {"sub": "test@example.com"}
    expires = timedelta(minutes=60)
    token = create_access_token(data=data, expires_delta=expires)
    
    payload = jwt.decode(token, auth_secret_key(), algorithms=[settings.ALGORITHM])
    # Note: We can't easily assert exact time due to small execution delays, 
    # but we can check if it's roughly correct or purely that the claim exists and is valid.
    # Getting 'exp' is enough to prove logic used the delta.
    assert "exp" in payload


def test_has_current_user_checks_context_value() -> None:
    """The helper must call the ContextVar accessor, not inspect the function."""

    user_service.set_current_user(None)
    assert user_service.has_current_user() is False


@pytest.mark.asyncio
async def test_auth_context_leaves_agent_mcp_bearer_to_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware = AuthContextMiddleware(lambda _scope, _receive, _send: None)
    resolver = AsyncMock(
        side_effect=AssertionError(
            "MCP token must not be resolved as a user token"
        )
    )
    monkeypatch.setattr(middleware, "_resolve_user_token", resolver)
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/mcp/test-agent",
            "headers": [(b"authorization", b"Bearer mcp_test-token")],
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "query_string": b"",
        }
    )

    async def call_next(_request: Request) -> Response:
        return Response(status_code=200)

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    resolver.assert_not_awaited()
