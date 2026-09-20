"""
LLM provider handlers.
"""
from .base import BaseLLMHandler, LLMModelInfo
from .detector import get_handler, get_handler_for_url
from .openai_compatible import OpenAICompatibleHandler

__all__ = [
    "BaseLLMHandler",
    "LLMModelInfo",
    "get_handler",
    "get_handler_for_url",
    "OpenAICompatibleHandler",
]
