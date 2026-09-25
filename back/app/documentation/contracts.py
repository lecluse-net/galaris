"""Immutable source records; authorization belongs to the exposing transport."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Page:
    path: str
    title: str
    language: str
    domain: str
    kind: str
    status: str
    content: str
    checksum: str

    @property
    def uri(self) -> str:
        from urllib.parse import quote

        return "galaris://documentation/" + quote(self.path, safe="/-._")


@dataclass(frozen=True)
class Passage:
    fingerprint: str
    page: Page
    heading: str
    start: int
    end: int

    @property
    def text(self) -> str:
        return self.page.content[self.start:self.end]


@dataclass(frozen=True)
class Corpus:
    revision: str
    build_version: str
    pages: tuple[Page, ...]
    passages: tuple[Passage, ...]
