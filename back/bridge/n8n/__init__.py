"""Register the n8n adapter with the process core."""

from app.process import registry

from .client import N8NClient
from .engine import N8NProcessEngine

registry.register(N8NProcessEngine())

__all__ = ["N8NClient", "N8NProcessEngine"]
