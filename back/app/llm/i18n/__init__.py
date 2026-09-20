"""LLM localization catalog and language-specific routing vocabulary."""

from .en import ACTION_KEYWORDS as EN_ACTION_KEYWORDS, default as en
from .fr import ACTION_KEYWORDS as FR_ACTION_KEYWORDS, default as fr

ACTION_KEYWORDS = (*EN_ACTION_KEYWORDS, *FR_ACTION_KEYWORDS)
messages = {"en": en, "fr": fr}

__all__ = ["ACTION_KEYWORDS", "messages"]
