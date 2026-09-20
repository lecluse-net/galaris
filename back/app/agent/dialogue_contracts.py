from dataclasses import dataclass, field
from typing import Literal
from pydantic import BaseModel, Field


class DialogueDecision(BaseModel):
    allowed: bool
    source: Literal["manager", "global", "same_team", "default", "inactive"]
    team_ids: list[int] = Field(default_factory=list[int])


class DialogueAgent(BaseModel):
    id: int
    label: str
    code: str
    manager_user_id: int
    team_ids: list[int]
    has_avatar: bool = False


@dataclass
class DialoguePolicy:
    """Request-local snapshot. Never cache this across requests or live emissions."""
    agents: dict[int, DialogueAgent] = field(default_factory=dict[int, DialogueAgent])
    humans: dict[int, set[int]] = field(default_factory=dict[int, set[int]])

    def human(self, user_id: int, agent_id: int, *, active: bool = True, global_access: bool = False) -> DialogueDecision:
        agent = self.agents.get(agent_id)
        if not active or agent is None:
            return DialogueDecision(allowed=False, source="inactive")
        if global_access:
            return DialogueDecision(allowed=True, source="global")
        if agent.manager_user_id == user_id:
            return DialogueDecision(allowed=True, source="manager")
        human_teams = self.humans.get(user_id, set())
        common = sorted(human_teams.intersection(agent.team_ids))
        if common:
            return DialogueDecision(allowed=True, source="same_team", team_ids=common)
        return DialogueDecision(allowed=False, source="default")

    def peers(self, left: int, right: int) -> DialogueDecision:
        a, b = self.agents.get(left), self.agents.get(right)
        if a is None or b is None:
            return DialogueDecision(allowed=False, source="inactive")
        common = sorted(set(a.team_ids).intersection(b.team_ids))
        if left == right or common:
            return DialogueDecision(allowed=True, source="same_team", team_ids=common)
        return DialogueDecision(allowed=False, source="default")
