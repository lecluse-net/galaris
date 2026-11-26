"""Bound the SDK transcript restored into a fresh, isolated workspace."""

import json
import re
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import cast
from uuid import UUID

from .claude_skills import SKILL_TOOLS
from .claude_media import TRANSIENT_MEDIA_PREFIX, TRANSIENT_MEDIA_TYPES
from .claude_tool_discovery import SEARCH_TOOLS


_MAX_TRANSCRIPT = 4 * 1024 * 1024
_LIVE_CATALOG_RESULTS = SKILL_TOOLS | {SEARCH_TOOLS}


@dataclass(frozen=True)
class ClaudeSession:
    id: UUID
    transcript: str

    def deep_history(self, session_id: UUID) -> str:
        return json.dumps({
            "format": "galaris.claude-deep-history/v1",
            "deep_session": str(session_id), "sdk_session": str(self.id), "transcript": self.transcript,
        }, ensure_ascii=False)

    @classmethod
    def from_deep_history(cls, history: str, session_id: UUID) -> "ClaudeSession":
        raw: object = json.loads(history)
        if not isinstance(raw, dict):
            raise ValueError("Invalid saved Claude Deep history.")
        data = cast(dict[str, object], raw)
        transcript, identifier = data.get("transcript"), data.get("sdk_session")
        if (not isinstance(identifier, str) or not isinstance(transcript, str)
                or not transcript or len(transcript.encode()) > _MAX_TRANSCRIPT
                or data.get("format") != "galaris.claude-deep-history/v1"
                or data.get("deep_session") != str(session_id)):
            raise ValueError("The saved Claude history does not belong to this Deep session.")
        return cls(UUID(identifier), transcript)

    @classmethod
    def capture(cls, workspace: Path, session_id: str, *, transient_input_bytes: int = 0) -> "ClaudeSession | None":
        identifier = UUID(session_id)
        path = _transcript_path(workspace, identifier)
        if not path.is_file() or path.is_symlink():
            return None
        # The raw tape includes the current input. Apply the history limit after removing it.
        read_limit = _MAX_TRANSCRIPT + transient_input_bytes * 2
        with path.open("rb") as reader:
            raw = reader.read(read_limit + 1)
        if not raw or len(raw) > read_limit:
            return None
        transcript = _project_transcript(raw.decode("utf-8"), expire_catalog=False)
        return cls(identifier, transcript) if len(transcript.encode()) <= _MAX_TRANSCRIPT else None

    def restore(self, workspace: Path) -> None:
        path = _transcript_path(workspace, self.id)
        path.parent.mkdir(parents=True, mode=0o700)
        path.write_text(_project_transcript(self.transcript), encoding="utf-8")
        path.chmod(0o600)


def _transcript_path(workspace: Path, identifier: UUID) -> Path:
    # The bundled CLI files each session under its sanitized absolute working directory.
    project = re.sub(r"[^a-zA-Z0-9-]", "-", str(workspace))
    return workspace / "projects" / project / f"{identifier}.jsonl"


def _project_transcript(transcript: str, *, expire_catalog: bool = True) -> str:
    """Preserve history and tool pairing without persisting transient user media."""
    catalog_calls: set[str] = set()
    lines: list[str] = []
    for line in StringIO(transcript):
        try:
            record: object = json.loads(line)
        except ValueError:
            lines.append(line)
            continue
        if not isinstance(record, dict):
            lines.append(line)
            continue
        message = cast(dict[str, object], record).get("message")
        if not isinstance(message, dict):
            lines.append(line)
            continue
        data = cast(dict[str, object], message)
        raw_blocks = data.get("content")
        blocks = cast(list[object], raw_blocks) if isinstance(raw_blocks, list) else []
        retained = [block for block in blocks if not _is_attempt_media(block)] if data.get("role") == "user" else blocks
        pruned_media = len(retained) != len(blocks)
        if pruned_media:
            data["content"] = retained
        changed = False
        for block in retained if expire_catalog else ():
            if not isinstance(block, dict):
                continue
            content = cast(dict[str, object], block)
            if (content.get("type") == "tool_use" and isinstance(name := content.get("name"), str)
                    and name.startswith("mcp__galaris__")
                    and name.removeprefix("mcp__galaris__") in _LIVE_CATALOG_RESULTS
                    and isinstance(call_id := content.get("id"), str)):
                catalog_calls.add(call_id)
            elif (content.get("type") == "tool_result" and isinstance(call_id := content.get("tool_use_id"), str)
                  and call_id in catalog_calls):
                content["content"] = "Galaris catalog results expire at the end of an attempt. Check the current catalog."
                changed = True
        if changed:
            cast(dict[str, object], record).pop("toolUseResult", None)
        lines.append(json.dumps(record, ensure_ascii=False) + "\n" if changed or pruned_media else line)
    return "".join(lines)


def _is_attempt_media(block: object) -> bool:
    if not isinstance(block, dict):
        return False
    data = cast(dict[str, object], block)
    kind = data.get("type")
    return isinstance(kind, str) and (kind in TRANSIENT_MEDIA_TYPES or (
        kind == "text" and isinstance(text := data.get("text"), str) and text.startswith(TRANSIENT_MEDIA_PREFIX)
    ))
