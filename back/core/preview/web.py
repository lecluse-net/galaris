"""Public Web preview port; the active transport owns URL and network policy."""

from core.user import HumanActor

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class WebLinkPreview:
    title: str
    description: str
    site_name: str
    image: bytes | None = None
    page_url: str | None = None


class WebPreviewProvider(Protocol):
    async def __call__(self, url: str, *, agent_id: int | HumanActor) -> WebLinkPreview: ...


_provider: WebPreviewProvider | None = None


def register_web_preview_provider(provider: WebPreviewProvider) -> None:
    """Bind the public HTTPS transport at application composition."""
    global _provider
    _provider = provider


async def preview_web_link(url: str, *, agent_id: int | HumanActor) -> WebLinkPreview:
    if _provider is None:
        raise ValueError("Web previews are unavailable")
    return await _provider(url, agent_id=agent_id)
