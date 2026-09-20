"""API contracts for the operational dashboard."""

from datetime import date

from pydantic import BaseModel, Field


class DashboardTotals(BaseModel):
    """Headline indicators for one calendar month."""

    tasks: int = 0
    successful_tasks: int = 0
    task_errors: int = 0
    llm_calls: int = 0
    llm_errors: int = 0
    incidents: int = 0
    tokens: int = 0
    cost: float = 0.0
    inference_cost: float = 0.0
    average_llm_duration: float = 0.0
    task_success_rate: float = 0.0
    llm_success_rate: float = 0.0


class DailyLlmUsage(BaseModel):
    """Usage of one configured or effective model on one day."""

    date: date
    llm_key: str
    llm_label: str
    provider_name: str = ""
    calls: int = 0
    errors: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tokens: int = 0
    cost: float = 0.0
    inference_cost: float = 0.0


class AgentUsage(BaseModel):
    """Monthly workload and reliability indicators for one agent."""

    agent_id: int
    agent_name: str
    job_title: str | None = None
    has_avatar: bool = False
    tasks: int = 0
    successful_tasks: int = 0
    task_errors: int = 0
    llm_calls: int = 0
    llm_errors: int = 0
    incidents: int = 0
    tokens: int = 0
    cost: float = 0.0
    average_llm_duration: float = 0.0
    task_success_rate: float = 0.0


class DashboardResponse(BaseModel):
    """Complete data required to render one monthly dashboard."""

    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    available_months: list[str]
    totals: DashboardTotals
    previous_totals: DashboardTotals
    daily_usage: list[DailyLlmUsage]
    agents: list[AgentUsage]
