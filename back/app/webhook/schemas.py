from pydantic import BaseModel
from typing import Any, Dict, Optional


class WebhookPayload(BaseModel):
    """Payload received from an external webhook."""
    event: str
    data: Dict[str, Any]
    timestamp: Optional[str] = None


class WebhookResponse(BaseModel):
    """Webhook processing response."""
    status: str
    message: str
    task_id: Optional[str] = None
