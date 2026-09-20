"""Pydantic contracts for the skill library API."""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


SKILL_CODE_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
SkillAuthorizationState = Literal["default", "enabled", "disabled"]
SkillGlobalAuthorizationState = Literal["enabled", "disabled"]
SkillCategoryAuthorizationState = SkillAuthorizationState


class SkillBase(BaseModel):
    code: str = Field(min_length=1, max_length=100, pattern=SKILL_CODE_PATTERN)
    label: str = Field(min_length=1, max_length=255)

    @field_validator("code", "label", mode="before")
    @classmethod
    def trim_strings(cls, value: str) -> str:
        return str(value).strip()


class SkillCreate(SkillBase):
    markdown: Optional[str] = None
    category_id: Optional[int] = Field(default=None, gt=0)


class SkillUpdate(BaseModel):
    label: Optional[str] = Field(default=None, min_length=1, max_length=255)
    markdown: Optional[str] = None

    @field_validator("label", mode="before")
    @classmethod
    def trim_label(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if isinstance(value, str) else value


class SkillFile(BaseModel):
    path: str
    name: str
    size: int
    text: bool


class SkillFileContent(BaseModel):
    path: str
    content: str
    size: int


class SkillPublic(SkillBase):
    id: int
    system: bool
    available: bool
    valid: bool
    validation_error: Optional[str] = None
    description: Optional[str] = None
    category_id: Optional[int] = None
    category_label: Optional[str] = None
    file_count: int = 0
    total_size: int = 0
    created_at: datetime
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SkillAuthorizationUpdate(BaseModel):
    state: SkillAuthorizationState


class SkillGlobalAuthorizationUpdate(BaseModel):
    state: SkillGlobalAuthorizationState


class SkillCategoryAuthorizationUpdate(BaseModel):
    state: SkillCategoryAuthorizationState


class SkillCategoryBase(BaseModel):
    label: str = Field(min_length=1, max_length=255)

    @field_validator("label", mode="before")
    @classmethod
    def trim_label(cls, value: str) -> str:
        return str(value).strip()


class SkillCategoryCreate(SkillCategoryBase):
    pass


class SkillCategoryUpdate(SkillCategoryBase):
    pass


class SkillCategoryPublic(SkillCategoryBase):
    id: int
    skill_count: int


class SkillCategoryAssignmentUpdate(BaseModel):
    category_id: Optional[int] = Field(default=None, gt=0)


class SkillAuthorization(BaseModel):
    skill_id: int
    code: str
    label: str
    agent_id: int
    agent_code: str
    agent_label: str
    agent_driver: str
    description: Optional[str] = None
    category_id: Optional[int] = None
    category_label: Optional[str] = None
    available: bool
    valid: bool
    global_state: SkillGlobalAuthorizationState
    category_state: SkillCategoryAuthorizationState
    agent_state: SkillAuthorizationState
    effective: bool


class SkillAuthorizations(BaseModel):
    authorizations: list[SkillAuthorization]


class SkillAuthorizationResult(SkillAuthorization):
    affected_agent_ids: list[int]


class SkillCategoryResult(BaseModel):
    category: SkillCategoryPublic
    affected_agent_ids: list[int] = Field(default_factory=list[int])


class SkillCategoryAuthorizationResult(BaseModel):
    category_id: int
    agent_id: int
    state: SkillCategoryAuthorizationState
    affected_agent_ids: list[int] = Field(default_factory=list[int])


class SkillCategoryDeleteResult(BaseModel):
    affected_skill_ids: list[int]
    affected_agent_ids: list[int]


class SkillCategoryAssignmentResult(BaseModel):
    skill: SkillPublic
    affected_agent_ids: list[int]


class SkillDeleteResult(BaseModel):
    affected_agent_ids: list[int]


class SkillRescanResult(BaseModel):
    created: int
    restored: int
    invalid_directories: list[str]


class SkillImportResult(BaseModel):
    skill: SkillPublic
    created: bool


class SkillAgent(BaseModel):
    id: int
    code: str
    label: str
    driver: str


class LearnedSkillEvidencePublic(BaseModel):
    id: UUID
    source_ref: str
    operation: Literal["CREATE", "REINFORCE", "REVISE", "WEAKEN"]
    polarity: Literal["positive", "negative"]
    weight: float
    confidence: float
    evidence_refs: list[str]
    rationale: str
    created_at: datetime


class LearnedSkillPublic(BaseModel):
    id: UUID
    agent_id: int
    code: str
    label: str
    description: str
    revision: int
    positive_weight: float
    negative_weight: float
    evidence_count: int
    score: float
    suspended: bool
    injectable: bool
    last_evidence_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class LearnedSkillDetail(LearnedSkillPublic):
    markdown: str
    evidences: list[LearnedSkillEvidencePublic]


class LearnedSkillPage(BaseModel):
    items: list[LearnedSkillPublic]
    total: int
    page: int
    page_size: int


class LearnedSkillSuspensionUpdate(BaseModel):
    suspended: bool


class LearnedSkillMutationResult(BaseModel):
    skill: LearnedSkillPublic
    affected_agent_ids: list[int]


class LearnedSkillLearningStatus(BaseModel):
    mode: Literal["off", "observe", "learn"]
    enabled: bool
