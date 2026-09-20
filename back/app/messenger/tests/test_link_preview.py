from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.messenger import link_preview
from app.file_share import (
    MaterializedResource,
    PublicHttpsContent,
    ResourceDescriptor,
    ResourceRead,
)


def test_extract_preview_references_normalizes_deduplicates_and_trims_markdown() -> None:
    document_id = uuid4()
    text = (
        f"[document](document://{document_id}) puis document://{document_id}. "
        "Une page https://example.test/guide?q=chat#section), et "
        f"un objet `galaris://task/{uuid4()}`."
    )

    references = link_preview.extract_preview_references(text)

    assert references[0] == f"document://{document_id}"
    assert references[1] == "https://example.test/guide?q=chat"
    assert references[2].startswith("galaris://task/")
    assert len(references) == 3


def test_extract_preview_references_includes_private_file_schemes_only_when_allowed() -> None:
    text = (
        "[page](console://reports/demo.html), "
        "nextcloud://Shared/report.pdf and ftp://example.test/private.txt"
    )

    assert link_preview.extract_preview_references(text) == ()
    assert link_preview.extract_preview_references(
        text,
        include_file_resources=True,
    ) == (
        "console://reports/demo.html",
        "nextcloud://Shared/report.pdf",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type,content_format", [("text/markdown", "markdown"), ("text/html", "html")])
async def test_resource_preview_preserves_document_format_and_revision(
    monkeypatch: pytest.MonkeyPatch, media_type: str, content_format: str,
) -> None:
    document_id = uuid4()
    uri = f"document://{document_id}"
    revision = 3
    updated_at = "2026-09-16T19:00:00+00:00"

    async def info(*_args: object, **_kwargs: object) -> ResourceDescriptor:
        return ResourceDescriptor(
            uri=uri,
            name="Compte rendu",
            media_type=media_type,
            revision=revision,
            modified_at=updated_at,
            capabilities=["info", "read"],
            metadata={"folder": "Réunions", "node_kind": "document", "content_profile_version": 1},
        )

    async def read(*_args: object, **_kwargs: object) -> ResourceRead:
        return ResourceRead(
            uri=uri,
            content="<h1>Décisions</h1><p>Le projet continue.</p>" if media_type == "text/html" else "# Décisions\n\nLe projet continue.",
            media_type=media_type,
            start=0,
            end=33,
            total=60,
            next_offset=33,
            revision=revision,
        )

    monkeypatch.setattr(link_preview, "resource_info", info)
    monkeypatch.setattr(link_preview, "resource_read", read)

    preview = await link_preview.preview_reference(uri, agent_id=7)

    assert preview is not None
    assert preview.kind == "document"
    assert preview.title == "Compte rendu"
    assert preview.content_format == content_format
    assert preview.truncated is True
    assert preview.download_available is False
    assert preview.metadata["revision"] == 3
    assert preview.metadata["updated_at"] == updated_at
    assert preview.metadata["folder"] == "Réunions"
    revision = 4
    updated_at = "2026-09-16T20:00:00+00:00"
    refreshed = await link_preview.preview_reference(uri, agent_id=7)
    assert refreshed is not None
    assert refreshed.metadata["revision"] == 4
    assert refreshed.metadata["updated_at"] == updated_at


@pytest.mark.asyncio
async def test_resource_preview_exposes_html_file_for_bounded_browser_loading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uri = "console://reports/demo.html"

    async def info(*_args: object, **_kwargs: object) -> ResourceDescriptor:
        return ResourceDescriptor(
            uri=uri,
            name="demo.html",
            media_type="text/html",
            size=1234,
            capabilities=["info", "read"],
        )

    read = AsyncMock()
    monkeypatch.setattr(link_preview, "resource_info", info)
    monkeypatch.setattr(link_preview, "resource_read", read)

    preview = await link_preview.preview_reference(uri, agent_id=7)

    assert preview is not None
    assert preview.kind == "file"
    assert preview.title == "demo.html"
    assert preview.media_type == "text/html"
    assert preview.content_format == "none"
    assert preview.image_available is True
    assert preview.download_available is True
    read.assert_not_awaited()


@pytest.mark.asyncio
async def test_materialize_preview_resource_keeps_bounded_copy_until_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def materialize(
        _context: object,
        uri: object,
        destination: object,
        *,
        max_bytes: int,
    ) -> MaterializedResource:
        assert max_bytes == 64 * 1_048_576
        assert isinstance(destination, Path)
        path = destination
        path.write_text("<h1>Preview</h1>", encoding="utf-8")
        return MaterializedResource(
            uri=str(uri),
            name="demo.html",
            media_type="text/html",
            size=16,
        )

    monkeypatch.setattr(link_preview, "materialize_resource", materialize)

    resource = await link_preview.materialize_preview_resource(
        "console://demo.html",
        agent_id=7,
    )

    assert resource is not None
    assert resource.path.read_text(encoding="utf-8") == "<h1>Preview</h1>"
    parent = resource.path.parent
    resource.cleanup()
    assert not parent.exists()


@pytest.mark.asyncio
async def test_web_html_preview_schedules_a_cached_screenshot_and_opens_externally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = PublicHttpsContent(
        url="https://example.test/article",
        media_type="text/html",
        content=(
            b'<html><head><meta property="og:title" content="Article test">'
            b'<meta property="og:description" content="Description propre">'
            b'<meta property="og:image" content="/cover.jpg"></head></html>'
        ),
    )
    async def fetch(
        remote: str,
        *,
        max_bytes: int,
        truncate: bool = False,
    ) -> PublicHttpsContent:
        del max_bytes, truncate
        return page

    from app.file_share import web_preview
    monkeypatch.setattr(web_preview, "read_public_https_bytes", fetch)
    monkeypatch.setattr(link_preview, "read_public_https_bytes", fetch)
    preview = await link_preview.preview_reference(page.url, agent_id=7)

    assert preview is not None
    assert preview.kind == "web"
    assert preview.title == "Article test"
    assert preview.description == "Description propre"
    assert preview.image_available is True
    assert preview.open_mode == "external"


@pytest.mark.asyncio
async def test_youtube_preview_uses_nocookie_embed_and_thumbnail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video_id = "dQw4w9WgXcQ"
    oembed = PublicHttpsContent(
        url="https://www.youtube.com/oembed",
        media_type="application/json",
        content=(
            b'{"title":"Demo video","author_name":"Demo channel",'
            b'"thumbnail_url":"https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"}'
        ),
    )

    async def fetch(
        remote: str,
        *,
        max_bytes: int,
        truncate: bool = False,
    ) -> PublicHttpsContent:
        del remote, max_bytes, truncate
        return oembed

    from app.file_share import web_preview
    monkeypatch.setattr(web_preview, "read_public_https_bytes", fetch)
    monkeypatch.setattr(link_preview, "read_public_https_bytes", fetch)

    preview = await link_preview.preview_reference(
        f"https://youtu.be/{video_id}",
        agent_id=7,
    )

    assert preview is not None
    assert preview.kind == "youtube"
    assert preview.title == "Demo video"
    assert preview.subtitle == "Demo channel"
    assert preview.embed_url == f"https://www.youtube-nocookie.com/embed/{video_id}"
