"""Shared public voice discovery; each provider owns an isolated catalogue cache."""

from re import Pattern
from time import monotonic

import httpx

from .capabilities import with_capability
from .handlers import LLMModelInfo


class PublicVoiceCatalog:
    def __init__(self, url: str, pattern: Pattern[str], *, ttl_seconds: float = 6 * 60 * 60) -> None:
        self._url = url
        self._pattern = pattern
        self._ttl_seconds = ttl_seconds
        self._snapshot: tuple[float, tuple[str, ...]] | None = None

    def clear(self) -> None:
        self._snapshot = None

    async def list_resources(self) -> list[LLMModelInfo]:
        now = monotonic()
        if self._snapshot is not None and now - self._snapshot[0] < self._ttl_seconds:
            voice_ids = self._snapshot[1]
        else:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(self._url, headers={"Accept": "text/html"})
                response.raise_for_status()
                voice_ids = tuple(sorted(set(self._pattern.findall(response.text))))
            self._snapshot = (now, voice_ids)
        # Build fresh descriptors so callers cannot mutate a cached provider catalogue.
        return [
            with_capability(
                LLMModelInfo(
                    id=f"voice:{voice_id}",
                    name=voice_id,
                    description=f"Catalogue public · {'-'.join(voice_id.split('-', 2)[:2])}",
                    resource_type="voice",
                    metadata_source="public-catalog",
                ),
                "speech",
                resource_type="voice",
            )
            for voice_id in voice_ids
        ]
