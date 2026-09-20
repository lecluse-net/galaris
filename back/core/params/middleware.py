"""Accept the administrator-selected runtime API hostname without a restart."""

from urllib.parse import urlsplit

from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from core.settings import settings
from .runtime_settings import runtime_settings


class RuntimeTrustedHostMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        hosts = settings.ALLOWED_HOSTS
        hostname = urlsplit(runtime_settings.HARNESS_MANAGER_GALARIS_API_URL).hostname
        if hostname:
            hosts.append(hostname)
        await TrustedHostMiddleware(self.app, allowed_hosts=hosts)(scope, receive, send)
