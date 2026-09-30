"""Account credits from ElevenLabs' documented subscription endpoint."""

from datetime import datetime, timezone

from app.llm.facade import (
    ProviderConnection, ProviderQuota, amount_window, quota_number, quota_reset, read_quota_payload,
)


class ElevenLabsQuota:
    async def get_quota(self, connection: ProviderConnection) -> ProviderQuota:
        payload = await read_quota_payload(connection, "user/subscription", auth_header="xi-api-key")
        window = amount_window(
            "credits", used=quota_number(payload.get("character_count")),
            limit=quota_number(payload.get("character_limit")),
            resets_at=quota_reset(payload.get("next_character_count_reset_unix")),
        )
        return ProviderQuota(windows=[window] if window else [], checked_at=datetime.now(timezone.utc))
