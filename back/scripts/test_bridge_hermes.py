"""Check the generic manager used by per-agent Hermes containers."""

import asyncio

from loguru import logger

from bridge.hermes.manager import manager
from core.database import get_db_session, load_models
from core.params import params_service


async def main() -> None:
    load_models()
    async with get_db_session():
        await params_service.load_params()
    if not await manager.check_reachable():
        raise RuntimeError(
            "Hermes management is unreachable; check the low-level harness manager "
            "preferences and run make test-harness-management"
        )
    agents = await manager.list_agents()
    logger.success(
        "Hermes per-agent management is reachable ({} managed harness instance(s) visible)",
        len(agents),
    )


if __name__ == "__main__":
    asyncio.run(main())
