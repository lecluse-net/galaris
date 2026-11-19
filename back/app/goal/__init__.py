"""Long-running Goals advanced through ordinary scheduled Tasks."""

from core.scheduling import PeriodicJobRegistrar
from app.agent import register_context_provider

from .document_store import (
    GoalDocumentKind,
    GoalDocumentStore,
    GoalMarkdown,
    get_goal_document_store,
    register_goal_document_store,
)
from .models import (
    Goal,
    GoalCycle,
    GoalCycleTrigger,
    GoalCycleTriggerKind,
    GoalCycleStatus,
    GoalReferrerType,
    GoalStatus,
    GoalVerdict,
)
from .privileges import GOAL_ACCESS, GOAL_EDIT
from .lifecycle import register_goal_observer, unregister_goal_observer
from .schemas import (
    GoalCommand,
    GoalCreate,
    GoalCyclePage,
    GoalDetail,
    GoalPage,
    GoalRead,
    GoalSettingsRead,
    GoalSettingsUpdate,
    GoalTreeNode,
    GoalTreePage,
    GoalUpdate,
)
from . import goal_service, settings_service
from .facade import GoalOutcomeObservation, get_goal_outcome_for_task
from .context import conversation_goal_context
from .retrospective import (
    RetrospectiveLearning as RetrospectiveLearning,
    ensure_weekly_retrospective as ensure_weekly_retrospective,
    register_retrospective_learning as register_retrospective_learning,
    weekly_retrospective_created as weekly_retrospective_created,
)
from .contact_port import (
    GoalContactDirectoryPort,
    GoalHumanContact,
    register_goal_contact_directory,
)
from .resource_facade import (
    list_goal_cycle_resources,
    list_goal_resources,
    read_goal_cycle_resource,
    read_goal_resource,
)

register_context_provider("active_goals", conversation_goal_context)


def register_scheduler_jobs(register: PeriodicJobRegistrar) -> None:
    """Register the Goal worker in the existing durable task scheduler."""

    from .referrer_wait import register_referrer_interaction_handler
    from .runner import process_goals
    from .retrospective import reconcile_weekly_retrospectives

    register_referrer_interaction_handler()
    register("goal-runner", process_goals, interval=2.0)
    register("goal-weekly-retrospectives", reconcile_weekly_retrospectives, interval=60.0)


__all__ = [
    "GoalDocumentKind",
    "GoalDocumentStore",
    "GoalMarkdown",
    "Goal",
    "GoalCycle",
    "GoalCycleTrigger",
    "GoalCycleTriggerKind",
    "GoalCycleStatus",
    "GoalReferrerType",
    "GoalStatus",
    "GoalVerdict",
    "GoalCommand",
    "GoalCreate",
    "GoalCyclePage",
    "GoalDetail",
    "GoalPage",
    "GoalRead",
    "GoalSettingsRead",
    "GoalSettingsUpdate",
    "GoalTreeNode",
    "GoalTreePage",
    "GoalUpdate",
    "GOAL_ACCESS",
    "GOAL_EDIT",
    "GoalOutcomeObservation",
    "GoalContactDirectoryPort",
    "GoalHumanContact",
    "get_goal_outcome_for_task",
    "get_goal_document_store",
    "list_goal_cycle_resources",
    "list_goal_resources",
    "read_goal_cycle_resource",
    "read_goal_resource",
    "register_goal_observer",
    "register_goal_document_store",
    "register_goal_contact_directory",
    "register_scheduler_jobs",
    "goal_service",
    "settings_service",
    "unregister_goal_observer",
]

from .events import register_events

register_events()
