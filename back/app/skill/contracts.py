"""Identity and authorization contracts shared by Skills adapters."""

from enum import StrEnum
import hashlib
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


SKILLS_TOOL_CODE = "skills"
PERSONAL_URI_SEGMENT = "personnal"
SKILL_CATALOGUE_LOCK = 1741533121


class SkillScope(StrEnum):
    USAGE = "usage"
    PERSONAL = "personal"
    TEAM = "team"
    ALL = "all"


class SkillPackageRef(BaseModel):
    """Stable identity; a code alone cannot identify a personal package."""

    model_config = ConfigDict(frozen=True)

    id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    owner_agent_id: int | None = Field(gt=0)
    revision: int = Field(gt=0)

    @computed_field
    @property
    def kind(self) -> Literal["generic", "personal"]:
        return "generic" if self.owner_agent_id is None else "personal"

    @computed_field
    @property
    def uri(self) -> str:
        if self.owner_agent_id is None:
            return f"galaris://skill/{self.code}/"
        return f"galaris://skill/{PERSONAL_URI_SEGMENT}/{self.owner_agent_id}/{self.code}/"


class SkillPackageCreate(BaseModel):
    """Ownership comes exclusively from the authenticated calling agent."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    label: str = Field(min_length=1, max_length=255)
    markdown: str


class SkillRevisionConflict(RuntimeError):
    """The package changed after the caller read it."""


def runtime_skill_name(code: str, kind: str, identity: str, occupied: set[str]) -> str:
    """Keep short existing names, allocate bounded collision-free projection names."""
    candidate = code
    attempt = 0
    while candidate in occupied or len(candidate) > 40:
        digest = hashlib.sha256(f"{kind}:{identity}:{attempt}".encode()).hexdigest()[:12]
        candidate = f"{kind[:8]}-{code[:18]}-{digest}"
        attempt += 1
    occupied.add(candidate)
    return candidate
