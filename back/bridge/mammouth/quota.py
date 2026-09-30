"""Mammouth API key spending; application session quotas are separate."""

from dataclasses import replace
from datetime import datetime, timezone

from app.llm.facade import (
    ProviderConnection, ProviderQuota, amount_window, quota_number, quota_reset, read_quota_payload,
)
from core.util import as_dict


class MammouthQuota:
    async def get_quota(self, connection: ProviderConnection) -> ProviderQuota:
        # /key/info is outside the OpenAI-compatible /v1 namespace.
        root = replace(connection, base_url=connection.base_url.rstrip('/').removesuffix('/v1'))
        payload = await read_quota_payload(root, "key/info")
        info = as_dict(payload.get("info"))
        window = amount_window(
            "budget", used=quota_number(info.get("spend")), limit=quota_number(info.get("max_budget")),
            unit="USD", resets_at=quota_reset(info.get("budget_reset_at")),
        )
        return ProviderQuota(
            windows=[window] if window else [], checked_at=datetime.now(timezone.utc), scope="api_key",
        )
