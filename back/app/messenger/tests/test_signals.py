from unittest.mock import AsyncMock

import pytest

from app.messenger.events import Signal


@pytest.mark.asyncio
async def test_notification_failure_does_not_fail_business_admission():
    signal = Signal("incoming")
    notification = AsyncMock(side_effect=RuntimeError("socket unavailable"))
    admission = AsyncMock()
    signal.connect(notification, required=False)
    assert signal.has_receivers
    assert not signal.has_required_receivers
    signal.connect(admission)
    assert signal.has_required_receivers
    assert await signal.send_async_collect("message") == []
    admission.assert_awaited_once_with("message")
    failure = RuntimeError("admission failed")
    admission.side_effect = failure
    assert await signal.send_async_collect("next") == [failure]
    signal.disconnect(admission)
    assert not signal.has_required_receivers
