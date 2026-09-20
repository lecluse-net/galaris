"""Canonical resource URI parsing and Tool-code namespace rules."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from uuid import UUID


RESOURCE_SCHEME_PATTERN = re.compile(r"^[a-z][a-z0-9+.-]*$")
_RESOURCE_URI_PATTERN = re.compile(
    r"^(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*)://(?P<locator>.*)$",
    flags=re.DOTALL,
)
_CONTROL_PATTERN = re.compile(r"[\x00-\x1f\x7f]")

PROTOCOL_SCHEMES = frozenset(
    {
        "about",
        "blob",
        "cid",
        "coap",
        "coaps",
        "data",
        "dav",
        "dns",
        "file",
        "ftp",
        "ftps",
        "git",
        "http",
        "https",
        "imap",
        "ipfs",
        "ipns",
        "javascript",
        "ldap",
        "ldaps",
        "magnet",
        "mailto",
        "nfs",
        "nntp",
        "pop",
        "rtmp",
        "rtsp",
        "sftp",
        "smb",
        "smtp",
        "ssh",
        "svn",
        "tel",
        "telnet",
        "urn",
        "ws",
        "wss",
    }
)
NATIVE_RESOURCE_SCHEMES = frozenset(
    {
        "console",
        "document",
        "galaris",
        "memory",
        "resource",
    }
)
RETIRED_RESOURCE_SCHEMES = frozenset({"workspace"})
SYSTEM_TOOL_CODES = frozenset(
    {
        "audio",
        "browser",
        "calendar",
        "file_sharing",
        "galaris_admin",
        "goal_management",
        "image",
        "mail",
        "messenger",
        "n8n",
        "process_admin",
        "search",
        "skill_management",
        "voice",
    }
)
FUTURE_RESOURCE_SCHEMES = frozenset(
    {"agent", "connection", "conversation", "goal", "process", "round", "task", "tool"}
)
RESERVED_TOOL_CODES = (
    PROTOCOL_SCHEMES
    | NATIVE_RESOURCE_SCHEMES
    | RETIRED_RESOURCE_SCHEMES
    | SYSTEM_TOOL_CODES
    | FUTURE_RESOURCE_SCHEMES
)


class ResourceUriError(ValueError):
    """A resource URI cannot be represented safely or canonically."""


@dataclass(frozen=True, slots=True)
class ResourceUri:
    """One normalized URI split into a scheme and an opaque provider locator."""

    scheme: str
    locator: str

    @property
    def uri(self) -> str:
        return f"{self.scheme}://{self.locator}"

    @property
    def is_collection(self) -> bool:
        return not self.locator or self.locator.endswith("/")

    @property
    def decoded_locator(self) -> str:
        """Return the provider-facing locator represented by the canonical URI."""

        return unquote(self.locator)

    @property
    def segments(self) -> tuple[str, ...]:
        return tuple(
            part for part in self.decoded_locator.strip("/").split("/") if part
        )

    def __str__(self) -> str:
        return self.uri


def _normalize_web_uri(value: str) -> ResourceUri:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ResourceUriError("Invalid Web resource URI.") from exc
    scheme = parsed.scheme.lower()
    if (
        scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65_535)
    ):
        raise ResourceUriError(
            "Web resource URIs require HTTP(S), a host, no credentials, and no fragment."
        )
    hostname = parsed.hostname.lower()
    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ResourceUriError("Invalid Web resource hostname.") from exc
    host = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None:
        host = f"{host}:{port}"
    decoded_path = unicodedata.normalize("NFC", unquote(parsed.path or "/"))
    normalized_query = unicodedata.normalize("NFC", parsed.query)
    decoded_query = unquote(normalized_query)
    if _CONTROL_PATTERN.search(decoded_path) or _CONTROL_PATTERN.search(decoded_query):
        raise ResourceUriError("A Web resource URI cannot contain control characters.")
    path = quote(decoded_path, safe="/!$&'()*+,-.;=@_~:")
    query = quote(normalized_query, safe="!$&'()*+,-./:;=?@_~%")
    canonical = urlunsplit((scheme, host, path, query, ""))
    return ResourceUri(scheme, canonical.removeprefix(f"{scheme}://"))


def _normalize_locator(locator: str, *, allow_empty: bool) -> str:
    raw = unicodedata.normalize("NFC", locator.strip().replace("\\", "/"))
    if _CONTROL_PATTERN.search(raw):
        raise ResourceUriError("A resource URI cannot contain control characters.")
    if "?" in raw or "#" in raw:
        raise ResourceUriError(
            "Provider resource locators cannot contain a query or fragment."
        )
    trailing = raw.endswith("/")
    decoded = unquote(raw)
    if _CONTROL_PATTERN.search(decoded):
        raise ResourceUriError("A resource URI cannot contain encoded control characters.")
    normalized_parts: list[str] = []
    for part in decoded.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise ResourceUriError("A resource URI cannot traverse to a parent path.")
        normalized_parts.append(quote(part, safe="!$&'()*+,-.;=@_~:"))
    result = "/".join(normalized_parts)
    if trailing and result:
        result += "/"
    if not result and not allow_empty:
        raise ResourceUriError("A resource URI requires a locator.")
    return result


def parse_resource_uri(
    value: object,
    *,
    allow_empty: bool = False,
) -> ResourceUri:
    """Parse an explicit canonical resource URI."""

    raw = "" if value is None else str(value).strip()
    if not raw:
        raise ResourceUriError("A resource URI is required.")
    match = _RESOURCE_URI_PATTERN.match(raw)
    if match is None:
        raise ResourceUriError("A canonical resource URI with an explicit scheme is required.")
    scheme = match.group("scheme").lower()
    locator = match.group("locator")
    if not RESOURCE_SCHEME_PATTERN.fullmatch(scheme):
        raise ResourceUriError(f"Invalid resource scheme: {scheme!r}.")
    if scheme in RETIRED_RESOURCE_SCHEMES:
        raise ResourceUriError(
            "workspace:// has been removed; use console:// or an exact provider URI."
        )
    if scheme in {"http", "https"}:
        return _normalize_web_uri(f"{scheme}://{locator}")
    normalized = _normalize_locator(locator, allow_empty=allow_empty)
    if scheme == "memory" and normalized:
        parts = [part for part in normalized.strip("/").split("/") if part]
        if len(parts) != 1:
            raise ResourceUriError("memory:// requires exactly one UUID.")
        try:
            normalized = str(UUID(unquote(parts[0])))
        except ValueError as exc:
            raise ResourceUriError("memory:// requires a valid UUID.") from exc
    if scheme == "document" and normalized:
        parts = [part for part in normalized.strip("/").split("/") if part]
        try:
            document_id = str(UUID(unquote(parts[0])))
        except (IndexError, ValueError) as exc:
            raise ResourceUriError("document:// requires a valid document UUID.") from exc
        if len(parts) == 1:
            normalized = document_id
        elif len(parts) == 2 and unquote(parts[1]) == "attachments":
            normalized = f"{document_id}/attachments/"
        elif len(parts) == 3 and unquote(parts[1]) == "attachments":
            try:
                attachment_id = str(UUID(unquote(parts[2])))
            except ValueError as exc:
                raise ResourceUriError(
                    "A document attachment URI requires a valid attachment UUID."
                ) from exc
            normalized = f"{document_id}/attachments/{attachment_id}"
        else:
            raise ResourceUriError(
                "document:// accepts a document UUID or its attachments collection."
            )
    return ResourceUri(scheme, normalized)


def validate_external_tool_code(
    code: str,
    *,
    file_share: bool,
    messenger: bool = False,
) -> str:
    """Validate a user-managed Tool code against the resource namespace."""

    normalized = code.strip()
    if not normalized:
        raise ValueError("A Tool code is required.")
    if normalized.lower() in RESERVED_TOOL_CODES:
        raise ValueError(f"Tool code {normalized!r} is reserved by Galaris.")
    if (file_share or messenger) and (
        normalized != normalized.lower()
        or RESOURCE_SCHEME_PATTERN.fullmatch(normalized) is None
    ):
        raise ValueError(
            "A resource-capable Tool code must be a lowercase URI scheme matching "
            "[a-z][a-z0-9+.-]*."
        )
    return normalized


__all__ = [
    "NATIVE_RESOURCE_SCHEMES",
    "PROTOCOL_SCHEMES",
    "SYSTEM_TOOL_CODES",
    "FUTURE_RESOURCE_SCHEMES",
    "RESERVED_TOOL_CODES",
    "RESOURCE_SCHEME_PATTERN",
    "ResourceUri",
    "ResourceUriError",
    "parse_resource_uri",
    "validate_external_tool_code",
]
