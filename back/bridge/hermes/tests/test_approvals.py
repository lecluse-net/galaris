from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.messenger.interactions import ChoiceResolution, PendingChoice
from bridge.hermes import approvals, client


def _interaction() -> PendingChoice:
    return PendingChoice(
        id=uuid4(),
        kind=approvals.HERMES_APPROVAL_INTERACTION,
        agent_id=7,
        tool_id=None,
        room_id="room-1",
        user_id="human-1",
        title="Approval",
        body="Approve command",
        options=[],
        metadata={"run_id": "run-gone"},
        expires_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        client.HermesRunNotFound("run-gone"),
        client.HermesApprovalNotPending("run-gone"),
    ],
)
async def test_stale_approval_is_consumed_without_replay(
    monkeypatch: pytest.MonkeyPatch,
    error: RuntimeError,
) -> None:
    import app.agent as agent_domain
    from bridge.hermes import config_service

    agent = SimpleNamespace(code="alice")
    snapshot = {"url": "unused", "api_key": "unused", "model": "unused"}
    target = client.HermesTarget(
        url="http://hermes:8642/v1",
        api_key="test-key",
        model="test-model",
    )
    monkeypatch.setattr(
        agent_domain,
        "get_agent_record",
        AsyncMock(return_value=agent),
    )
    monkeypatch.setattr(
        config_service,
        "execution_snapshot",
        AsyncMock(return_value=snapshot),
    )
    monkeypatch.setattr(
        approvals,
        "HermesTarget",
        SimpleNamespace(
            from_config=lambda config, *, agent_code: (
                target
                if config is snapshot and agent_code == "alice"
                else None
            )
        ),
    )
    submit = AsyncMock(side_effect=error)
    monkeypatch.setattr(approvals.client, "submit_run_approval", submit)
    interaction = _interaction()
    resolution = ChoiceResolution(
        interaction_id=interaction.id,
        kind=interaction.kind,
        option_id="session",
        metadata={},
    )

    await approvals._handle_hermes_approval(  # pyright: ignore[reportPrivateUsage]
        interaction,
        resolution,
    )

    submit.assert_awaited_once_with(target, "run-gone", "session")
