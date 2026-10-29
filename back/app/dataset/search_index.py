"""Compatibility import; canonical implementation lives in app.document.data."""
from app.document.data.search_index import *  # noqa: F403

import sys as _sys
from app.document.data import search_index as _canonical
_sys.modules[__name__] = _canonical
