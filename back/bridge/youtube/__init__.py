"""Pure YouTube caption bridge used by ``app.audio``.

The bridge has no router, model, or import-time registration, so it is not listed in
``back/modules.py``.
"""

from . import transcript_service

__all__ = ["transcript_service"]
