"""Manual test that displays the Hermes bridge status.

This script checks:
- whether the Hermes server is reachable;
- the status of every Docker container managed by Hermes.

Run:
    make back-exec-manual hermes_status  # from the repository root

Or from the backend container:
    python tests/manual/hermes_status.py
"""

from typing import Any, Dict

from loguru import logger
from devtools import debug

from bridge.hermes.manager import manager as hermes_manager


async def check_bridge_reachable() -> bool:
    """Check whether the Hermes bridge server is reachable."""
    logger.info("🔍 Checking connectivity to the Hermes server...")
    reachable = await hermes_manager.check_reachable()
    if reachable:
        logger.success("✅ Hermes server reachable")
    else:
        logger.error("❌ Hermes server unreachable")
    return reachable


async def get_hermes_status() -> Dict[str, Any]:
    """Fetch and display container status through Hermes."""
    logger.info("📡 Fetching container status...")
    try:
        status = await hermes_manager.get_status()
        logger.success("✅ Status fetched successfully")
        return status
    except Exception as e:
        logger.error(f"❌ Error while fetching status: {e}")
        raise


def print_containers_status(status: Dict[str, Any]) -> None:
    """Display formatted container status."""
    services = status.get("services", [])

    if not services:
        logger.info("ℹ️ No container found")
        return

    logger.info(f"📦 Container count: {len(services)}")
    print("\n" + "=" * 80)
    print(f"{'Service':<20} {'Container':<25} {'Status':<15} {'Health'}")
    print("=" * 80)

    for svc in services:
        if isinstance(svc, dict):
            service_name = svc.get("Service", "N/A")
            container_name = svc.get("Name", "N/A")
            state = svc.get("State", "N/A")
            health = svc.get("Health", "N/A") if svc.get("Health") else "-"

            status_icon = "🟢" if state == "running" else "🔴" if state == "exited" else "🟡"
            print(f"{service_name:<20} {container_name:<25} {status_icon} {state:<12} {health}")
        else:
            # Print raw string output unchanged.
            print(str(svc))

    print("=" * 80)


async def main() -> None:
    """Run the manual test."""
    logger.info("🚀 Starting Hermes status test")
    print("\n")

    # Step 1: check whether the server is reachable.
    if not await check_bridge_reachable():
        logger.error("❌ Could not reach the Hermes server.")
        print("\n💡 Current configuration:")
        print(f"   URL: {hermes_manager._get_base_url()}")
        secret_configured = "Yes" if hermes_manager._get_headers().get("X-Hermes-Secret") else "No"
        print(f"   Secret configured: {secret_configured}")
        return

    print("\n")

    # Step 2: fetch and display container status.
    try:
        status = await get_hermes_status()
        print("\n")
        print_containers_status(status)
        print("\n")
        logger.success("🎉 Hermes status test completed successfully!")

        # Full raw output for deeper analysis.
        logger.debug("📊 Raw status data:")
        debug(status)

    except Exception as e:
        logger.error(f"❌ Test failed: {e}")
        raise
