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

from .models import Tool as ToolModel
from .descriptions import DESCRIPTIONS


DEFAULT_CONVERSATION_TOOL_CODES = frozenset(
    {
        "galaris", "conversation", "memory", "file_sharing",
        "browser", "console", "search", "image", "multimedia",
    }
)
SYSTEM_TOOL_CODES = frozenset({"galaris", "conversation", "memory", "file_sharing"})


@dataclass(frozen=True)
class IntegratedToolSpec:
    """Built-in tool definition and its native MCP functions."""

    code: str
    label: str
    description: str
    mcp_tools: tuple[str, ...]
    auto_connect_agents: bool = True
    default_active: bool = False
    file_share_service: str | None = None
    messenger_service: str | None = None


INTEGRATED_TOOL_SPECS: tuple[IntegratedToolSpec, ...] = (
    IntegratedToolSpec(
        code="lab", label="Lab Galaris", description=DESCRIPTIONS["lab"],
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
    IntegratedToolSpec(
        code="multimedia", label="Multimedia",
        description=DESCRIPTIONS["multimedia"],
        mcp_tools=("audio_read", "video_read", "sound_generate", "music_generate", "video_generate"),
        default_active=True,
    ),
    IntegratedToolSpec(
        code="chat",
        label="Chat",
        description=DESCRIPTIONS["chat"],
        mcp_tools=(),
        default_active=True,
        messenger_service="internal",
    ),
    IntegratedToolSpec(
        code="search",
        label="Web search",
        description=DESCRIPTIONS["search"],
        mcp_tools=("search_web",),
        default_active=True,
    ),
    IntegratedToolSpec(
        code="browser",
        label="Browser",
        description=DESCRIPTIONS["browser"],
        mcp_tools=(
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
    IntegratedToolSpec(
        code="galaris",
        label="Galaris",
        description=DESCRIPTIONS["galaris"],
        mcp_tools=(
            "agent_list", "agent_get",
            "task_run", "task_get", "task_stop",
            "goal_update_suivi",
            "goal_run_now", "goal_ask_referrer",
            "process_list", "process_get", "process_start", "process_list_runs",
            "process_get_run", "process_analyze_run",
            "tools_list",
        ),
        default_active=True,
    ),
    IntegratedToolSpec(
        code="conversation",
        label="Conversation",
        description=DESCRIPTIONS["conversation"],
        mcp_tools=(
            "document_show", "conversation_task_submit", "conversation_task_list",
            "conversation_task_status", "conversation_task_pause", "conversation_task_resume",
            "conversation_task_retry", "conversation_task_stop", "conversation_choice_resolve",
            "conversation_process_start",
        ),
        default_active=True,
    ),
    IntegratedToolSpec(
        code="memory",
        label="Memory",
        description=DESCRIPTIONS["memory"],
        mcp_tools=(
            "memory_remember",
            "memory_forget",
            "memory_summarize",
            "document_share",
            "memory_sharing",
            "memory_share",
        ),
        default_active=True,
    ),
    IntegratedToolSpec(
        code="file_sharing",
        label="File sharing",
        description=DESCRIPTIONS["file_sharing"],
        mcp_tools=(
            "file_schemes", "file_list", "file_info", "file_search",
            "file_read", "file_create", "file_write", "file_append", "file_edit",
            "file_copy", "file_move", "file_delete",
        ),
        default_active=True,
    ),
    IntegratedToolSpec(
        code="process_admin",
        label="Process administration",
        description=DESCRIPTIONS["process_admin"],
        mcp_tools=(
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
        default_active=False,
    ),
    IntegratedToolSpec(
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
    IntegratedToolSpec(
        code="goal_management",
        label="Gestion des objectifs",
        description=DESCRIPTIONS["goal_management"],
        mcp_tools=(
            "goal_create",
            "goal_update",
            "goal_pause",
            "goal_resume",
            "goal_complete",
            "goal_delete",
        ),
        default_active=False,
    ),
    IntegratedToolSpec(
        code="skill_management",
        label="Gestion des compétences",
        description=DESCRIPTIONS["skill_management"],
        mcp_tools=("skills_list", "skill_read"),
        default_active=False,
    ),
    IntegratedToolSpec(
        code="galaris_admin",
        label="Galaris Admin",
        description=DESCRIPTIONS["galaris_admin"],
        mcp_tools=("conversation_round_get", "voice_turn_get", "llm_call", "llm_calls",
                   "documentation_catalog", "documentation_search"),
        default_active=False,
    ),
    IntegratedToolSpec(
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
    IntegratedToolSpec(
        code="mail",
        label="Mail",
        description=DESCRIPTIONS["mail"],
        mcp_tools=(
            "mail_connection_status",
            "mail_list_mailboxes",
            "mail_search",
            "mail_get",
            "mail_send",
            "mail_reply",
            "mail_forward",
            "mail_set_flags",
            "mail_move",
            "mail_trash",
        ),
        auto_connect_agents=False,
        default_active=False,
        file_share_service="mail",
        messenger_service="mail",
    ),
    IntegratedToolSpec(
        code="calendar",
        label="Calendar",
        description=DESCRIPTIONS["calendar"],
        mcp_tools=(
            "calendar_list",
            "calendar_events",
            "calendar_is_available",
            "calendar_find_free_slots",
            "calendar_create_event",
            "calendar_update_event",
            "calendar_delete_event",
        ),
        auto_connect_agents=False,
        default_active=False,
    ),
    IntegratedToolSpec(
        code="n8n",
        label="n8n",
        description=DESCRIPTIONS["n8n"],
        mcp_tools=(),
        auto_connect_agents=False,
    ),
    IntegratedToolSpec(
        code="image",
        label="Image",
        description=DESCRIPTIONS["image"],
        mcp_tools=("image_generate", "image_read"),
        default_active=True,
    ),
    IntegratedToolSpec(
        code="audio",
        label="Audio",
        description=DESCRIPTIONS["audio"],
        mcp_tools=("audio_transcribe",),
    ),
    IntegratedToolSpec(
        code="voice",
        label="Voice",
        description=DESCRIPTIONS["voice"],
        mcp_tools=("voice_call_start", "voice_call_stop", "voice_call_list"),
    ),
)

INTEGRATED_TOOL_CODES = frozenset(spec.code for spec in INTEGRATED_TOOL_SPECS)
AUTO_CONNECTED_INTEGRATED_TOOL_CODES = frozenset(
    spec.code for spec in INTEGRATED_TOOL_SPECS if spec.auto_connect_agents
)
DEFAULT_ACTIVE_INTEGRATED_TOOL_CODES = frozenset(
    spec.code for spec in INTEGRATED_TOOL_SPECS
    if spec.auto_connect_agents and spec.default_active
)
DEFAULT_INACTIVE_INTEGRATED_TOOL_CODES = frozenset(
    spec.code for spec in INTEGRATED_TOOL_SPECS
    if spec.auto_connect_agents and not spec.default_active
)


def _param(
    type_: str = "string",
    *,
    required: bool = True,
    default: str = "",
    description: str = "",
) -> dict[str, Any]:
    return {
        "type": type_,
        "required": required,
        "default": default,
        "description": description,
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
        "default_output": _param(
            required=False,
            default="content",
            description="Default browser response: content or screenshot",
        ),
    }


def _mail_connection_params() -> dict[str, dict[str, Any]]:
    return {
        "email_address": _param(description="Mailbox email address used as SMTP sender"),
        "password": _param(
            "password",
            description="Mailbox password or application password used by IMAP and SMTP",
        ),
        "imap_host": _param(description="IMAP server DNS name"),
        "imap_port": _param("integer", default="993", description="IMAP server port"),
        "imap_security": _param(
            default="tls", description="IMAP transport security: tls or starttls"
        ),
        "smtp_host": _param(description="SMTP submission server DNS name"),
        "smtp_port": _param("integer", default="465", description="SMTP submission port"),
        "smtp_security": _param(
            default="tls", description="SMTP transport security: tls or starttls"
        ),
        "connect_timeout_s": _param(
            "integer", required=False, default="10", description="Connection timeout in seconds"
        ),
        "operation_timeout_s": _param(
            "integer", required=False, default="30", description="I/O timeout in seconds"
        ),
        "poll_interval_s": _param(
            "integer",
            required=False,
            default="60",
            description="Delay between inbox polls in seconds",
        ),
        "max_attachment_mb": _param(
            "integer",
            required=False,
            default="10",
            description="Maximum size of one attachment in megabytes",
        ),
        "max_total_attachment_mb": _param(
            "integer",
            required=False,
            default="20",
            description="Maximum total attachment size per outgoing message in megabytes",
        ),
        "approval_required": _param(
            "boolean",
            required=False,
            default="false",
            description="Require the configured human user to approve every outgoing message",
        ),
        "approver_user_id": _param(
            "user",
            required=False,
            description="Human user responsible for approving outgoing messages",
        ),
    }


def _calendar_connection_params() -> dict[str, dict[str, Any]]:
    return {
        "timezone": _param(
            required=False,
            default="Europe/Paris",
            description="IANA timezone used to search for available working-hour slots",
        ),
        "workday_start": _param(
            required=False,
            default="09:00",
            description="Default local start of the working day (HH:MM)",
        ),
        "workday_end": _param(
            required=False,
            default="18:00",
            description="Default local end of the working day (HH:MM)",
        ),
        "slot_step_minutes": _param(
            "integer",
            required=False,
            default="15",
            description="Default increment in minutes when searching for free slots",
        ),
    }


def mandatory_tool_rows() -> list[dict[str, Any]]:
    """Return built-in tool rows ready for persistence."""
    from app.tools.tool_service import default_global_params

    rows: list[dict[str, Any]] = []
    messenger_kind_by_tool = {
        "nextcloud_talk": "nextcloud_talk",
        "matrix": "matrix",
        "telegram": "telegram",
        "whatsapp": "whatsapp",
        "one_bot": "one_bot",
    }
    for spec in INTEGRATED_TOOL_SPECS:
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
                    else _mail_connection_params()
                    if spec.code == "mail"
                    else _calendar_connection_params()
                    if spec.code == "calendar"
                    else _browser_connection_params()
                    if spec.code == "browser"
                    else {}
                )
            }
        )
        params = cast(dict[str, dict[str, Any]], connection_schema.get("params") or {})
        for order, definition in enumerate(params.values()):
            definition["order"] = order
        rows.append({
            "code": spec.code,
            "can_disable": spec.code not in SYSTEM_TOOL_CODES,
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
            "global_params": default_global_params(connection_schema),
            "task_config": None,
        })
    return rows


async def sync_mandatory_tools() -> list[ToolModel]:
    """Apply the module DataSource through the DbAdmin merge engine."""
    from core.dbadmin import reconcile_dataset
    from .dbadmin import datasets

    db = get_db()
    for dataset in datasets():
        await reconcile_dataset(db, dataset)
    await db.flush()
    codes = tuple(str(row["code"]) for row in mandatory_tool_rows())
    synced = list(
        (
            await db.scalars(
                select(ToolModel).where(ToolModel.code.in_(codes))
            )
        ).all()
    )
    logger.info("System tools synchronized through DbAdmin: {}", ", ".join(codes))
    return synced


async def initialize_admin_agent_connections(agent_id: int) -> None:
    """Initialize the optional administration grant for a newly seeded agent."""
    from sqlalchemy import update
    from app.connection import Connection

    await sync_integrated_tool_connections(agent_id)
    await get_db().execute(
        update(Connection).where(
            Connection.agent_id == agent_id,
            Connection.tool_id == select(ToolModel.id).where(
                ToolModel.code == "galaris_admin"
            ).scalar_subquery(),
        ).values(active=True)
    )


async def sync_integrated_tool_connections(agent_id: int | None = None) -> int:
    """Merge missing auto-connected agent-to-tool connections.

    Core connections start active while optional capabilities start inactive. Tools requiring
    per-agent credentials opt out and remain administrator-managed.
    """
    from core.dbadmin import reconcile_dataset
    from .dbadmin import datasets

    dataset = datasets(agent_id=agent_id)[1]
    result = await reconcile_dataset(get_db(), dataset)
    if result.inserted:
        logger.info("{} built-in connection(s) created for agents", result.inserted)
    return result.inserted
