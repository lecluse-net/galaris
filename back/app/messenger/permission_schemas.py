"""Read contracts for remembered human decisions."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class PermissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    agent_id: int
    permission_key: str
    question: str
    allowed: bool | None
    approver_user_id: int
    approver_label: str = ""
    created_at: datetime
    answered_at: datetime | None


class PermissionPage(BaseModel):
    items: list[PermissionRead]
    total: int
