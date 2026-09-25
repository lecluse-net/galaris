"""Load only shipped documentation, never arbitrary repository or host files."""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

from markdown_it import MarkdownIt

from .contracts import Corpus, Page, Passage


MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_CORPUS_BYTES = 64 * 1024 * 1024
MAX_PASSAGES = 20_000
PASSAGE_CHARS = 6000
_MARKDOWN = MarkdownIt()


def source_root() -> Path:
    repository = Path(__file__).resolve().parents[3]
    if (repository / "docs").is_dir():
        return repository
    return Path("/opt/galaris-documentation")


def _files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for relative in ("docs", "project/decisions", "project/plans"):
        directory = root / relative
        if not directory.is_dir() or directory.is_symlink():
            continue
        for path in directory.rglob("*"):
            if path.suffix.lower() not in {".md", ".json", ".html"}:
                continue
            if path.is_symlink() or not path.is_file():
                continue
            if any(parent.is_symlink() for parent in path.parents if parent != root):
                continue
            if path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("A documentation source exceeds the file size limit.")
            files.append(path)
    return tuple(sorted(files))


def _sections(page: Page) -> list[Passage]:
    content = page.content
    offsets = [0]
    for line in content.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    boundaries: list[tuple[int, str]] = [(0, page.title)]
    hierarchy: list[tuple[int, str]] = []
    if page.path.endswith(".md"):
        tokens = _MARKDOWN.parse(content)
        for index, token in enumerate(tokens):
            if token.type != "heading_open" or token.map is None:
                continue
            level = int(token.tag[1:])
            title = tokens[index + 1].content
            hierarchy = [(depth, text) for depth, text in hierarchy if depth < level]
            hierarchy.append((level, title))
            position = offsets[token.map[0]]
            heading = " > ".join(text for _, text in hierarchy)
            if position == boundaries[-1][0]:
                boundaries[-1] = (position, heading)
            else:
                boundaries.append((position, heading))
    passages: list[Passage] = []
    for index, (start, heading) in enumerate(boundaries):
        stop = boundaries[index + 1][0] if index + 1 < len(boundaries) else len(content)
        while start < stop:
            end = min(stop, start + PASSAGE_CHARS)
            if end < stop:
                paragraph = content.rfind("\n\n", start + PASSAGE_CHARS // 2, end)
                if paragraph >= 0:
                    end = paragraph + 2
            text = content[start:end]
            if text.strip():
                key = f"v1\0{page.path}\0{page.status}\0{heading}\0{start}\0{text}"
                passages.append(Passage(hashlib.sha256(key.encode()).hexdigest(), page, heading, start, end))
            start = end
    return passages


@lru_cache(maxsize=2)
def _load(root: Path, signature: tuple[tuple[str, int, int], ...], version: str) -> Corpus:
    if sum(size for _, _, size in signature) > MAX_CORPUS_BYTES:
        raise ValueError("The documentation corpus exceeds the size limit.")
    contents = {path: (root / path).read_text(encoding="utf-8") for path, _, _ in signature}
    plan_index = contents.get("project/plans/README.md", "")
    statuses = dict(re.findall(r"\]\(([^)]+\.md)\)\s*\|\s*`([^`]+)`", plan_index))
    pages: list[Page] = []
    digest = hashlib.sha256(b"documentation-corpus-v1")
    digest.update(version.encode())
    for path, content in contents.items():
        parts = path.split("/")
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else Path(path).name
        kind = "plan" if path.startswith("project/plans/") else (
            "decision" if path.startswith("project/decisions/") else "documentation"
        )
        status = statuses.get(Path(path).name, "design") if kind == "plan" else (
            "recorded" if kind == "decision" else "current"
        )
        language = parts[1] if len(parts) > 1 and parts[1] in {"fr", "en"} else "und"
        domain = parts[2] if len(parts) > 3 and parts[0] == "docs" else kind
        checksum = hashlib.sha256(content.encode()).hexdigest()
        pages.append(Page(path, title, language, domain, kind, status, content, checksum))
        digest.update(f"\0{path}\0{status}\0{checksum}".encode())
    if not pages:
        raise FileNotFoundError("The shipped Galaris documentation corpus is unavailable.")
    passages = tuple(p for page in pages for p in _sections(page))
    if len(passages) > MAX_PASSAGES:
        raise ValueError("The documentation corpus exceeds the passage count limit.")
    return Corpus(digest.hexdigest(), version, tuple(pages), passages)


def load_corpus(*, root: Path | None = None) -> Corpus:
    root = root if root is not None else source_root()
    signature = tuple((str(path.relative_to(root)), path.stat().st_mtime_ns, path.stat().st_size) for path in _files(root))
    version_path = Path("/opt/galaris-version")
    version = version_path.read_text().strip() if version_path.is_file() else "development"
    return _load(root, signature, version)


def page_at(corpus: Corpus, path: str) -> Page:
    # Exact manifest lookup also rejects absolute paths, traversal and unshipped files.
    for page in corpus.pages:
        if page.path == path:
            return page
    raise FileNotFoundError("Documentation source not found in the current corpus.")
