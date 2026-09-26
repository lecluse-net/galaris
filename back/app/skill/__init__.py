"""Skill library public API."""

from .models import (
    AgentSkill,
    AgentSkillCategory,
    LearnedSkill,
    LearnedSkillEvidence,
    Skill,
    SkillCategory,
)
from .learning_contracts import (
    LearnedSkillApplyResult,
    LearnedSkillContext,
    LearnedSkillDecision,
    LearnedSkillOperation,
    LearnedSkillRuntimeRefresher,
    refresh_learned_skill_runtime,
    register_learned_skill_runtime_refresher,
)
from .learning_service import (
    apply_learning_decision,
    learning_code_prefix,
    list_injectable,
    list_learning_context,
)
from .schemas import SkillCreate, SkillPublic, SkillUpdate
from .skill_service import has_configured_skills, initialize_galaris_agent_skills
from . import skill_service, storage
from .resource_facade import (
    append_skill_file,
    can_manage_skill_resources,
    create_skill_file,
    delete_skill_file,
    get_skill_resource,
    list_skill_files,
    list_skill_resources,
    move_skill_file,
    read_skill_file,
    require_skill_management_access,
    write_skill_file,
)
from .projection import (
    SkillProjectionFile,
    SkillProjectionSnapshot,
    build_skill_projection,
    build_skill_prompt,
)

__all__ = [
    "AgentSkill",
    "AgentSkillCategory",
    "LearnedSkill",
    "LearnedSkillEvidence",
    "LearnedSkillApplyResult",
    "LearnedSkillContext",
    "LearnedSkillDecision",
    "LearnedSkillOperation",
    "LearnedSkillRuntimeRefresher",
    "Skill",
    "SkillCategory",
    "SkillCreate",
    "SkillPublic",
    "SkillUpdate",
    "SkillProjectionFile",
    "SkillProjectionSnapshot",
    "append_skill_file",
    "apply_learning_decision",
    "can_manage_skill_resources",
    "create_skill_file",
    "delete_skill_file",
    "get_skill_resource",
    "has_configured_skills",
    "initialize_galaris_agent_skills",
    "list_skill_files",
    "list_injectable",
    "list_learning_context",
    "learning_code_prefix",
    "list_skill_resources",
    "move_skill_file",
    "read_skill_file",
    "require_skill_management_access",
    "refresh_learned_skill_runtime",
    "register_learned_skill_runtime_refresher",
    "skill_service",
    "storage",
    "write_skill_file",
    "build_skill_projection",
    "build_skill_prompt",
]
