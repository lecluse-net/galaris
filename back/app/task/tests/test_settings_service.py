from unittest.mock import Mock

import pytest

from app.task import settings_service
from core.params import Params


@pytest.mark.asyncio
async def test_task_parameter_change_wakes_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake = Mock()
    monkeypatch.setattr(settings_service.scheduler, "wake", wake)

    await settings_service.on_parameter_change(
        Params.TASK_SCHEDULER_MAX_CONCURRENCY,
        "4",
    )

    wake.assert_called_once_with()


@pytest.mark.asyncio
async def test_unrelated_parameter_does_not_wake_scheduler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wake = Mock()
    monkeypatch.setattr(settings_service.scheduler, "wake", wake)

    await settings_service.on_parameter_change(Params.SEARCH_TIMEOUT, "15")

    wake.assert_not_called()
