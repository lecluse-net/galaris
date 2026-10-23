"""Generic business processes without dependencies on a concrete bridge."""

from core.scheduling import PeriodicJobRegistrar, PeriodicJobRemover

from .engine import ProcessEngine, ProcessEngineError
from .fake_engine import FakeProcessEngine
from .models import (
    ProcessDefinition,
    ProcessRun,
    ProcessRunFile,
    ProcessRunEvent,
    ProcessStartJob,
    ProcessNodeRun,
    ProcessNodeAttempt,
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
    ProcessFileInput,
)
from .sanitizer import sanitize as sanitize_process_payload
from .agent_capabilities import build_agent_process_advertisement, agent_process_dispatch_candidates
from .resource_facade import list_process_resources, list_process_run_resources, read_process_resource, read_process_run_resource
from .resource_previews import process_reference, process_resource_preview
from .run_resources import read_run_data, write_run_data, run_file_path, add_run_file, delete_run_file
from .run_resources import prepare_tool_deletion
from app.tools.facade import register_tool_deletion_cleanup

register_tool_deletion_cleanup("process", prepare_tool_deletion)
from .process_service import has_process_definitions, list_run_summaries_page_for_scope
from . import process_service, registry
from .retention import register_retention_guard
from .replacement import replacement_blocked_task_ids, coordinate_replacement
from .program_contracts import ProgramExecutor, register_program_executor
from .isolated_code import CodeInvocation, CodeObservation, IsolatedCodeRunner, register_isolated_code_runner

registry.register(FakeProcessEngine())
from .native_engine import NativeProcessEngine
registry.register(NativeProcessEngine())


async def configure_default_engine(register: PeriodicJobRegistrar, unregister: PeriodicJobRemover) -> None:
    """Apply and watch database-backed process-engine configuration."""
    from core.params import runtime_settings
    from core.params import Params, params_service

    registry.set_default(runtime_settings.PROCESS_ENGINE_DEFAULT)

    async def refresh_process_runtime(name: str, _value: str | None) -> None:
        if name == Params.PROCESS_ENGINE_DEFAULT:
            registry.set_default(runtime_settings.PROCESS_ENGINE_DEFAULT)
        if name == Params.PROCESS_REFRESH_STALENESS_SECONDS:
            register_scheduler_jobs(register, unregister)

    params_service.register_change_listener(refresh_process_runtime)

def register_scheduler_jobs(register: PeriodicJobRegistrar, unregister: PeriodicJobRemover) -> None:
    """Register maintenance jobs after all modules load, avoiding import cycles."""
    from core.params import runtime_settings
    from functools import partial
    from .engine import IntegratedProcessEngine
    from .workers import start_engine_jobs
    from .activity_jobs import run_external_activity_jobs
    from .human_requests import deliver_human_requests
    from app.llm import register_trace_release
    from .retention import released_trace_ids

    register_trace_release("process_run", released_trace_ids)

    unregister("process-outbox")
    unregister("process-refresh")
    register("process-external-activities", run_external_activity_jobs, interval=1.0, timeout=360)
    register("process-human-requests", deliver_human_requests, interval=1.0, timeout=60)
    for code in registry.codes():
        engine = registry.get(code)
        start_timeout = engine.start_timeout_seconds if isinstance(engine, IntegratedProcessEngine) else runtime_settings.PROCESS_START_TIMEOUT_SECONDS
        refresh_timeout = engine.refresh_timeout_seconds if isinstance(engine, IntegratedProcessEngine) else runtime_settings.PROCESS_REFRESH_TIMEOUT_SECONDS
        register(
            f"process-outbox:{code}", partial(start_engine_jobs, code), interval=1.0,
            timeout=start_timeout + 60,
        )
        register(
            f"process-refresh:{code}",
            partial(process_service.refresh_active_runs, engine_code=code, parallel=True, batch_size=4),
            interval=1.0 if code == "galaris" else max(1.0, min(float(runtime_settings.PROCESS_REFRESH_STALENESS_SECONDS or 1), 10.0)),
            timeout=refresh_timeout + 60,
        )
    register(
        "process-retention", process_service.purge_retention, interval=3600.0
    )

from .human_directory import (ProcessHumanContact, ProcessHumanDirectory, register_process_human_directory,
    ProcessHumanRequest, ProcessHumanMessenger, register_process_human_messenger)

__all__ = [
    "ProcessHumanContact", "ProcessHumanDirectory", "register_process_human_directory",
    "ProcessHumanRequest", "ProcessHumanMessenger", "register_process_human_messenger",
    "ProcessDefinition",
    "ProgramExecutor", "register_program_executor",
    "CodeInvocation", "CodeObservation", "IsolatedCodeRunner", "register_isolated_code_runner",
    "ProcessEngine",
    "ProcessEngineError",
    "ProcessRun",
    "ProcessRunFile",
    "read_run_data", "write_run_data", "run_file_path", "add_run_file", "delete_run_file",
    "ProcessRunEvent",
    "ProcessStartJob",
    "ProcessNodeRun",
    "ProcessNodeAttempt",
    "EngineError",
    "EngineProcessDefinition",
    "EngineRunReference",
    "EngineRunSnapshot",
    "EngineStartResult",
    "ProcessEngineHealth",
    "ProcessRunRead",
    "ProcessStartPayload",
    "ProcessFileInput",
    "build_agent_process_advertisement",
    "agent_process_dispatch_candidates",
    "list_process_resources",
    "has_process_definitions",
    "list_run_summaries_page_for_scope",
    "read_process_resource",
    "read_process_run_resource",
    "list_process_run_resources",
    "process_reference",
    "process_resource_preview",
    "process_service",
    "registry",
    "configure_default_engine",
    "register_scheduler_jobs",
    "register_retention_guard",
    "replacement_blocked_task_ids",
    "coordinate_replacement",
    "sanitize_process_payload",
]

from .events import register_events

register_events()
