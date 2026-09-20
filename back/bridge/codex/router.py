"""Capability-authenticated credential broker for the managed Codex runtime."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Response, status
from pydantic import BaseModel

from core.authorize import independent_auth

from .runtime_credentials import resolve_for_system_token


class RuntimeCredentialResponse(BaseModel):
    auth_mode: Literal["chatgpt"]
    secret: str
    account_id: str | None = None
    plan_type: str | None = None


router = APIRouter(prefix="/codex", tags=["codex"])


@router.get(
    "/runtime-credential",
    response_model=RuntimeCredentialResponse,
    include_in_schema=False,
)
@independent_auth(reason="Managed Codex bearer capability token")
async def runtime_credential(
    response: Response,
    authorization: str | None = Header(default=None),
) -> RuntimeCredentialResponse:
    """Deliver a fresh access token without exposing the stored refresh token."""

    scheme, _, supplied = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not supplied.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A managed-runtime bearer token is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        credential = await resolve_for_system_token(supplied)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return RuntimeCredentialResponse(
        auth_mode=credential.auth_mode,
        secret=credential.secret,
        account_id=credential.account_id,
        plan_type=credential.plan_type,
    )


__all__ = ["router"]
