"""Initial privilege organization, owned by administrators after installation."""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminDatasetResult

from .models import Privilege, PrivilegeList, PrivilegeListDefault


@dataclass(frozen=True)
class DefaultPrivilegeList:
    code: str
    legacy_name: str
    privilege_codes: tuple[str, ...]

    @property
    def display_name(self) -> str:
        return f"authorize.privilegeLists.defaults.{self.code}"


DEFAULT_PRIVILEGE_LISTS = (
    DefaultPrivilegeList("functionalSettings", "Réglages par fonction", (
        "LANGUAGE_CONFIG_ACCESS",
        "LANGUAGE_CONFIG_EDIT",
        "SEARCH_CONFIG_ACCESS",
        "SEARCH_CONFIG_EDIT",
        "INSTRUCTION_CONFIG_ACCESS",
        "INSTRUCTION_CONFIG_EDIT",
        "LOG_CONFIG_ACCESS",
        "LOG_CONFIG_EDIT",
        "MESSAGING_CONFIG_ACCESS",
        "MESSAGING_CONFIG_EDIT",
        "MEMORY_CONFIG_ACCESS",
        "MEMORY_CONFIG_EDIT",
        "VOICE_CONFIG_ACCESS",
        "VOICE_CONFIG_EDIT",
        "AUDIO_CONFIG_ACCESS",
        "AUDIO_CONFIG_EDIT",
        "PROCESS_CONFIG_ACCESS",
        "PROCESS_CONFIG_EDIT",
        "TASK_CONFIG_ACCESS",
        "TASK_CONFIG_EDIT",
        "JANUS_CONFIG_ACCESS",
        "JANUS_CONFIG_EDIT",
        "BROWSER_CONFIG_ACCESS",
        "BROWSER_CONFIG_EDIT",
        "GOAL_CONFIG_ACCESS",
        "GOAL_CONFIG_EDIT",
        "DREAM_CONFIG_ACCESS",
    )),
    DefaultPrivilegeList("mailCalendars", "Mail & calendriers", (
        "MAIL_ACCESS", "MAIL_EDIT", "CALENDAR_ACCESS", "CALENDAR_EDIT",
    )),
    DefaultPrivilegeList("administration", "Administration", (
        "CONSOLE_ACCESS", "CONSOLE_ADMIN", "HARNESS_CONFIG_ACCESS", "HARNESS_CONFIG_EDIT",
        "INCIDENT_ACCESS", "INCIDENT_EDIT", "INCIDENT_PURGE", "LLM_MODEL_ACCESS",
        "LLM_MODEL_EDIT", "LLM_PROFILE_ACCESS", "LLM_PROFILE_EDIT", "LLM_PROVIDER_ACCESS",
        "LLM_PROVIDER_EDIT", "PARAMS_ACCESS", "PARAMS_EDIT",
    )),
    DefaultPrivilegeList("agentsTeams", "Agents & équipes", (
        "AGENT_ACCESS", "AGENT_EDIT", "AGENT_MANAGE_ALL", "LLM_API_ACCESS", "MCP_API_ACCESS",
        "TEAM_ACCESS", "TEAM_EDIT", "TEAM_MEMBERS_EDIT",
    )),
    DefaultPrivilegeList("discussion", "Discussion", (
        "CHAT_ACCESS", "CHAT_CALL", "CHAT_IMPERSONATE", "CHAT_MANAGE", "CHAT_SEND",
        "CONTACT_ACCESS", "CONTACT_EDIT",
    )),
    DefaultPrivilegeList("documentsDatasets", "Documents & jeux de données", (
        "DATASET_ADMIN", "DATASET_EDIT", "DATASET_READ", "DOCUMENT_ACCESS", "DOCUMENT_ADMIN",
        "DOCUMENT_ASSIGN_ALL_USERS", "DOCUMENT_EDIT",
    )),
    DefaultPrivilegeList("filesDream", "Fichiers & Dream", (
        "DREAM_ACCESS", "DREAM_EDIT", "FILE_ACCESS", "FILE_EDIT", "FILE_INDEX_ACCESS", "FILE_INDEX_RUN",
    )),
    DefaultPrivilegeList("lab", "Lab", (
        "CONVERSATION_EXECUTOR_EVALUATION_ACCESS", "CONVERSATION_EXECUTOR_EVALUATION_EDIT",
        "DISPATCHER_EVALUATION_ACCESS", "DISPATCHER_EVALUATION_EDIT", "EVALUATION_ACCESS",
        "EVALUATION_EDIT", "GOAL_TRACKING_EVALUATION_ACCESS", "GOAL_TRACKING_EVALUATION_EDIT",
        "MEMORY_EXTRACTION_EVALUATION_ACCESS", "MEMORY_EXTRACTION_EVALUATION_EDIT",
        "OUTCOME_REFLECTION_EVALUATION_ACCESS", "OUTCOME_REFLECTION_EVALUATION_EDIT",
        "PLANNER_EVALUATION_ACCESS", "PLANNER_EVALUATION_EDIT", "PROCESS_EVALUATION_ACCESS",
        "PROCESS_EVALUATION_EDIT", "TASK_EXECUTOR_EVALUATION_ACCESS", "TASK_EXECUTOR_EVALUATION_EDIT",
        "TOPIC_CLASSIFICATION_EVALUATION_ACCESS", "TOPIC_CLASSIFICATION_EVALUATION_EDIT",
        "VOICE_EXECUTOR_EVALUATION_ACCESS", "VOICE_EXECUTOR_EVALUATION_EDIT",
    )),
    DefaultPrivilegeList("memoryTopics", "Mémoire & dossiers", (
        "MEMORY_ACCESS", "MEMORY_ADMIN", "MEMORY_EDIT", "TOPIC_ACCESS", "TOPIC_EDIT",
    )),
    DefaultPrivilegeList("goals", "Objectifs", ("GOAL_ACCESS", "GOAL_EDIT")),
    DefaultPrivilegeList("toolsSkills", "Outils & compétences", (
        "CODE_ACCESS", "CONNECTION_ACCESS", "CONNECTION_EDIT", "PERMISSION_ACCESS",
        "SKILL_ACCESS", "SKILL_ASSIGN", "SKILL_EDIT", "TOOL_ACCESS", "TOOL_EDIT",
    )),
    DefaultPrivilegeList("processes", "Processus", (
        "PROCESS_ADMIN", "PROCESS_EDIT", "PROCESS_LAUNCH", "PROCESS_READ",
    )),
    DefaultPrivilegeList("tasksExecution", "Tâches & exécution", (
        "AGENT_API_ACCESS", "CONVERSATION_ACCESS", "CONVERSATION_CONTROL", "DASHBOARD_ACCESS",
        "LLM_CALL_ACCESS", "LLM_CALL_CONTROL", "LLM_CALL_PURGE", "PERMISSION_DECIDE",
        "PERMISSION_REVOKE", "TASK_ACCESS", "TASK_EDIT", "TASK_PURGE", "VOICE_HISTORY_ACCESS",
        "VOICE_HISTORY_CONTROL",
    )),
    DefaultPrivilegeList("usersAccess", "Utilisateurs & accès", (
        "CREATE_USER", "DELETE_USER", "MANAGE_ASSIGNMENT", "MANAGE_PRIVILEGE", "MANAGE_ROLE",
        "READ_ASSIGNMENT", "READ_PRIVILEGE", "READ_ROLE", "READ_USER", "UPDATE_USER",
    )),
)


async def initialize_default_lists(
    session: AsyncSession,
    _result: DbAdminDatasetResult,
) -> None:
    """Initialize each category once, in the dataset transaction with its receipt."""
    pending = {
        receipt.code: receipt
        for receipt in await session.scalars(
            select(PrivilegeListDefault).where(PrivilegeListDefault.initialized_at.is_(None))
        )
    }
    for default in DEFAULT_PRIVILEGE_LISTS:
        receipt = pending.get(default.code)
        if receipt is None:
            continue
        category = await session.scalar(
            select(PrivilegeList).where(PrivilegeList.display_name == default.display_name)
        )
        if category is None:
            category = await session.scalar(
                select(PrivilegeList).where(PrivilegeList.display_name == default.legacy_name)
            )
            if category is None:
                category = PrivilegeList(display_name=default.display_name)
                session.add(category)
            else:
                category.display_name = default.display_name
        category.translation_key = default.display_name
        await session.flush()
        # Existing custom organization takes priority over initial assignments.
        await session.execute(
            update(Privilege)
            .where(Privilege.code.in_(default.privilege_codes), Privilege.privilege_list_id.is_(None))
            .values(privilege_list_id=category.id)
        )
        receipt.initialized_at = datetime.now(timezone.utc)
    await session.flush()
