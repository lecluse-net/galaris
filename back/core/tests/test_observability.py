"""Observability safety contracts."""

from fastapi import FastAPI
import logging
import pytest
from unittest.mock import Mock

from core import settings
from core import observability
from core.params import runtime_settings


@pytest.mark.parametrize(
    ("configured_level", "expected"),
    [
        ("TRACE", logging.DEBUG),
        ("DEBUG", logging.DEBUG),
        ("SUCCESS", logging.INFO),
        ("WARNING", logging.WARNING),
    ],
)
def test_loguru_levels_map_to_logfire(
    monkeypatch: pytest.MonkeyPatch,
    configured_level: str,
    expected: int,
) -> None:
    monkeypatch.setattr(settings, "LOG_LEVEL", configured_level)
    assert observability._logfire_min_level() == expected


@pytest.mark.parametrize("environment", ["dev", "prod", "pp", "test", "demo", "custom"])
def test_environment_label_preserves_framework_instrumentation(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", environment)
    instrument = Mock()
    monkeypatch.setattr(observability.logfire, "instrument_fastapi", instrument)
    app = FastAPI()
    observability.instrument_fastapi(app)
    assert instrument.call_args.args == (app,)
    assert instrument.call_args.kwargs["capture_headers"] is False


@pytest.mark.parametrize("environment", ["dev", "prod", "pp", "test", "demo", "custom"])
def test_telemetry_preserves_label_without_special_test_mode(monkeypatch, environment):
    configure = Mock()
    monkeypatch.setattr(settings, "APP_ENV", environment)
    monkeypatch.setattr(observability, "_configured", False)
    monkeypatch.setattr(runtime_settings, "LOGFIRE_TOKEN", "")
    monkeypatch.setenv("LOGFIRE_TOKEN", "obsolete-env-token-must-not-enable-export")
    monkeypatch.setattr(observability.logfire, "configure", configure)
    instruments = [Mock() for _ in range(4)]
    for name, instrument in zip(
        ("instrument_httpx", "instrument_sqlalchemy", "instrument_pydantic_ai", "instrument_system_metrics"),
        instruments,
    ):
        monkeypatch.setattr(observability.logfire, name, instrument)
    observability.configure_observability()
    assert configure.call_args.kwargs["environment"] == environment
    assert configure.call_args.kwargs["send_to_logfire"] is False
    assert all(instrument.call_count == 1 for instrument in instruments)


def test_token_changes_switch_export_without_reinstrumenting(monkeypatch):
    configure = Mock()
    monkeypatch.setattr(observability, '_configured', False)
    monkeypatch.setattr(observability, '_configured_token', None)
    monkeypatch.setattr(runtime_settings, 'LOGFIRE_TOKEN', '')
    monkeypatch.setattr(observability.logfire, 'configure', configure)
    instruments = [Mock() for _ in range(4)]
    for name, instrument in zip(
        ('instrument_httpx', 'instrument_sqlalchemy', 'instrument_pydantic_ai', 'instrument_system_metrics'), instruments,
    ):
        monkeypatch.setattr(observability.logfire, name, instrument)
    observability.configure_observability()
    assert configure.call_args.kwargs['send_to_logfire'] is False
    for token in ('first-external-token', 'replacement-external-token', ''):
        runtime_settings.LOGFIRE_TOKEN = token
        observability.configure_observability()
        assert configure.call_args.kwargs['token'] == token
        assert configure.call_args.kwargs['send_to_logfire'] is bool(token)
        observability.configure_observability()
    assert configure.call_count == 4
    assert all(instrument.call_count == 1 for instrument in instruments)


@pytest.mark.asyncio
async def test_failed_export_configuration_keeps_token_out_of_logs_and_can_retry(monkeypatch):
    from loguru import logger

    token = 'sensitive-submitted-logfire-token'
    configure = Mock(side_effect=ValueError(token))
    monkeypatch.setattr(observability, '_configured', True)
    monkeypatch.setattr(observability, '_configured_token', '')
    monkeypatch.setattr(runtime_settings, 'LOGFIRE_TOKEN', token)
    monkeypatch.setattr(observability.logfire, 'configure', configure)
    messages = []
    sink = logger.add(messages.append, format='{message}')
    try:
        await observability._on_parameter_change('LOGFIRE_TOKEN', token)
        assert messages and all(token not in str(message) for message in messages)
        assert observability._configured_token == ''
        configure.side_effect = None
        await observability._on_parameter_change('LOGFIRE_TOKEN', token)
        assert observability._configured_token == token
    finally:
        logger.remove(sink)


def test_test_harness_does_not_export_or_join_external_traces(monkeypatch):
    from tests.runtime_isolation import isolated_api_import

    configure = Mock()
    monkeypatch.setattr(observability.logfire, "configure", configure)
    with isolated_api_import():
        pass
    assert configure.call_args.kwargs["send_to_logfire"] is False
    assert configure.call_args.kwargs["distributed_tracing"] is False
