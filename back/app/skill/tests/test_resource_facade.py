from unittest.mock import AsyncMock

import pytest

from app.connection import connection_service
from app.skill.resource_facade import (
    can_manage_skill_resources,
    require_skill_management_access,
)


@pytest.mark.asyncio
async def test_skill_file_access_requires_the_live_management_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    witness = AsyncMock(return_value=False)
    monkeypatch.setattr(connection_service, "has_active_tool_connection", witness)

    assert await can_manage_skill_resources(42) is False
    with pytest.raises(PermissionError, match="skill_management"):
        await require_skill_management_access(42)

    assert witness.await_count == 2
    witness.assert_awaited_with(
        agent_id=42,
        tool_code="skill_management",
    )


@pytest.mark.asyncio
async def test_skill_file_access_accepts_the_live_management_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    witness = AsyncMock(return_value=True)
    monkeypatch.setattr(connection_service, "has_active_tool_connection", witness)

    await require_skill_management_access(42)

    witness.assert_awaited_once_with(
        agent_id=42,
        tool_code="skill_management",
    )
