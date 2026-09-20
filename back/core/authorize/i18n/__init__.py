"""Authorization translation catalog."""

from .en import default as en
from .fr import default as fr
from .zh import default as zh

messages = {"en": en, "fr": fr, "zh": zh}

__all__ = ["messages"]
