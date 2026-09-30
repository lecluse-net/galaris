"""Remaining credits for SunoAPI.org, distinct from the official Suno subscription."""

from datetime import datetime, timezone

from app.llm.facade import (
    ProviderAuthenticationError, ProviderConnection, ProviderQuota, amount_window, quota_number, read_quota_payload,
)
from core.i18n import tr


class SunoApiQuota:
    async def get_quota(self, connection: ProviderConnection) -> ProviderQuota:
        payload = await read_quota_payload(connection, "generate/credit")
        if payload.get("code") != 200:
            raise ProviderAuthenticationError(
                await tr("llm_api.errors.provider_quota_unavailable"), code="provider_quota_unavailable",
            )
        window = amount_window("credits", remaining=quota_number(payload.get("data")))
        return ProviderQuota(windows=[window] if window else [], checked_at=datetime.now(timezone.utc))
