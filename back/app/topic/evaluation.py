"""Side-effect-free Topic detection adapter used by the AI Lab."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.llm import LLM
from app.agent.contracts import TaskMessage as Message

from .schemas import TopicCandidate, TopicClassification
from .sequential_detection import (
    ContinuityPriorParameters,
    TOPIC_CONTINUITY_SYSTEM_PROMPT,
    TOPIC_RESOLUTION_SYSTEM_PROMPT,
    PromptedTopicDetectionModel,
    TopicDetectionDependencies,
    detect_topic_with_diagnostics,
    topic_continuity_system_prompt,
    topic_resolution_system_prompt,
)


TOPIC_LAB_CONFIGURATION_SCHEMA = "galaris.topic-lab-configuration/v1"


class TopicDetectionLabTopic(BaseModel):
    """Human-readable Topic representation used in datasets and judge prompts."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=4_000)
    keywords: list[str] = Field(default_factory=list[str], max_length=20)

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("keywords")
    @classmethod
    def normalize_keywords(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip()[:80] for value in values if value.strip()))


class TopicDetectionLabInput(BaseModel):
    """One ordered two-party exchange evaluated message by message."""

    model_config = ConfigDict(extra="forbid")

    messages: list[Message] = Field(min_length=1, max_length=500)
    initial_topic: TopicDetectionLabTopic | None = None

    @model_validator(mode="after")
    def validate_messages(self) -> "TopicDetectionLabInput":
        if any(not message.text.strip() for message in self.messages):
            raise ValueError("Every message in the exchange must contain usable text.")
        return self


class TopicDetectionLabOutput(BaseModel):
    """Expected or detected human-readable Topic for every message."""

    model_config = ConfigDict(extra="forbid")

    topics: list[str | None] = Field(min_length=1, max_length=500)

    @field_validator("topics")
    @classmethod
    def normalize_topics(cls, values: list[str | None]) -> list[str | None]:
        topics = [value.strip() if value is not None else None for value in values]
        if any(value == "" for value in topics):
            raise ValueError("A Topic must be a non-empty title or null when not yet known.")
        return topics


class TopicDetectionLabPrompts(BaseModel):
    """Exact system prompts used by a portable Topic Lab dataset."""

    model_config = ConfigDict(extra="forbid")

    continuity_system_prompt: str = Field(min_length=1, max_length=50_000)
    resolution_system_prompt: str = Field(min_length=1, max_length=50_000)

    @field_validator("continuity_system_prompt", "resolution_system_prompt")
    @classmethod
    def strip_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A Topic detection system prompt cannot be blank.")
        return value


class TopicDetectionLabConfiguration(BaseModel):
    """Portable catalogue and prompts belonging to one Topic Lab dataset."""

    model_config = ConfigDict(extra="forbid")

    schema_: Literal["galaris.topic-lab-configuration/v1"] = Field(
        default=TOPIC_LAB_CONFIGURATION_SCHEMA,
        alias="schema",
        serialization_alias="schema",
    )
    topics: list[TopicDetectionLabTopic] = Field(
        default_factory=list[TopicDetectionLabTopic], max_length=500
    )
    prompts: TopicDetectionLabPrompts
    window_messages: int = Field(default=10, ge=1, le=10)
    context_characters: int = Field(default=12_000, ge=100, le=100_000)
    continuity_threshold: float = Field(default=0.55, ge=0, le=1)
    prior: ContinuityPriorParameters = Field(default_factory=ContinuityPriorParameters)

    @model_validator(mode="after")
    def unique_topic_titles(self) -> "TopicDetectionLabConfiguration":
        normalized = [topic.title.casefold() for topic in self.topics]
        if len(normalized) != len(set(normalized)):
            raise ValueError("Predefined Topic titles must be unique.")
        return self


async def default_topic_lab_configuration() -> TopicDetectionLabConfiguration:
    """Resolve visible runtime prompt preferences into a self-contained dataset."""

    return TopicDetectionLabConfiguration(
        topics=[],
        prompts=TopicDetectionLabPrompts(
            continuity_system_prompt=await topic_continuity_system_prompt(),
            resolution_system_prompt=await topic_resolution_system_prompt(),
        ),
    )


def built_in_topic_lab_configuration() -> TopicDetectionLabConfiguration:
    """Return the database-independent defaults used by isolated callers."""

    return TopicDetectionLabConfiguration(
        topics=[],
        prompts=TopicDetectionLabPrompts(
            continuity_system_prompt=TOPIC_CONTINUITY_SYSTEM_PROMPT,
            resolution_system_prompt=TOPIC_RESOLUTION_SYSTEM_PROMPT,
        ),
    )


async def resolve_topic_lab_configuration(
    value: object,
) -> TopicDetectionLabConfiguration:
    """Validate stored data, filling only legacy datasets that predate configuration."""

    if isinstance(value, dict) and value:
        return TopicDetectionLabConfiguration.model_validate(value)
    return await default_topic_lab_configuration()


class ReadOnlyLabTopicCatalog:
    """Use only a dataset's portable catalogue without persisting decisions."""

    def __init__(
        self,
        current_topic: TopicDetectionLabTopic | None = None,
        topics: Sequence[TopicDetectionLabTopic] = (),
    ) -> None:
        self._candidates: dict[UUID, TopicCandidate] = {}
        self.current_topic_id: UUID | None = None
        for topic in topics:
            topic_id = _lab_topic_id(topic)
            self._candidates[topic_id] = TopicCandidate(
                id=topic_id,
                title=topic.title,
                description=topic.description,
                keywords=topic.keywords,
            )
        if current_topic is not None:
            self.current_topic_id = _lab_topic_id(current_topic)
            self._candidates[self.current_topic_id] = TopicCandidate(
                id=self.current_topic_id,
                title=current_topic.title,
                description=current_topic.description,
                keywords=current_topic.keywords,
            )

    async def get_candidate(self, topic_id: UUID) -> TopicCandidate | None:
        return self._candidates.get(topic_id)

    async def list_candidates(self, *, activity: str) -> list[TopicCandidate]:
        del activity
        return list(self._candidates.values())

    async def resolve(
        self,
        decision: TopicClassification,
        *,
        allowed_topic_ids: set[UUID],
    ) -> UUID:
        if decision.action == "reuse":
            if decision.topic_id not in allowed_topic_ids:
                raise ValueError("The selected Topic is outside the Lab catalogue.")
            assert decision.topic_id is not None
            return decision.topic_id
        topic = TopicDetectionLabTopic(
            title=decision.title,
            description=decision.description,
            keywords=decision.keywords,
        )
        topic_id = _lab_topic_id(topic)
        self._candidates[topic_id] = TopicCandidate(
            id=topic_id,
            title=topic.title,
            description=topic.description,
            keywords=topic.keywords,
        )
        return topic_id


def _lab_topic_id(topic: TopicDetectionLabTopic) -> UUID:
    identity = json.dumps(
        {
            "title": topic.title.casefold(),
            "description": topic.description.casefold(),
            "keywords": sorted(keyword.casefold() for keyword in topic.keywords),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return uuid5(NAMESPACE_URL, f"galaris:lab:topic:{identity}")


def topic_detection_case_prompt(value: Any) -> str:
    """Validate and serialize the human-readable Lab detector input."""

    detector_input = TopicDetectionLabInput.model_validate(value)
    return detector_input.model_dump_json()


async def evaluate_topic_detection(
    *,
    input_data: Any,
    llm: LLM,
    configuration: TopicDetectionLabConfiguration | None = None,
    use_decision_profile: bool = False,
) -> tuple[dict[str, list[str | None]], float]:
    """Execute the production detector sequentially for a complete exchange."""

    detector_input = TopicDetectionLabInput.model_validate(input_data)
    configuration = configuration or built_in_topic_lab_configuration()
    catalog = ReadOnlyLabTopicCatalog(
        detector_input.initial_topic,
        configuration.topics,
    )
    dependencies = TopicDetectionDependencies(
        catalog=catalog,
        model=PromptedTopicDetectionModel(
            llm,
            use_decision_profile=use_decision_profile,
            continuity_system_prompt=configuration.prompts.continuity_system_prompt,
            resolution_system_prompt=configuration.prompts.resolution_system_prompt,
        ),
    )
    current_topics: dict[tuple[str, str], UUID | None] = {}
    detected_topics: list[str | None] = []
    cost = 0.0
    for index, message in enumerate(detector_input.messages):
        scope = (
            message.platform,
            str(message.room_id or message.room_external_id),
        )
        current_topic_id = current_topics.get(scope, catalog.current_topic_id)
        window_start = max(0, index - configuration.window_messages + 1)
        window = detector_input.messages[window_start : index + 1]
        run = await detect_topic_with_diagnostics(
            window,
            len(window) - 1,
            current_topic_id,
            dependencies=dependencies,
            threshold=configuration.continuity_threshold,
            prior_parameters=configuration.prior,
            context_characters=configuration.context_characters,
        )
        if run.evaluation.topic_id is None:
            current_topics[scope] = None
            detected_topics.append(None)
            cost += run.cost
            continue
        selected_topic = await catalog.get_candidate(run.evaluation.topic_id)
        if selected_topic is None:
            raise ValueError("The Lab detector returned an unknown Topic.")
        current_topics[scope] = run.evaluation.topic_id
        detected_topics.append(selected_topic.title)
        cost += run.cost
    return TopicDetectionLabOutput(topics=detected_topics).model_dump(mode="json"), cost


__all__ = [
    "TOPIC_CONTINUITY_SYSTEM_PROMPT",
    "TOPIC_LAB_CONFIGURATION_SCHEMA",
    "TOPIC_RESOLUTION_SYSTEM_PROMPT",
    "ReadOnlyLabTopicCatalog",
    "TopicDetectionLabConfiguration",
    "TopicDetectionLabInput",
    "TopicDetectionLabOutput",
    "TopicDetectionLabPrompts",
    "TopicDetectionLabTopic",
    "built_in_topic_lab_configuration",
    "default_topic_lab_configuration",
    "evaluate_topic_detection",
    "resolve_topic_lab_configuration",
    "topic_detection_case_prompt",
]
