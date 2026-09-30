"""DeepSeek reports monetary balances, without an original spending ceiling."""

from dataclasses import replace
from datetime import datetime, timezone

from app.llm.facade import (
    ProviderConnection, ProviderQuota, ProviderQuotaWindow, amount_window, quota_number, read_quota_payload,
)
from core.util import as_dict, as_list


class DeepSeekQuota:
    async def get_quota(self, connection: ProviderConnection) -> ProviderQuota:
        root = replace(connection, base_url=connection.base_url.rstrip('/').removesuffix('/v1'))
        payload = await read_quota_payload(root, "user/balance")
        windows: list[ProviderQuotaWindow] = []
        for raw in as_list(payload.get("balance_infos")):
            info = as_dict(raw)
            currency = info.get("currency")
            if currency not in {"USD", "CNY"}:
                continue
            window = amount_window(
                "balance", remaining=quota_number(info.get("total_balance"), signed=True),
                unit="USD" if currency == "USD" else "CNY",
            )
            if window is not None:
                windows.append(window)
        return ProviderQuota(windows=windows, checked_at=datetime.now(timezone.utc))
