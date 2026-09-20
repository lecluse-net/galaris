"""The legacy shared-token webhook is retired.

The module exposes no HTTP endpoint. Its task
translation code is retained for a possible future integration with user tokens.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/webhook", tags=["webhook"])
