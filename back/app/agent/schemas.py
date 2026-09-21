from core.util import normalize_html
from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator
from typing import Optional
from uuid import UUID


class ExecutorDriverInfo(BaseModel):
    """Driver metadata exposed to the agent driver selector."""
    name: str
    label_key: str
    available: bool
    manages_runtime: bool
    enabled: bool = True
    configured: bool = True
    ready: bool = True
    reason: Optional[str] = None
    supports_streaming: bool = True
    supports_cancellation: bool = False
    use_planner: bool = False
    use_briefing: bool = False
    briefing_efforts: list[str] = Field(default_factory=list)
    execution_efforts: list[str] = Field(default_factory=lambda: ["standard"])
    uses_llm_calls: bool = False


# Title schemas
class TitleBase(BaseModel):
    label: str
    gender: str = Field(..., pattern="^[MF]$")

class TitleCreate(TitleBase):
    pass

class TitleUpdate(BaseModel):
    label: Optional[str] = None
    gender: Optional[str] = Field(default=None, pattern="^[MF]$")

class Title(TitleBase):
    id: int

    model_config = ConfigDict(from_attributes=True)

# AgentGroup schemas
class AgentGroupBase(BaseModel):
    name: str
    order: int = 0

class AgentGroupCreate(AgentGroupBase):
    pass

class AgentGroupUpdate(BaseModel):
    name: Optional[str] = None
    order: Optional[int] = None

class AgentGroup(AgentGroupBase):
    id: int

    model_config = ConfigDict(from_attributes=True)

# Agent schemas
class AgentBase(BaseModel):
    title_id: int
    group_id: Optional[int] = None
    code: str
    first_name: str
    last_name: str
    personality: Optional[str] = None
    job_description: Optional[str] = None
    job_title: Optional[str] = None
    agent_driver: str = "internal"
    profile_id: Optional[int] = None
    voice: Optional[str] = Field(default=None, max_length=512)

    @field_validator('agent_driver', mode='before')
    @classmethod
    def default_agent_driver(cls, v: Optional[str]) -> str:
        return v or "internal"

    @field_validator("voice", mode="before")
    @classmethod
    def normalize_voice(cls, value: Optional[str]) -> Optional[str]:
        from .voice import normalize_voice_selection

        return normalize_voice_selection(value)

_STR_NULLABLE = ["personality", "job_description", "job_title"]

class AgentCreate(AgentBase):
    user_id: Optional[int] = None

    @field_validator(*_STR_NULLABLE, mode='before')
    @classmethod
    def empty_str_to_none(cls, v: Optional[str]) -> Optional[str]:
        return None if v == '' else v

    @field_validator("personality", "job_description")
    @classmethod
    def validate_editorial_html(cls, value: str | None) -> str | None:
        return normalize_html(value) if value is not None else None


class AgentUpdate(BaseModel):
    user_id: Optional[int] = None
    title_id: Optional[int] = None
    group_id: Optional[int] = None
    code: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    personality: Optional[str] = None
    job_description: Optional[str] = None
    job_title: Optional[str] = None
    agent_driver: Optional[str] = None
    profile_id: Optional[int] = None
    voice: Optional[str] = Field(default=None, max_length=512)

    @field_validator(*_STR_NULLABLE, mode='before')
    @classmethod
    def empty_str_to_none(cls, v: Optional[str]) -> Optional[str]:
        return None if v == '' else v

    @field_validator("voice", mode="before")
    @classmethod
    def normalize_voice(cls, value: Optional[str]) -> Optional[str]:
        from .voice import normalize_voice_selection

        return normalize_voice_selection(value)

    @field_validator("user_id")
    @classmethod
    def require_user_id_when_provided(cls, value: Optional[int]) -> int:
        if value is None:
            raise ValueError("user_id cannot be null")
        return value


    @field_validator("personality", "job_description")
    @classmethod
    def validate_editorial_html(cls, value: str | None) -> str | None:
        return normalize_html(value) if value is not None else None


class AgentManagerInfo(BaseModel):
    id: int
    email: str
    display_name: Optional[str] = None
    is_current_user: bool = False

    model_config = ConfigDict(from_attributes=True)

class LlmProfileInfo(BaseModel):
    """Minimal profile descriptor attached to an agent."""

    id: int
    label: str

    model_config = ConfigDict(from_attributes=True)


class Agent(AgentBase):
    team_ids: list[int] = Field(default_factory=list[int])
    profile_media_type: str = "text/html"
    content_profile: str = "rich-text"
    content_profile_version: int = 1
    id: int
    task_harness_id: Optional[UUID] = None
    user_id: int
    user: AgentManagerInfo
    memory_item_id: Optional[UUID] = None
    title: Optional[Title] = None
    has_avatar: bool = False
    is_owner: bool = False
    profile: Optional[LlmProfileInfo] = None

    @computed_field
    @property
    def resource_uri(self) -> str:
        return f"galaris://agent/{self.id}"

    model_config = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)
