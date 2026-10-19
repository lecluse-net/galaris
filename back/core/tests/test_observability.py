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


@pytest.mark.parametrize("environment", ["", "dev", "prod", "pp", "test", "demo", "custom"])
def test_exception_sinks_keep_tracebacks_without_local_secrets(tmp_path, environment):
    """Exercise both configured sinks and the stdlib bridge in an isolated process."""
    import subprocess
    import sys

    script = tmp_path / "synthetic_logging_failure.py"
    # A real source file is necessary: Loguru cannot inspect locals from python -c.
    script.write_text('''
import io
import logging
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.getcwd())
os.environ["LOGURU_DIAGNOSE"] = "YES"
from asyncpg.exceptions import CannotConnectNowError
from loguru import logger
from core import settings
from core.logging import setup_logging

settings.APP_ENV = sys.argv[1]
settings.LOG_LEVEL = "INFO"
console = io.StringIO()
mirrored = []

class CaptureHandler(logging.Handler):
    def emit(self, record):
        mirrored.append(record.getMessage())

def refuse_connection(parameters):
    try:
        raise OSError("synthetic connection refused")
    except OSError as cause:
        raise CannotConnectNowError("synthetic database is shutting down") from cause

def connect():
    parameters = {"password": "synthetic-db-password-never-log"}
    refuse_connection(parameters)

with patch("sys.stdout", console), patch("logfire.LogfireLoggingHandler", return_value=CaptureHandler()):
    setup_logging()
    for standard_logging in (False, True):
        try:
            connect()
        except CannotConnectNowError:
            if standard_logging:
                logging.getLogger("synthetic.database").exception("Synthetic database unavailable")
            else:
                logger.exception("Synthetic database unavailable")
    logger.remove()

for output in (console.getvalue(), "\\n".join(mirrored)):
    assert "synthetic-db-password-never-log" not in output
    assert output.count("Synthetic database unavailable") == 2
    assert output.count("CannotConnectNowError: synthetic database is shutting down") == 2
    assert output.count("OSError: synthetic connection refused") == 2
    assert "Traceback (most recent call last)" in output
    assert 'in refuse_connection' in output
''', encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), environment],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_sql_traces_keep_parent_duration_and_errors_without_varying_query_text(monkeypatch):
    """The configured SQL instrumentation preserves diagnostics and reusable SQL."""
    import json
    import subprocess
    import sys

    configure = Mock()
    sql_instrument = Mock()
    monkeypatch.setattr(observability, "_configured", False)
    monkeypatch.setattr(runtime_settings, "LOGFIRE_TOKEN", "")
    monkeypatch.setattr(observability.logfire, "configure", configure)
    monkeypatch.setattr(observability.logfire, "instrument_sqlalchemy", sql_instrument)
    for name in ("instrument_httpx", "instrument_pydantic_ai", "instrument_system_metrics"):
        monkeypatch.setattr(observability.logfire, name, Mock())
    observability.configure_observability()
    options = {key: value for key, value in sql_instrument.call_args.kwargs.items() if key != "engine"}
    # A separate interpreter avoids replacing the test application's global OTel
    # instrumentor. SQLite and the span exporter are entirely in memory.
    subprocess.run([sys.executable, "-c", '''
import json, sys
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DBAPIError
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.trace import SpanKind, StatusCode
provider = TracerProvider()
exporter = InMemorySpanExporter()
provider.add_span_processor(SimpleSpanProcessor(exporter))
engine = create_engine("sqlite:///:memory:")
SQLAlchemyInstrumentor().instrument(engine=engine, tracer_provider=provider, **json.loads(sys.argv[1]))
statements = []
@event.listens_for(engine, "before_cursor_execute")
def capture(conn, cursor, statement, parameters, context, executemany):
    statements.append(statement)
with engine.connect() as connection:
    with provider.get_tracer("synthetic").start_as_current_span("request") as parent:
        parent_context = parent.get_span_context()
        for _ in range(2):
            assert connection.scalar(text("SELECT 1")) == 1
        try:
            connection.execute(text("SELECT * FROM synthetic_missing_table"))
        except DBAPIError:
            pass
spans = [span for span in exporter.get_finished_spans()
         if span.kind == SpanKind.CLIENT and span.parent and span.parent.span_id == parent_context.span_id]
assert len(spans) == 3
assert all(span.context.trace_id == parent_context.trace_id for span in spans)
assert all(span.end_time > span.start_time for span in spans)
assert all("db.statement" in span.attributes or "db.query.text" in span.attributes for span in spans)
assert sum(span.status.status_code == StatusCode.ERROR for span in spans) == 1
assert len(set(statements[:2])) == 1, "Repeated SQL must reuse the same query text"
engine.dispose()
provider.shutdown()
''', json.dumps(options)], check=True, capture_output=True, text=True, timeout=30)
