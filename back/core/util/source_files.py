"""Recognize source attachments and serve their bytes as inert text."""

import mimetypes
from pathlib import PurePosixPath
from urllib.parse import quote


_SOURCE_EXTENSIONS = frozenset({
    ".js", ".mjs", ".cjs", ".jsx", ".ts", ".mts", ".cts", ".tsx",
    ".py", ".pyi", ".pyw", ".sh", ".bash", ".zsh", ".fish", ".csh",
    ".ps1", ".psm1", ".bat", ".cmd", ".rb", ".php", ".pl", ".pm",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".cs", ".java",
    ".kt", ".kts", ".go", ".rs", ".swift", ".lua", ".r", ".dart",
    ".vue", ".svelte", ".css", ".scss", ".less", ".sql",
    ".json", ".jsonl", ".ipynb", ".yaml", ".yml", ".xml", ".xsd", ".xsl",
    ".ini", ".toml", ".conf", ".diff", ".patch", ".env",
})
_SOURCE_MEDIA_TYPES = frozenset({
    "application/javascript", "text/javascript", "application/ecmascript", "text/ecmascript",
    "application/x-javascript", "application/typescript", "text/typescript",
    "application/x-sh", "application/x-shellscript", "text/x-shellscript", "application/x-csh",
    "text/x-python", "application/x-python", "application/x-httpd-php", "text/x-php",
    "text/css", "text/x-c", "text/x-c++", "text/x-java-source",
})


def source_code_media_type(name: str, media_type: str) -> str | None:
    """A source filename takes precedence over a misleading active MIME type."""
    filename = PurePosixPath(name.replace("\\", "/")).name.lower()
    normalized = media_type.split(";", 1)[0].strip().lower()
    if (PurePosixPath(filename).suffix in _SOURCE_EXTENSIONS
        or filename in {"dockerfile", "makefile", "gnumakefile", ".env"}
        or filename.startswith(("dockerfile.", ".env."))):
        guessed = mimetypes.guess_type(filename)[0] or ""
        return guessed if guessed and not guessed.startswith(("image/", "audio/", "video/")) else "text/plain"
    return normalized if normalized in _SOURCE_MEDIA_TYPES else None


def source_code_response_headers(name: str, media_type: str) -> dict[str, str]:
    if source_code_media_type(name, media_type) is None:
        return {}
    return {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Disposition": "attachment; filename*=utf-8''" + quote(name, safe=""),
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }
