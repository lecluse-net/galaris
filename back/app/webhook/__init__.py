"""Historical webhook translation; the retired router exposes no HTTP routes."""

from .router import router
from .schemas import WebhookResponse

__all__ = ["router", "WebhookResponse"]
