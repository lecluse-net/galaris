"""Privilege mappings shared by the Lab router and its assertions."""

from __future__ import annotations

from typing import Final, Literal

from core.authorize import Privileges

from .schemas import EvaluationMechanism

LabAccessMode = Literal["read", "edit"]
PrivilegePair = tuple[str, str]

TASK_ANALYSIS_PRIVILEGES: Final[PrivilegePair] = (
    Privileges.EVALUATION_ACCESS,
    Privileges.EVALUATION_EDIT,
)
DISPATCHER_PRIVILEGES: Final[PrivilegePair] = (
    Privileges.DISPATCHER_EVALUATION_ACCESS,
    Privileges.DISPATCHER_EVALUATION_EDIT,
)

MECHANISM_PRIVILEGES: Final[dict[EvaluationMechanism, PrivilegePair]] = {
    "dispatcher": DISPATCHER_PRIVILEGES,
    "task_analysis": TASK_ANALYSIS_PRIVILEGES,
    "briefing": (
        Privileges.BRIEFING_EVALUATION_ACCESS,
        Privileges.BRIEFING_EVALUATION_EDIT,
    ),
    "planner": (
        Privileges.PLANNER_EVALUATION_ACCESS,
        Privileges.PLANNER_EVALUATION_EDIT,
    ),
    "topic_classification": (
        Privileges.TOPIC_CLASSIFICATION_EVALUATION_ACCESS,
        Privileges.TOPIC_CLASSIFICATION_EVALUATION_EDIT,
    ),
    "memory_extraction": (
        Privileges.MEMORY_EXTRACTION_EVALUATION_ACCESS,
        Privileges.MEMORY_EXTRACTION_EVALUATION_EDIT,
    ),
    "outcome_reflection": (
        Privileges.OUTCOME_REFLECTION_EVALUATION_ACCESS,
        Privileges.OUTCOME_REFLECTION_EVALUATION_EDIT,
    ),
    "goal_tracking": (
        Privileges.GOAL_TRACKING_EVALUATION_ACCESS,
        Privileges.GOAL_TRACKING_EVALUATION_EDIT,
    ),
    "task_executor": (
        Privileges.TASK_EXECUTOR_EVALUATION_ACCESS,
        Privileges.TASK_EXECUTOR_EVALUATION_EDIT,
    ),
    "conversation_executor": (
        Privileges.CONVERSATION_EXECUTOR_EVALUATION_ACCESS,
        Privileges.CONVERSATION_EXECUTOR_EVALUATION_EDIT,
    ),
    "voice_executor": (
        Privileges.VOICE_EXECUTOR_EVALUATION_ACCESS,
        Privileges.VOICE_EXECUTOR_EVALUATION_EDIT,
    ),
}

MECHANISM_READ_PRIVILEGES: Final[list[str]] = [
    privilege
    for read_privilege, edit_privilege in MECHANISM_PRIVILEGES.values()
    for privilege in (read_privilege, edit_privilege)
]
MECHANISM_EDIT_PRIVILEGES: Final[list[str]] = [
    edit_privilege for _, edit_privilege in MECHANISM_PRIVILEGES.values()
]
ALL_EVALUATION_LAB_PRIVILEGES: Final[list[str]] = [
    *MECHANISM_READ_PRIVILEGES,
]


def privileges_for_mechanism(
    mechanism: EvaluationMechanism,
    mode: LabAccessMode,
) -> list[str]:
    """Return the accepted privilege codes for one mechanism and access mode."""

    read_privilege, edit_privilege = MECHANISM_PRIVILEGES[mechanism]
    return [edit_privilege] if mode == "edit" else [read_privilege, edit_privilege]
