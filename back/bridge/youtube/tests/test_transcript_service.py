from dataclasses import dataclass
from typing import Iterator

import pytest
from requests import PreparedRequest, Response, Session

from bridge.youtube import transcript_service


_VIDEO_ID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    (
        f"https://www.youtube.com/watch?v={_VIDEO_ID}",
        f"https://youtu.be/{_VIDEO_ID}?si=tracking",
        f"https://m.youtube.com/shorts/{_VIDEO_ID}",
        f"https://www.youtube.com/live/{_VIDEO_ID}?feature=share",
        f"https://www.youtube-nocookie.com/embed/{_VIDEO_ID}",
    ),
)
def test_youtube_video_id_accepts_supported_https_urls(url: str) -> None:
    assert transcript_service.youtube_video_id(url) == _VIDEO_ID


@pytest.mark.parametrize(
    "url",
    (
        _VIDEO_ID,
        f"http://www.youtube.com/watch?v={_VIDEO_ID}",
        f"https://youtube.com.evil.example/watch?v={_VIDEO_ID}",
        f"https://user@www.youtube.com/watch?v={_VIDEO_ID}",
        f"https://www.youtube.com:443/watch?v={_VIDEO_ID}",
        "https://www.youtube.com/playlist?list=PL123",
    ),
)
def test_youtube_video_id_rejects_non_video_or_unsafe_urls(url: str) -> None:
    with pytest.raises(transcript_service.InvalidYouTubeUrl):
        transcript_service.youtube_video_id(url)


@dataclass(frozen=True)
class _Snippet:
    text: str
    start: float
    duration: float


class _Fetched:
    def __init__(self, language: str, language_code: str, generated: bool) -> None:
        self.language = language
        self.language_code = language_code
        self.is_generated = generated
        self._snippets = (
            _Snippet(" First caption ", 0.4, 1.5),
            _Snippet("Second\ncaption", 601.0, 2.0),
        )

    def __iter__(self) -> Iterator[_Snippet]:
        return iter(self._snippets)


class _Track:
    def __init__(self, language: str, language_code: str, generated: bool) -> None:
        self.language = language
        self.language_code = language_code
        self.is_generated = generated

    def fetch(self) -> _Fetched:
        return _Fetched(self.language, self.language_code, self.is_generated)


@pytest.mark.asyncio
async def test_fetch_prefers_requested_language_and_normalizes_captions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    english_manual = _Track("English", "en", False)
    french_generated = _Track("French", "fr", True)

    class _Api:
        def __init__(self, *, http_client: Session) -> None:
            assert isinstance(http_client, transcript_service._TimeoutSession)

        def list(self, video_id: str) -> tuple[_Track, ...]:
            assert video_id == _VIDEO_ID
            return english_manual, french_generated

    monkeypatch.setattr(transcript_service, "YouTubeTranscriptApi", _Api)

    result = await transcript_service.fetch_youtube_transcript(
        f"https://youtu.be/{_VIDEO_ID}",
        language="fr-FR",
    )

    assert result.language_code == "fr"
    assert result.is_generated is True
    assert result.captions[0].text == "First caption"
    assert result.captions[1].text == "Second caption"
    assert result.source_url == f"https://www.youtube.com/watch?v={_VIDEO_ID}"


@pytest.mark.asyncio
async def test_fetch_matches_requested_base_language_to_regional_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    english_manual = _Track("English", "en", False)
    canadian_french_manual = _Track("Français canadien", "fr-CA", False)

    class _Api:
        def __init__(self, *, http_client: Session) -> None:
            assert isinstance(http_client, transcript_service._TimeoutSession)

        def list(self, _video_id: str) -> tuple[_Track, ...]:
            return english_manual, canadian_french_manual

    monkeypatch.setattr(transcript_service, "YouTubeTranscriptApi", _Api)

    result = await transcript_service.fetch_youtube_transcript(
        f"https://youtu.be/{_VIDEO_ID}",
        language="fr",
    )

    assert result.language_code == "fr-CA"


def test_youtube_http_session_applies_a_bounded_default_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    response = Response()

    def fake_send(
        _session: Session,
        _request: PreparedRequest,
        **kwargs: object,
    ) -> Response:
        captured.update(kwargs)
        return response

    monkeypatch.setattr(Session, "send", fake_send)

    result = transcript_service._TimeoutSession().send(  # pyright: ignore[reportPrivateUsage]
        PreparedRequest(),
        timeout=None,
    )

    assert result is response
    assert captured["timeout"] == (10.0, 30.0)


def test_segment_and_render_transcript_preserve_source_and_timestamps() -> None:
    transcript = transcript_service.YouTubeTranscript(
        video_id=_VIDEO_ID,
        source_url=f"https://www.youtube.com/watch?v={_VIDEO_ID}",
        language="Français",
        language_code="fr",
        is_generated=True,
        captions=(
            transcript_service.YouTubeCaption("Bonjour", 4.0, 2.0),
            transcript_service.YouTubeCaption("La suite", 605.0, 3.0),
        ),
    )

    segments = transcript_service.segment_youtube_transcript(transcript)
    rendered = transcript_service.render_youtube_transcript(transcript, segments)

    assert len(segments) == 2
    assert segments[1].start_seconds == 600
    assert "[00:00:04] Bonjour" in rendered
    assert "[00:10:05] La suite" in rendered
    assert transcript.source_url in rendered
    assert "automatically generated" in rendered
