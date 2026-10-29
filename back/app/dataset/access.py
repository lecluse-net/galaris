"""Compatibility import; canonical implementation lives in app.document.data."""
from app.document.data.access import *  # noqa: F403

import sys as _sys
from app.document.data import access as _canonical
_sys.modules[__name__] = _canonical
