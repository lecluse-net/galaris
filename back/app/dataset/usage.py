"""Compatibility import; canonical implementation lives in app.document.data."""
from app.document.data.usage import *  # noqa: F403

import sys as _sys
from app.document.data import usage as _canonical
_sys.modules[__name__] = _canonical
