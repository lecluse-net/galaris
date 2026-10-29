"""Compatibility import; canonical implementation lives in app.document.data."""
from app.document.data.service import *  # noqa: F403

import sys as _sys
from app.document.data import service as _canonical
_sys.modules[__name__] = _canonical
