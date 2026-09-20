"""n8n setup diagnostics for administrators of application preferences."""

from fastapi import APIRouter
from core.authorize import Privileges, authorize

from .configuration import configuration_defaults, test_connection
from .schemas import N8NConfigurationDefaults, N8NConnectionTest

router = APIRouter(prefix="/n8n", tags=["n8n"])


@router.get("/settings", response_model=N8NConfigurationDefaults)
@authorize(privileges=[Privileges.PARAMS_ACCESS, Privileges.PARAMS_EDIT])
async def read_settings() -> N8NConfigurationDefaults:
    return configuration_defaults()


@router.post("/test", response_model=N8NConnectionTest)
@authorize(privileges=Privileges.PARAMS_EDIT)
async def check_connection() -> N8NConnectionTest:
    return await test_connection()
