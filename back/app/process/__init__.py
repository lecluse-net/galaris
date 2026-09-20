"""Generic business processes without dependencies on a concrete bridge."""

from .engine import ProcessEngine, ProcessEngineError
from .fake_engine import FakeProcessEngine
from .models import (
    ProcessDefinition,
    ProcessRun,
    ProcessRunEvent,
    ProcessStartJob,
)
from .schemas import (
    EngineError,
    EngineProcessDefinition,
    EngineRunReference,
    EngineRunSnapshot,
    EngineStartResult,
    ProcessEngineHealth,
    ProcessRunRead,
    ProcessStartPayload,
)
from .sanitizer import sanitize as sanitize_process_payload
from .agent_capabilities import build_agent_process_advertisement
from .resource_facade import list_process_resources, read_process_resource
from .process_service import has_process_definitions, list_run_summaries_page_for_scope
from . import process_service, registry
from .retention import register_retention_guard
from .replacement import replacement_blocked_task_ids

registry.register(FakeProcessEngine())


async def configure_default_engine() -> None:
    """Apply and watch database-backed process-engine configuration."""
    from core.params import runtime_settings
    from core.params import Params, params_service

    registry.set_default(runtime_settings.PROCESS_ENGINE_DEFAULT)

    async def refresh_process_runtime(name: str, _value: str | None) -> None:
        if name == Params.PROCESS_ENGINE_DEFAULT:
            registry.set_default(runtime_settings.PROCESS_ENGINE_DEFAULT)
        if name == Params.PROCESS_REFRESH_STALENESS_SECONDS:
            register_scheduler_jobs()

    params_service.register_change_listener(refresh_process_runtime)

def register_scheduler_jobs() -> None:
    """Register maintenance jobs after all modules load, avoiding import cycles."""
    from app.task import scheduler
    from core.params import runtime_settings
    from functools import partial
    from .engine import IntegratedProcessEngine
    from .workers import start_engine_jobs
    from app.llm import register_trace_release
    from .retention import released_trace_ids

    register_trace_release("process_run", released_trace_ids)

    scheduler.unregister_periodic_job("process-outbox")
    scheduler.unregister_periodic_job("process-refresh")
    for code in registry.codes():
        engine = registry.get(code)
        start_timeout = engine.start_timeout_seconds if isinstance(engine, IntegratedProcessEngine) else runtime_settings.PROCESS_START_TIMEOUT_SECONDS
        refresh_timeout = engine.refresh_timeout_seconds if isinstance(engine, IntegratedProcessEngine) else runtime_settings.PROCESS_REFRESH_TIMEOUT_SECONDS
        scheduler.register_periodic_job(
            f"process-outbox:{code}", partial(start_engine_jobs, code), interval=1.0,
            timeout=start_timeout + 60,
        )
        scheduler.register_periodic_job(
            f"process-refresh:{code}",
            partial(process_service.refresh_active_runs, engine_code=code, parallel=True, batch_size=4),
            interval=max(1.0, min(float(runtime_settings.PROCESS_REFRESH_STALENESS_SECONDS or 1), 10.0)),
            timeout=refresh_timeout + 60,
        )
    scheduler.register_periodic_job(
        "process-retention", process_service.purge_retention, interval=3600.0
    )

__all__ = [
    "ProcessDefinition",
    "ProcessEngine",
    "ProcessEngineError",
    "ProcessRun",
    "ProcessRunEvent",
    "ProcessStartJob",
    "EngineError",
    "EngineProcessDefinition",
    "EngineRunReference",
    "EngineRunSnapshot",
    "EngineStartResult",
    "ProcessEngineHealth",
    "ProcessRunRead",
    "ProcessStartPayload",
    "build_agent_process_advertisement",
    "list_process_resources",
    "has_process_definitions",
    "list_run_summaries_page_for_scope",
    "read_process_resource",
    "process_service",
    "registry",
    "configure_default_engine",
    "register_scheduler_jobs",
    "register_retention_guard",
    "replacement_blocked_task_ids",
    "sanitize_process_payload",
]

from .events import register_events

register_events()
