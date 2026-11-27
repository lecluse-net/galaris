from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

type TeamMember = tuple[Literal["agent", "user"], int]


class TeamFields(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    order: int = 0


class TeamWrite(TeamFields):
    manager_user_id: int | None = Field(default=None, gt=0)


class TeamCreate(TeamFields):
    manager_user_id: int = Field(gt=0)


class HumanInfo(BaseModel):
    id: int
    label: str
    active: bool
    avatar_url: str | None = None


class TeamInfo(TeamWrite):
    id: int
    human_count: int = 0
    human_members: list[HumanInfo] = Field(default_factory=list[HumanInfo])
    manager: HumanInfo | None = None
    model_config = ConfigDict(from_attributes=True)


class MembershipUpdate(BaseModel):
    present: bool


class ManagerAssignment(BaseModel):
    user_id: int = Field(gt=0)


class TeamMove(BaseModel):
    target_team_id: int = Field(gt=0)
    after: bool = False


class SelectionTeam(BaseModel):
    id: int
    name: str
    order: int


class HumanSelection(BaseModel):
    id: int
    teams: list[SelectionTeam] = Field(default_factory=list[SelectionTeam])
