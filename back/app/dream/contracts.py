"""Public contracts for sequential, opportunistic Dream maintenance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol, Union, cast
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from app.memory import MemoryTemporalAnchor, AtomicMemoryFact
from core.util import local_timezone_name


MAX_MEMORY_EXTRACTION_CANDIDATES = 10
MemoryRetentionReason = Literal[
    "explicit_user_preference",
    "stable_personal_fact",
    "explicit_decision_or_commitment",
    "recurring_constraint",
    "reusable_procedure",
    "explicit_correction",
    "durable_relationship",
    "unspecified",
]
MemoryFutureUtility = Literal["high", "low"]
MemoryExtractionSourceKind = Literal["task", "conversation_round"]
OutcomeKind = Literal["verified_success", "failure", "recovered", "mixed", "unknown"]
LessonKind = Literal["procedure", "anti_pattern", "correction", "observation", "none"]
ExperienceScope = Literal["agent", "tool", "project", "domain"]
SignificanceReason = Literal[
    "explicit_human_correction",
    "explicit_human_validation",
    "definitive_failure",
    "recovered_after_failure",
    "guard_retry",
    "verified_tool_success",
    "mixed_plan",
    "repeated_failure",
    "goal_validation",
    "goal_refutation",
    "unowned_task",
    "unverified_success",
    "expected_interruption",
    "isolated_transient_failure",
    "no_reusable_signal",
]
DreamKeyword = Annotated[str, Field(min_length=1, max_length=80)]
DreamRuntimeStatus = Literal[
    "disabled",
    "stopped",
    "starting",
    "running",
    "paused_voice",
    "paused_tasks",
    "idle",
    "unavailable",
    "faulted",
]
DreamRuntimePhase = Literal[
    "stopped",
    "starting",
    "checking",
    "claiming",
    "preparing",
    "applying",
    "waiting",
    "faulted",
]
DreamRuntimeReason = Literal[
    "not_started",
    "startup",
    "disabled",
    "voice_active",
    "task_active",
    "checking_activity",
    "checking_mechanism",
    "claiming_subject",
    "preparing_subject",
    "applying_subject",
    "cycle_completed",
    "no_eligible_subject",
    "mechanism_unavailable",
    "worker_error",
    "stopping",
]


class ExtractedMemory(BaseModel):
    """One independently useful durable memory proposed by a Dream mechanism."""

    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=8_000)
    keywords: list[DreamKeyword] = Field(default_factory=list, max_length=20)
    retention_reason: MemoryRetentionReason = "unspecified"
    future_utility: MemoryFutureUtility = "low"


class MemoryExtractionExistingMemory(BaseModel):
    """One self-contained existing-memory candidate shown to the extractor."""

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1, max_length=8_000)
    keywords: list[DreamKeyword] = Field(default_factory=list, max_length=20)
    score: float = Field(default=0.0)
    temporal: MemoryTemporalAnchor | None = None
    revision: int | None = Field(default=None, ge=1)
    can_enrich: bool = False


class MemoryExtractionEvidence(BaseModel):
    """A bounded source passage, distinct from the extractor's interpretation."""

    ref: str = Field(min_length=1, max_length=200)
    kind: Literal["written", "transcription", "document_extraction", "document_interpretation", "attachment"]
    message_id: UUID
    uri: str | None = Field(default=None, max_length=8192)
    text: str = Field(default="", max_length=8_000)
    version: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    locator: str | None = Field(default=None, max_length=200)


class MemoryExtractionMessage(BaseModel):
    occurred_at: datetime | None = None
    speaker_name: str = Field(min_length=1, max_length=500)
    speaker_kind: Literal["human", "AI"]
    text: str = Field(min_length=1, max_length=8_000)
    evidence: list[MemoryExtractionEvidence] = Field(default_factory=lambda: list[MemoryExtractionEvidence](), max_length=64)

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_role(cls, value: object) -> object:
        """Accept saved Lab cases while serializing only identity-aware fields."""

        if not isinstance(value, dict):
            return value
        source = cast(dict[str, Any], value)
        if "speaker_kind" in source and "speaker_name" in source:
            return source
        role = str(source.get("role") or "human")
        normalized = dict(source)
        normalized.setdefault("speaker_kind", "AI" if role == "assistant" else "human")
        normalized.setdefault(
            "speaker_name",
            "Agent" if role == "assistant" else "Participant",
        )
        return normalized


class MemoryExtractionInput(BaseModel):
    """Portable input shared by Dream and the isolated Memory Lab."""

    source_kind: MemoryExtractionSourceKind
    source_at: datetime | None = None
    timezone: str = Field(default_factory=local_timezone_name)
    topic: dict[str, Any]
    history: list[MemoryExtractionMessage] = Field(
        default_factory=lambda: list[MemoryExtractionMessage](), max_length=5
    )
    current: list[MemoryExtractionMessage] = Field(min_length=1, max_length=20)
    task_trace: dict[str, Any] | None = None
    existing_memories: list[MemoryExtractionExistingMemory] = Field(
        default_factory=lambda: list[MemoryExtractionExistingMemory](),
        max_length=MAX_MEMORY_EXTRACTION_CANDIDATES,
    )


class MemoryCreateOperation(BaseModel):
    """Create one new, independently useful durable fact from the source."""

    action: Literal["CREATE"] = "CREATE"
    temporal: MemoryTemporalAnchor | None = None
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=8_000)
    fact: AtomicMemoryFact | None = None
    keywords: list[DreamKeyword] = Field(default_factory=list, max_length=20)
    retention_reason: MemoryRetentionReason = Field(
        default="unspecified",
        description=(
            "The single closed-list reason why this fact remains useful beyond "
            "the current source. Only a supported reason is retained server-side."
        )
    )
    future_utility: MemoryFutureUtility = Field(
        default="low",
        description=(
            "Use high only when the fact materially improves a relevant future "
            "interaction. Low-utility creations are discarded server-side."
        ),
    )
    reason: str = Field(default="", max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class MemoryLinkOperation(BaseModel):
    """Attach the source to an existing memory that already covers the same fact."""

    action: Literal["LINK"] = "LINK"
    target_memory_id: str = Field(min_length=1, max_length=100)
    reason: str = Field(default="", max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class MemoryEnrichOperation(BaseModel):
    """Add a complementary fact without replacing any existing content."""

    action: Literal["ENRICH"] = "ENRICH"
    target_memory_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)
    temporal: MemoryTemporalAnchor | None = None
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=8_000)
    fact: AtomicMemoryFact | None = None
    keywords: list[DreamKeyword] = Field(default_factory=list, max_length=20)
    retention_reason: MemoryRetentionReason = "unspecified"
    future_utility: MemoryFutureUtility = "low"
    reason: str = Field(default="", max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class MemoryContradictOperation(BaseModel):
    """Preserve an incompatible fact separately and link its provenance."""

    action: Literal["CONTRADICT"] = "CONTRADICT"
    target_memory_id: str = Field(min_length=1, max_length=100)
    title: str = Field(default="", max_length=500)
    content: str = Field(default="", max_length=8_000)
    fact: AtomicMemoryFact | None = None
    keywords: list[DreamKeyword] = Field(default_factory=list, max_length=20)
    retention_reason: MemoryRetentionReason = "unspecified"
    future_utility: MemoryFutureUtility = "low"
    temporal: MemoryTemporalAnchor | None = None
    reason: str = Field(default="", max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


MemoryExtractionOperation = Annotated[
    Union[MemoryCreateOperation, MemoryLinkOperation, MemoryEnrichOperation, MemoryContradictOperation],
    Field(discriminator="action"),
]


class MemoryExtractionDecision(BaseModel):
    """A single-pass decision; an empty operation list means IGNORE."""

    operations: list[MemoryExtractionOperation] = Field(
        default_factory=lambda: list[MemoryExtractionOperation](),
        max_length=12,
        description=(
            "One CREATE, LINK, ENRICH or CONTRADICT per qualifying durable fact after actively checking "
            "the entire source; empty only when no fact qualifies."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_model_operation_variants(cls, value: object) -> object:
        """Accept harmless small-model variants before discriminated-union parsing."""

        if not isinstance(value, dict):
            return value
        source = cast(dict[str, Any], value)
        raw_operations = source.get("operations")
        if not isinstance(raw_operations, list):
            return source
        operations: list[Any] = []
        for raw_operation in cast(list[Any], raw_operations):
            if not isinstance(raw_operation, dict):
                operations.append(raw_operation)
                continue
            operation = dict(cast(dict[str, Any], raw_operation))
            raw_action = operation.get("action")
            if isinstance(raw_action, str):
                action = raw_action.strip().upper()
                if action == "IGNORE":
                    continue
                if action in {"CREATE", "LINK", "ENRICH", "CONTRADICT"}:
                    operation["action"] = action
            elif "target_memory_id" in operation:
                operation["action"] = "LINK"
            elif "title" in operation or "content" in operation:
                operation["action"] = "CREATE"
            operations.append(operation)
        normalized = dict(source)
        normalized["operations"] = operations
        return normalized

    @model_validator(mode="after")
    def one_enrichment_per_revision(self) -> MemoryExtractionDecision:
        targets = [operation.target_memory_id for operation in self.operations
                   if isinstance(operation, MemoryEnrichOperation)]
        if len(targets) != len(set(targets)):
            raise ValueError("Combine complementary facts into one ENRICH per target revision")
        return self


class MemoryExtractionAppliedOperation(BaseModel):
    """Durable proof that one checkpointed memory operation was applied."""

    operation_index: int = Field(ge=0, le=11)
    action: Literal["CREATE", "LINK", "ENRICH", "CONTRADICT"]
    memory_id: UUID | None = None
    status: Literal["stored", "merged", "rejected"]
    rejection_reason: Literal["contact_coordinates"] | None = None

    @model_validator(mode="after")
    def valid_outcome(self) -> "MemoryExtractionAppliedOperation":
        if self.status == "rejected":
            if self.memory_id is not None or self.rejection_reason != "contact_coordinates":
                raise ValueError("An omitted contact coordinate requires an explicit policy outcome")
        elif self.memory_id is None or self.rejection_reason is not None:
            raise ValueError("A stored memory outcome requires its memory identifier")
        return self


class MemoryExtractionApplication(BaseModel):
    """Server-owned outcomes written only after every operation succeeds."""

    operations: list[MemoryExtractionAppliedOperation] = Field(
        default_factory=lambda: list[MemoryExtractionAppliedOperation](),
        max_length=12,
    )

    @property
    def stored_count(self) -> int:
        return sum(outcome.status in {"stored", "merged"} for outcome in self.operations)


class MemoryExtractionPrepared(BaseModel):
    """Checkpointed decision, LINK allow-list, and durable application proof."""

    decision: MemoryExtractionDecision
    decision_inference: dict[str, Any] | None = None
    candidate_memory_ids: list[UUID] = Field(
        default_factory=lambda: list[UUID](), max_length=20
    )
    application: MemoryExtractionApplication | None = None
    source_snapshot: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_application_proof(self) -> MemoryExtractionPrepared:
        if self.application is None:
            return self
        expected = self.decision.operations
        applied = self.application.operations
        if len(applied) != len(expected):
            raise ValueError("Memory application proof must cover every operation")
        for index, (operation, outcome) in enumerate(zip(expected, applied)):
            action_matches = outcome.action == operation.action or (
                operation.action == "CREATE"
                and outcome.action == "LINK"
                and outcome.status == "merged"
            )
            if outcome.operation_index != index or not action_matches:
                raise ValueError("Memory application proof does not match its decision")
        return self


def _empty_extracted_memories() -> list[ExtractedMemory]:
    return []


class TaskMemoryExtraction(BaseModel):
    """Prompted JSON output accepted from the small local Dream model."""

    memories: list[ExtractedMemory] = Field(
        default_factory=_empty_extracted_memories,
        max_length=12,
    )


class TaskOutcomeEvidenceItem(BaseModel):
    reference: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=80)
    status: str = Field(default="", max_length=80)
    name: str = Field(default="", max_length=200)
    detail: str = Field(default="", max_length=2_000)
    retryable: bool | None = None
    duration_seconds: float | None = Field(default=None, ge=0.0)


def _empty_evidence_items() -> list[TaskOutcomeEvidenceItem]:
    return []


def _empty_uuids() -> list[UUID]:
    return []


class TaskOutcomeEvidence(BaseModel):
    task_id: UUID
    owner_agent_id: int | None
    language: str = Field(default="", max_length=10)
    label: str = Field(default="", max_length=500)
    objective: str = Field(default="", max_length=4_000)
    terminal_status: str = Field(max_length=40)
    final_result: str = Field(default="", max_length=4_000)
    normalized_error: str = Field(default="", max_length=2_000)
    driver_code: str = Field(default="", max_length=100)
    model_code: str = Field(default="", max_length=100)
    effort: str = Field(default="", max_length=40)
    route: str = Field(default="", max_length=40)
    observations: list[TaskOutcomeEvidenceItem] = Field(
        default_factory=_empty_evidence_items, max_length=48
    )
    injected_memory_ids: list[UUID] = Field(default_factory=_empty_uuids, max_length=50)
    fingerprint: str = Field(min_length=64, max_length=64)


class ExperienceLesson(BaseModel):
    outcome_kind: OutcomeKind
    lesson_kind: LessonKind
    situation: str = Field(min_length=1, max_length=800)
    applicability: str = Field(min_length=1, max_length=800)
    recommended_action: str = Field(default="", max_length=1_200)
    avoid_action: str = Field(default="", max_length=1_200)
    observed_result: str = Field(min_length=1, max_length=1_000)
    evidence_refs: list[str] = Field(min_length=1, max_length=12)
    confidence: float = Field(ge=0.0, le=1.0)
    scope: ExperienceScope = "agent"


def _empty_experience_lessons() -> list[ExperienceLesson]:
    return []


def _empty_extracted_memory_list() -> list[ExtractedMemory]:
    return []


class TaskOutcomeReflection(BaseModel):
    lessons: list[ExperienceLesson] = Field(
        default_factory=_empty_experience_lessons, max_length=6
    )


class TaskOutcomeReflectionPrepared(BaseModel):
    evidence: TaskOutcomeEvidence
    significance_reason: SignificanceReason
    included: bool
    lessons: list[ExperienceLesson] = Field(
        default_factory=_empty_experience_lessons, max_length=6
    )
    memories: list[ExtractedMemory] = Field(
        default_factory=_empty_extracted_memory_list, max_length=6
    )
    application_mode: Literal["observe", "learn"] = "observe"


@dataclass(frozen=True, slots=True)
class DreamClaim:
    receipt_id: UUID
    lease_token: UUID
    subject_kind: str
    subject_id: str
    attempts: int
    prepared_payload: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class DreamPrepared:
    payload: dict[str, Any]
    cost: float = 0.0


@dataclass(frozen=True, slots=True)
class DreamRuntimeSnapshot:
    status: DreamRuntimeStatus
    phase: DreamRuntimePhase
    reason: DreamRuntimeReason
    worker_running: bool
    current_mechanism: str | None
    current_subject_kind: str | None
    current_subject_id: str | None
    last_cycle_at: datetime | None
    last_cycle_finished_at: datetime | None
    next_cycle_at: datetime | None
    state_changed_at: datetime | None
    cycle_count: int
    last_error_type: str | None


class DreamMechanism(Protocol):
    """One ordered background mechanism processing at most one subject per cycle."""

    key: str

    async def is_available(self) -> bool: ...

    async def count_pending(self) -> int: ...

    async def claim_one(self) -> DreamClaim | None: ...

    async def prepare(self, claim: DreamClaim) -> DreamPrepared: ...

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int: ...


__all__ = [
    "DreamClaim",
    "DreamMechanism",
    "DreamPrepared",
    "DreamRuntimePhase",
    "DreamRuntimeReason",
    "DreamRuntimeSnapshot",
    "DreamRuntimeStatus",
    "ExtractedMemory",
    "MAX_MEMORY_EXTRACTION_CANDIDATES",
    "MemoryCreateOperation",
    "MemoryExtractionApplication",
    "MemoryExtractionAppliedOperation",
    "MemoryExtractionDecision",
    "MemoryExtractionExistingMemory",
    "MemoryExtractionInput",
    "MemoryExtractionMessage",
    "MemoryExtractionOperation",
    "MemoryExtractionPrepared",
    "MemoryExtractionSourceKind",
    "MemoryLinkOperation",
    "ExperienceLesson",
    "ExperienceScope",
    "LessonKind",
    "OutcomeKind",
    "SignificanceReason",
    "TaskMemoryExtraction",
    "TaskOutcomeEvidence",
    "TaskOutcomeEvidenceItem",
    "TaskOutcomeReflection",
    "TaskOutcomeReflectionPrepared",
]


class MemoryExtractionLabOutput(BaseModel):
    """Decision plus retrieval diagnostics used by the Memory Lab."""

    operations: list[MemoryExtractionOperation] = Field(
        default_factory=lambda: list[MemoryExtractionOperation](), max_length=12
    )
    relevant_memory_ids: list[str] = Field(
        default_factory=list, max_length=MAX_MEMORY_EXTRACTION_CANDIDATES
    )
    ranked_memory_ids: list[str] = Field(
        default_factory=list, max_length=MAX_MEMORY_EXTRACTION_CANDIDATES
    )
