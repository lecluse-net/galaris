"""Retrieve and segment captions from public YouTube video URLs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from requests import PreparedRequest, RequestException, Response, Session

from youtube_transcript_api import (  # pyright: ignore[reportMissingTypeStubs]
    AgeRestricted,
    FetchedTranscript,
    IpBlocked,
    NoTranscriptFound,
    PoTokenRequired,
    RequestBlocked,
    Transcript,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_DEFAULT_SEGMENT_SECONDS = 10 * 60
_REQUEST_TIMEOUT = (10.0, 30.0)
_YOUTUBE_HOSTS = frozenset({
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
})
_YOUTUBE_EMBED_HOSTS = frozenset({
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
})


class YouTubeTranscriptError(RuntimeError):
    """Base class for expected YouTube transcript retrieval failures."""


class InvalidYouTubeUrl(YouTubeTranscriptError):
    """Raised when a value is not a supported public YouTube video URL."""


class YouTubeCaptionsUnavailable(YouTubeTranscriptError):
    """Raised when the video exposes no usable caption track."""


class YouTubeVideoUnavailable(YouTubeTranscriptError):
    """Raised when the video cannot be accessed without additional authorization."""


class YouTubeAccessBlocked(YouTubeTranscriptError):
    """Raised when YouTube blocks caption access from the Galaris server."""


class YouTubeTranscriptFetchFailed(YouTubeTranscriptError):
    """Raised for other expected failures reported by the caption client."""


class _TimeoutSession(Session):
    """Bound every request made internally by youtube-transcript-api."""

    def send(
        self,
        request: PreparedRequest,
        **kwargs: Any,
    ) -> Response:
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = _REQUEST_TIMEOUT
        return super().send(request, **kwargs)


@dataclass(frozen=True)
class YouTubeCaption:
    """One timestamped YouTube caption snippet."""

    text: str
    start_seconds: float
    duration_seconds: float

    @property
    def end_seconds(self) -> float:
        return self.start_seconds + self.duration_seconds


@dataclass(frozen=True)
class YouTubeTranscript:
    """Caption metadata and normalized snippets for one public video."""

    video_id: str
    source_url: str
    language: str
    language_code: str
    is_generated: bool
    captions: tuple[YouTubeCaption, ...]

    @property
    def duration_seconds(self) -> float:
        return max((caption.end_seconds for caption in self.captions), default=0.0)


@dataclass(frozen=True)
class YouTubeTranscriptSegment:
    """One bounded chronological caption segment."""

    index: int
    start_seconds: float
    end_seconds: float
    transcript: str


def youtube_video_id(url: str) -> str:
    """Extract a video ID from an allow-listed HTTPS YouTube URL."""
    raw = url.strip()
    try:
        parsed = urlparse(raw)
        port = parsed.port
    except ValueError as exc:
        raise InvalidYouTubeUrl from exc

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
    ):
        raise InvalidYouTubeUrl

    path_parts = tuple(part for part in parsed.path.split("/") if part)
    candidate = ""
    if hostname == "youtu.be" and len(path_parts) == 1:
        candidate = path_parts[0]
    elif hostname in _YOUTUBE_HOSTS:
        if parsed.path.rstrip("/") == "/watch":
            candidate = next(iter(parse_qs(parsed.query).get("v", ())), "")
        elif len(path_parts) == 2 and path_parts[0] in {"embed", "live", "shorts"}:
            candidate = path_parts[1]
    elif hostname in _YOUTUBE_EMBED_HOSTS:
        if len(path_parts) == 2 and path_parts[0] == "embed":
            candidate = path_parts[1]

    if not _VIDEO_ID_RE.fullmatch(candidate):
        raise InvalidYouTubeUrl
    return candidate


def _language_priority(language: str) -> tuple[str, ...]:
    raw = language.strip().replace("_", "-")
    if not raw:
        return ()
    parts = raw.split("-")
    normalized = parts[0].lower()
    if len(parts) > 1:
        normalized += "-" + "-".join(part.upper() for part in parts[1:])
    candidates = (raw, normalized, raw.lower(), parts[0].lower())
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))


def _select_track(
    tracks: tuple[Transcript, ...],
    language: str,
) -> Transcript:
    if not tracks:
        raise YouTubeCaptionsUnavailable

    preferred = _language_priority(language)
    for code in preferred:
        for track in tracks:
            if track.language_code.casefold() == code.casefold():
                return track
    preferred_bases = tuple(
        dict.fromkeys(code.split("-", 1)[0].casefold() for code in preferred)
    )
    for base in preferred_bases:
        for track in tracks:
            if track.language_code.split("-", 1)[0].casefold() == base:
                return track
    return tracks[0]


def _fetch_youtube_transcript(video_id: str, language: str) -> YouTubeTranscript:
    try:
        with _TimeoutSession() as http_client:
            transcript_list = YouTubeTranscriptApi(http_client=http_client).list(video_id)
            tracks = tuple(transcript_list)
            track = _select_track(tracks, language)
            fetched: FetchedTranscript = track.fetch()
    except (IpBlocked, RequestBlocked, PoTokenRequired) as exc:
        raise YouTubeAccessBlocked from exc
    except (TranscriptsDisabled, NoTranscriptFound) as exc:
        raise YouTubeCaptionsUnavailable from exc
    except (AgeRestricted, VideoUnavailable, VideoUnplayable) as exc:
        raise YouTubeVideoUnavailable from exc
    except YouTubeTranscriptApiException as exc:
        raise YouTubeTranscriptFetchFailed from exc
    except RequestException as exc:
        raise YouTubeTranscriptFetchFailed from exc

    captions = tuple(
        YouTubeCaption(
            text=" ".join(snippet.text.split()),
            start_seconds=max(0.0, float(snippet.start)),
            duration_seconds=max(0.0, float(snippet.duration)),
        )
        for snippet in fetched
        if snippet.text.strip()
    )
    if not captions:
        raise YouTubeCaptionsUnavailable
    return YouTubeTranscript(
        video_id=video_id,
        source_url=f"https://www.youtube.com/watch?v={video_id}",
        language=" ".join(fetched.language.split()),
        language_code=fetched.language_code,
        is_generated=fetched.is_generated,
        captions=captions,
    )


async def fetch_youtube_transcript(
    url: str,
    *,
    language: str = "",
) -> YouTubeTranscript:
    """Retrieve captions off the event loop with one client instance per worker thread."""
    video_id = youtube_video_id(url)
    return await asyncio.to_thread(_fetch_youtube_transcript, video_id, language)


def _clock(seconds: float) -> str:
    total = max(0, round(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def segment_youtube_transcript(
    transcript: YouTubeTranscript,
    *,
    segment_seconds: int = _DEFAULT_SEGMENT_SECONDS,
) -> tuple[YouTubeTranscriptSegment, ...]:
    """Group snippets into chronological windows bounded to about ten minutes."""
    if segment_seconds <= 0:
        raise ValueError("segment_seconds must be positive")
    buckets: dict[int, list[YouTubeCaption]] = {}
    for caption in transcript.captions:
        bucket = int(caption.start_seconds // segment_seconds)
        buckets.setdefault(bucket, []).append(caption)

    segments: list[YouTubeTranscriptSegment] = []
    for index, (bucket, captions) in enumerate(sorted(buckets.items()), start=1):
        start_seconds = bucket * segment_seconds
        end_seconds = max(caption.end_seconds for caption in captions)
        text = "\n".join(
            f"[{_clock(caption.start_seconds)}] {caption.text}" for caption in captions
        )
        segments.append(
            YouTubeTranscriptSegment(
                index=index,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                transcript=text,
            )
        )
    return tuple(segments)


def render_youtube_transcript(
    transcript: YouTubeTranscript,
    segments: tuple[YouTubeTranscriptSegment, ...],
) -> str:
    """Render a stable Markdown transcript with source metadata and timestamps."""
    caption_type = "automatically generated" if transcript.is_generated else "manual"
    lines = [
        f"# YouTube transcript — {transcript.video_id}",
        "",
        f"- Source: {transcript.source_url}",
        f"- Caption language: {transcript.language} ({transcript.language_code})",
        f"- Caption type: {caption_type}",
        f"- Approximate duration: {_clock(transcript.duration_seconds)}",
        "",
    ]
    for segment in segments:
        lines.extend((
            f"## Segment {segment.index} — {_clock(segment.start_seconds)}–"
            f"{_clock(segment.end_seconds)}",
            "",
            segment.transcript,
            "",
        ))
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "InvalidYouTubeUrl",
    "YouTubeAccessBlocked",
    "YouTubeCaptionsUnavailable",
    "YouTubeCaption",
    "YouTubeTranscript",
    "YouTubeTranscriptError",
    "YouTubeTranscriptFetchFailed",
    "YouTubeTranscriptSegment",
    "YouTubeVideoUnavailable",
    "fetch_youtube_transcript",
    "render_youtube_transcript",
    "segment_youtube_transcript",
    "youtube_video_id",
]
