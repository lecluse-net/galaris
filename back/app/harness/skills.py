"""Expose centrally assigned skills as deferred Pydantic AI capabilities."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from loguru import logger
from pydantic_ai import ModelRetry, RunContext
from pydantic_ai.capabilities import Capability
from pydantic_ai.tools import ToolDefinition

from app.skill import learning_service, skill_service, storage


_MAX_INLINE_SKILL_INSTRUCTIONS_CHARS = 12_000
_MAX_RESOURCE_PATH_HINT_CHARS = 1_200
_MAX_SECTION_SCHEMA_VALUES = 200
_RESOURCE_ERROR_PREFIXES = (
    "A path is required",
    "The section parameter",
    "Section ",
    "Unable to read resource",
)


def _resource_tool_name(code: str) -> str:
    return f"skill_{code.replace('-', '_')}_read_file"


def _markdown_headings(content: str) -> list[tuple[int, str]]:
    """Return Markdown ATX headings without pulling their bodies into a prompt."""
    headings: list[tuple[int, str]] = []
    for line in content.splitlines():
        stripped = line.lstrip()
        marker = len(stripped) - len(stripped.lstrip("#"))
        if 1 <= marker <= 6 and len(stripped) > marker and stripped[marker] == " ":
            headings.append((marker, stripped[marker + 1 :].rstrip(" #").strip()))
    return headings


def _read_markdown_section(content: str, section: str) -> str:
    """Read one named Markdown section, including nested subsections."""
    requested = section.strip()
    marker = len(requested) - len(requested.lstrip("#"))
    if 1 <= marker <= 6 and len(requested) > marker and requested[marker] == " ":
        requested = requested[marker + 1 :].rstrip(" #").strip()
    wanted = requested.casefold()
    lines = content.splitlines()
    start: int | None = None
    level = 0
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        marker = len(stripped) - len(stripped.lstrip("#"))
        if not (1 <= marker <= 6 and len(stripped) > marker and stripped[marker] == " "):
            continue
        heading = stripped[marker + 1 :].rstrip(" #").strip()
        if start is None:
            if heading.casefold() == wanted:
                start = index
                level = marker
        elif marker <= level:
            return "\n".join(lines[start:index]).rstrip() + "\n"
    if start is not None:
        return "\n".join(lines[start:]).rstrip() + "\n"
    available = ", ".join(title for _, title in _markdown_headings(content))
    return (
        f"Section {section!r} not found. Copy one available heading exactly without "
        "translating or paraphrasing it; optional leading Markdown # markers are accepted. "
        f"Available headings: {available}"
    )


def _resource_path_hint(code: str) -> str:
    """Expose a bounded exact path catalogue directly in the tool definition."""
    paths = [str(item["path"]) for item in storage.list_files(code)]
    if not paths:
        return "This skill currently has no resource files."
    catalogue = ", ".join(paths)
    if len(catalogue) <= _MAX_RESOURCE_PATH_HINT_CHARS:
        return f"Exact available resource paths: {catalogue}."
    return (
        "The resource catalogue is too large to embed here; call this tool with an empty "
        "path to list the exact paths before reading one."
    )


def _section_schema_values(code: str) -> tuple[str, ...]:
    """Return bounded exact headings accepted by the skill reader schema."""

    values: list[str] = []
    seen: set[str] = set()
    for item in storage.list_files(code):
        path = str(item["path"])
        if not bool(item["text"]) or not path.lower().endswith((".md", ".markdown")):
            continue
        try:
            content = storage.read_text(code, path)
        except (FileNotFoundError, OSError, ValueError):
            continue
        for _level, heading in _markdown_headings(content):
            if heading in seen:
                continue
            seen.add(heading)
            values.append(heading)
            if len(values) >= _MAX_SECTION_SCHEMA_VALUES:
                return tuple(values)
    return tuple(values)


def _read_skill_resource(code: str, path: str = "", section: str = "") -> str:
    """List a skill package or read one of its text resources."""
    if not path.strip():
        if section.strip():
            return "A path is required when reading a section."
        files = storage.list_files(code)
        if not files:
            return f"Skill {code!r} has no files."
        return "\n".join(
            f"- {item['path']} ({item['size']} bytes, "
            f"{'text' if item['text'] else 'binary'})"
            for item in files
        )
    try:
        content = storage.read_text(code, path.strip())
        if section.strip():
            if not path.strip().lower().endswith((".md", ".markdown")):
                return "The section parameter is supported only for Markdown resources."
            return _read_markdown_section(content, section)
        return content
    except (FileNotFoundError, OSError, ValueError) as exc:
        files = storage.list_files(code)
        available = ", ".join(str(item["path"]) for item in files) or "none"
        return (
            f"Unable to read resource {path!r} from skill {code!r}: {exc}. "
            f"Available files: {available}. Do not retry the same missing path; use an "
            "available path, or omit path to list files."
        )


def _capability_instructions(code: str, instructions: str, tool_name: str) -> str:
    """Keep large skills progressive instead of billing their full guide every turn."""
    resource_guide = (
        "## Internal harness resources\n\n"
        f"The primary guide is `SKILL.md`. Use `{tool_name}` with `path=\"SKILL.md\"` "
        "and an exact `section` when the guide section is known. Omit `path` only to list "
        "the package's actual files; never guess or synthesize a resource filename. "
        "Copy path and section values verbatim from the values shown here; never translate "
        "or paraphrase a heading. For Markdown, pass `section` to read only one named "
        "heading and its subsections; leading `#` markers are optional. "
        "Binary resources can be listed but are not inserted into the model context."
    )
    if len(instructions) <= _MAX_INLINE_SKILL_INSTRUCTIONS_CHARS:
        return f"{instructions.rstrip()}\n\n{resource_guide}"

    headings = [
        f"- {title}"
        for level, title in _markdown_headings(instructions)
        if level <= 2
    ]
    heading_index = "\n".join(headings) or "- SKILL.md (no headings detected)"
    return (
        f"# {code} capability\n\n"
        "The complete guide is intentionally kept out of the recurring model context because "
        f"it is large ({len(instructions)} characters). Read only the section needed for the "
        "current task; do not request the complete SKILL.md unless no targeted section can "
        "answer the question. The capability's tools remain available after loading.\n\n"
        "## Guide sections\n\n"
        f"{heading_index}\n\n"
        f"{resource_guide}"
    )


def _build_capability(code: str) -> Capability[None] | None:
    inspection = storage.inspect(code)
    if not inspection.valid or not inspection.description:
        logger.warning(
            "Harness skill capability skipped invalid skill: code={} error={}",
            code,
            inspection.validation_error,
        )
        return None

    try:
        instructions = storage.read_text(code, "SKILL.md")
    except (FileNotFoundError, OSError, ValueError) as exc:
        logger.warning(
            "Harness skill capability skipped unreadable SKILL.md: code={} error={}",
            code,
            exc,
        )
        return None

    tool_name = _resource_tool_name(code)
    resource_path_hint = _resource_path_hint(code)
    section_values = _section_schema_values(code)
    capability: Capability[None] = Capability(
        id=code,
        description=inspection.description,
        instructions=_capability_instructions(code, instructions, tool_name),
        defer_loading=True,
    )

    def read_file(path: str = "", section: str = "") -> str:
        result = _read_skill_resource(code, path, section)
        if result.startswith(_RESOURCE_ERROR_PREFIXES):
            raise ModelRetry(result)
        return result

    def prepare_read_file(
        _ctx: RunContext[None],
        definition: ToolDefinition,
    ) -> ToolDefinition:
        if not section_values:
            return definition
        parameters = dict(definition.parameters_json_schema)
        properties = dict(parameters.get("properties", {}))
        section_schema = dict(properties.get("section", {}))
        section_schema["enum"] = ["", *section_values]
        section_schema["description"] = (
            "Empty, or one exact Markdown heading from the loaded skill package. "
            "Never translate or paraphrase it."
        )
        properties["section"] = section_schema
        parameters["properties"] = properties
        return replace(definition, parameters_json_schema=parameters)

    capability.tool_plain(
        name=tool_name,
        description=(
            f"List files from the loaded {code!r} skill when path is empty, or read one "
            "text resource by its relative path. For Markdown, set section to an exact "
            "heading to return only that section and its subsections. Copy exact path and "
            "heading values without translating or paraphrasing them. "
            f"{resource_path_hint}"
        ),
        # A failed resource guess and a failed heading guess still leave the model
        # one turn to use the exact path and heading returned by the tool.  Keep
        # this aligned with the internal harness tool retry budget.
        retries=3,
        prepare=prepare_read_file,
    )(read_file)
    return capability


def _build_learned_capability(
    code: str,
    description: str,
    instructions: str,
) -> Capability[None]:
    """Build one DB-owned, single-file capability without filesystem tools."""

    return Capability(
        id=code,
        description=description,
        instructions=instructions.rstrip(),
        defer_loading=True,
    )


async def build_internal_skill_capabilities(agent_id: int) -> list[Any]:
    """Build deferred capabilities for skills assigned to an agent using this harness."""
    capabilities: list[Any] = []
    for code in await skill_service.get_assigned_codes(agent_id):
        capability = _build_capability(code)
        if capability is not None:
            capabilities.append(capability)
    assigned_ids = {str(capability.id) for capability in capabilities}
    for learned in await learning_service.list_injectable(agent_id):
        if learned.code in assigned_ids:
            continue
        capabilities.append(
            _build_learned_capability(
                learned.code,
                learned.description,
                learned.markdown,
            )
        )
    return capabilities


__all__ = ["build_internal_skill_capabilities"]
