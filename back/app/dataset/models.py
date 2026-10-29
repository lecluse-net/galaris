"""Compatibility import; canonical implementation lives in app.document.data."""
from app.document.data.models import *  # noqa: F403

import sys as _sys
from app.document.data import models as _canonical
_sys.modules[__name__] = _canonical
