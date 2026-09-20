"""Application parameter-key constants.

These constants access configuration stored in the database through the
parameter service.

Labels and descriptions live exclusively in frontend vue-i18n catalogs indexed
by parameter name. Configurable system-prompt defaults use one canonical English
Markdown file per value under ``core/params/prompt_defaults``. Prompt content is
never part of i18n. Its literal value is ``None`` here and
``params_service.get_or_default`` resolves it.
"""

from typing import Literal, NotRequired, Optional, TypedDict


ParamValueKind = Literal[
    "string", "secret", "boolean", "integer", "float", "choice", "prompt"
]


class ParamConfig(TypedDict):
    """Configuration for a parameter's optional literal default.

    ``None`` means either no default or a packaged default supplied by ``core.params``.
    """

    value: Optional[str]
    runtime_field: NotRequired[str]
    kind: NotRequired[ParamValueKind]
    choices: NotRequired[tuple[str, ...]]
    display_default: NotRequired[bool]
    empty_uses_default: NotRequired[bool]


class Params:
    """
    Accessor for application params.

    This class groups all parameter keys used to access application configuration.
    """

    # Internal, immutable through the administration API.
    AUTH_SECRET_KEY = "AUTH_SECRET_KEY"
    WEB_PUSH_VAPID_KEYS = "WEB_PUSH_VAPID_KEYS"
    WEB_PUSH_VAPID_SUBJECT = "WEB_PUSH_VAPID_SUBJECT"
    WEB_PUSH_DELAY_SECONDS = "WEB_PUSH_DELAY_SECONDS"

    HARNESS_MANAGER_URL = "HARNESS_MANAGER_URL"
    HARNESS_MANAGER_GALARIS_API_URL = "HARNESS_MANAGER_GALARIS_API_URL"
    HARNESS_MANAGER_SECRET = "HARNESS_MANAGER_SECRET"

    # Example param name definition
    # MY_PARAM = "ma.param"

    # Administrable operation limits.
    HTTP_RATE_LIMIT_PER_MINUTE = "HTTP_RATE_LIMIT_PER_MINUTE"
    ALLOW_USER_REGISTRATION = "ALLOW_USER_REGISTRATION"
    MESSENGER_MAX_INLINE_MB = "MESSENGER_MAX_INLINE_MB"
    PYDANTIC_AI_BINARY_INPUT_MAX_BYTES = "PYDANTIC_AI_BINARY_INPUT_MAX_BYTES"
    LOGFIRE_TOKEN = "LOGFIRE_TOKEN"
    GALARIS_INTERNAL_MESSENGER_MAX_BYTES = "GALARIS_INTERNAL_MESSENGER_MAX_BYTES"
    MEMORY_RESOURCE_MAX_BYTES = "MEMORY_RESOURCE_MAX_BYTES"
    BROWSER_EXECUTOR_TIMEOUT_SECONDS = "BROWSER_EXECUTOR_TIMEOUT_SECONDS"
    BROWSER_SESSION_TTL_SECONDS = "BROWSER_SESSION_TTL_SECONDS"
    BROWSER_MAX_SESSIONS = "BROWSER_MAX_SESSIONS"
    BROWSER_CONTENT_MAX_CHARS = "BROWSER_CONTENT_MAX_CHARS"
    BROWSER_HTML_MAX_BYTES = "BROWSER_HTML_MAX_BYTES"
    BROWSER_SCREENSHOT_TILE_HEIGHT = "BROWSER_SCREENSHOT_TILE_HEIGHT"
    BROWSER_SCREENSHOT_MAX_TILES = "BROWSER_SCREENSHOT_MAX_TILES"
    BROWSER_SCREENSHOT_MAX_TOTAL_BYTES = "BROWSER_SCREENSHOT_MAX_TOTAL_BYTES"
    BROWSER_VIEWPORT_WIDTH = "BROWSER_VIEWPORT_WIDTH"
    BROWSER_VIEWPORT_HEIGHT = "BROWSER_VIEWPORT_HEIGHT"

    # Global pointer to the active LLM profile (the profiles of the usage page).
    # It is not a model value; the LLM soft-delete purge must leave it alone.
    LLM_PROFILE_ID = "llm_profile_id"

    # Configurable Markdown system prompts and prompt additions.
    AI_TASK_OBJECTIVE_SYSTEM_PROMPT = "ai.task-objective-system-prompt"
    AI_PLANNER_SYSTEM_PROMPT = "ai.planner-system-prompt"
    AI_BRIEFING_SYSTEM_PROMPT = "ai.briefing-system-prompt"
    AI_EXECUTOR_SYSTEM_PROMPT = "ai.executor-system-prompt"
    AI_CONVERSATION_EXECUTOR_SYSTEM_PROMPT = "ai.conversation-executor-system-prompt"
    AI_VOICE_EXECUTOR_SYSTEM_PROMPT = "ai.voice-executor-system-prompt"
    AI_CONVERSATION_ACTION_POLICY = "ai.conversation-action-policy"
    AI_TOPIC_CLASSIFICATION_SYSTEM_PROMPT = "ai.topic-classification-system-prompt"
    AI_TOPIC_CONTINUITY_SYSTEM_PROMPT = "ai.topic-continuity-system-prompt"
    AI_TOPIC_RESOLUTION_SYSTEM_PROMPT = "ai.topic-resolution-system-prompt"
    AI_MEMORY_EXTRACTION_SYSTEM_PROMPT = "ai.memory-extraction-system-prompt"
    AUDIO_SUMMARY_MEETING_SEGMENT_SYSTEM_PROMPT = (
        "audio.summary-meeting-segment-system-prompt"
    )
    AUDIO_SUMMARY_MEETING_REDUCE_SYSTEM_PROMPT = (
        "audio.summary-meeting-reduce-system-prompt"
    )
    AUDIO_SUMMARY_MEETING_FINAL_SYSTEM_PROMPT = (
        "audio.summary-meeting-final-system-prompt"
    )
    AUDIO_SUMMARY_VIDEO_SEGMENT_SYSTEM_PROMPT = (
        "audio.summary-video-segment-system-prompt"
    )
    AUDIO_SUMMARY_VIDEO_REDUCE_SYSTEM_PROMPT = (
        "audio.summary-video-reduce-system-prompt"
    )
    AUDIO_SUMMARY_VIDEO_FINAL_SYSTEM_PROMPT = (
        "audio.summary-video-final-system-prompt"
    )

    # Hermes defaults for new agents.
    HERMES_DEFAULT_CONFIG  = "hermes.default.config"
    HARNESS_DEFAULT_COMPOSE = "harness.default.compose"
    # Global data/.env keys injected into every Hermes agent. This JSON dictionary
    # is encrypted at rest because it may contain shared secrets.
    HERMES_DEFAULT_DATA_ENV = "hermes.default.data-env"

    # Janus OpenAI-compatible routing agent.
    JANUS_ALIASES = "janus.aliases"

    # Semantic AI-to-AI termination gate. The dispatcher's hard-coded
    # AI_BURST_WINDOW_SECONDS / AI_BURST_MAX provide the temporal safeguard.
    MESSENGER_AI_GATE = "messenger.ai-contribution-gate"

    # Global Goal runner pause and common weekly availability window.
    GOAL_RUNTIME_SETTINGS = "goal.runtime.settings"

    # Language and regional context used outside an explicit user context.
    DEFAULT_LANGUAGE = "DEFAULT_LANGUAGE"
    LOCALIZATION = "LOCALIZATION"

    # Messaging provider and bridge-wide configuration. Per-agent credentials
    # remain connection parameters in app.tools.
    MESSENGER_DRIVER = "MESSENGER_DRIVER"
    MESSENGER_ENABLED_CHANNELS = "MESSENGER_ENABLED_CHANNELS"
    MESSENGER_NEXTCLOUD_TALK_BASE_URL = "MESSENGER_NEXTCLOUD_TALK_BASE_URL"
    MESSENGER_NEXTCLOUD_TALK_INBOUND = "MESSENGER_NEXTCLOUD_TALK_INBOUND"
    MESSENGER_NEXTCLOUD_TALK_HPB_URL = "MESSENGER_NEXTCLOUD_TALK_HPB_URL"
    MESSENGER_NEXTCLOUD_TALK_ROOM_DISCOVERY_INTERVAL = (
        "MESSENGER_NEXTCLOUD_TALK_ROOM_DISCOVERY_INTERVAL"
    )
    MESSENGER_NEXTCLOUD_TALK_LONGPOLL_TIMEOUT = (
        "MESSENGER_NEXTCLOUD_TALK_LONGPOLL_TIMEOUT"
    )
    MESSENGER_ONE_BOT_PLATFORM = "MESSENGER_ONE_BOT_PLATFORM"
    MESSENGER_ONE_BOT_SECRET_KEY = "MESSENGER_ONE_BOT_SECRET_KEY"
    MESSENGER_MATRIX_HOMESERVER = "MESSENGER_MATRIX_HOMESERVER"
    MESSENGER_MATRIX_SYNC_TIMEOUT_MS = "MESSENGER_MATRIX_SYNC_TIMEOUT_MS"
    MESSENGER_TELEGRAM_POLL_TIMEOUT_S = "MESSENGER_TELEGRAM_POLL_TIMEOUT_S"
    MESSENGER_TELEGRAM_UPDATE_MAX_AGE_SECONDS = (
        "MESSENGER_TELEGRAM_UPDATE_MAX_AGE_SECONDS"
    )
    MESSENGER_WHATSAPP_GRAPH_URL = "MESSENGER_WHATSAPP_GRAPH_URL"
    MESSENGER_WHATSAPP_GRAPH_VERSION = "MESSENGER_WHATSAPP_GRAPH_VERSION"
    MESSENGER_WHATSAPP_APP_SECRET = "MESSENGER_WHATSAPP_APP_SECRET"
    MESSENGER_WHATSAPP_VERIFY_TOKEN = "MESSENGER_WHATSAPP_VERIFY_TOKEN"
    MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES = "MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES"
    MESSENGER_WHATSAPP_HTTP_TIMEOUT_S = "MESSENGER_WHATSAPP_HTTP_TIMEOUT_S"
    MESSENGER_CONTENT_MAX_MB = "MESSENGER_CONTENT_MAX_MB"
    MESSENGER_VOICE_MAX_DURATION_MINUTES = "MESSENGER_VOICE_MAX_DURATION_MINUTES"
    MESSENGER_SESSION_MAX_MESSAGES = "MESSENGER_SESSION_MAX_MESSAGES"
    MESSENGER_SESSION_MAX_CHARS = "MESSENGER_SESSION_MAX_CHARS"

    # Governed long-term memory and asynchronous capture.
    MEMORY_CONTEXT_ENABLED = "MEMORY_CONTEXT_ENABLED"
    MEMORY_CONTEXT_MAX_ITEMS = "MEMORY_CONTEXT_MAX_ITEMS"
    MEMORY_CONTEXT_MAX_CHARS = "MEMORY_CONTEXT_MAX_CHARS"
    MEMORY_RECALL_CANDIDATE_LIMIT = "MEMORY_RECALL_CANDIDATE_LIMIT"
    MEMORY_RECALL_SEMANTIC_QUERY_MAX_CHARS = (
        "MEMORY_RECALL_SEMANTIC_QUERY_MAX_CHARS"
    )
    MEMORY_RECALL_SEMANTIC_WEIGHT = "MEMORY_RECALL_SEMANTIC_WEIGHT"
    MEMORY_RECALL_LEXICAL_WEIGHT = "MEMORY_RECALL_LEXICAL_WEIGHT"
    MEMORY_RECALL_TOPIC_WEIGHT = "MEMORY_RECALL_TOPIC_WEIGHT"
    MEMORY_RECALL_GRAPH_WEIGHT = "MEMORY_RECALL_GRAPH_WEIGHT"
    MEMORY_RECALL_SUGGESTED_LINK_WEIGHT = (
        "MEMORY_RECALL_SUGGESTED_LINK_WEIGHT"
    )
    MEMORY_RECALL_AUTHORITY_WEIGHT = "MEMORY_RECALL_AUTHORITY_WEIGHT"
    MEMORY_RECALL_FRESHNESS_WEIGHT = "MEMORY_RECALL_FRESHNESS_WEIGHT"
    MEMORY_RECALL_CENTRALITY_WEIGHT = "MEMORY_RECALL_CENTRALITY_WEIGHT"
    MEMORY_RECALL_DIVERSITY_LAMBDA = "MEMORY_RECALL_DIVERSITY_LAMBDA"
    MEMORY_FORGET_AFTER_DAYS = "MEMORY_FORGET_AFTER_DAYS"
    MEMORY_CAPTURE_ENABLED = "MEMORY_CAPTURE_ENABLED"
    MEMORY_CAPTURE_MIN_CHARS = "MEMORY_CAPTURE_MIN_CHARS"
    MEMORY_AUTOMATION_POLL_SECONDS = "MEMORY_AUTOMATION_POLL_SECONDS"
    MEMORY_AUTOMATION_MAX_ATTEMPTS = "MEMORY_AUTOMATION_MAX_ATTEMPTS"
    MEMORY_DUPLICATE_MODE = "MEMORY_DUPLICATE_MODE"
    MEMORY_DUPLICATE_SIMILARITY_THRESHOLD = "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD"
    MEMORY_CONTRADICTION_MODE = "MEMORY_CONTRADICTION_MODE"
    MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD = (
        "MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD"
    )
    MEMORY_AGING_MODE = "MEMORY_AGING_MODE"
    MEMORY_AGING_AFTER_DAYS = "MEMORY_AGING_AFTER_DAYS"
    MEMORY_LINK_RECONCILIATION_TRIGGER_MODE = (
        "MEMORY_LINK_RECONCILIATION_TRIGGER_MODE"
    )
    MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS = (
        "MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS"
    )

    # Opportunistic, preemptible background maintenance.
    DREAM_ENABLED = "DREAM_ENABLED"
    DREAM_ATTACHMENT_TEXT_ENABLED = "DREAM_ATTACHMENT_TEXT_ENABLED"
    DREAM_ATTACHMENT_DOCUMENT_ENABLED = "DREAM_ATTACHMENT_DOCUMENT_ENABLED"
    DREAM_ATTACHMENT_IMAGE_ENABLED = "DREAM_ATTACHMENT_IMAGE_ENABLED"
    DREAM_ATTACHMENT_VIDEO_ENABLED = "DREAM_ATTACHMENT_VIDEO_ENABLED"
    DREAM_TOPIC_CREATION_MODE = "DREAM_TOPIC_CREATION_MODE"
    DREAM_SKILL_LEARNING_MODE = "DREAM_SKILL_LEARNING_MODE"
    DREAM_SKILL_MIN_EVIDENCE = "DREAM_SKILL_MIN_EVIDENCE"
    DREAM_SKILL_ACTIVATION_SCORE = "DREAM_SKILL_ACTIVATION_SCORE"
    DREAM_SKILL_MAX_ACTIVE = "DREAM_SKILL_MAX_ACTIVE"
    DREAM_EXPERIENCE_MODE = "DREAM_EXPERIENCE_MODE"
    DREAM_EXPERIENCE_MAX_ITEMS = "DREAM_EXPERIENCE_MAX_ITEMS"
    DREAM_EXPERIENCE_MAX_CHARS = "DREAM_EXPERIENCE_MAX_CHARS"
    DREAM_POLL_SECONDS = "DREAM_POLL_SECONDS"
    DREAM_LEASE_SECONDS = "DREAM_LEASE_SECONDS"
    DREAM_CLAIM_TIMEOUT_SECONDS = "DREAM_CLAIM_TIMEOUT_SECONDS"
    DREAM_MAX_ATTEMPTS = "DREAM_MAX_ATTEMPTS"

    # General real-time voice configuration. Provider-specific voice settings
    # live with their messaging bridge above.
    VOICE_ENABLED = "VOICE_ENABLED"
    VOICE_SAMPLE_RATE = "VOICE_SAMPLE_RATE"
    VOICE_CHANNELS = "VOICE_CHANNELS"
    VOICE_AUTO_ANSWER_ENABLED = "VOICE_AUTO_ANSWER_ENABLED"
    VOICE_AUTO_ANSWER_POLL_INTERVAL = "VOICE_AUTO_ANSWER_POLL_INTERVAL"
    VOICE_AUTO_ANSWER_DISCOVERY_INTERVAL = "VOICE_AUTO_ANSWER_DISCOVERY_INTERVAL"

    # Durable task scheduler, retry, planning, budget, and collaboration limits.
    TASK_SCHEDULER_MAX_CONCURRENCY = "TASK_SCHEDULER_MAX_CONCURRENCY"
    TASK_SCHEDULER_LEASE_SECONDS = "TASK_SCHEDULER_LEASE_SECONDS"
    TASK_ROOT_MAX_TOKENS = "TASK_ROOT_MAX_TOKENS"
    TASK_ROOT_MAX_COST = "TASK_ROOT_MAX_COST"
    TASK_ROOT_MAX_SECONDS = "TASK_ROOT_MAX_SECONDS"
    TASK_ROOT_RESERVE_TOKENS = "TASK_ROOT_RESERVE_TOKENS"
    TASK_ROOT_RESERVE_COST = "TASK_ROOT_RESERVE_COST"
    TASK_BUDGET_SHARE_GOAL = "TASK_BUDGET_SHARE_GOAL"
    TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER = "TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER"
    TASK_SCHEDULER_FAIRNESS_SECONDS = "TASK_SCHEDULER_FAIRNESS_SECONDS"
    INCIDENT_TRACE_RETENTION_DAYS = "INCIDENT_TRACE_RETENTION_DAYS"
    LLM_TRACE_RETENTION_DAYS = "LLM_TRACE_RETENTION_DAYS"
    TASK_ACTION_MAX_ATTEMPTS = "TASK_ACTION_MAX_ATTEMPTS"
    TASK_ACTION_RETRY_BASE_SECONDS = "TASK_ACTION_RETRY_BASE_SECONDS"
    TASK_NETWORK_MAX_ATTEMPTS = "TASK_NETWORK_MAX_ATTEMPTS"
    TASK_NETWORK_RETRY_BASE_SECONDS = "TASK_NETWORK_RETRY_BASE_SECONDS"
    TASK_NETWORK_RETRY_MAX_SECONDS = "TASK_NETWORK_RETRY_MAX_SECONDS"
    TASK_ACTION_TIMEOUT_SECONDS = "TASK_ACTION_TIMEOUT_SECONDS"
    TASK_TOOL_TIMEOUT_SECONDS = "TASK_TOOL_TIMEOUT_SECONDS"
    TASK_PLAN_MAX_DEPTH = "TASK_PLAN_MAX_DEPTH"
    TASK_PLAN_MAX_NODES = "TASK_PLAN_MAX_NODES"
    TASK_PLAN_MAX_LEAVES = "TASK_PLAN_MAX_LEAVES"
    TASK_AGENT_MAX_REQUESTS = "TASK_AGENT_MAX_REQUESTS"
    TASK_AGENT_MAX_TOOL_CALLS = "TASK_AGENT_MAX_TOOL_CALLS"
    TASK_ASK_AGENT_TIMEOUT_SECONDS = "TASK_ASK_AGENT_TIMEOUT_SECONDS"
    TASK_ASK_AGENT_MAX_ROUNDS = "TASK_ASK_AGENT_MAX_ROUNDS"

    # Business-process configuration.
    PROCESS_ENGINE_DEFAULT = "PROCESS_ENGINE_DEFAULT"
    PROCESS_FILE_REF_TTL_SECONDS = "PROCESS_FILE_REF_TTL_SECONDS"
    PROCESS_START_TIMEOUT_SECONDS = "PROCESS_START_TIMEOUT_SECONDS"
    PROCESS_REFRESH_TIMEOUT_SECONDS = "PROCESS_REFRESH_TIMEOUT_SECONDS"
    PROCESS_REFRESH_STALENESS_SECONDS = "PROCESS_REFRESH_STALENESS_SECONDS"
    PROCESS_WAIT_MAX_SECONDS = "PROCESS_WAIT_MAX_SECONDS"
    PROCESS_START_MAX_RETRIES = "PROCESS_START_MAX_RETRIES"
    PROCESS_START_RETRY_BACKOFF_SECONDS = "PROCESS_START_RETRY_BACKOFF_SECONDS"
    PROCESS_IDEMPOTENCY_WINDOW_SECONDS = "PROCESS_IDEMPOTENCY_WINDOW_SECONDS"
    PROCESS_REFRESH_MAX_FAILURES = "PROCESS_REFRESH_MAX_FAILURES"
    PROCESS_SANITIZE_MAX_BYTES = "PROCESS_SANITIZE_MAX_BYTES"
    PROCESS_RETENTION_RAW_SNAPSHOT_DAYS = "PROCESS_RETENTION_RAW_SNAPSHOT_DAYS"
    PROCESS_RETENTION_EVENTS_DAYS = "PROCESS_RETENTION_EVENTS_DAYS"
    PROCESS_RETENTION_OUTPUT_DAYS = "PROCESS_RETENTION_OUTPUT_DAYS"
    PROCESS_RETENTION_RUN_DAYS = "PROCESS_RETENTION_RUN_DAYS"
    PROCESS_N8N_BASE_URL = "PROCESS_N8N_BASE_URL"
    PROCESS_N8N_API_TOKEN = "PROCESS_N8N_API_TOKEN"
    PROCESS_N8N_WEBHOOK_BASE_URL = "PROCESS_N8N_WEBHOOK_BASE_URL"
    PROCESS_GALARIS_BASE_URL = "PROCESS_GALARIS_BASE_URL"
    PROCESS_N8N_WEBHOOK_AUTH_HEADER = "PROCESS_N8N_WEBHOOK_AUTH_HEADER"
    PROCESS_N8N_WEBHOOK_AUTH_TOKEN = "PROCESS_N8N_WEBHOOK_AUTH_TOKEN"
    PROCESS_N8N_CALLBACK_AUTH_HEADER = "PROCESS_N8N_CALLBACK_AUTH_HEADER"

    # Global availability of code-provided agent Harness bridges. Reusable
    # OpenAI Messages configurations are persisted by app.harnesses instead.
    HARNESS_CLAUDE_AGENT_ENABLED = "harness.claude-agent.enabled"
    HARNESS_CODEX_ENABLED = "harness.codex.enabled"
    HARNESS_DEEPSEEK_ENABLED = "harness.deepseek.enabled"
    HARNESS_HERMES_ENABLED = "harness.hermes.enabled"

    # Search client configuration. The SearXNG instance secret is generated in
    # its private config file and is not an application setting.
    SEARCH_DEFAULT_LANGUAGE = "SEARCH_DEFAULT_LANGUAGE"
    SEARCH_TIMEOUT = "SEARCH_TIMEOUT"


# Application defaults. Translatable system prompts use value=None and resolve
# their defaults through core.i18n.
DEFAULT_PARAMS: dict[str, ParamConfig] = {
    Params.ALLOW_USER_REGISTRATION: {"value": "false", "runtime_field": "ALLOW_USER_REGISTRATION", "kind": "boolean"},
    Params.MESSENGER_MAX_INLINE_MB: {"value": "3.814697265625", "runtime_field": "MESSENGER_MAX_INLINE_MB", "kind": "float"},
    Params.PYDANTIC_AI_BINARY_INPUT_MAX_BYTES: {"value": "20000000", "runtime_field": "PYDANTIC_AI_BINARY_INPUT_MAX_BYTES", "kind": "integer"},
    Params.LOGFIRE_TOKEN: {"value": "", "runtime_field": "LOGFIRE_TOKEN", "kind": "secret"},
    Params.HARNESS_MANAGER_URL: {"value": "http://host.docker.internal:8485", "runtime_field": "HARNESS_MANAGER_URL", "kind": "string"},
    Params.HARNESS_MANAGER_GALARIS_API_URL: {"value": "", "runtime_field": "HARNESS_MANAGER_GALARIS_API_URL", "kind": "string"},
    Params.HARNESS_MANAGER_SECRET: {"value": "", "runtime_field": "HARNESS_MANAGER_SECRET", "kind": "secret"},
    Params.AUTH_SECRET_KEY: {"value": None, "kind": "secret"},
    Params.WEB_PUSH_VAPID_KEYS: {"value": None, "kind": "secret"},
    Params.WEB_PUSH_VAPID_SUBJECT: {"value": "mailto:admin@localhost", "runtime_field": "WEB_PUSH_VAPID_SUBJECT", "kind": "string"},
    Params.WEB_PUSH_DELAY_SECONDS: {"value": "3", "runtime_field": "WEB_PUSH_DELAY_SECONDS", "kind": "float"},
    Params.HTTP_RATE_LIMIT_PER_MINUTE: {
        "value": "1000", "runtime_field": "HTTP_RATE_LIMIT_PER_MINUTE", "kind": "integer"
    },
    Params.GALARIS_INTERNAL_MESSENGER_MAX_BYTES: {
        "value": "10000000000", "runtime_field": "GALARIS_INTERNAL_MESSENGER_MAX_BYTES", "kind": "integer"
    },
    Params.MEMORY_RESOURCE_MAX_BYTES: {
        "value": "100000000", "runtime_field": "MEMORY_RESOURCE_MAX_BYTES", "kind": "integer"
    },
    Params.BROWSER_EXECUTOR_TIMEOUT_SECONDS: {
        "value": "45", "runtime_field": "BROWSER_EXECUTOR_TIMEOUT_SECONDS", "kind": "float"
    },
    Params.BROWSER_SESSION_TTL_SECONDS: {
        "value": "120", "runtime_field": "BROWSER_SESSION_TTL_SECONDS", "kind": "integer"
    },
    Params.BROWSER_MAX_SESSIONS: {
        "value": "32", "runtime_field": "BROWSER_MAX_SESSIONS", "kind": "integer"
    },
    Params.BROWSER_CONTENT_MAX_CHARS: {
        "value": "20000", "runtime_field": "BROWSER_CONTENT_MAX_CHARS", "kind": "integer"
    },
    Params.BROWSER_HTML_MAX_BYTES: {
        "value": "500000", "runtime_field": "BROWSER_HTML_MAX_BYTES", "kind": "integer"
    },
    Params.BROWSER_SCREENSHOT_TILE_HEIGHT: {
        "value": "3000", "runtime_field": "BROWSER_SCREENSHOT_TILE_HEIGHT", "kind": "integer"
    },
    Params.BROWSER_SCREENSHOT_MAX_TILES: {
        "value": "8", "runtime_field": "BROWSER_SCREENSHOT_MAX_TILES", "kind": "integer"
    },
    Params.BROWSER_SCREENSHOT_MAX_TOTAL_BYTES: {
        "value": "25000000", "runtime_field": "BROWSER_SCREENSHOT_MAX_TOTAL_BYTES", "kind": "integer"
    },
    Params.BROWSER_VIEWPORT_WIDTH: {
        "value": "1440", "runtime_field": "BROWSER_VIEWPORT_WIDTH", "kind": "integer"
    },
    Params.BROWSER_VIEWPORT_HEIGHT: {
        "value": "900", "runtime_field": "BROWSER_VIEWPORT_HEIGHT", "kind": "integer"
    },
    # Set by the profile service once the default profile exists.
    Params.LLM_PROFILE_ID: {"value": None},

    # Prompt defaults. Canonical English values are independent from UI language.
    Params.AI_TASK_OBJECTIVE_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AI_PLANNER_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AI_BRIEFING_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },

    # Prompt additions. Empty means no instance-specific instructions.
    Params.AI_EXECUTOR_SYSTEM_PROMPT: {
        "value": None, "kind": "prompt", "display_default": True,
        "empty_uses_default": True,
    },
    Params.AI_CONVERSATION_EXECUTOR_SYSTEM_PROMPT: {
        "value": None, "kind": "prompt", "display_default": True,
        "empty_uses_default": True,
    },
    Params.AI_VOICE_EXECUTOR_SYSTEM_PROMPT: {
        "value": None, "kind": "prompt", "display_default": True,
        "empty_uses_default": True,
    },
    Params.AI_CONVERSATION_ACTION_POLICY: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AI_TOPIC_CLASSIFICATION_SYSTEM_PROMPT: {
        "value": None, "kind": "prompt", "display_default": True,
        "empty_uses_default": True,
    },
    Params.AI_TOPIC_CONTINUITY_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AI_TOPIC_RESOLUTION_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AI_MEMORY_EXTRACTION_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AUDIO_SUMMARY_MEETING_SEGMENT_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AUDIO_SUMMARY_MEETING_REDUCE_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AUDIO_SUMMARY_MEETING_FINAL_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AUDIO_SUMMARY_VIDEO_SEGMENT_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AUDIO_SUMMARY_VIDEO_REDUCE_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },
    Params.AUDIO_SUMMARY_VIDEO_FINAL_SYSTEM_PROMPT: {
        "value": None,
        "kind": "prompt",
        "display_default": True,
        "empty_uses_default": True,
    },

    # Hermes defaults for new agents.
    Params.HERMES_DEFAULT_CONFIG: {"value": None},
    Params.HARNESS_DEFAULT_COMPOSE: {"value": None},
    Params.HERMES_DEFAULT_DATA_ENV: {"value": None},

    Params.JANUS_ALIASES: {"value": ""},

    Params.MESSENGER_AI_GATE: {"value": "on"},

    Params.GOAL_RUNTIME_SETTINGS: {
        "value": (
            '{"globally_paused":false,"schedule_enabled":false,"schedule":[]}'
        )
    },

    Params.DEFAULT_LANGUAGE: {
        "value": "",
        "runtime_field": "DEFAULT_LANGUAGE",
        "kind": "choice",
        "choices": ("", "en", "fr", "zh"),
    },
    Params.LOCALIZATION: {
        "value": "",
        "runtime_field": "LOCALIZATION",
        "kind": "string",
    },

    Params.MESSENGER_DRIVER: {
        "value": "nextcloud_talk",
        "runtime_field": "MESSENGER_DRIVER",
        "kind": "choice",
        "choices": ("nextcloud_talk", "matrix", "one_bot", "telegram", "whatsapp"),
    },
    Params.MESSENGER_ENABLED_CHANNELS: {
        "value": '["internal","nextcloud_talk","telegram","matrix","whatsapp","one_bot"]',
        "runtime_field": "MESSENGER_ENABLED_CHANNELS",
    },
    Params.MESSENGER_NEXTCLOUD_TALK_BASE_URL: {
        "value": "", "runtime_field": "MESSENGER_NEXTCLOUD_TALK_BASE_URL", "kind": "string"
    },
    Params.MESSENGER_NEXTCLOUD_TALK_INBOUND: {
        "value": "polling",
        "runtime_field": "MESSENGER_NEXTCLOUD_TALK_INBOUND",
        "kind": "choice",
        "choices": ("polling", "signaling"),
    },
    Params.MESSENGER_NEXTCLOUD_TALK_HPB_URL: {
        "value": "", "runtime_field": "MESSENGER_NEXTCLOUD_TALK_HPB_URL", "kind": "string"
    },
    Params.MESSENGER_NEXTCLOUD_TALK_ROOM_DISCOVERY_INTERVAL: {
        "value": "30", "runtime_field": "MESSENGER_NEXTCLOUD_TALK_ROOM_DISCOVERY_INTERVAL", "kind": "float"
    },
    Params.MESSENGER_NEXTCLOUD_TALK_LONGPOLL_TIMEOUT: {
        "value": "30", "runtime_field": "MESSENGER_NEXTCLOUD_TALK_LONGPOLL_TIMEOUT", "kind": "integer"
    },
    Params.MESSENGER_ONE_BOT_PLATFORM: {
        "value": "", "runtime_field": "MESSENGER_ONE_BOT_PLATFORM", "kind": "string"
    },
    Params.MESSENGER_ONE_BOT_SECRET_KEY: {
        "value": "", "runtime_field": "MESSENGER_ONE_BOT_SECRET_KEY", "kind": "secret"
    },
    Params.MESSENGER_MATRIX_HOMESERVER: {
        "value": "", "runtime_field": "MESSENGER_MATRIX_HOMESERVER", "kind": "string"
    },
    Params.MESSENGER_MATRIX_SYNC_TIMEOUT_MS: {
        "value": "30000", "runtime_field": "MESSENGER_MATRIX_SYNC_TIMEOUT_MS", "kind": "integer"
    },
    Params.MESSENGER_TELEGRAM_POLL_TIMEOUT_S: {
        "value": "30", "runtime_field": "MESSENGER_TELEGRAM_POLL_TIMEOUT_S", "kind": "integer"
    },
    Params.MESSENGER_TELEGRAM_UPDATE_MAX_AGE_SECONDS: {
        "value": "300", "runtime_field": "MESSENGER_TELEGRAM_UPDATE_MAX_AGE_SECONDS", "kind": "integer"
    },
    Params.MESSENGER_WHATSAPP_GRAPH_URL: {
        "value": "https://graph.facebook.com", "runtime_field": "MESSENGER_WHATSAPP_GRAPH_URL", "kind": "string"
    },
    Params.MESSENGER_WHATSAPP_GRAPH_VERSION: {
        "value": "v23.0", "runtime_field": "MESSENGER_WHATSAPP_GRAPH_VERSION", "kind": "string"
    },
    Params.MESSENGER_WHATSAPP_APP_SECRET: {
        "value": "", "runtime_field": "MESSENGER_WHATSAPP_APP_SECRET", "kind": "secret"
    },
    Params.MESSENGER_WHATSAPP_VERIFY_TOKEN: {
        "value": "", "runtime_field": "MESSENGER_WHATSAPP_VERIFY_TOKEN", "kind": "secret"
    },
    Params.MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES: {
        "value": "1000000", "runtime_field": "MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES", "kind": "integer"
    },
    Params.MESSENGER_WHATSAPP_HTTP_TIMEOUT_S: {
        "value": "30", "runtime_field": "MESSENGER_WHATSAPP_HTTP_TIMEOUT_S", "kind": "float"
    },
    Params.MESSENGER_CONTENT_MAX_MB: {
        "value": "1000", "runtime_field": "MESSENGER_CONTENT_MAX_MB", "kind": "integer"
    },
    Params.MESSENGER_VOICE_MAX_DURATION_MINUTES: {
        "value": "15", "runtime_field": "MESSENGER_VOICE_MAX_DURATION_MINUTES", "kind": "integer"
    },
    Params.MESSENGER_SESSION_MAX_MESSAGES: {
        "value": "40", "runtime_field": "MESSENGER_SESSION_MAX_MESSAGES", "kind": "integer"
    },
    Params.MESSENGER_SESSION_MAX_CHARS: {
        "value": "20000", "runtime_field": "MESSENGER_SESSION_MAX_CHARS", "kind": "integer"
    },

    Params.MEMORY_CONTEXT_ENABLED: {
        "value": "true", "runtime_field": "MEMORY_CONTEXT_ENABLED", "kind": "boolean"
    },
    Params.MEMORY_CONTEXT_MAX_ITEMS: {
        "value": "8", "runtime_field": "MEMORY_CONTEXT_MAX_ITEMS", "kind": "integer"
    },
    Params.MEMORY_CONTEXT_MAX_CHARS: {
        "value": "12000", "runtime_field": "MEMORY_CONTEXT_MAX_CHARS", "kind": "integer"
    },
    Params.MEMORY_RECALL_CANDIDATE_LIMIT: {
        "value": "48", "runtime_field": "MEMORY_RECALL_CANDIDATE_LIMIT", "kind": "integer"
    },
    Params.MEMORY_RECALL_SEMANTIC_QUERY_MAX_CHARS: {
        "value": "1500", "runtime_field": "MEMORY_RECALL_SEMANTIC_QUERY_MAX_CHARS", "kind": "integer"
    },
    Params.MEMORY_RECALL_SEMANTIC_WEIGHT: {
        "value": "0.45", "runtime_field": "MEMORY_RECALL_SEMANTIC_WEIGHT", "kind": "float"
    },
    Params.MEMORY_RECALL_LEXICAL_WEIGHT: {
        "value": "0.20", "runtime_field": "MEMORY_RECALL_LEXICAL_WEIGHT", "kind": "float"
    },
    Params.MEMORY_RECALL_TOPIC_WEIGHT: {
        "value": "0.35", "runtime_field": "MEMORY_RECALL_TOPIC_WEIGHT", "kind": "float"
    },
    Params.MEMORY_RECALL_GRAPH_WEIGHT: {
        "value": "0.15", "runtime_field": "MEMORY_RECALL_GRAPH_WEIGHT", "kind": "float"
    },
    Params.MEMORY_RECALL_SUGGESTED_LINK_WEIGHT: {
        "value": "0.25",
        "runtime_field": "MEMORY_RECALL_SUGGESTED_LINK_WEIGHT",
        "kind": "float",
    },
    Params.MEMORY_RECALL_AUTHORITY_WEIGHT: {
        "value": "0.08", "runtime_field": "MEMORY_RECALL_AUTHORITY_WEIGHT", "kind": "float"
    },
    Params.MEMORY_RECALL_FRESHNESS_WEIGHT: {
        "value": "0.05", "runtime_field": "MEMORY_RECALL_FRESHNESS_WEIGHT", "kind": "float"
    },
    Params.MEMORY_RECALL_CENTRALITY_WEIGHT: {
        "value": "0.07", "runtime_field": "MEMORY_RECALL_CENTRALITY_WEIGHT", "kind": "float"
    },
    Params.MEMORY_RECALL_DIVERSITY_LAMBDA: {
        "value": "0.20", "runtime_field": "MEMORY_RECALL_DIVERSITY_LAMBDA", "kind": "float"
    },
    Params.MEMORY_FORGET_AFTER_DAYS: {
        "value": "0", "runtime_field": "MEMORY_FORGET_AFTER_DAYS", "kind": "integer"
    },
    Params.MEMORY_CAPTURE_ENABLED: {
        "value": "true", "runtime_field": "MEMORY_CAPTURE_ENABLED", "kind": "boolean"
    },
    Params.MEMORY_CAPTURE_MIN_CHARS: {
        "value": "120", "runtime_field": "MEMORY_CAPTURE_MIN_CHARS", "kind": "integer"
    },
    Params.MEMORY_AUTOMATION_POLL_SECONDS: {
        "value": "5", "runtime_field": "MEMORY_AUTOMATION_POLL_SECONDS", "kind": "float"
    },
    Params.MEMORY_AUTOMATION_MAX_ATTEMPTS: {
        "value": "5", "runtime_field": "MEMORY_AUTOMATION_MAX_ATTEMPTS", "kind": "integer"
    },
    Params.MEMORY_DUPLICATE_MODE: {
        "value": "manual", "runtime_field": "MEMORY_DUPLICATE_MODE", "kind": "choice",
        "choices": ("off", "manual", "automatic"),
    },
    Params.MEMORY_DUPLICATE_SIMILARITY_THRESHOLD: {
        "value": "0.92", "runtime_field": "MEMORY_DUPLICATE_SIMILARITY_THRESHOLD", "kind": "float"
    },
    Params.MEMORY_CONTRADICTION_MODE: {
        "value": "manual", "runtime_field": "MEMORY_CONTRADICTION_MODE", "kind": "choice",
        "choices": ("off", "manual", "automatic"),
    },
    Params.MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD: {
        "value": "0.86", "runtime_field": "MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD", "kind": "float"
    },
    Params.MEMORY_AGING_MODE: {
        "value": "manual", "runtime_field": "MEMORY_AGING_MODE", "kind": "choice",
        "choices": ("off", "manual", "automatic"),
    },
    Params.MEMORY_AGING_AFTER_DAYS: {
        "value": "365", "runtime_field": "MEMORY_AGING_AFTER_DAYS", "kind": "integer"
    },
    Params.MEMORY_LINK_RECONCILIATION_TRIGGER_MODE: {
        "value": "after_dream_and_scheduled",
        "runtime_field": "MEMORY_LINK_RECONCILIATION_TRIGGER_MODE",
        "kind": "choice",
        "choices": (
            "manual_only",
            "after_dream",
            "scheduled",
            "after_dream_and_scheduled",
        ),
    },
    Params.MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS: {
        "value": "24",
        "runtime_field": "MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS",
        "kind": "integer",
    },

    Params.DREAM_ENABLED: {
        "value": "true", "runtime_field": "DREAM_ENABLED", "kind": "boolean"
    },
    Params.DREAM_ATTACHMENT_TEXT_ENABLED: {
        "value": "false", "runtime_field": "DREAM_ATTACHMENT_TEXT_ENABLED", "kind": "boolean"
    },
    Params.DREAM_ATTACHMENT_DOCUMENT_ENABLED: {
        "value": "false", "runtime_field": "DREAM_ATTACHMENT_DOCUMENT_ENABLED", "kind": "boolean"
    },
    Params.DREAM_ATTACHMENT_IMAGE_ENABLED: {
        "value": "false", "runtime_field": "DREAM_ATTACHMENT_IMAGE_ENABLED", "kind": "boolean"
    },
    Params.DREAM_ATTACHMENT_VIDEO_ENABLED: {
        "value": "false", "runtime_field": "DREAM_ATTACHMENT_VIDEO_ENABLED", "kind": "boolean"
    },
    Params.DREAM_TOPIC_CREATION_MODE: {
        "value": "propose",
        "runtime_field": "DREAM_TOPIC_CREATION_MODE",
        "kind": "choice",
        "choices": ("forbid", "propose", "auto"),
    },
    Params.DREAM_SKILL_LEARNING_MODE: {
        "value": "off",
        "runtime_field": "DREAM_SKILL_LEARNING_MODE",
        "kind": "choice",
        "choices": ("off", "observe", "learn"),
    },
    Params.DREAM_SKILL_MIN_EVIDENCE: {
        "value": "3", "runtime_field": "DREAM_SKILL_MIN_EVIDENCE", "kind": "integer"
    },
    Params.DREAM_SKILL_ACTIVATION_SCORE: {
        "value": "0.75", "runtime_field": "DREAM_SKILL_ACTIVATION_SCORE", "kind": "float"
    },
    Params.DREAM_SKILL_MAX_ACTIVE: {
        "value": "20", "runtime_field": "DREAM_SKILL_MAX_ACTIVE", "kind": "integer"
    },
    Params.DREAM_EXPERIENCE_MODE: {
        "value": "off",
        "runtime_field": "DREAM_EXPERIENCE_MODE",
        "kind": "string",
        "choices": ("off", "observe", "learn", "active"),
    },
    Params.DREAM_EXPERIENCE_MAX_ITEMS: {
        "value": "2", "runtime_field": "DREAM_EXPERIENCE_MAX_ITEMS", "kind": "integer"
    },
    Params.DREAM_EXPERIENCE_MAX_CHARS: {
        "value": "4000", "runtime_field": "DREAM_EXPERIENCE_MAX_CHARS", "kind": "integer"
    },
    Params.DREAM_POLL_SECONDS: {
        "value": "60", "runtime_field": "DREAM_POLL_SECONDS", "kind": "float"
    },
    Params.DREAM_LEASE_SECONDS: {
        "value": "600", "runtime_field": "DREAM_LEASE_SECONDS", "kind": "integer"
    },
    Params.DREAM_CLAIM_TIMEOUT_SECONDS: {
        "value": "300", "runtime_field": "DREAM_CLAIM_TIMEOUT_SECONDS", "kind": "float"
    },
    Params.DREAM_MAX_ATTEMPTS: {
        "value": "5", "runtime_field": "DREAM_MAX_ATTEMPTS", "kind": "integer"
    },

    Params.VOICE_ENABLED: {
        "value": "true", "runtime_field": "VOICE_ENABLED", "kind": "boolean"
    },
    Params.VOICE_SAMPLE_RATE: {
        "value": "48000", "runtime_field": "VOICE_SAMPLE_RATE", "kind": "integer"
    },
    Params.VOICE_CHANNELS: {
        "value": "1", "runtime_field": "VOICE_CHANNELS", "kind": "integer"
    },
    Params.VOICE_AUTO_ANSWER_ENABLED: {
        "value": "true", "runtime_field": "VOICE_AUTO_ANSWER_ENABLED", "kind": "boolean"
    },
    Params.VOICE_AUTO_ANSWER_POLL_INTERVAL: {
        "value": "2", "runtime_field": "VOICE_AUTO_ANSWER_POLL_INTERVAL", "kind": "float"
    },
    Params.VOICE_AUTO_ANSWER_DISCOVERY_INTERVAL: {
        "value": "30", "runtime_field": "VOICE_AUTO_ANSWER_DISCOVERY_INTERVAL", "kind": "float"
    },

    Params.TASK_SCHEDULER_MAX_CONCURRENCY: {
        "value": "8", "runtime_field": "TASK_SCHEDULER_MAX_CONCURRENCY", "kind": "integer"
    },
    Params.TASK_SCHEDULER_LEASE_SECONDS: {
        "value": "120", "runtime_field": "TASK_SCHEDULER_LEASE_SECONDS", "kind": "integer"
    },
    Params.TASK_ROOT_MAX_TOKENS: {"value": "0", "runtime_field": "TASK_ROOT_MAX_TOKENS", "kind": "integer"},
    Params.TASK_ROOT_MAX_COST: {"value": "0", "runtime_field": "TASK_ROOT_MAX_COST", "kind": "float"},
    Params.TASK_ROOT_MAX_SECONDS: {"value": "0", "runtime_field": "TASK_ROOT_MAX_SECONDS", "kind": "integer"},
    Params.TASK_ROOT_RESERVE_TOKENS: {"value": "30000", "runtime_field": "TASK_ROOT_RESERVE_TOKENS", "kind": "integer"},
    Params.TASK_ROOT_RESERVE_COST: {"value": "1", "runtime_field": "TASK_ROOT_RESERVE_COST", "kind": "float"},
    Params.TASK_BUDGET_SHARE_GOAL: {"value": "false", "runtime_field": "TASK_BUDGET_SHARE_GOAL", "kind": "boolean"},
    Params.TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER: {"value": "0", "runtime_field": "TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER", "kind": "integer"},
    Params.TASK_SCHEDULER_FAIRNESS_SECONDS: {"value": "0", "runtime_field": "TASK_SCHEDULER_FAIRNESS_SECONDS", "kind": "integer"},
    Params.INCIDENT_TRACE_RETENTION_DAYS: {"value": "0", "runtime_field": "INCIDENT_TRACE_RETENTION_DAYS", "kind": "integer"},
    Params.LLM_TRACE_RETENTION_DAYS: {"value": "0", "runtime_field": "LLM_TRACE_RETENTION_DAYS", "kind": "integer"},
    Params.TASK_ACTION_MAX_ATTEMPTS: {
        "value": "3", "runtime_field": "TASK_ACTION_MAX_ATTEMPTS", "kind": "integer"
    },
    Params.TASK_ACTION_RETRY_BASE_SECONDS: {
        "value": "2", "runtime_field": "TASK_ACTION_RETRY_BASE_SECONDS", "kind": "float"
    },
    Params.TASK_NETWORK_MAX_ATTEMPTS: {
        "value": "8", "runtime_field": "TASK_NETWORK_MAX_ATTEMPTS", "kind": "integer"
    },
    Params.TASK_NETWORK_RETRY_BASE_SECONDS: {
        "value": "30", "runtime_field": "TASK_NETWORK_RETRY_BASE_SECONDS", "kind": "float"
    },
    Params.TASK_NETWORK_RETRY_MAX_SECONDS: {
        "value": "300", "runtime_field": "TASK_NETWORK_RETRY_MAX_SECONDS", "kind": "float"
    },
    Params.TASK_ACTION_TIMEOUT_SECONDS: {
        "value": "1800", "runtime_field": "TASK_ACTION_TIMEOUT_SECONDS", "kind": "integer"
    },
    Params.TASK_TOOL_TIMEOUT_SECONDS: {
        "value": "300", "runtime_field": "TASK_TOOL_TIMEOUT_SECONDS", "kind": "float"
    },
    Params.TASK_PLAN_MAX_DEPTH: {
        "value": "3", "runtime_field": "TASK_PLAN_MAX_DEPTH", "kind": "integer"
    },
    Params.TASK_PLAN_MAX_NODES: {
        "value": "24", "runtime_field": "TASK_PLAN_MAX_NODES", "kind": "integer"
    },
    Params.TASK_PLAN_MAX_LEAVES: {
        "value": "12", "runtime_field": "TASK_PLAN_MAX_LEAVES", "kind": "integer"
    },
    Params.TASK_AGENT_MAX_REQUESTS: {
        "value": "200", "runtime_field": "TASK_AGENT_MAX_REQUESTS", "kind": "integer"
    },
    Params.TASK_AGENT_MAX_TOOL_CALLS: {
        "value": "5000", "runtime_field": "TASK_AGENT_MAX_TOOL_CALLS", "kind": "integer"
    },
    Params.TASK_ASK_AGENT_TIMEOUT_SECONDS: {
        "value": "7200", "runtime_field": "TASK_ASK_AGENT_TIMEOUT_SECONDS", "kind": "integer"
    },
    Params.TASK_ASK_AGENT_MAX_ROUNDS: {
        "value": "5", "runtime_field": "TASK_ASK_AGENT_MAX_ROUNDS", "kind": "integer"
    },
    Params.PROCESS_ENGINE_DEFAULT: {
        "value": "n8n", "runtime_field": "PROCESS_ENGINE_DEFAULT", "kind": "choice", "choices": ("n8n",)
    },
    Params.PROCESS_FILE_REF_TTL_SECONDS: {
        "value": "3600", "runtime_field": "PROCESS_FILE_REF_TTL_SECONDS", "kind": "integer"
    },
    Params.PROCESS_START_TIMEOUT_SECONDS: {
        "value": "15", "runtime_field": "PROCESS_START_TIMEOUT_SECONDS", "kind": "float"
    },
    Params.PROCESS_REFRESH_TIMEOUT_SECONDS: {
        "value": "5", "runtime_field": "PROCESS_REFRESH_TIMEOUT_SECONDS", "kind": "float"
    },
    Params.PROCESS_REFRESH_STALENESS_SECONDS: {
        "value": "30", "runtime_field": "PROCESS_REFRESH_STALENESS_SECONDS", "kind": "integer"
    },
    Params.PROCESS_WAIT_MAX_SECONDS: {
        "value": "7200", "runtime_field": "PROCESS_WAIT_MAX_SECONDS", "kind": "integer"
    },
    Params.PROCESS_START_MAX_RETRIES: {
        "value": "5", "runtime_field": "PROCESS_START_MAX_RETRIES", "kind": "integer"
    },
    Params.PROCESS_START_RETRY_BACKOFF_SECONDS: {
        "value": "5", "runtime_field": "PROCESS_START_RETRY_BACKOFF_SECONDS", "kind": "float"
    },
    Params.PROCESS_IDEMPOTENCY_WINDOW_SECONDS: {
        "value": "300", "runtime_field": "PROCESS_IDEMPOTENCY_WINDOW_SECONDS", "kind": "integer"
    },
    Params.PROCESS_REFRESH_MAX_FAILURES: {
        "value": "10", "runtime_field": "PROCESS_REFRESH_MAX_FAILURES", "kind": "integer"
    },
    Params.PROCESS_SANITIZE_MAX_BYTES: {
        "value": "64000", "runtime_field": "PROCESS_SANITIZE_MAX_BYTES", "kind": "integer"
    },
    Params.PROCESS_RETENTION_RAW_SNAPSHOT_DAYS: {
        "value": "30", "runtime_field": "PROCESS_RETENTION_RAW_SNAPSHOT_DAYS", "kind": "integer"
    },
    Params.PROCESS_RETENTION_EVENTS_DAYS: {
        "value": "90", "runtime_field": "PROCESS_RETENTION_EVENTS_DAYS", "kind": "integer"
    },
    Params.PROCESS_RETENTION_OUTPUT_DAYS: {
        "value": "0", "runtime_field": "PROCESS_RETENTION_OUTPUT_DAYS", "kind": "integer"
    },
    Params.PROCESS_RETENTION_RUN_DAYS: {
        "value": "0", "runtime_field": "PROCESS_RETENTION_RUN_DAYS", "kind": "integer"
    },
    Params.PROCESS_N8N_BASE_URL: {
        "value": "", "runtime_field": "PROCESS_N8N_BASE_URL", "kind": "string"
    },
    Params.PROCESS_N8N_API_TOKEN: {
        "value": "", "runtime_field": "PROCESS_N8N_API_TOKEN", "kind": "secret"
    },
    Params.PROCESS_N8N_WEBHOOK_BASE_URL: {
        "value": "", "runtime_field": "PROCESS_N8N_WEBHOOK_BASE_URL", "kind": "string"
    },
    Params.PROCESS_GALARIS_BASE_URL: {
        "value": "", "runtime_field": "PROCESS_GALARIS_BASE_URL", "kind": "string"
    },
    Params.PROCESS_N8N_WEBHOOK_AUTH_HEADER: {
        "value": "X-Galaris-Webhook-Token", "runtime_field": "PROCESS_N8N_WEBHOOK_AUTH_HEADER", "kind": "string"
    },
    Params.PROCESS_N8N_WEBHOOK_AUTH_TOKEN: {
        "value": "", "runtime_field": "PROCESS_N8N_WEBHOOK_AUTH_TOKEN", "kind": "secret"
    },
    Params.PROCESS_N8N_CALLBACK_AUTH_HEADER: {
        "value": "X-Galaris-Callback-Token", "runtime_field": "PROCESS_N8N_CALLBACK_AUTH_HEADER", "kind": "string"
    },

    Params.HARNESS_CLAUDE_AGENT_ENABLED: {
        "value": "true", "runtime_field": "HARNESS_CLAUDE_AGENT_ENABLED", "kind": "boolean"
    },
    Params.HARNESS_CODEX_ENABLED: {
        "value": "true", "runtime_field": "HARNESS_CODEX_ENABLED", "kind": "boolean"
    },
    Params.HARNESS_DEEPSEEK_ENABLED: {
        "value": "true", "runtime_field": "HARNESS_DEEPSEEK_ENABLED", "kind": "boolean"
    },
    Params.HARNESS_HERMES_ENABLED: {
        "value": "true", "runtime_field": "HARNESS_HERMES_ENABLED", "kind": "boolean"
    },
    Params.SEARCH_DEFAULT_LANGUAGE: {
        "value": "en", "runtime_field": "SEARCH_DEFAULT_LANGUAGE", "kind": "string"
    },
    Params.SEARCH_TIMEOUT: {
        "value": "10", "runtime_field": "SEARCH_TIMEOUT", "kind": "integer"
    },
}


# Parameters encrypted at rest. The runtime cache retains plaintext for internal
# consumers; the administration API exposes only whether a secret is configured.
SECRET_PARAMS: set[str] = {
    Params.LOGFIRE_TOKEN,
    Params.HARNESS_MANAGER_SECRET,
    Params.AUTH_SECRET_KEY,
    Params.WEB_PUSH_VAPID_KEYS,
    Params.HERMES_DEFAULT_DATA_ENV,
    Params.MESSENGER_ONE_BOT_SECRET_KEY,
    Params.MESSENGER_WHATSAPP_APP_SECRET,
    Params.MESSENGER_WHATSAPP_VERIFY_TOKEN,
    Params.PROCESS_N8N_API_TOKEN,
    Params.PROCESS_N8N_WEBHOOK_AUTH_TOKEN,
}

# These parameters are software-owned and omitted entirely from administration.
INTERNAL_PARAMS: frozenset[str] = frozenset({Params.AUTH_SECRET_KEY, Params.WEB_PUSH_VAPID_KEYS})
