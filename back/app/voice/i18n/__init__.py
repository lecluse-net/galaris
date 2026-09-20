"""Voice catalog aggregated by ``core.i18n``."""

from .en import default as en
from .fr import default as fr

messages = {"en": en, "fr": fr}

__all__ = ["messages"]
