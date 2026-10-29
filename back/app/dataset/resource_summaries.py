"""Compatibility import; canonical implementation lives in app.document.data."""
from app.document.data.resource_summaries import *  # noqa: F403

import sys as _sys
from app.document.data import resource_summaries as _canonical
_sys.modules[__name__] = _canonical
