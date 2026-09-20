"""Side-effect-free sequential Topic detection for one canonical message."""

from __future__ import annotations

import json
import math
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.llm import LLM, LLMCallPurpose, model_usages
from app.llm.structured_service import run_prompted
from app.agent.contracts import TaskMessage as Message
from core.params import Params, params_service, prompt_default

from .classifier import candidates_prompt
from .schemas import TopicCandidate, TopicClassification


MAX_MESSAGES = 10
MAX_CONTEXT_CHARACTERS = 12_000
MAX_UNIX_TIMESTAMP = 253_402_300_799
CONTINUITY_THRESHOLD = 0.55
CONTINUITY_DECISION_VERSION = "topic-continuity-decision:v1-heuristic"


def _required_prompt_default(name: str) -> str:
    value = str(prompt_default(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing built-in system prompt for {name}.")
    return value


TOPIC_CONTINUITY_SYSTEM_PROMPT = _required_prompt_default(Params.AI_TOPIC_CONTINUITY_SYSTEM_PROMPT)
TOPIC_RESOLUTION_SYSTEM_PROMPT = _required_prompt_default(Params.AI_TOPIC_RESOLUTION_SYSTEM_PROMPT)


async def topic_continuity_system_prompt() -> str:
    """Return the configured continuity prompt or its visible built-in default."""

    value = str(
        await params_service.get_or_default(Params.AI_TOPIC_CONTINUITY_SYSTEM_PROMPT) or ""
    ).strip()
    return value or TOPIC_CONTINUITY_SYSTEM_PROMPT


async def topic_resolution_system_prompt() -> str:
    """Return the configured resolution prompt or its visible built-in default."""

    value = str(
        await params_service.get_or_default(Params.AI_TOPIC_RESOLUTION_SYSTEM_PROMPT) or ""
    ).strip()
    return value or TOPIC_RESOLUTION_SYSTEM_PROMPT


TimestampQuality = Literal[
    "observed",
    "coarse_zero_gap",
    "missing",
    "non_monotonic",
    "no_previous_message",
]
TopicResolutionKind = Literal["continuity", "reuse", "create"]


@dataclass(frozen=True)
class ContinuityPriorParameters:
    """Versioned, pre-calibration parameters for the deterministic prior."""

    version: str = "topic-continuity-prior:v1-heuristic"
    beta_0: float = 2.5
    beta_absolute: float = 0.75
    beta_relative: float = 0.6
    absolute_scale_seconds: float = 300.0
    fallback_probability: float = 0.75

    def __post_init__(self) -> None:
        if self.absolute_scale_seconds <= 0:
            raise ValueError("absolute_scale_seconds must be positive.")
        if min(self.beta_absolute, self.beta_relative) < 0:
            raise ValueError("Temporal decay coefficients cannot be negative.")
        if not 0.0 <= self.fallback_probability <= 1.0:
            raise ValueError("fallback_probability must be between zero and one.")


DEFAULT_CONTINUITY_PRIOR_PARAMETERS = ContinuityPriorParameters()


class TopicDetectionInput(BaseModel):
    """Validated serialization of the exact public detector arguments."""

    model_config = ConfigDict(extra="forbid")

    messages: list[Message] = Field(min_length=1, max_length=MAX_MESSAGES)
    current_message_index: int
    current_topic_id: UUID | None = None

    @field_validator("messages")
    @classmethod
    def copy_messages(cls, values: list[Message]) -> list[Message]:
        return list(values)

    def validate_current_message(self) -> None:
        if not 0 <= self.current_message_index < len(self.messages):
            raise ValueError("current_message_index is outside the message window.")
        if not self.messages[self.current_message_index].text.strip():
            raise ValueError("The current message has no usable text.")


class TemporalContinuityPrior(BaseModel):
    """Observable result of the pure, deterministic temporal calculation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    probability: float = Field(ge=0.0, le=1.0)
    gap_seconds: float | None = Field(default=None, ge=0.0)
    local_median_gap_seconds: float | None = Field(default=None, gt=0.0)
    timestamp_quality: TimestampQuality
    version: str


class TopicContinuityInterpretation(BaseModel):
    """Strict raw semantic output produced by the model."""

    model_config = ConfigDict(extra="forbid")

    same_topic_probability: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class TopicContinuityDecision(TopicContinuityInterpretation):
    """Versioned code decision derived from the model probability."""

    same_topic: bool
    threshold: float = Field(ge=0.0, le=1.0)
    version: str


class TopicDetectionEvaluation(BaseModel):
    """Internal diagnostics shared with the AI Lab, never persisted by the detector."""

    model_config = ConfigDict(extra="forbid")

    topic_id: UUID
    resolution: TopicResolutionKind
    temporal_prior: TemporalContinuityPrior | None = None
    semantic_continuity: TopicContinuityDecision | None = None
    classification: TopicClassification | None = None


@dataclass(frozen=True)
class TopicDetectionRun:
    evaluation: TopicDetectionEvaluation
    cost: float


class TopicDetectionCatalog(Protocol):
    """Read/resolve port supplied by production or a side-effect-free sandbox."""

    async def get_candidate(self, topic_id: UUID) -> TopicCandidate | None: ...

    async def list_candidates(self, *, activity: str) -> list[TopicCandidate]: ...

    async def resolve(
        self,
        decision: TopicClassification,
        *,
        allowed_topic_ids: set[UUID],
    ) -> UUID: ...


class TopicDetectionModel(Protocol):
    """Model port kept independent from catalogue retrieval and persistence."""

    async def interpret_continuity(
        self,
        *,
        rendered_window: str,
        current_topic: TopicCandidate,
        temporal_prior: TemporalContinuityPrior,
    ) -> tuple[TopicContinuityInterpretation, float]: ...

    async def classify_current_message(
        self,
        *,
        rendered_window: str,
        candidates: list[TopicCandidate],
    ) -> tuple[TopicClassification, float]: ...


@dataclass(frozen=True)
class TopicDetectionDependencies:
    catalog: TopicDetectionCatalog
    model: TopicDetectionModel


class TopicDetectionConfigurationError(RuntimeError):
    """Raised when the pure detector has not received its runtime dependencies."""


class _TopicReuseDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_id: UUID | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=500)

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str) -> str:
        return value.strip()


class _TopicCreationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=4_000)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=500)

    @field_validator("title", "description", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip()[:80] for value in values if value.strip()))


class PromptedTopicDetectionModel:
    """Temperature-zero structured model implementation shared by runtime and Lab."""

    def __init__(
        self,
        llm: LLM,
        *,
        task_id: UUID | None = None,
        agent_id: int | None = None,
        continuity_system_prompt: str | None = None,
        resolution_system_prompt: str | None = None,
    ) -> None:
        self._llm = llm
        self._task_id = task_id
        self._agent_id = agent_id
        self._continuity_system_prompt = continuity_system_prompt
        self._resolution_system_prompt = resolution_system_prompt

    async def interpret_continuity(
        self,
        *,
        rendered_window: str,
        current_topic: TopicCandidate,
        temporal_prior: TemporalContinuityPrior,
    ) -> tuple[TopicContinuityInterpretation, float]:
        inference = await run_prompted(
            llm=self._llm,
            output_type=TopicContinuityInterpretation,
            prompt=continuity_prompt(
                rendered_window=rendered_window,
                current_topic=current_topic,
                temporal_prior=temporal_prior,
            ),
            system_prompt=(
                self._continuity_system_prompt or await topic_continuity_system_prompt()
            ),
            task_id=self._task_id,
            agent_id=self._agent_id,
            temperature=0.0,
            request_limit=None,
            output_retries=1,
            purpose=LLMCallPurpose.DREAM_TOPIC_CONTINUITY,
            model_field=model_usages.DREAM,
        )
        return inference.output, inference.cost

    async def classify_current_message(
        self,
        *,
        rendered_window: str,
        candidates: list[TopicCandidate],
    ) -> tuple[TopicClassification, float]:
        prompt = resolution_prompt(
            rendered_window=rendered_window,
            candidates=candidates,
        )
        system_prompt = self._resolution_system_prompt or await topic_resolution_system_prompt()
        total_cost = 0.0
        candidate_ids = {candidate.id for candidate in candidates}
        if candidates:
            reuse_inference = await run_prompted(
                llm=self._llm,
                output_type=_TopicReuseDecision,
                prompt=(
                    f"{prompt}\n\nReuse stage: choose the best existing topic_id when its "
                    "durable subject contains the marked message. Return topic_id=null only "
                    "when every supplied dossier is materially outside that subject."
                ),
                system_prompt=system_prompt,
                task_id=self._task_id,
                agent_id=self._agent_id,
                temperature=0.0,
                request_limit=None,
                output_retries=1,
                purpose=LLMCallPurpose.DREAM_TOPIC_REUSE,
                model_field=model_usages.DREAM,
            )
            total_cost += reuse_inference.cost
            reuse = reuse_inference.output
            if reuse.topic_id in candidate_ids:
                return (
                    TopicClassification(
                        action="reuse",
                        topic_id=reuse.topic_id,
                        confidence=reuse.confidence,
                        reason=reuse.reason,
                    ),
                    total_cost,
                )

        creation_inference = await run_prompted(
            llm=self._llm,
            output_type=_TopicCreationDecision,
            prompt=(
                f"{prompt}\n\nCreation stage: no existing dossier contains the marked "
                "message's durable subject. Propose one abstract, stable, non-redundant subject "
                "category; do not encode the action, solution, person, channel, or transient "
                "circumstance in its public metadata."
            ),
            system_prompt=system_prompt,
            task_id=self._task_id,
            agent_id=self._agent_id,
            temperature=0.0,
            request_limit=None,
            output_retries=1,
            purpose=LLMCallPurpose.DREAM_TOPIC_CREATION,
            model_field=model_usages.DREAM,
        )
        total_cost += creation_inference.cost
        creation = creation_inference.output
        return (
            TopicClassification(
                action="create",
                title=creation.title,
                description=creation.description,
                keywords=creation.keywords,
                confidence=creation.confidence,
                reason=creation.reason,
            ),
            total_cost,
        )


_active_dependencies: ContextVar[TopicDetectionDependencies | None] = ContextVar(
    "topic_detection_dependencies", default=None
)


@contextmanager
def use_topic_detection_dependencies(
    dependencies: TopicDetectionDependencies,
) -> Generator[None]:
    """Bind dependencies to the current async context without changing public arguments."""

    token = _active_dependencies.set(dependencies)
    try:
        yield
    finally:
        _active_dependencies.reset(token)


def _logistic(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def _previous_classifiable_index(messages: Sequence[Message], index: int) -> int | None:
    return next(
        (
            candidate_index
            for candidate_index in range(index - 1, -1, -1)
            if messages[candidate_index].text.strip()
        ),
        None,
    )


def _local_prior_intervals(messages: Sequence[Message], previous_index: int) -> list[float]:
    intervals: list[float] = []
    previous_time: int | None = None
    for message in messages[: previous_index + 1]:
        if not message.text.strip():
            continue
        if not _usable_timestamp(message.time):
            previous_time = None
            continue
        if previous_time is not None and message.time > previous_time:
            intervals.append(float(message.time - previous_time))
        previous_time = message.time
    return intervals


def _usable_timestamp(timestamp: int) -> bool:
    return 0 < timestamp <= MAX_UNIX_TIMESTAMP


def calculate_continuity_prior(
    messages: Sequence[Message],
    current_message_index: int,
    *,
    parameters: ContinuityPriorParameters = DEFAULT_CONTINUITY_PRIOR_PARAMETERS,
) -> TemporalContinuityPrior:
    """Calculate the temporal prior using only messages before the pointed message."""

    if not 0 <= current_message_index < len(messages):
        raise ValueError("current_message_index is outside the message window.")
    previous_index = _previous_classifiable_index(messages, current_message_index)
    if previous_index is None:
        return TemporalContinuityPrior(
            probability=parameters.fallback_probability,
            timestamp_quality="no_previous_message",
            version=parameters.version,
        )

    current_time = messages[current_message_index].time
    previous_time = messages[previous_index].time
    if not _usable_timestamp(current_time) or not _usable_timestamp(previous_time):
        return TemporalContinuityPrior(
            probability=parameters.fallback_probability,
            timestamp_quality="missing",
            version=parameters.version,
        )
    if current_time < previous_time:
        return TemporalContinuityPrior(
            probability=parameters.fallback_probability,
            timestamp_quality="non_monotonic",
            version=parameters.version,
        )

    gap = float(current_time - previous_time)
    intervals = _local_prior_intervals(messages, previous_index)
    local_median = float(median(intervals)) if intervals else None
    logit = parameters.beta_0 - parameters.beta_absolute * math.log1p(
        gap / parameters.absolute_scale_seconds
    )
    if local_median is not None:
        logit -= parameters.beta_relative * math.log1p(gap / local_median)
    return TemporalContinuityPrior(
        probability=_logistic(logit),
        gap_seconds=gap,
        local_median_gap_seconds=local_median,
        timestamp_quality=("coarse_zero_gap" if gap == 0 else "observed"),
        version=parameters.version,
    )


def _timestamp_value(timestamp: int) -> dict[str, int | str] | None:
    if not _usable_timestamp(timestamp):
        return None
    return {
        "unix_seconds": timestamp,
        "utc": datetime.fromtimestamp(timestamp, tz=UTC).isoformat(),
    }


def render_message_window(
    messages: Sequence[Message],
    current_message_index: int,
    *,
    context_characters: int = MAX_CONTEXT_CHARACTERS,
) -> str:
    """Render bounded context while preserving the current message text in full."""

    if not 0 <= current_message_index < len(messages):
        raise ValueError("current_message_index is outside the message window.")
    other_count = max(1, len(messages) - 1)
    per_context_message = context_characters // other_count
    rendered: list[str] = []
    for index, message in enumerate(messages):
        current = index == current_message_index
        text = message.text if current else message.text[:per_context_message]
        rendered.append(
            json.dumps(
                {
                    "index": index,
                    "current_message": current,
                    "role": "assistant" if message.is_ai else "user",
                    "time": _timestamp_value(message.time),
                    "text": text,
                    "context_truncated": not current and len(text) < len(message.text),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return "\n".join(rendered)


def continuity_prompt(
    *,
    rendered_window: str,
    current_topic: TopicCandidate,
    temporal_prior: TemporalContinuityPrior,
) -> str:
    return (
        "Current Topic (JSON):\n"
        f"{json.dumps(current_topic.model_dump(mode='json'), ensure_ascii=False)}\n\n"
        "Deterministic temporal prior (JSON; weak and revisable):\n"
        f"{json.dumps(temporal_prior.model_dump(mode='json'), ensure_ascii=False)}\n\n"
        "Ordered message window (one JSON object per line):\n"
        f"{rendered_window}"
    )


def resolution_prompt(*, rendered_window: str, candidates: list[TopicCandidate]) -> str:
    return (
        "Existing thematic dossiers (JSON):\n"
        f"{candidates_prompt(candidates)}\n\n"
        "Ordered message window (one JSON object per line):\n"
        f"{rendered_window}"
    )


async def detect_topic_with_diagnostics(
    messages: Sequence[Message],
    current_message_index: int,
    current_topic_id: UUID | None,
    *,
    dependencies: TopicDetectionDependencies,
    threshold: float = CONTINUITY_THRESHOLD,
    prior_parameters: ContinuityPriorParameters = DEFAULT_CONTINUITY_PRIOR_PARAMETERS,
    context_characters: int = MAX_CONTEXT_CHARACTERS,
) -> TopicDetectionRun:
    """Run the isolated detector and return diagnostics for tests and the Lab."""

    detector_input = TopicDetectionInput(
        messages=list(messages),
        current_message_index=current_message_index,
        current_topic_id=current_topic_id,
    )
    detector_input.validate_current_message()
    current_topic = None
    if current_topic_id is not None:
        current_topic = await dependencies.catalog.get_candidate(current_topic_id)
        if current_topic is None:
            raise ValueError("current_topic_id does not designate a usable Topic.")

    rendered_window = render_message_window(
        detector_input.messages,
        detector_input.current_message_index,
        context_characters=context_characters,
    )
    total_cost = 0.0
    prior: TemporalContinuityPrior | None = None
    semantic_decision: TopicContinuityDecision | None = None
    if current_topic is not None:
        prior = calculate_continuity_prior(
            detector_input.messages,
            detector_input.current_message_index,
            parameters=prior_parameters,
        )
        interpretation, continuity_cost = await dependencies.model.interpret_continuity(
            rendered_window=rendered_window,
            current_topic=current_topic,
            temporal_prior=prior,
        )
        total_cost += continuity_cost
        same_topic = interpretation.same_topic_probability >= threshold
        semantic_decision = TopicContinuityDecision(
            same_topic_probability=interpretation.same_topic_probability,
            reason=interpretation.reason,
            same_topic=same_topic,
            threshold=threshold,
            version=CONTINUITY_DECISION_VERSION,
        )
        if same_topic:
            return TopicDetectionRun(
                evaluation=TopicDetectionEvaluation(
                    topic_id=current_topic.id,
                    resolution="continuity",
                    temporal_prior=prior,
                    semantic_continuity=semantic_decision,
                ),
                cost=total_cost,
            )

    current_message = detector_input.messages[detector_input.current_message_index]
    candidates = await dependencies.catalog.list_candidates(activity=current_message.text)
    classification, classification_cost = await dependencies.model.classify_current_message(
        rendered_window=rendered_window,
        candidates=candidates,
    )
    total_cost += classification_cost
    allowed_topic_ids = {candidate.id for candidate in candidates}
    if classification.action == "reuse" and classification.topic_id not in allowed_topic_ids:
        raise ValueError("The selected Topic was not among the proposed candidates.")
    topic_id = await dependencies.catalog.resolve(
        classification, allowed_topic_ids=allowed_topic_ids
    )
    return TopicDetectionRun(
        evaluation=TopicDetectionEvaluation(
            topic_id=topic_id,
            resolution=classification.action,
            temporal_prior=prior,
            semantic_continuity=semantic_decision,
            classification=classification,
        ),
        cost=total_cost,
    )


async def detect_topic(
    messages: Sequence[Message],
    current_message_index: int,
    current_topic_id: UUID | None,
) -> UUID:
    """Return the Topic UUID for exactly one pointed message without persisting it."""

    dependencies = _active_dependencies.get()
    if dependencies is None:
        raise TopicDetectionConfigurationError(
            "Topic detection dependencies are not bound in this execution context."
        )
    run = await detect_topic_with_diagnostics(
        messages,
        current_message_index,
        current_topic_id,
        dependencies=dependencies,
    )
    return run.evaluation.topic_id


__all__ = [
    "CONTINUITY_DECISION_VERSION",
    "CONTINUITY_THRESHOLD",
    "ContinuityPriorParameters",
    "DEFAULT_CONTINUITY_PRIOR_PARAMETERS",
    "MAX_MESSAGES",
    "PromptedTopicDetectionModel",
    "TOPIC_CONTINUITY_SYSTEM_PROMPT",
    "TOPIC_RESOLUTION_SYSTEM_PROMPT",
    "TemporalContinuityPrior",
    "TopicContinuityDecision",
    "TopicContinuityInterpretation",
    "TopicDetectionCatalog",
    "TopicDetectionConfigurationError",
    "TopicDetectionDependencies",
    "TopicDetectionEvaluation",
    "TopicDetectionInput",
    "TopicDetectionModel",
    "TopicDetectionRun",
    "TopicResolutionKind",
    "calculate_continuity_prior",
    "continuity_prompt",
    "detect_topic",
    "detect_topic_with_diagnostics",
    "render_message_window",
    "resolution_prompt",
    "topic_continuity_system_prompt",
    "topic_resolution_system_prompt",
    "use_topic_detection_dependencies",
]
