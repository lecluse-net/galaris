"""Public Dream inference contracts used by isolated AI Lab benchmarks."""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.llm import LLM

from .contracts import (
    MemoryExtractionLabOutput as MemoryExtractionLabOutput,
    MAX_MEMORY_EXTRACTION_CANDIDATES,
    MemoryExtractionInput,
    TaskOutcomeReflection,
)
from .mechanisms.memory_extraction import (
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
    memory_extraction_system_prompt,
    rank_existing_memories,
    run_memory_extraction,
)
from .mechanisms.task_outcome_reflection import outcome_reflection_system_prompt


class MemoryExtractionLabConfiguration(BaseModel):
    """One dataset-owned prompt, independent from runtime after creation."""

    model_config = ConfigDict(extra="forbid")

    schema_: Literal["galaris.memory-extraction-lab-configuration"] = Field(
        default="galaris.memory-extraction-lab-configuration",
        alias="schema",
        serialization_alias="schema",
    )
    system_prompt: str = Field(min_length=1, max_length=50_000)
    language_instruction: str = Field(default="", max_length=2000)
    ranking_limit: int = Field(default=10, ge=1, le=10)
    title_weight: float = Field(default=3.0, ge=0, le=100)
    content_weight: float = Field(default=1.0, ge=0, le=100)
    output_attempts: int = Field(default=2, ge=1, le=5)

    @field_validator("system_prompt")
    @classmethod
    def prompt_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("The memory extraction system prompt cannot be blank.")
        return value


async def default_memory_extraction_lab_configuration() -> MemoryExtractionLabConfiguration:
    return MemoryExtractionLabConfiguration(system_prompt=await memory_extraction_system_prompt())


def built_in_memory_extraction_lab_configuration() -> MemoryExtractionLabConfiguration:
    return MemoryExtractionLabConfiguration(system_prompt=MEMORY_EXTRACTION_SYSTEM_PROMPT)


async def resolve_memory_extraction_lab_configuration(
    value: object,
) -> MemoryExtractionLabConfiguration:
    if isinstance(value, dict) and value:
        return MemoryExtractionLabConfiguration.model_validate(value)
    return await default_memory_extraction_lab_configuration()


async def evaluate_memory_extraction(
    *,
    input_data: object,
    llm: LLM,
    configuration: MemoryExtractionLabConfiguration | None = None,
    use_decision_profile: bool = False,
) -> tuple[dict[str, object], float]:
    """Run production extraction using only the case-local memory corpus."""

    bounded_input = input_data
    if isinstance(input_data, dict):
        input_mapping = cast(dict[str, Any], input_data)
        memories = input_mapping.get("existing_memories")
        if isinstance(memories, list):
            bounded_input = cast(
                dict[str, Any],
                {
                    **input_mapping,
                    "existing_memories": cast(list[Any], memories)[
                        :MAX_MEMORY_EXTRACTION_CANDIDATES
                    ],
                },
            )
    extraction_input = MemoryExtractionInput.model_validate(bounded_input)
    if not extraction_input.topic:
        raise ValueError("Memory extraction requires a non-null Topic.")
    resolved = configuration or built_in_memory_extraction_lab_configuration()
    ranked = rank_existing_memories(
        extraction_input,
        limit=resolved.ranking_limit,
        title_weight=resolved.title_weight,
        content_weight=resolved.content_weight,
    )
    isolated_input = extraction_input.model_copy(update={"existing_memories": ranked})
    prepared, cost = await run_memory_extraction(
        llm=llm,
        input_data=isolated_input,
        system_prompt=resolved.system_prompt,
        task_id=None,
        agent_id=None,
        language_instruction=resolved.language_instruction,
        output_attempts=resolved.output_attempts,
        use_decision_profile=use_decision_profile,
    )
    output = MemoryExtractionLabOutput(
        operations=prepared.decision.operations,
        ranked_memory_ids=[item.id for item in ranked],
    )
    return output.model_dump(mode="json"), cost


__all__ = [
    "MEMORY_EXTRACTION_SYSTEM_PROMPT",
    "MemoryExtractionInput",
    "MemoryExtractionLabConfiguration",
    "MemoryExtractionLabOutput",
    "TaskOutcomeReflection",
    "built_in_memory_extraction_lab_configuration",
    "default_memory_extraction_lab_configuration",
    "evaluate_memory_extraction",
    "memory_extraction_system_prompt",
    "outcome_reflection_system_prompt",
    "resolve_memory_extraction_lab_configuration",
]
