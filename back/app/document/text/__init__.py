"""Editorial HTML behavior for Text documents."""

from core.util import ContentProfile, convert_to_html, visible_text


def normalize(content: str, media_type: str = "text/html", *, profile: ContentProfile = "document") -> str:
    return convert_to_html(content, media_type, profile=profile)


def validate(content: str) -> None:
    content.encode("utf-8")


def extract(content: str) -> str:
    return visible_text(content)
