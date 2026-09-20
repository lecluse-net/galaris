"""Centralized, privacy-conscious Logfire instrumentation."""

from __future__ import annotations

from fastapi import FastAPI
import logging
import logfire
from loguru import logger
from starlette.concurrency import run_in_threadpool
from threading import Lock

from core import settings
from core.params import Params, params_service, runtime_settings

_configured = False
_configured_token: str | None = None
_configuration_lock = Lock()

_pressure_gauges = {name: logfire.metric_gauge(name) for name in (
    "buffered_io_reserved_bytes", "buffered_io_active_operations", "db_pool_checked_out", "db_pool_capacity",
    "temporary_filesystem_free_bytes",
)}


async def record_runtime_pressure() -> None:
    import shutil
    import tempfile
    from sqlalchemy.pool import QueuePool
    from core.database import engine
    from core.util import buffered_io_budget

    _pressure_gauges["buffered_io_reserved_bytes"].set(buffered_io_budget.used)
    _pressure_gauges["buffered_io_active_operations"].set(buffered_io_budget.active)
    _pressure_gauges["temporary_filesystem_free_bytes"].set(shutil.disk_usage(tempfile.gettempdir()).free)
    if isinstance(engine.pool, QueuePool):
        _pressure_gauges["db_pool_checked_out"].set(engine.pool.checkedout())
        _pressure_gauges["db_pool_capacity"].set(settings.DB_POOL_SIZE + settings.DB_MAX_OVERFLOW)


def _logfire_min_level() -> int:
    """Translate Loguru-only levels to their nearest stdlib equivalent."""

    if settings.LOG_LEVEL == "TRACE":
        return logging.DEBUG
    if settings.LOG_LEVEL == "SUCCESS":
        return logging.INFO
    return int(getattr(logging, settings.LOG_LEVEL))


def configure_observability() -> None:
    """Start locally before DB access; switch exporters when the stored token changes."""
    with _configuration_lock:
        _configure_observability()


def _configure_observability() -> None:
    global _configured, _configured_token
    token = runtime_settings.LOGFIRE_TOKEN
    if _configured and token == _configured_token:
        return

    # Explicit False prevents the SDK from exporting with obsolete environment
    # tokens or credentials files while preferences are empty or not loaded yet.
    # The SDK replaces its providers behind stable proxies on reconfiguration.
    logfire.configure(
        token=token,
        send_to_logfire=bool(token),
        service_name=settings.APP_NAME,
        service_version=settings.APP_VERSION,
        environment=settings.APP_ENV,
        console=False,
        inspect_arguments=False,
        min_level=_logfire_min_level(),
    )
    _configured_token = token
    if _configured:
        return
    _configured = True

    # Avoid capturing headers, bodies and model content: they may contain
    # credentials, prompts, private files or conversation data.
    logfire.instrument_httpx(
        capture_headers=False,
        capture_request_body=False,
        capture_response_body=False,
    )
    from core.database import engine

    logfire.instrument_sqlalchemy(engine=engine, enable_commenter=True)
    logfire.instrument_pydantic_ai(
        include_content=False,
        include_binary_content=False,
        version=3,
    )
    logfire.instrument_system_metrics(base="full")


async def _on_parameter_change(name: str, _value: str | None) -> None:
    if name != Params.LOGFIRE_TOKEN:
        return
    try:
        # SDK exporter shutdown can wait for network I/O; keep it off the API loop.
        await run_in_threadpool(configure_observability)
    except Exception:
        # Never log a traceback with local variables holding a submitted token.
        # Console logging stays available even when this optional export fails.
        logger.error("Could not apply Logfire configuration; save the token again to retry")


async def configure_runtime_observability() -> None:
    """Apply hydrated preferences, then react to committed administrator changes."""
    params_service.register_change_listener(_on_parameter_change)
    await _on_parameter_change(Params.LOGFIRE_TOKEN, None)


def instrument_fastapi(app: FastAPI) -> None:
    """Attach request tracing after the FastAPI instance exists."""

    logfire.instrument_fastapi(
        app,
        capture_headers=False,
        record_send_receive=False,
        excluded_urls=r"/api/(health|ready|live)$",
    )


__all__ = ["configure_observability", "configure_runtime_observability", "instrument_fastapi"]
