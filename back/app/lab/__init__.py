"""Evidence-based AI analysis and mechanism evaluation Lab."""

from .models import (
    LabEvaluationCase,
    LabEvaluationDataset,
    LabEvaluationRun,
    LabEvaluationRunCase,
    LabTask,
    LabTaskDiagnosis,
)
from . import (
    analysis_service,
    diagnosis_service,
    dispatcher_evaluation_service,
    evaluation_service,
    evidence_service,
    executor_prompt_service,
    mechanism_evaluation_service,
)


def register_scheduler_jobs() -> None:
    """Register durable Lab work in the task scheduler composition root."""

    from app.task import scheduler
    from .operation_worker import tick

    scheduler.register_periodic_job("lab-operations", tick, interval=1.0, timeout=720.0)

    scheduler.register_periodic_job(
        "lab-mechanism-evaluations",
        mechanism_evaluation_service.process_runs,
        interval=1.0,
    )




__all__ = [
    "LabTask",
    "LabTaskDiagnosis",
    "LabEvaluationDataset",
    "LabEvaluationCase",
    "LabEvaluationRun",
    "LabEvaluationRunCase",
    "analysis_service",
    "diagnosis_service",
    "dispatcher_evaluation_service",
    "evaluation_service",
    "evidence_service",
    "executor_prompt_service",
    "mechanism_evaluation_service",
    "register_scheduler_jobs",
]
