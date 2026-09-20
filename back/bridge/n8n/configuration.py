"""Read-only setup checks; no workflow is started or modified."""

from core import settings
from core.params import runtime_settings

from .engine import N8NProcessEngine
from .schemas import N8NConfigurationDefaults, N8NConnectionTest


def configuration_defaults() -> N8NConfigurationDefaults:
    return N8NConfigurationDefaults(galaris_base_url=settings.APP_HOST.rstrip("/"))


async def test_connection() -> N8NConnectionTest:
    if not runtime_settings.PROCESS_N8N_BASE_URL:
        return N8NConnectionTest(ok=False, code="missing_url")
    if not runtime_settings.PROCESS_N8N_API_TOKEN:
        return N8NConnectionTest(ok=False, code="missing_api_key")
    health = await N8NProcessEngine().health()
    if health.status == "healthy":
        return N8NConnectionTest(ok=True, code="healthy", message=health.message)
    # Remote HTTP bodies may contain credentials; return only a classified error.
    return N8NConnectionTest(ok=False, code=health.details[0] if health.details else "unknown")
