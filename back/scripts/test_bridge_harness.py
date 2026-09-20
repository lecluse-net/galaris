"""Check the low-level harness manager deployment configuration."""

import asyncio

from loguru import logger

from bridge.harness import manager
from core.params import params_service, runtime_settings as settings
from core.database import get_db_session


async def main() -> None:
    async with get_db_session():
        await params_service.load_params()
    if not manager.configured:
        raise RuntimeError("Configure the shared secret in Preferences > Harnesses")
    if not await manager.check_reachable():
        raise RuntimeError(
            f"Harness manager is unreachable at {settings.HARNESS_MANAGER_URL}; "
            "check the service, URL, shared secret, and IP policy"
        )
    instances = await manager.list_instances()
    logger.success(
        "Harness manager is reachable ({} instance(s))",
        len(instances),
    )


if __name__ == "__main__":
    asyncio.run(main())
