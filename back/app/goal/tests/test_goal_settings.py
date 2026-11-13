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


@pytest.mark.parametrize(
    ("common", "own", "eligible", "expected"),
    [
        # No restrictions, and eligibility already inside both windows.
        ([], [], "2026-07-17T08:30:00+00:00", "2026-07-17T08:30:00+00:00"),
        ([([4], "09:00", "17:00")], [([4], "10:00", "18:00")],
         "2026-07-17T08:30:00+00:00", "2026-07-17T08:30:00+00:00"),
        # An excluded end boundary moves to the next opening, even with a daily delay.
        ([], [([4, 5], "09:00", "17:00")],
         "2026-07-17T15:00:00+00:00", "2026-07-18T07:00:00+00:00"),
        ([([0], "09:00", "17:00")], [],
         "2026-07-19T10:00:00+00:00", "2026-07-20T07:00:00+00:00"),
        # Opening each schedule separately is insufficient: find their intersection.
        ([([0], "10:00", "18:00")], [([0, 5], "09:00", "17:00")],
         "2026-07-17T16:00:00+00:00", "2026-07-20T08:00:00+00:00"),
        ([([0], "09:00", "10:00")], [([0], "10:00", "11:00")],
         "2026-07-17T16:00:00+00:00", None),
        # An overnight window belongs to its starting weekday, including after midnight.
        ([([0], "22:00", "02:00")], [([1], "01:00", "03:00")],
         "2026-07-13T23:30:00+00:00", "2026-07-13T23:30:00+00:00"),
        ([([0], "22:00", "02:00")], [([1], "01:00", "03:00")],
         "2026-07-13T19:00:00+00:00", "2026-07-13T23:00:00+00:00"),
        # Unsorted and overlapping windows still produce the earliest opening.
        ([([0], "14:00", "18:00"), ([0], "09:00", "12:00")],
         [([0], "11:00", "15:00"), ([0], "10:00", "13:00")],
         "2026-07-20T06:00:00+00:00", "2026-07-20T08:00:00+00:00"),
        # Timezone offsets follow the actual date of opening across DST transitions.
        ([], [([6], "09:00", "17:00")],
         "2026-03-28T18:00:00+00:00", "2026-03-29T07:00:00+00:00"),
        ([], [([6], "09:00", "17:00")],
         "2026-10-24T18:00:00+00:00", "2026-10-25T08:00:00+00:00"),
        # A nonexistent spring opening must not be announced as executable.
        ([], [([6], "02:30", "03:00")],
         "2026-03-28T18:00:00+00:00", "2026-04-05T00:30:00+00:00"),
        # The repeated autumn hour uses the same boundaries as runner admission.
        ([], [([6], "02:30", "02:45")],
         "2026-10-25T01:00:00+00:00", "2026-11-01T01:30:00+00:00"),
    ],
)
def test_next_schedule_at_is_the_first_common_executable_instant(
    monkeypatch: pytest.MonkeyPatch, common, own, eligible: str, expected: str | None,
) -> None:
    monkeypatch.setenv("TZ", "Europe/Paris")

    def schedule(windows) -> GoalScheduleConfig:
        return GoalScheduleConfig(
            schedule_enabled=bool(windows),
            schedule=[GoalScheduleWindow(weekdays=days, start_time=start, end_time=end)
                      for days, start, end in windows],
        )

    config = GoalSettingsConfig(**schedule(common).model_dump())
    individual = schedule(own)
    result = settings_service.next_schedule_at(
        individual, config, not_before=datetime.fromisoformat(eligible),
    )
    assert result == (datetime.fromisoformat(expected) if expected is not None else None)
    if result is not None:
        assert settings_service.evaluate_settings(config, now=result).is_active
        assert settings_service.is_goal_processing_allowed(individual, now=result)


def test_next_schedule_does_not_announce_a_cycle_while_globally_paused() -> None:
    assert settings_service.next_schedule_at(
        GoalScheduleConfig(), GoalSettingsConfig(globally_paused=True),
        not_before=datetime(2026, 7, 17, tzinfo=timezone.utc),
    ) is None


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
    events = {call.args[0]: call.args[2] for call in emit.await_args_list}
    assert set(events) == {"goal_settings", "goal_runtime"}
    assert "schedule" in events["goal_settings"]
    assert "schedule" not in events["goal_runtime"]


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
