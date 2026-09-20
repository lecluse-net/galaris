from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.goal import goal_service, runner, settings_service
from app.goal.schemas import (
    GoalScheduleConfig,
    GoalScheduleWindow,
    GoalSettingsConfig,
    GoalSettingsUpdate,
)


def _example_schedule(**changes: object) -> GoalScheduleConfig:
    payload: dict[str, object] = {
        "schedule_enabled": True,
        "schedule": [
            {
                "weekdays": [3, 4, 5],
                "start_time": "09:00",
                "end_time": "17:00",
            }
        ],
    }
    payload.update(changes)
    return GoalScheduleConfig.model_validate(payload)


def test_schedule_window_normalizes_days_and_rejects_zero_length() -> None:
    window = GoalScheduleWindow(
        weekdays=[5, 3, 5, 4],
        start_time="09:00",
        end_time="17:00",
    )
    assert window.weekdays == [3, 4, 5]

    with pytest.raises(ValidationError):
        GoalScheduleWindow(
            weekdays=[3],
            start_time="09:00",
            end_time="09:00",
        )


def test_enabled_schedule_requires_a_window_and_updates_are_not_empty() -> None:
    with pytest.raises(ValidationError):
        GoalScheduleConfig(schedule_enabled=True)
    with pytest.raises(ValidationError):
        GoalSettingsUpdate()
    with pytest.raises(ValidationError):
        GoalSettingsUpdate.model_validate({"globally_paused": None})


def test_example_schedule_uses_application_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")
    config = _example_schedule()

    friday_open, next_opening = settings_service.evaluate_goal_schedule(
        config,
        now=datetime(2026, 7, 17, 8, 30, tzinfo=timezone.utc),
    )
    assert friday_open is True
    assert next_opening is None

    friday_closed, next_opening = settings_service.evaluate_goal_schedule(
        config,
        now=datetime(2026, 7, 17, 16, 0, tzinfo=timezone.utc),
    )
    assert friday_closed is False
    assert next_opening == datetime(
        2026, 7, 18, 7, 0, tzinfo=timezone.utc
    )


def test_global_pause_has_priority_over_the_common_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")
    result = settings_service.evaluate_settings(
        GoalSettingsConfig(globally_paused=True),
        now=datetime(2026, 7, 17, 8, 30, tzinfo=timezone.utc),
    )

    assert result.is_active is False
    assert result.inactive_reason == "GLOBAL_PAUSE"


def test_global_schedule_blocks_every_goal_outside_common_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")
    config = GoalSettingsConfig(
        schedule_enabled=True,
        schedule=[
            GoalScheduleWindow(
                weekdays=[0, 1, 2, 3, 4, 5],
                start_time="09:00",
                end_time="17:00",
            )
        ],
    )

    sunday = settings_service.evaluate_settings(
        config,
        now=datetime(2026, 7, 19, 10, 0, tzinfo=timezone.utc),
    )
    monday = settings_service.evaluate_settings(
        config,
        now=datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
    )

    assert sunday.is_active is False
    assert sunday.inactive_reason == "OUTSIDE_SCHEDULE"
    assert sunday.next_active_at == datetime(2026, 7, 20, 7, 0, tzinfo=timezone.utc)
    assert monday.is_active is True
    assert monday.inactive_reason is None


def test_schedule_window_can_cross_midnight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")
    config = GoalScheduleConfig(
        schedule_enabled=True,
        schedule=[
            GoalScheduleWindow(
                weekdays=[0],
                start_time="22:00",
                end_time="02:00",
            )
        ],
    )

    is_active, _ = settings_service.evaluate_goal_schedule(
        config,
        now=datetime(2026, 7, 13, 23, 0, tzinfo=timezone.utc),
    )
    assert is_active is True


@pytest.mark.asyncio
async def test_process_goals_blocks_new_cycles_while_globally_paused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AsyncMock(
        return_value=SimpleNamespace(
            is_active=False,
            inactive_reason="GLOBAL_PAUSE",
        )
    )
    wait = AsyncMock()
    terminal = AsyncMock()
    start = AsyncMock()
    monkeypatch.setattr(settings_service, "get_settings", settings)
    monkeypatch.setattr("app.goal.referrer_wait.process_due_referrer_wait", wait)
    monkeypatch.setattr(runner, "process_terminal_cycle", terminal)
    monkeypatch.setattr(runner, "start_due_cycle", start)

    await runner.process_goals()

    settings.assert_awaited_once()
    terminal.assert_awaited_once_with()
    wait.assert_not_awaited()
    start.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_goals_starts_only_manual_cycles_outside_global_schedule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AsyncMock(
        return_value=SimpleNamespace(
            is_active=False,
            inactive_reason="OUTSIDE_SCHEDULE",
        )
    )
    wait = AsyncMock()
    terminal = AsyncMock()
    start = AsyncMock()
    monkeypatch.setattr(settings_service, "get_settings", settings)
    monkeypatch.setattr("app.goal.referrer_wait.process_due_referrer_wait", wait)
    monkeypatch.setattr(runner, "process_terminal_cycle", terminal)
    monkeypatch.setattr(runner, "start_due_cycle", start)

    await runner.process_goals()

    settings.assert_awaited_once()
    terminal.assert_awaited_once_with()
    wait.assert_not_awaited()
    start.assert_awaited_once_with(manual_only=True)


@pytest.mark.asyncio
async def test_process_goals_runs_referrer_waits_and_due_cycles_when_globally_active(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = AsyncMock(
        return_value=SimpleNamespace(
            is_active=True,
            inactive_reason=None,
        )
    )
    wait = AsyncMock()
    terminal = AsyncMock()
    start = AsyncMock()
    monkeypatch.setattr(settings_service, "get_settings", settings)
    monkeypatch.setattr("app.goal.referrer_wait.process_due_referrer_wait", wait)
    monkeypatch.setattr(runner, "process_terminal_cycle", terminal)
    monkeypatch.setattr(runner, "start_due_cycle", start)

    await runner.process_goals()

    settings.assert_awaited_once()
    terminal.assert_awaited_once_with()
    wait.assert_awaited_once_with()
    start.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_global_settings_update_refreshes_stale_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = GoalSettingsConfig()
    save = AsyncMock(side_effect=[False, True])
    refresh = AsyncMock()
    emit = AsyncMock()
    monkeypatch.setattr(settings_service, "get_config", AsyncMock(return_value=config))
    monkeypatch.setattr(settings_service.params_service, "set", save)
    monkeypatch.setattr(settings_service.params_service, "refresh", refresh)
    monkeypatch.setattr(settings_service.websocket, "emit", emit)

    result = await settings_service.update_settings(
        GoalSettingsUpdate(globally_paused=True)
    )

    assert result.globally_paused is True
    refresh.assert_awaited_once()
    assert save.await_count == 2
    saved_payload = json.loads(save.await_args_list[-1].args[1])
    assert saved_payload == {
        "globally_paused": True,
        "schedule_enabled": False,
        "schedule": [],
    }
    emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_global_schedule_update_is_persisted_with_the_pause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    save = AsyncMock(return_value=True)
    monkeypatch.setattr(
        settings_service,
        "get_config",
        AsyncMock(return_value=GoalSettingsConfig(globally_paused=True)),
    )
    monkeypatch.setattr(settings_service.params_service, "set", save)
    monkeypatch.setattr(settings_service.websocket, "emit", AsyncMock())

    result = await settings_service.update_settings(
        GoalSettingsUpdate(
            schedule_enabled=True,
            schedule=[
                GoalScheduleWindow(
                    weekdays=[0, 1, 2, 3, 4, 5],
                    start_time="08:00",
                    end_time="18:00",
                )
            ],
        )
    )

    assert result.globally_paused is True
    assert result.schedule_enabled is True
    saved_payload = json.loads(save.await_args.args[1])
    assert saved_payload["schedule"][0]["weekdays"] == [0, 1, 2, 3, 4, 5]


def test_persisted_global_schedule_is_loaded_as_the_common_gate() -> None:
    config = settings_service._decode(  # pyright: ignore[reportPrivateUsage]
        json.dumps(
            {
                "globally_paused": True,
                "schedule_enabled": True,
                "schedule": [
                    {"weekdays": [0], "start_time": "09:00", "end_time": "17:00"}
                ],
            }
        )
    )

    assert config == GoalSettingsConfig(
        globally_paused=True,
        schedule_enabled=True,
        schedule=[
            GoalScheduleWindow(
                weekdays=[0],
                start_time="09:00",
                end_time="17:00",
            )
        ],
    )
