"""
OAuth2 scheme configuration.

This module is separate from router.py to avoid circular imports.
The oauth2_scheme is needed by both the auth router and other modules
that need to accept bearer tokens.
"""

from fastapi.security import OAuth2PasswordBearer

# OAuth2 scheme for FastAPI - used by Swagger UI and other OAuth2 clients
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)
