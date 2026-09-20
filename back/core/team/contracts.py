from pydantic import BaseModel, ConfigDict, Field


class TeamWrite(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=4000)
    order: int = 0


class HumanInfo(BaseModel):
    id: int
    label: str
    active: bool
    avatar_url: str | None = None


class TeamInfo(TeamWrite):
    id: int
    human_count: int = 0
    human_members: list[HumanInfo] = Field(default_factory=list[HumanInfo])
    model_config = ConfigDict(from_attributes=True)


class MembershipUpdate(BaseModel):
    present: bool


class TeamMove(BaseModel):
    target_team_id: int = Field(gt=0)
    after: bool = False
