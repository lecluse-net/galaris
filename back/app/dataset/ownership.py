"""Compatibility import; canonical implementation lives in app.document.data."""
from app.document.data.ownership import *  # noqa: F403

import sys as _sys
from app.document.data import ownership as _canonical
_sys.modules[__name__] = _canonical
