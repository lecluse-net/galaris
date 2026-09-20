"""Ollama model-management bridge."""

from app.llm.provider_facade import (
    register_model_management,
    register_openai_protocol_adapter,
    register_resource_discovery,
)

from .services import OllamaServices
from app.llm.provider_facade import CHAT_PARAMETERS, RequestParameterPolicy, register_request_parameter_policy


def _request_parameters(model: str) -> RequestParameterPolicy:
    return RequestParameterPolicy(
        chat=CHAT_PARAMETERS - {"parallel_tool_calls"},
        efforts=("none", "low", "medium", "high"),
    )


# Custom Ollama connections do not have a fixed catalog profile.
SERVICES = OllamaServices()
register_resource_discovery("ollama", SERVICES)
register_model_management("ollama", SERVICES)
register_openai_protocol_adapter("ollama", SERVICES)
register_request_parameter_policy("ollama", _request_parameters)

__all__ = ["SERVICES"]
