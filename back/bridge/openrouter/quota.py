"""Read remaining key funds, or the account balance with a management key."""

from datetime import datetime, timezone
from dataclasses import replace

from app.llm.facade import (
    ProviderConnection, ProviderQuota, amount_window, quota_number, read_quota_payload,
)
from core.util import as_dict


class OpenRouterQuota:
    async def get_quota(self, connection: ProviderConnection) -> ProviderQuota:
        if connection.management_api_key:
            # This temporary credential substitution is confined to the credit endpoint.
            return await self._account_credits(replace(
                connection, api_key=connection.management_api_key, management_api_key=None,
            ))
        info = as_dict((await read_quota_payload(connection, "key")).get("data"))
        if info.get("is_management_key") is True:
            return await self._account_credits(connection)
        remaining = quota_number(info.get("limit_remaining"), signed=True)
        window = amount_window("budget", remaining=remaining, unit="USD")
        return ProviderQuota(
            windows=[window] if window else [], checked_at=datetime.now(timezone.utc), scope="api_key",
        )

    async def _account_credits(self, connection: ProviderConnection) -> ProviderQuota:
        credits = as_dict((await read_quota_payload(connection, "credits")).get("data"))
        total = quota_number(credits.get("total_credits"))
        used = quota_number(credits.get("total_usage"))
        # Cumulative purchases are not a spending ceiling. Only expose available funds.
        window = amount_window(
            "balance", remaining=total - used if total is not None and used is not None else None, unit="USD",
        )
        return ProviderQuota(windows=[window] if window else [], checked_at=datetime.now(timezone.utc))
