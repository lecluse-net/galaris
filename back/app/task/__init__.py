"""Durable task scheduling, state, persistence, and administration."""

# Models and schemas are always available.
from .models import Task, TaskAttemptStatus, TaskStatus
from . import timing_events as _timing_events  # noqa: F401 - persistence observers # pyright: ignore[reportUnusedImport]
from app.agent.contracts import TaskMessage, TaskMessageAttachment
from .schemas import (
    Task as TaskRead,
    TaskCreate,
    TaskCommand,
    TaskUpdate,
    TaskFull,
)
from .privileges import TASK_ACCESS, TASK_EDIT
from .agent_slot import try_lock_agent
from .settings_service import register_runtime_settings
from .activity import has_active_task_work
from .retention import protected_task_ids
from .active_lease import unique_leased_task_for_agent
from .conversation import (
    ConversationFollowup,
    ConversationPredecessor,
    ConversationScope,
    get_conversation_followup,
    get_conversation_predecessor,
    get_conversation_scope,
)
from .outcome import TaskOutcomeObservation, get_task_outcome_observation
from .startup_timing import STARTUP_TIMING_DATA_KEY, TaskAdmissionTiming, TaskStartupTiming, task_startup_timings
from .working_set import (
    parse_working_set,
    register_working_set_context,
    upsert_working_resource,
)
from .resource_facade import (
    list_task_amendments_by_source,
    list_task_resources,
    read_task_resource,
)

__all__ = [
    "STARTUP_TIMING_DATA_KEY",
    "TaskAdmissionTiming",
    "TaskStartupTiming",
    "task_startup_timings",
    "protected_task_ids",
    "Task",
    "TaskStatus",
    "TaskAttemptStatus",
    "TaskMessage",
    "TaskMessageAttachment",
    "TaskCreate",
    "TaskRead",
    "TaskCommand",
    "TaskUpdate",
    "TaskFull",
    "TASK_ACCESS",
    "TASK_EDIT",
    "try_lock_agent",
    "register_runtime_settings",
    "has_active_task_work",
    "unique_leased_task_for_agent",
    "ConversationFollowup",
    "ConversationPredecessor",
    "ConversationScope",
    "get_conversation_followup",
    "get_conversation_predecessor",
    "get_conversation_scope",
    "TaskOutcomeObservation",
    "get_task_outcome_observation",
    "register_working_set_context",
    "parse_working_set",
    "upsert_working_resource",
    "list_task_amendments_by_source",
    "list_task_resources",
    "read_task_resource",
    "amendment_basis",
    "prepare_replacement",
    "reconcile_replacements",
    "replacement_state",
    "register_replacement_blocker",
]

# Import the service separately to avoid circular dependencies.
try:
    from . import task_service as task_service
    __all__.append("task_service")
except ImportError:
    pass

# Register the durable port consumed by ``app.agent`` without reversing the dependency.
from . import agent_adapter as _agent_adapter  # noqa: F401 - registers the durable port # pyright: ignore[reportUnusedImport]
from .amendment_service import amendment_basis
from .replacement import prepare_replacement, reconcile_replacements, replacement_state, register_replacement_blocker
from .run_events import register_events as _register_run_events

_register_run_events()

try:
    from .runner import go_next as go_next, run_stream as run_stream
    __all__.extend(["go_next", "run_stream"])
except ImportError:
    pass
