from unittest.mock import AsyncMock

import pytest

from app.connection import facade as connection_service
from app.tools.admin_access import require_galaris_admin_access


@pytest.mark.asyncio
async def test_galaris_admin_access_requires_an_active_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    witness = AsyncMock(return_value=False)
    monkeypatch.setattr(connection_service, "has_active_tool_connection", witness)

    with pytest.raises(PermissionError, match="galaris_admin"):
        await require_galaris_admin_access(42)

    witness.assert_awaited_once_with(
        agent_id=42,
        tool_code="galaris_admin",
    )


@pytest.mark.asyncio
async def test_galaris_admin_access_accepts_an_active_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    witness = AsyncMock(return_value=True)
    monkeypatch.setattr(connection_service, "has_active_tool_connection", witness)

    await require_galaris_admin_access(42)
