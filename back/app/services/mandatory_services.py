"""Idempotent seed for built-in Galaris tools.

Reserved tools group native MCP functions by domain. System services are mandatory;
optional tool connections remain configurable per agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from loguru import logger
from sqlalchemy import select

from core.database import get_db
from core.params import runtime_settings

from .models import Service as ServiceModel
from .descriptions import DESCRIPTIONS
from .contracts import CHAT_CHANNEL_PARAM, MANAGEMENT_SCOPE_OPTIONS


AGENT_DISCOVERY_TOOLS = ("agent_list", "agent_get", "team_list", "team_members")
SERVICE_DISCOVERY_TOOLS = ("services_list",)
ADMIN_TOOLS = ("documentation_catalog", "documentation_search", "llm_call", "llm_calls", "incidents_list", "incident_get")
CONVERSATION_INSPECTION_TOOLS = ("conversation_round_get", "voice_turn_get")
VOICE_TOOLS = ("voice_call_start", "voice_call_stop", "voice_call_list")
CHAT_TOOLS = (*CONVERSATION_INSPECTION_TOOLS, *VOICE_TOOLS, "repository_show", "conversation_choice_resolve")
CONTACT_TOOLS = ("contact_list", "contact_get", "contact_create", "contact_update")
TASK_TOOLS = ("task_run", "task_get", "task_work_update", "task_stop")
DOCUMENT_ANALYSIS_TOOLS = ("document_analyze", "document_analysis_get", "document_analysis_cancel")
CONVERSATION_TASK_TOOLS = (
    "conversation_task_submit", "conversation_task_list", "conversation_task_status", "conversation_task_pause",
    "conversation_task_resume", "conversation_task_retry", "conversation_task_stop",
)
CONVERSATION_PROCESS_TOOLS = (
    "conversation_process_start", "conversation_process_prepare", "conversation_process_pending", "conversation_process_respond",
)
IMAGE_TOOLS = ("image_generate", "image_read", "image_from_pdf")
AUDIO_TOOLS = ("audio_transcribe",)
SEARCH_TOOLS = ("search_web",)
SPECIALIST_MEDIA_TOOLS = ("audio_read", "video_read", "sound_generate", "music_generate", "video_generate")

GOAL_SELF_SERVICE_TOOLS = (
    "goal_update_suivi", "goal_run_now", "goal_ask_referrer",
    "goal_retrospective_evidence", "goal_retrospective_learn", "goal_retrospective_record",
)

PROCESS_SELF_SERVICE_TOOLS = (
    "process_list", "process_get", "process_start", "process_list_runs",
    "process_get_run", "process_analyze_run", "processus_get",
    "process_activity_complete", "process_activity_question",
    "process_definition_read", "process_create", "process_update", "process_validate",
    "process_history", "process_restore", "process_archive", "process_share",
    "process_run_inspect", "process_run_occurrence", "process_run_children", "process_run_metrics", "process_run_control", "process_run_cancel", "process_run_retry",
)

SYSTEM_SERVICE_CODES = frozenset({"galaris", "chat", "memory", "document", "file_sharing", "calendar", "contact", "task"})


@dataclass(frozen=True)
class IntegratedServiceSpec:
    """Built-in tool definition and its native MCP functions."""

    code: str
    label: str
    description: str
    mcp_tools: tuple[str, ...]
    auto_connect_agents: bool = True
    default_active: bool = False
    file_share_service: str | None = None
    messenger_service: str | None = None
    @property
    def management_scopes(self) -> tuple[str, ...]:
        return MANAGEMENT_SCOPE_OPTIONS.get(self.code, ())


INTEGRATED_SERVICE_SPECS: tuple[IntegratedServiceSpec, ...] = (
    IntegratedServiceSpec(code="calendar", label="Agenda", description=DESCRIPTIONS["calendar"],
        mcp_tools=("calendar_list", "calendar_events", "calendar_is_available", "calendar_find_free_slots",
                   "calendar_create_event", "calendar_update_event", "calendar_delete_event",
                   "calendar_event_get", "calendar_actions", "calendar_action_set"), default_active=True),
    IntegratedServiceSpec(
        code="service", label="Services", description=DESCRIPTIONS["service"],
        mcp_tools=(
            *SERVICE_DISCOVERY_TOOLS,
            "service_admin_list", "service_admin_get", "service_admin_create", "service_admin_update",
            "service_admin_impact", "service_admin_delete", "service_admin_global_params_set",
            "service_admin_mcp_test", "service_admin_function_list",
            "service_admin_function_get", "service_admin_function_set", "service_admin_connection_list",
            "service_admin_connection_get", "service_admin_connection_create", "service_admin_connection_update",
            "service_admin_connection_delete", "service_admin_connection_params_set", "service_admin_connection_param_delete",
            "service_admin_connection_test", "service_admin_connection_function_list", "service_admin_connection_function_set",
            "service_admin_catalog_refresh",
        ),
        default_active=True,
    ),
    IntegratedServiceSpec(
        code="lab", label="Lab", description=DESCRIPTIONS["lab"],
        mcp_tools=(
            "lab_list",
            "lab_get",
            "lab_models",
            "lab_prompt_defaults",
            "lab_dataset_list",
            "lab_dataset_get",
            "lab_dataset_create",
            "lab_dataset_update",
            "lab_dataset_clone",
            "lab_dataset_delete",
            "lab_case_list",
            "lab_case_get",
            "lab_case_create",
            "lab_case_update",
            "lab_case_duplicate",
            "lab_case_delete",
            "lab_case_restore_source",
            "lab_input_preview",
            "lab_source_list",
            "lab_case_import",
            "lab_topic_agent_list",
            "lab_topic_person_list",
            "lab_topic_messages_preview",
            "lab_topic_messages_import",
            "lab_run_start",
            "lab_run_list",
            "lab_run_get",
            "lab_run_results",
            "lab_run_cancel",
            "lab_run_resume",
            "lab_run_rejudge",
            "lab_run_delete",
            "lab_campaign_list",
            "lab_campaign_get",
            "lab_run_compare",
            "lab_dataset_generate",
            "lab_process_dataset_create", "lab_process_dataset_generate", "lab_process_campaign_start",
            "lab_process_campaign_get", "lab_process_campaign_cancel",
            "lab_expected_generate",
            "lab_run_analyze",
            "lab_task_analyze",
            "lab_operation_get",
            "lab_operation_cancel",
            "lab_task_candidates",
            "lab_task_list",
            "lab_task_add",
            "lab_task_remove",
            "lab_task_diagnoses",
            "lab_review_list",
            "lab_review_get",
            "lab_review_submit",
            "lab_content_read",
        ),
        default_active=False,
    ),
    IntegratedServiceSpec(
        code="multimedia", label="Multimedia",
        description=DESCRIPTIONS["multimedia"],
        mcp_tools=(*SPECIALIST_MEDIA_TOOLS, "multimedia_get_run", *IMAGE_TOOLS, *AUDIO_TOOLS),
        default_active=True,
    ),
    IntegratedServiceSpec(
        code="chat",
        label="Chat",
        description=DESCRIPTIONS["chat"],
        mcp_tools=CHAT_TOOLS,
        default_active=True,
        messenger_service="internal",
    ),
    IntegratedServiceSpec(
        code="browser",
        label="Browser",
        description=DESCRIPTIONS["browser"],
        mcp_tools=(
            *SEARCH_TOOLS,
            "browser_open",
            "browser_navigate",
            "browser_content",
            "browser_screenshot",
            "browser_click",
            "browser_type",
            "browser_press",
            "browser_scroll",
            "browser_back",
            "browser_close",
        ),
        default_active=True,
    ),
    IntegratedServiceSpec(
        code="galaris",
        label="Galaris",
        description=DESCRIPTIONS["galaris"],
        mcp_tools=ADMIN_TOOLS,
        default_active=True,
    ),
    IntegratedServiceSpec(
        code="memory",
        label="Memory",
        description=DESCRIPTIONS["memory"],
        mcp_tools=(
            "memory_remember",
            "memory_upcoming",
            "memory_forget",
            "memory_summarize",
                    ),
        default_active=True,
    ),
    IntegratedServiceSpec(
        code="document", label="Documents", description=DESCRIPTIONS["document"],
        mcp_tools=("document_sharing", "document_share", "document_revision_list", "document_revision_compare",
                    "document_show", *DOCUMENT_ANALYSIS_TOOLS, "mindmap_create", "mindmap_read", "mindmap_add", "mindmap_edit"),
        default_active=True,
    ),
    IntegratedServiceSpec(code="contact", label="Contact", description=DESCRIPTIONS["contact"],
                          mcp_tools=CONTACT_TOOLS, default_active=True),
    IntegratedServiceSpec(code="task", label="Tasks", description=DESCRIPTIONS["task"],
                          mcp_tools=(*TASK_TOOLS, *CONVERSATION_TASK_TOOLS), default_active=True),
    IntegratedServiceSpec(
        code="file_sharing",
        label="File sharing",
        description=DESCRIPTIONS["file_sharing"],
        mcp_tools=(
            "file_schemes", "file_list", "file_info", "file_search",
            "file_read", "file_create", "file_write", "file_append", "file_edit",
            "file_copy", "file_move", "file_rename", "file_delete", "file_to_pdf",
            "dataset_query",
        ),
        default_active=True,
    ),
    IntegratedServiceSpec(
        code="process",
        label="Processes",
        description=DESCRIPTIONS["process"],
        mcp_tools=(
            *PROCESS_SELF_SERVICE_TOOLS,
            *CONVERSATION_PROCESS_TOOLS,
            "process_admin_engines",
            "process_admin_sync",
            "process_admin_list",
            "process_admin_get",
            "process_admin_create",
            "process_admin_update",
            "process_admin_delete",
            "process_admin_start",
            "process_admin_list_runs",
            "process_admin_get_run",
            "process_admin_refresh_run",
            "process_admin_cancel_run",
            "process_admin_retry_run",
            "process_admin_analyze_run",
            "process_admin_delete_run",
        ),
        default_active=True,
    ),
    IntegratedServiceSpec(
        code="agent", label="Agent", description=DESCRIPTIONS["agent"],
        mcp_tools=(
            *AGENT_DISCOVERY_TOOLS,
            "agent_create", "agent_update", "agent_delete", "agent_options",
            "agent_avatar_set", "agent_avatar_delete", "agent_avatar_generate",
            "agent_team_list", "agent_team_set", "agent_service_list",
            "agent_connection_list", "agent_connection_get", "agent_connection_create",
            "agent_connection_update", "agent_connection_delete", "agent_connection_params_set",
            "agent_connection_param_delete", "agent_connection_function_list", "agent_connection_function_set",
            "agent_harness_get", "agent_harness_set", "agent_harness_reset", "agent_harness_status",
            "agent_harness_action", "agent_harness_logs", "agent_harness_blockers",
            "agent_title_list", "agent_title_create", "agent_title_update", "agent_title_delete",
            "agent_group_list", "agent_group_create", "agent_group_update", "agent_group_delete",
        ),
        default_active=True,
    ),
    IntegratedServiceSpec(
        code="topic",
        label="Topics",
        description=DESCRIPTIONS["topic"],
        mcp_tools=(
            "topic_list",
            "topic_get",
            "topic_items_list",
            "topic_create",
            "topic_update",
            "topic_item_move",
            "topic_merge",
            "topic_split",
        ),
        auto_connect_agents=False,
        default_active=False,
    ),
    IntegratedServiceSpec(
        code="goal",
        label="Goals",
        description=DESCRIPTIONS["goal"],
        mcp_tools=(
            *GOAL_SELF_SERVICE_TOOLS,
            "goal_create",
            "goal_update",
            "goal_pause",
            "goal_resume",
            "goal_complete",
            "goal_delete",
        ),
        default_active=True,
    ),
    IntegratedServiceSpec(
        code="skills",
        label="Skills",
        description=DESCRIPTIONS["skills"],
        mcp_tools=("skills_list", "skill_read", "skill_update", "skill_set_enabled", "skill_delete",
                   "skill_set_authorization", "skill_set_category_authorization", "skill_release_ownership"),
        default_active=True,
    ),
    IntegratedServiceSpec(
        code="console",
        label="Console SSH",
        description=DESCRIPTIONS["console"],
        mcp_tools=(
            "console_status",
            "console_exec",
            "console_start",
            "console_poll",
            "console_write",
            "console_stop",
        ),
        # The console observer provisions credentials for new internal agents;
        # a generic dataset connection would lack its SSH account and keys.
        auto_connect_agents=False,
        default_active=True,
        file_share_service="console",
    ),
)

INTEGRATED_SERVICE_CODES = frozenset(spec.code for spec in INTEGRATED_SERVICE_SPECS)
AUTO_CONNECTED_INTEGRATED_SERVICE_CODES = frozenset(
    spec.code for spec in INTEGRATED_SERVICE_SPECS if spec.auto_connect_agents
)
DEFAULT_ACTIVE_INTEGRATED_SERVICE_CODES = frozenset(
    spec.code for spec in INTEGRATED_SERVICE_SPECS
    if spec.auto_connect_agents and spec.default_active
)
DEFAULT_INACTIVE_INTEGRATED_SERVICE_CODES = frozenset(
    spec.code for spec in INTEGRATED_SERVICE_SPECS
    if spec.auto_connect_agents and not spec.default_active
)


def _param(
    type_: str = "string",
    *,
    required: bool = True,
    default: str = "",
    description: str = "",
    options: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "type": type_,
        "required": required,
        "default": default,
        "description": description,
        "options": options or [],
    }


def _messenger_connection_params(
    kind: str | None = None,
) -> dict[str, dict[str, Any]]:
    kind = kind or runtime_settings.MESSENGER_DRIVER
    if kind == "nextcloud_talk":
        return {
            "login": _param(description="Nextcloud identifier for the agent account"),
            "password": _param(
                "password",
                description="Nextcloud password",
            ),
        }
    if kind == "matrix":
        return {
            "user_id": _param(description="Matrix bot identifier, for example @bot:example.org"),
            "access_token": _param(
                "password",
                required=False,
                description="Long-lived access token",
            ),
            "password": _param(
                "password",
                required=False,
                description="Matrix password when no access_token is provided",
            ),
            "allowed_user_ids": _param(
                required=False,
                description="Comma-separated authorized Matrix user IDs",
            ),
            "allowed_room_ids": _param(
                required=False,
                description="Comma-separated authorized Matrix room IDs",
            ),
            "require_group_mention": _param(
                "boolean",
                required=False,
                default="false",
                description="Require the bot Matrix ID or mention in group rooms",
            ),
            "auto_join_invites": _param(
                "boolean",
                required=False,
                default="false",
                description="Join unencrypted invitations matching an explicit allowlist",
            ),
        }
    if kind == "one_bot":
        return {
            "user_id": _param(description="Bot identifier on the OneBot platform"),
            "password": _param(
                "password",
                required=False,
                description="Optional OneBot adapter secret",
            ),
        }
    if kind == "telegram":
        return {
            "bot_token": _param("password", description="Telegram BotFather token"),
            "allowed_user_ids": _param(
                required=False,
                description="Comma-separated authorized Telegram user IDs",
            ),
            "allowed_chat_ids": _param(
                required=False,
                description="Comma-separated authorized private or group chat IDs",
            ),
            "require_group_mention": _param(
                "boolean",
                required=False,
                default="true",
                description="Require a mention or direct reply in groups",
            ),
        }
    if kind == "whatsapp":
        return {
            "access_token": _param("password", description="Meta permanent access token"),
            "phone_number_id": _param(description="WhatsApp Business phone number ID"),
            "business_account_id": _param(
                required=False,
                description="WhatsApp Business Account ID",
            ),
            "allowed_phone_numbers": _param(
                required=False,
                description="Comma-separated authorized E.164 phone numbers",
            ),
            "template_name": _param(
                required=False,
                description="Approved template for proactive messages",
            ),
            "template_language": _param(
                required=False,
                default="en_US",
                description="Approved template locale",
            ),
        }
    return {}


def _console_connection_params() -> dict[str, dict[str, Any]]:
    return {
        "code_runtime_port": _param("integer", required=False,
            description="Prepared external IDE broker loopback port (SSH PermitOpen required)"),
        "code_runtime_token": _param("password", required=False,
            description="Prepared external IDE broker credential; never sent to the browser"),
        "host": _param(description="SSH server DNS name or IP address"),
        "port": _param("integer", default="22", description="SSH server port"),
        "username": _param(description="Dedicated Unix user"),
        "private_key": _param("password", description="OpenSSH private key"),
        "private_key_passphrase": _param(
            "password",
            required=False,
            description="Optional private-key passphrase",
        ),
        "known_host_key": _param(
            "password",
            description="Pinned SSH host public key or known_hosts entry",
        ),
        "connect_timeout_s": _param(
            "integer",
            required=False,
            default="10",
            description="SSH connection timeout in seconds",
        ),
        "command_timeout_s": _param(
            "integer",
            required=False,
            default="300",
            description="Default command timeout in seconds",
        ),
    }


def _browser_connection_params() -> dict[str, dict[str, Any]]:
    return {
        "public_access_mode": _param(required=False, default="ask",
            options=[{"value": "allow"}, {"value": "ask"}],
            description="Allow public sites without per-site approval, or ask per site; local network restrictions and explicit denials remain active"),
        "allow_local_network": _param("boolean", required=False, default="false",
            description="Allow asking permission for local network access; otherwise block it"),
        "network_filter_mode": _param(required=False, default="block",
            options=[{"value": "block"}, {"value": "allow"}],
            description="block: deny listed destinations; allow: permit only listed destinations"),
        "network_filter": _param(required=False,
            description="Domains, *.subdomains, IPs or CIDRs separated by commas; optional :port (IPv6 in brackets)"),
        "permission_methods": _param(required=False, default="POST PUT PATCH DELETE WEBSOCKET",
            description="HTTP methods requiring remembered approval in per-site mode or on local networks, separated by spaces"),
        "default_output": _param(
            required=False,
            default="content",
            options=[{"value": "content"}, {"value": "screenshot"}],
            description="Default browser response: content or screenshot",
        ),
    }


def mandatory_service_rows() -> list[dict[str, Any]]:
    """Return built-in tool rows ready for persistence."""
    from app.services.service import default_global_params
    from .parameter_definitions import with_standard_params

    rows: list[dict[str, Any]] = []
    messenger_kind_by_tool = {
        "nextcloud_talk": "nextcloud_talk",
        "matrix": "matrix",
        "telegram": "telegram",
        "whatsapp": "whatsapp",
        "one_bot": "one_bot",
    }
    for spec in INTEGRATED_SERVICE_SPECS:
        if (
            spec.code == "messenger"
            and runtime_settings.MESSENGER_DRIVER == "nextcloud_talk"
        ):
            continue
        bridge_kind = messenger_kind_by_tool.get(spec.code)
        connection_schema: dict[str, Any] = (
            {
                "params": _messenger_connection_params(
                    bridge_kind if bridge_kind is not None else None
                )
            }
            if spec.code == "messenger" or bridge_kind is not None
            else {
                "params": (
                    _console_connection_params()
                    if spec.code == "console"
                    else _browser_connection_params()
                    if spec.code == "browser"
                    else {}
                )
            }
        )
        params = cast(dict[str, dict[str, Any]], connection_schema.get("params") or {})
        if spec.code == "chat":
            params[CHAT_CHANNEL_PARAM] = {
                **_param("boolean", required=False, default="true"),
                "label": "services.connectionParamLabels.chatChannel",
                "description": "services.connectionParamDescriptions.chatChannel",
            }
        if spec.management_scopes:
            from .contracts import default_management_scope
            from .parameter_definitions import management_scope_parameter
            params["services.management_scope"] = management_scope_parameter(
                spec.management_scopes, default=default_management_scope(spec.code))
            if spec.code == "skills":
                scope = params["services.management_scope"]
                scope["label"] = "services.connectionParamLabels.skillsScope"
                scope["description"] = "services.connectionParamDescriptions.skillsScope"
                for option in scope["options"]:
                    option["label"] = f"services.connectionParamOptions.skillsScope.{option['value']}"
        connection_schema["params"] = params
        for order, (name, definition) in enumerate(params.items()):
            definition["order"] = order
            definition.setdefault("label", f"services.connectionParamLabels.{name}")
            definition["builtin"] = True
            for option in definition["options"]:
                if name != "services.management_scope":
                    option["label"] = f"services.connectionParamOptions.{spec.code}.{name}.{option['value']}"
        connection_schema = with_standard_params(connection_schema, code=spec.code,
            file_share_config={"service": spec.file_share_service} if spec.file_share_service else None,
            messenger_config={"service": spec.messenger_service or bridge_kind or runtime_settings.MESSENGER_DRIVER}
            if spec.messenger_service or bridge_kind or spec.code == "messenger" else None)
        global_params = default_global_params(connection_schema)
        if spec.code == "browser":
            # Installation seed only: DbAdmin derives defaults for existing Services
            # from their schema, preserving the legacy per-site policy.
            global_params["public_access_mode"] = {"value": "allow", "forced": False}
        rows.append({
            "code": spec.code,
            "can_disable": spec.code not in SYSTEM_SERVICE_CODES,
            "label": spec.label,
            "description": spec.description,
            "mcp_config": None,
            "file_share_config": (
                {
                    "service": spec.file_share_service,
                    "base_url": "",
                    "param_map": {},
                }
                if spec.file_share_service is not None
                else None
            ),
            "messenger_config": (
                {
                    "service": spec.messenger_service,
                    "settings": {},
                    "param_map": {},
                }
                if spec.messenger_service is not None
                else None
            ),
            "listener_config": None,
            "connection_schema": connection_schema,
            "global_params": global_params,
            "task_config": None,
        })
    from .capabilities import capabilities_from_values
    for row in rows:
        row["capabilities"] = ["internal.calendar"] if row["code"] == "calendar" else capabilities_from_values(row)
    return rows


async def sync_mandatory_services() -> list[ServiceModel]:
    """Apply the module DataSource through the DbAdmin merge engine."""
    from core.dbadmin import reconcile_dataset
    from .builtin_merge import merge_builtin_services, merge_conversation_into_chat, merge_media_and_search_services
    from .dbadmin import datasets, move_galaris_function_policies

    db = get_db()
    for dataset in datasets():
        await reconcile_dataset(db, dataset)
    await move_galaris_function_policies(db)
    await merge_builtin_services(db)
    await merge_conversation_into_chat(db)
    await merge_media_and_search_services(db)
    await db.flush()
    codes = tuple(str(row["code"]) for row in mandatory_service_rows())
    synced = list(
        (
            await db.scalars(
                select(ServiceModel).where(ServiceModel.code.in_(codes))
            )
        ).all()
    )
    logger.info("System tools synchronized through DbAdmin: {}", ", ".join(codes))
    return synced


async def initialize_admin_agent_connections(agent_id: int) -> None:
    """Seed native permissions once, when the Galaris assistant is created."""
    from app.connection import Connection
    from app.connection.facade import (
        get_or_create_connection, set_connection_function_state, set_management_scope, set_voice_auto_answer,
    )
    from .contracts import MANAGEMENT_SCOPE_PARAM
    from .mcp_loader import load_mcp_tools, native_service_codes_for_service

    await sync_integrated_service_connections(agent_id)
    # Topics are native but opt-in for ordinary agents. Console, Mail and Calendar
    # require an explicitly configured external connection and remain separate.
    topic = await get_db().scalar(select(ServiceModel).where(ServiceModel.code == "topic"))
    if topic is not None:
        await get_or_create_connection(topic.id, agent_id, commit=False)
    definitions = load_mcp_tools()
    for connection, tool in await get_db().execute(
        select(Connection, ServiceModel).join(ServiceModel, ServiceModel.id == Connection.service_id).where(
            Connection.agent_id == agent_id,
            ServiceModel.code.in_(AUTO_CONNECTED_INTEGRATED_SERVICE_CODES | {"topic"}),
        )
    ):
        connection.active = True
        if tool.code not in {"calendar", "contact", "document", "goal", "process", "task"} and MANAGEMENT_SCOPE_PARAM in tool.connection_schema.get("params", {}):
            await set_management_scope(connection.id, "all", commit=False, authorized=True)
        if tool.code == "chat":
            await set_voice_auto_answer(connection.id, True, commit=False)
        codes = native_service_codes_for_service(tool)
        for definition in definitions:
            if definition.service_code in codes:
                await set_connection_function_state(connection.id, definition.name, "enabled", commit=False)


async def sync_integrated_service_connections(agent_id: int | None = None) -> int:
    """Merge missing auto-connected agent-to-tool connections.

    Core connections start active while optional capabilities start inactive. Services requiring
    per-agent credentials opt out and remain administrator-managed.
    """
    from core.dbadmin import reconcile_dataset
    from .dbadmin import datasets

    dataset = next(item for item in datasets(agent_id=agent_id) if item.key == "app.services.mandatory.connections")
    result = await reconcile_dataset(get_db(), dataset)
    if result.inserted:
        logger.info("{} built-in connection(s) created for agents", result.inserted)
    return result.inserted
