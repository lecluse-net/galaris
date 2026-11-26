"""Project Galaris skills into the embedded Claude runtime."""

from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.skill import storage
from core.database import get_db_session

from .skills import (
    RuntimeSkill, SKILL_RESOURCE_ERROR_PREFIXES, list_runtime_skills, read_skill_resource,
    require_skill_access, skill_guide_instructions,
)


LOAD_SKILL = "load_capability"
READ_SKILL = "read_skill_file"
SKILL_TOOLS = frozenset({LOAD_SKILL, READ_SKILL})


class _LoadInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(description="Exact skill ID from the current Galaris catalog.")


class _ReadInput(_LoadInput):
    path: str = Field(default="", description="Exact relative text file path. Omit both fields to list package files.")
    section: str = Field(default="", description="Exact Markdown heading. Without a path, reads a section of SKILL.md.")


class ClaudeSkills:
    def __init__(self, agent_id: int) -> None:
        self._agent_id = agent_id
        self._skills: dict[str, RuntimeSkill] = {}
        self._loaded: set[str] = set()
        self.definitions: dict[str, Tool] = {}
        self.instructions = ""

    @classmethod
    async def build(cls, agent_id: int) -> "ClaudeSkills":
        runtime = cls(agent_id)
        async with get_db_session():
            skills = await list_runtime_skills(agent_id)
        eager: list[str] = []
        deferred: list[str] = []
        for skill in skills:
            try:
                inspection = storage.inspect(skill.code, owner_agent_id=skill.owner_agent_id)
                if not inspection.valid or not inspection.description:
                    continue
                guide = _guide(skill) if skill.eager else None
            except (OSError, ValueError):
                continue
            if guide is not None:
                eager.append(f"### {skill.id}\n\n{guide}")
                runtime._loaded.add(skill.id)
            else:
                deferred.append(f"- {skill.id}: {inspection.description}")
            runtime._skills[skill.id] = skill
        if runtime._skills:
            runtime.definitions[READ_SKILL] = Tool.model_validate({
                "name": READ_SKILL,
                "description": "Read a text resource of a loaded Galaris skill, or list its package files.",
                "inputSchema": _ReadInput.model_json_schema(),
            })
        if deferred:
            runtime.definitions[LOAD_SKILL] = Tool.model_validate({
                "name": LOAD_SKILL,
                "description": "Load a deferred Galaris skill by exact ID from the current system instructions.",
                "inputSchema": _LoadInput.model_json_schema(),
            })
        sections: list[str] = []
        if deferred:
            sections.append(
                "## Deferred Galaris skills\n\n"
                f"Call `mcp__galaris__{LOAD_SKILL}` by exact ID only when the described skill applies to the work.\n\n"
                + "\n".join(deferred),
            )
        if eager:
            sections.append("## Eager Galaris skills\n\n" + "\n\n".join(eager))
        runtime.instructions = "\n\n".join(sections)
        return runtime

    async def call(self, name: str, arguments: dict[str, object]) -> CallToolResult:
        try:
            request = (_LoadInput if name == LOAD_SKILL else _ReadInput).model_validate(arguments)
        except ValidationError:
            return _result("Use an exact skill ID and the fields defined by this tool.", error=True)
        skill = self._skills.get(request.id)
        if skill is None:
            return _result("This Galaris skill is unavailable.", error=True)
        try:
            async with get_db_session():
                await require_skill_access(self._agent_id, skill.code, skill.owner_agent_id, skill.package_id)
            if isinstance(request, _ReadInput):
                if skill.id not in self._loaded:
                    return _result(f"Load skill {skill.id!r} with `mcp__galaris__{LOAD_SKILL}` first.", error=True)
                content = read_skill_resource(skill.code, request.path, request.section, owner_agent_id=skill.owner_agent_id)
                return _result(content, error=content.startswith(SKILL_RESOURCE_ERROR_PREFIXES))
            content = _guide(skill)
        except (OSError, ValueError):
            return _result("This Galaris skill is unavailable.", error=True)
        self._loaded.add(skill.id)
        return _result(content)


def _guide(skill: RuntimeSkill) -> str:
    instructions = storage.read_text(skill.code, "SKILL.md", owner_agent_id=skill.owner_agent_id)
    return skill_guide_instructions(skill.code, instructions, f"mcp__galaris__{READ_SKILL}", skill_id=skill.id)


def _result(text: str, *, error: bool = False) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], is_error=error)
