"""Safe, actionable diagnostics shared by every native MCP function."""

from __future__ import annotations

import errno
import re
import traceback
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from core.i18n import render_prompt, t


class RecoverableToolError(RuntimeError):
    """A bounded, model-safe domain error that the caller can act on.

    Native tools must only use this exception for messages deliberately written for
    model consumption. Arbitrary provider exceptions continue through the categorized,
    redacted path so credentials and transport details cannot leak.
    """


ToolFailureKind = Literal[
    "actionable",
    "invalid_arguments",
    "not_found",
    "already_exists",
    "permission_denied",
    "authentication",
    "unsupported",
    "timeout",
    "connection",
    "capacity",
    "rate_limited",
    "provider",
    "unexpected",
]


@dataclass(frozen=True)
class ToolFailure:
    kind: ToolFailureKind
    error_type: str
    detail: str = ""
    http_status: int | None = None


_INLINE_SECRET = re.compile(
    r"(?i)(bearer\s+)[a-z0-9._~+/=-]{12,}|"
    r"((?:api[_-]?key|access[_-]?token|refresh[_-]?token|authorization|cookie|"
    r"credential|password|passwd|private[_-]?key|token|secret)\s*[:=]\s*)"
    r"[^\s,;]+|"
    r"(?:sk|ghp|gho|github_pat|xox[baprs])[-_][a-z0-9_-]{12,}|"
    r"eyj[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}\.[a-z0-9_-]{10,}"
)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.IGNORECASE,
)


def _public_error_detail(value: object, *, limit: int = 2_000) -> str:
    """Return a bounded diagnostic deliberately safe for model consumption."""

    detail = " ".join(str(value or "").split())
    if not detail or _PRIVATE_KEY.search(detail):
        return ""

    def replacement(match: re.Match[str]) -> str:
        return f"{match.group(1) or match.group(2) or ''}[redacted]"

    return _INLINE_SECRET.sub(replacement, detail)[:limit]


def _exception_chain(exc: BaseException) -> tuple[BaseException, ...]:
    chain: list[BaseException] = []
    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return tuple(chain)


def _http_status(chain: Sequence[BaseException]) -> int | None:
    for item in chain:
        if type(item).__name__ == "ModelHTTPError":
            status_code = getattr(item, "status_code", None)
            if isinstance(status_code, int):
                return status_code
        response = getattr(item, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code
    return None


def _has_exception_name(chain: Sequence[BaseException], *names: str) -> bool:
    expected = set(names)
    return any(type(item).__name__ in expected for item in chain)


def _declared_boundary_detail(exc: BaseException) -> str:
    """Expose only errors deliberately raised from a native MCP boundary."""

    frames = traceback.extract_tb(exc.__traceback__)
    if not frames or not frames[-1].filename.replace("\\", "/").endswith("/mcp.py"):
        return ""
    return _public_error_detail(exc)


def _value_error_kind(detail: str) -> ToolFailureKind:
    """Recover common domain semantics from model-safe boundary validation text."""

    normalized = detail.casefold().replace("’", "'")
    if any(
        marker in normalized
        for marker in ("not found", "does not exist", "introuvable", "n'existe pas")
    ):
        return "not_found"
    if "already exists" in normalized or "existe déjà" in normalized:
        return "already_exists"
    return "invalid_arguments"


def classify_tool_failure(exc: Exception) -> ToolFailure:
    """Classify failures without exposing arbitrary provider exception messages."""

    error_type = type(exc).__name__
    if isinstance(exc, RecoverableToolError):
        return ToolFailure(
            "actionable",
            error_type,
            _public_error_detail(exc),
        )

    chain = _exception_chain(exc)
    if _has_exception_name(
        chain,
        "GoalRevisionConflict",
        "MemoryConflictError",
    ):
        return ToolFailure("actionable", error_type, _public_error_detail(exc))
    status_code = _http_status(chain)
    if _has_exception_name(chain, "ModelHTTPError") and status_code in {400, 412, 422}:
        # An internal model request is not the caller's MCP argument contract.
        return ToolFailure("provider", error_type, http_status=status_code)
    if status_code in {400, 412, 422}:
        return ToolFailure("invalid_arguments", error_type, http_status=status_code)
    if status_code == 401:
        return ToolFailure("authentication", error_type, http_status=status_code)
    if status_code == 403:
        return ToolFailure("permission_denied", error_type, http_status=status_code)
    if status_code == 404:
        return ToolFailure("not_found", error_type, http_status=status_code)
    if status_code == 409:
        return ToolFailure("already_exists", error_type, http_status=status_code)
    if status_code in {405, 501}:
        return ToolFailure("unsupported", error_type, http_status=status_code)
    if status_code in {408, 504}:
        return ToolFailure("timeout", error_type, http_status=status_code)
    if status_code in {413, 507}:
        return ToolFailure("capacity", error_type, http_status=status_code)
    if status_code == 429:
        return ToolFailure("rate_limited", error_type, http_status=status_code)
    if status_code is not None and status_code >= 500:
        return ToolFailure("provider", error_type, http_status=status_code)

    if any(isinstance(item, FileExistsError) for item in chain):
        return ToolFailure("already_exists", error_type, _declared_boundary_detail(exc))
    if any(isinstance(item, FileNotFoundError) for item in chain) or _has_exception_name(
        chain,
        "SFTPNoSuchFile",
        "SFTPNoSuchPath",
        "SFTPNoMedia",
    ):
        return ToolFailure("not_found", error_type, _declared_boundary_detail(exc))
    if _has_exception_name(chain, "SFTPFileAlreadyExists"):
        return ToolFailure("already_exists", error_type, _declared_boundary_detail(exc))
    if any(isinstance(item, PermissionError) for item in chain) or _has_exception_name(
        chain,
        "SFTPPermissionDenied",
        "SFTPWriteProtect",
        "SFTPCannotDelete",
        "SFTPOwnerInvalid",
        "SFTPGroupInvalid",
    ):
        return ToolFailure(
            "permission_denied",
            error_type,
            _declared_boundary_detail(exc),
        )
    if any(isinstance(item, NotImplementedError) for item in chain) or _has_exception_name(
        chain,
        "SFTPOpUnsupported",
    ):
        return ToolFailure("unsupported", error_type, _declared_boundary_detail(exc))
    if any(isinstance(item, TimeoutError) for item in chain) or _has_exception_name(
        chain,
        "ConnectTimeout",
        "ReadTimeout",
        "WriteTimeout",
        "PoolTimeout",
    ):
        return ToolFailure("timeout", error_type)
    if any(isinstance(item, ConnectionError) for item in chain) or _has_exception_name(
        chain,
        "ConnectError",
        "NetworkError",
        "ConnectionLost",
        "DisconnectError",
        "ChannelOpenError",
        "SFTPNoConnection",
        "SFTPConnectionLost",
    ):
        return ToolFailure("connection", error_type)
    if any(
        isinstance(item, OSError) and item.errno in {errno.ENOSPC, errno.EDQUOT}
        for item in chain
    ):
        return ToolFailure("capacity", error_type)
    if _has_exception_name(chain, "SFTPNoSpaceOnFilesystem", "SFTPQuotaExceeded"):
        return ToolFailure("capacity", error_type)
    if any(isinstance(item, (IsADirectoryError, NotADirectoryError)) for item in chain) or (
        _has_exception_name(
            chain,
            "SFTPNotADirectory",
            "SFTPFileIsADirectory",
            "SFTPInvalidFilename",
            "SFTPInvalidParameter",
            "SFTPLinkLoop",
        )
    ):
        return ToolFailure("invalid_arguments", error_type)
    if isinstance(exc, ValueError):
        # ValueError is also raised by provider libraries. Its arbitrary text remains
        # redacted unless a tool deliberately raises it at its MCP boundary.
        detail = _declared_boundary_detail(exc)
        return ToolFailure(_value_error_kind(detail), error_type, detail)
    if _has_exception_name(chain, "SFTPFailure", "SFTPError"):
        return ToolFailure("provider", error_type)
    return ToolFailure("unexpected", error_type)


def _failure_hint_key(tool_name: str, kind: ToolFailureKind) -> str:
    if kind == "not_found" and tool_name == "file_create":
        return "not_found_file_create"
    if kind == "already_exists" and tool_name.startswith("file_"):
        return "already_exists_file"
    if kind == "not_found" and tool_name.startswith("file_"):
        return "not_found_file"
    return kind


def render_tool_failure(
    *,
    tool_name: str,
    failure: ToolFailure,
    language: str,
    reference: str,
) -> str:
    """Render a localized failure which tells the model what to do next."""

    # Keep the permission/effect category stable while distinguishing an HTTP
    # refusal from a local ACL failure. Never expose the provider URL or body.
    diagnostic_key = (
        "permission_denied_http"
        if failure.kind == "permission_denied" and failure.http_status == 403
        else failure.kind
    )
    hint_key = (
        diagnostic_key
        if diagnostic_key != failure.kind or failure.http_status is not None
        else _failure_hint_key(tool_name, failure.kind)
    )
    reason = failure.detail or t(
        f"tools.call_failure_reasons.{diagnostic_key}",
        language,
    )
    if failure.http_status is not None and failure.http_status != 403:
        reason = render_prompt(
            t("tools.call_failure_http", language),
            status=failure.http_status,
            reason=reason,
        )
    hint = t(
        f"tools.call_failure_hints.{hint_key}",
        language,
    )
    return render_prompt(
        t("tools.call_failure", language),
        name=tool_name,
        reason=reason,
        error_type=failure.error_type,
        hint=hint,
        reference=reference,
    )


def safe_trace(exc: BaseException) -> str:
    """Return code locations only, excluding exception values and tool arguments."""

    frames = traceback.extract_tb(exc.__traceback__)[-12:]
    return " <- ".join(
        f"{frame.filename.rsplit('/back/', 1)[-1]}:{frame.lineno}:{frame.name}"
        for frame in frames
    ) or "unavailable"


__all__ = [
    "RecoverableToolError",
    "ToolFailure",
    "classify_tool_failure",
    "render_tool_failure",
    "safe_trace",
]
