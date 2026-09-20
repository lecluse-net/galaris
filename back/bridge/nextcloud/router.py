"""Empty router for ``core.util.router_loader``.

The Talk bridge exposes no HTTP endpoint: Galaris is a Nextcloud client and
``NextcloudTalkMessenger.listen`` receives messages. The empty router ensures
the module loader imports the package and triggers bridge registration.
"""

from fastapi import APIRouter

router = APIRouter()
