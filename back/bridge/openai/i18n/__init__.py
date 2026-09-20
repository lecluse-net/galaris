"""OpenAI bridge localization catalog."""

from .en import default as en
from .fr import default as fr

messages = {"en": en, "fr": fr}

__all__ = ["messages"]
