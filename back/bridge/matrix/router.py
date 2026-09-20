"""Empty router for ``core.util.router_loader``.

The Matrix bridge exposes no HTTP endpoint: Galaris is a homeserver client and
receives messages through ``MatrixMessenger.listen``. The empty router follows
the bridge module convention and avoids a loader warning; registration happens
when ``__init__.py`` is imported.
"""

from fastapi import APIRouter

router = APIRouter()
