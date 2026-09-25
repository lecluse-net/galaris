"""Bounded requests and generated drafts for synthetic Lab datasets."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .contracts import LabInput
from .schemas import AnalysisLanguage, CaseCategory, EvaluationCaseCreate, EvaluationDatasetRead


class SyntheticDatasetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=300)
    instructions: str = Field(default="", max_length=6000)
    count: int = Field(default=8, ge=1, le=20)
    language: AnalysisLanguage = "fr"
    llm_id: int | None = Field(default=None, gt=0)
    source_dataset_id: UUID | None = None
    source_revision: int | None = Field(default=None, ge=1)
    categories: list[CaseCategory] = Field(
        default_factory=lambda: ["nominal", "ambiguity", "incomplete"], min_length=1, max_length=8
    )

    @model_validator(mode="after")
    def distinct_categories(self) -> "SyntheticDatasetRequest":
        if (self.source_dataset_id is None) != (self.source_revision is None):
            raise ValueError("Provide both the source dataset and its revision")
        self.categories = list(dict.fromkeys(self.categories))
        if len(self.categories) > self.count:
            raise ValueError("Request at least one case per selected category")
        return self


class SyntheticCase(EvaluationCaseCreate):
    input_data: LabInput
    expected_output: JsonValue
    categories: list[CaseCategory] = Field(min_length=1, max_length=8)


class SyntheticContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str = Field(min_length=1, max_length=10000)
    parameters: dict[str, JsonValue]
    cases: list[SyntheticCase] = Field(min_length=1, max_length=20)


class SyntheticDatasetResult(BaseModel):
    dataset: EvaluationDatasetRead
    cost: float


class SyntheticToolCall(BaseModel):
    name: str
    arguments: dict[str, JsonValue]


class SyntheticToolResult(SyntheticToolCall):
    result: JsonValue


class SyntheticExecutorOutput(BaseModel):
    action: Literal["reply", "start_task", "start_process", "read_status", "use_tool"]
    response: str = Field(min_length=1)
    tool_calls: list[SyntheticToolCall]
    tool_results: list[SyntheticToolResult]
