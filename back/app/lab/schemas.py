"""API and structured-analysis contracts for the task Lab."""

from __future__ import annotations
from .contracts import LabInput

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.evaluation import PlannerLabConfiguration
from app.dream.evaluation import MemoryExtractionLabConfiguration
from app.topic.evaluation import (
    TopicDetectionLabConfiguration,
)


AnalysisLanguage = Literal["fr", "en", "zh"]
AnalysisVerdict = Literal["success", "partial", "failure", "inconclusive"]
FindingSeverity = Literal["critical", "high", "medium", "low", "info"]
RecommendationPriority = Literal["high", "medium", "low"]
RecommendationScope = Literal[
    "task",
    "agent",
    "model",
    "tools",
    "skills",
    "connections",
    "runtime",
    "external",
]


class LabTaskAdd(BaseModel):
    task_id: UUID


class LabTaskSummary(BaseModel):
    task_id: UUID
    revision: int = 1
    label: str
    objective: str | None = None
    status: str
    paused: bool = False
    effort: str
    forced_route: str | None = None
    forced_effort: str | None = None
    feedback: str | None = None
    last_error: str | None = None
    cost: float = 0.0
    attempt_count: int = 0
    agent_id: int | None = None
    agent_name: str | None = None
    agent_code: str | None = None
    driver: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LabTaskReference(BaseModel):
    """One durable Lab reference enriched from the current canonical task."""

    task_id: UUID
    task: LabTaskSummary | None = None


class LabLlmOption(BaseModel):
    id: int
    code: str
    label: str
    model: str


class LabConfig(BaseModel):
    lab_llm_id: int | None = None
    dispatcher_llm_id: int | None = None
    llms: list[LabLlmOption] = Field(default_factory=list[LabLlmOption])
    decision_llms: list[LabLlmOption] = Field(default_factory=list[LabLlmOption])


class TaskAnalysisRequest(BaseModel):
    language: AnalysisLanguage = "fr"
    user_context: str = Field(default="", max_length=6_000)


class EvidenceCoverage(BaseModel):
    task_count: int = 0
    attempt_count: int = 0
    llm_call_count: int = 0
    tool_call_count: int = 0
    process_run_count: int = 0
    has_agent_configuration: bool = False
    has_final_result: bool = False
    truncated: bool = False


class AnalysisFinding(BaseModel):
    title: str
    severity: FindingSeverity
    observation: str
    impact: str
    evidence: list[str] = Field(default_factory=list)


class AnalysisRootCause(BaseModel):
    cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class AnalysisRecommendation(BaseModel):
    scope: RecommendationScope
    priority: RecommendationPriority
    action: str
    rationale: str
    expected_impact: str
    where_to_change: str
    evidence: list[str] = Field(default_factory=list)


class TaskAnalysisContent(BaseModel):
    """Validated diagnostic produced by the independent analysis LLM."""

    verdict: AnalysisVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str
    goal_assessment: str
    observed_outcome: str
    strengths: list[str] = Field(default_factory=list)
    findings: list[AnalysisFinding] = Field(default_factory=list[AnalysisFinding])
    root_causes: list[AnalysisRootCause] = Field(default_factory=list[AnalysisRootCause])
    recommendations: list[AnalysisRecommendation] = Field(
        default_factory=list[AnalysisRecommendation]
    )
    missing_evidence: list[str] = Field(default_factory=list)
    next_questions: list[str] = Field(default_factory=list)


class TaskAnalysis(TaskAnalysisContent):
    id: UUID
    task_id: UUID
    task_revision: int
    language: AnalysisLanguage
    prompt_version: str
    evidence: EvidenceCoverage
    model: str
    duration: float = 0.0
    cost: float = 0.0
    created_at: datetime
    created_by: int | None = None


DispatcherRoute = Literal["EXEC", "BRIEFING", "PLAN", "END"]
DispatcherEffort = Literal["standard", "high"]
EvaluationReadiness = Literal["draft", "ready"]
EvaluationRunStatus = Literal["queued", "running", "completed", "partial", "failed", "cancelled"]
EvaluationMechanism = Literal[
    "dispatcher",
    "task_analysis",
    "briefing",
    "planner",
    "topic_classification",
    "memory_extraction",
    "outcome_reflection",
    "goal_tracking",
    "task_executor",
    "conversation_executor",
    "voice_executor",
]
EvaluationValueFormat = Literal["json", "text"]
ExecutorPromptKind = Literal["task", "conversation", "voice"]


class DispatcherExpectedDecision(BaseModel):
    reasoning: str = Field(default="", max_length=10_000)
    route: DispatcherRoute
    effort: DispatcherEffort
    language: str = Field(default="en", min_length=2, max_length=10)


class EvaluationDatasetCreate(BaseModel):
    purpose: Literal["work", "validation", "holdout"] = "work"
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10_000)
    mechanism: Literal["dispatcher"] = "dispatcher"

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Dataset name cannot be blank")
        return value


class EvaluationDatasetUpdate(BaseModel):
    purpose: Literal["work", "validation", "holdout"] = "work"
    revision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10_000)
    prompt_suffix: str | None = Field(default=None, max_length=50_000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    configuration: dict[str, Any] | None = None

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Dataset name cannot be blank")
        return value


class EvaluationDatasetRead(BaseModel):
    purpose: Literal["work", "validation", "holdout"] = "work"
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    revision: int
    mechanism: str
    name: str
    description: str
    prompt_suffix: str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict[str, Any])
    parameters: dict[str, Any] = Field(default_factory=dict)
    case_count: int = 0
    ready_case_count: int = 0
    created_at: datetime
    updated_at: datetime | None = None


class DispatcherTaskCandidate(BaseModel):
    task_id: UUID
    revision: int
    label: str
    objective: str | None = None
    status: str
    agent_name: str | None = None
    driver: str | None = None
    created_at: datetime | None = None


class CaptureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmation_token: str | None = Field(default=None, min_length=64, max_length=64)


class DispatcherCaseImport(CaptureRequest):
    task_id: UUID
    name: str | None = Field(default=None, max_length=400)


class EvaluationCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=400)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Case name cannot be blank")
        return value


CaseCategory = Literal[
    "nominal",
    "ambiguity",
    "incomplete",
    "multilingual",
    "robustness",
    "security",
    "incident",
    "alternative",
]


class EvaluationCaseUpdate(BaseModel):
    categories: list[CaseCategory] = Field(default_factory=list[CaseCategory], max_length=8)
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=400)
    revision: int = Field(ge=1)
    input_data: LabInput
    expected_output: DispatcherExpectedDecision


class EvaluationCaseRead(BaseModel):
    categories: list[str] = Field(default_factory=list)
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    revision: int
    dataset_id: UUID
    derived_from_case_id: UUID | None = None
    source_task_id: UUID | None = None
    source_task_revision: int | None = None
    name: str
    enabled: bool
    readiness: Literal["draft", "ready"]
    input_data: Any
    expected_output: Any
    reference: dict[str, Any]
    source_capture: dict[str, Any]
    created_at: datetime
    updated_at: datetime | None = None


class EvaluationRunStart(BaseModel):
    repetitions: int = Field(default=1, ge=1, le=20)
    max_cost: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    llm_id: int
    judge_llm_id: int | None = None


class EvaluationRejudge(BaseModel):
    judge_llm_id: int | None = None


class EvaluationRunAnalysisRequest(BaseModel):
    language: AnalysisLanguage = "fr"


class BenchmarkCaseAnalysis(BaseModel):
    case_name: str = Field(min_length=1, max_length=400)
    score_percent: float | None = Field(default=None, ge=0.0, le=100.0)
    assessment: str = Field(min_length=1, max_length=4_000)
    strengths: list[str] = Field(default_factory=list[str], max_length=10)
    weaknesses: list[str] = Field(default_factory=list[str], max_length=10)
    improvements: list[str] = Field(default_factory=list[str], max_length=10)


class BenchmarkAnalysisContent(BaseModel):
    summary: str = Field(min_length=1, max_length=8_000)
    strengths: list[str] = Field(default_factory=list[str], max_length=30)
    weaknesses: list[str] = Field(default_factory=list[str], max_length=30)
    improvements: list[str] = Field(default_factory=list[str], max_length=30)
    case_analyses: list[BenchmarkCaseAnalysis] = Field(
        default_factory=list[BenchmarkCaseAnalysis], max_length=500
    )
    conclusion: str = Field(min_length=1, max_length=8_000)


class EvaluationExpectedGenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_data: LabInput | None = None


class EvaluationExpectedGenerated(BaseModel):
    output: DispatcherExpectedDecision
    llm: dict[str, Any]
    cost: float = 0.0


class EvaluationRunRead(BaseModel):
    repetitions: int = 1
    max_cost: float | None = None
    stop_reason: str | None = None
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    dataset_id: UUID
    llm_id: int | None
    judge_llm_id: int | None
    status: EvaluationRunStatus
    phase: Literal["execution", "judgment", "finished"] = "execution"
    judged_cases: int = 0
    candidate_cost: float = 0.0
    judge_cost: float = 0.0
    score_version: str
    llm_snapshot: dict[str, Any]
    judge_llm_snapshot: dict[str, Any]
    configuration_snapshot: dict[str, Any] = Field(default_factory=dict[str, Any])
    total_cases: int
    completed_cases: int
    score_percent: float | None = None
    structured_score_percent: float | None = None
    cost: float
    analysis_markdown: str | None = None
    analysis_llm_snapshot: dict[str, Any] = Field(default_factory=dict[str, Any])
    analysis_cost: float = 0.0
    analysis_language: str | None = None
    analysis_created_at: datetime | None = None
    error: str | None = None
    cancel_requested: bool
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class EvaluationRunCaseRead(BaseModel):
    repetition: int = 1
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    run_id: UUID
    case_id: UUID | None
    case_snapshot: dict[str, Any]
    actual_output: Any | None = None
    verdict: Literal["pass", "fail", "inconclusive"] | None = None
    score_details: dict[str, Any]
    judge_output: dict[str, Any] | None = None
    score_percent: float | None = None
    structured_score_percent: float
    cost: float
    duration: float
    error: str | None = None
    created_at: datetime


class JudgmentResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    result_id: UUID
    status: str
    verdict: str
    output: dict[str, Any] | None
    score_percent: float | None
    cost: float
    duration: float
    error: str | None


class JudgmentCampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    sequence: int
    status: str
    configuration: dict[str, Any]
    created_at: datetime
    results: list[JudgmentResultRead] = Field(default_factory=list[JudgmentResultRead])


class EvaluationRunDetail(EvaluationRunRead):
    campaigns: list[JudgmentCampaignRead] = Field(default_factory=list[JudgmentCampaignRead])
    results: list[EvaluationRunCaseRead] = Field(default_factory=list[EvaluationRunCaseRead])


class DispatcherJudgeOutput(BaseModel):
    score_percent: float = Field(ge=0.0, le=100.0)
    policy_consistency_percent: float = Field(ge=0.0, le=100.0)
    input_grounding_percent: float = Field(ge=0.0, le=100.0)
    decision_support_percent: float = Field(ge=0.0, le=100.0)
    explanation: str = Field(max_length=2_000)


class MechanismDescriptorRead(BaseModel):
    key: EvaluationMechanism
    contract: dict[str, Any] = Field(default_factory=dict)
    configuration_schema: dict[str, Any] = Field(default_factory=dict)
    algorithm: dict[str, Any] = Field(default_factory=dict)
    input_format: EvaluationValueFormat
    output_format: EvaluationValueFormat
    source_import: bool = True
    executor: ExecutorPromptKind | None = None


class ExecutorPromptDefaultsRead(BaseModel):
    defaults: dict[ExecutorPromptKind, str]


class MechanismDatasetCreate(BaseModel):
    purpose: Literal["work", "validation", "holdout"] = "work"
    name: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10_000)
    prompt_suffix: str | None = Field(default=None, max_length=50_000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Dataset name cannot be blank")
        return value.strip()


class LabInputPreview(BaseModel):
    candidate_prompt: str
    system_prompt: str
    input: LabInput
    native_input: Any
    configuration: dict[str, Any]
    parameters: dict[str, Any]
    origins: dict[str, Literal["dataset", "item"]]


class TopicDatasetConfigurationUpdate(BaseModel):
    revision: int = Field(ge=1)
    configuration: TopicDetectionLabConfiguration


class MemoryExtractionDatasetConfigurationUpdate(BaseModel):
    revision: int = Field(ge=1)
    configuration: MemoryExtractionLabConfiguration


class PlannerDatasetConfigurationUpdate(BaseModel):
    revision: int = Field(ge=1)
    configuration: PlannerLabConfiguration


class PlannerPromptDefaultRead(BaseModel):
    configuration: PlannerLabConfiguration


class MemoryExtractionPromptDefaultRead(BaseModel):
    configuration: MemoryExtractionLabConfiguration


class MechanismCaseUpdate(BaseModel):
    categories: list[CaseCategory] = Field(default_factory=list[CaseCategory], max_length=8)
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=400)
    revision: int = Field(ge=1)
    input_data: LabInput
    expected_output: Any


class MechanismSourceCandidate(BaseModel):
    source_id: UUID
    source_kind: Literal[
        "llm_call",
        "messenger_message",
        "task",
        "conversation_round",
        "voice_turn",
    ]
    call_id: UUID | None = None
    task_id: UUID | None = None
    label: str
    model: str
    created_at: datetime
    input_preview: str = ""


class MechanismCaseImport(CaptureRequest):
    source_id: UUID | None = None
    call_id: UUID | None = None
    name: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def validate_source(self) -> "MechanismCaseImport":
        if self.source_id is None and self.call_id is None:
            raise ValueError("A source_id is required")
        if (
            self.source_id is not None
            and self.call_id is not None
            and self.source_id != self.call_id
        ):
            raise ValueError("source_id and legacy call_id must designate the same source")
        return self

    @property
    def resolved_source_id(self) -> UUID:
        source_id = self.source_id or self.call_id
        assert source_id is not None
        return source_id


class TopicMessageAgentRead(BaseModel):
    id: int
    label: str
    message_count: int = Field(ge=0)


class TopicMessagePersonRead(BaseModel):
    connection_id: int
    user_id: str
    label: str
    platform: str
    message_count: int = Field(ge=0)


class TopicMessagePreview(BaseModel):
    journal_message_id: UUID
    message: dict[str, Any]
    role: Literal["human", "assistant"]
    occurred_at: datetime
    detected_topic: str | None = None


class TopicMessageRangePreview(BaseModel):
    agent_id: int
    connection_id: int
    user_id: str
    date_from: datetime
    date_to: datetime
    total_count: int = Field(ge=0)
    truncated: bool = False
    messages: list[TopicMessagePreview] = Field(max_length=500)


class TopicMessageRangeImport(CaptureRequest):
    agent_id: int = Field(ge=1)
    connection_id: int = Field(ge=1)
    user_id: str = Field(min_length=1, max_length=512)
    date_from: datetime
    date_to: datetime
    name: str | None = Field(default=None, max_length=400)

    @model_validator(mode="after")
    def validate_range(self) -> "TopicMessageRangeImport":
        if self.date_from.tzinfo is None or self.date_to.tzinfo is None:
            raise ValueError("date_from and date_to must include a timezone")
        if self.date_to < self.date_from:
            raise ValueError("date_to must be greater than or equal to date_from")
        return self


class ExecutorCaseImport(CaptureRequest):
    source_id: UUID
    name: str | None = Field(default=None, max_length=400)


class MechanismExpectedGenerate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_data: LabInput | None = None


class MechanismExpectedGenerated(BaseModel):
    output: Any
    llm: dict[str, Any]
    cost: float = 0.0


class MechanismJudgeDimension(BaseModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]{1,79}$")
    score_percent: float = Field(ge=0.0, le=100.0)
    assessment: str = Field(min_length=1, max_length=1_500)


class MechanismJudgeOutput(BaseModel):
    dimensions: list[MechanismJudgeDimension] = Field(min_length=1, max_length=8)
    strengths: list[str] = Field(default_factory=list[str], max_length=8)
    weaknesses: list[str] = Field(default_factory=list[str], max_length=8)
    critical_failures: list[str] = Field(default_factory=list[str], max_length=8)
    confidence_percent: float = Field(ge=0.0, le=100.0)
    explanation: str = Field(min_length=1, max_length=3_000)


class HumanReviewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    result_id: UUID
    campaign_id: UUID
    dimensions: list[MechanismJudgeDimension] = Field(min_length=1, max_length=20)
    critical_failures: list[str] = Field(default_factory=list, max_length=8)
    explanation: str = Field(min_length=1, max_length=4000)


class HumanReviewItem(BaseModel):
    result_id: UUID
    name: str
    repetition: int
    input: dict[str, Any]
    reference: Any
    output: Any
    assessment: dict[str, Any] | None = None
    human_score: float | None = None
    human_verdict: str | None = None
    judge: JudgmentResultRead | None = None


class HumanReviewQueue(BaseModel):
    campaign_id: UUID
    rubric: dict[str, Any]
    parameters: dict[str, Any]
    items: list[HumanReviewItem]
