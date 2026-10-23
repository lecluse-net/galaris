from unittest.mock import AsyncMock

import pytest

from app.connection import facade as connection_service
from app.tools.admin_access import require_galaris_admin_access


@pytest.mark.asyncio
async def test_galaris_admin_access_requires_an_active_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    witness = AsyncMock(return_value="usage")
    monkeypatch.setattr(connection_service, "get_management_scope", witness)

    with pytest.raises(PermissionError, match="galaris_admin"):
        await require_galaris_admin_access(42)

    witness.assert_awaited_once_with(42, "galaris_admin")


@pytest.mark.asyncio
async def test_galaris_admin_access_accepts_an_active_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    witness = AsyncMock(return_value="all")
    monkeypatch.setattr(connection_service, "get_management_scope", witness)

    await require_galaris_admin_access(42)
