"""Typed in-memory view of runtime parameters stored in PostgreSQL.

This model deliberately inherits from :class:`pydantic.BaseModel`, not
``BaseSettings``: environment variables are not a configuration source for
these fields. ``params_service`` loads and updates the singleton from the
``params`` table before runtime services start.
"""

import json
from typing import Literal, cast
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from core.settings import settings as bootstrap_settings


SUPPORTED_MESSENGER_CHANNELS = (
    "internal",
    "nextcloud_talk",
    "telegram",
    "matrix",
    "whatsapp",
    "one_bot",
)


class RuntimeSettings(BaseModel):
    """Validated application settings whose durable source is ``params``."""

    model_config = ConfigDict(validate_assignment=True, hide_input_in_errors=True)

    LOGFIRE_TOKEN: str = Field(default="", repr=False)
    ALLOW_USER_REGISTRATION: bool = False

    @field_validator("LOGFIRE_TOKEN")
    @classmethod
    def validate_logfire_token(cls, value: str) -> str:
        value = value.strip()
        if any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError("The Logfire token must not contain whitespace or control characters")
        return value

    WEB_PUSH_VAPID_SUBJECT: str = "mailto:admin@localhost"
    WEB_PUSH_DELAY_SECONDS: float = Field(default=3.0, ge=1.0, le=30.0)

    @field_validator("WEB_PUSH_VAPID_SUBJECT")
    @classmethod
    def validate_web_push_subject(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if not any(char.isspace() or ord(char) < 32 for char in value):
            if parsed.scheme == "mailto" and "@" in parsed.path and not parsed.query and not parsed.fragment:
                local, _, domain = parsed.path.partition("@")
                if local and domain and "@" not in domain:
                    return value
            if parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password:
                return value
        raise ValueError("Use a mailto: contact address or an HTTPS contact URL")

    HARNESS_MANAGER_URL: str = "http://host.docker.internal:8485"
    HARNESS_MANAGER_GALARIS_API_URL: str = ""
    HARNESS_MANAGER_SECRET: str = Field(default="", repr=False)

    @property
    def HARNESS_API_URL(self) -> str:
        return self.HARNESS_MANAGER_GALARIS_API_URL or bootstrap_settings.APP_API_URL

    @field_validator("HARNESS_MANAGER_URL", "HARNESS_MANAGER_GALARIS_API_URL")
    @classmethod
    def validate_manager_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return value
        try:
            parsed = urlsplit(value)
            valid = (
                parsed.scheme in {"http", "https"} and parsed.hostname
                and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment
                and not any(char.isspace() or ord(char) < 32 for char in value)
            )
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("Use an HTTP(S) URL without credentials, query or fragment")
        return value

    @field_validator("HARNESS_MANAGER_SECRET")
    @classmethod
    def validate_manager_secret(cls, value: str) -> str:
        value = value.strip()
        if value:
            value = value.rstrip("=") + "=" * (-len(value.rstrip("=")) % 4)
            try:
                Fernet(value.encode("ascii"))
            except (ValueError, UnicodeError):
                raise ValueError("Use a valid Fernet key") from None
        return value

    HTTP_RATE_LIMIT_PER_MINUTE: int = Field(default=1_000, ge=1)
    # Keep the legacy binary storage unit; fractions allow whole decimal MB in the UI.
    MESSENGER_MAX_INLINE_MB: float = Field(default=4_000_000 / 1_048_576, ge=1_000_000 / 1_048_576, le=1_000, allow_inf_nan=False)
    PYDANTIC_AI_BINARY_INPUT_MAX_BYTES: int = Field(default=20_000_000, ge=1_024, le=1_000 * 1024 * 1024)
    GALARIS_INTERNAL_MESSENGER_MAX_BYTES: int = Field(
        default=10_000_000_000, ge=1_000_000
    )
    MEMORY_RESOURCE_MAX_BYTES: int = Field(default=100_000_000, ge=1_024)

    # Operation limits are snapshotted into each authenticated browser request.
    BROWSER_SESSION_TTL_SECONDS: int = Field(default=120, ge=10, le=3_600)
    BROWSER_MAX_SESSIONS: int = Field(default=32, ge=1, le=256)
    BROWSER_EXECUTOR_TIMEOUT_SECONDS: float = Field(default=45.0, ge=5.0, le=180.0)
    BROWSER_CONTENT_MAX_CHARS: int = Field(default=20_000, ge=1_000, le=200_000)
    BROWSER_HTML_MAX_BYTES: int = Field(default=500_000, ge=10_000, le=750_000)
    BROWSER_SCREENSHOT_TILE_HEIGHT: int = Field(default=3_000, ge=500, le=10_000)
    BROWSER_SCREENSHOT_MAX_TILES: int = Field(default=8, ge=1, le=30)
    BROWSER_SCREENSHOT_MAX_TOTAL_BYTES: int = Field(
        default=25_000_000, ge=1_000_000, le=100_000_000
    )
    BROWSER_VIEWPORT_WIDTH: int = Field(default=1_440, ge=320, le=3_840)
    BROWSER_VIEWPORT_HEIGHT: int = Field(default=900, ge=240, le=2_160)

    # Language used outside a user context and regional context given to agents.
    DEFAULT_LANGUAGE: Literal["", "en", "fr", "zh"] = ""
    LOCALIZATION: str = ""

    # Messaging and provider-wide bridge settings.
    MESSENGER_DRIVER: Literal[
        "nextcloud_talk", "matrix", "one_bot", "telegram", "whatsapp"
    ] = "nextcloud_talk"
    # Global bridge availability. Disabled channels keep their durable configuration but are
    # excluded from runtime discovery, routing, search, and agent-facing capabilities.
    MESSENGER_ENABLED_CHANNELS: str = (
        '["internal","nextcloud_talk","telegram","matrix","whatsapp","one_bot"]'
    )
    MESSENGER_NEXTCLOUD_TALK_BASE_URL: str = ""
    MESSENGER_NEXTCLOUD_TALK_INBOUND: Literal["polling", "signaling"] = "polling"
    MESSENGER_NEXTCLOUD_TALK_HPB_URL: str = ""
    MESSENGER_NEXTCLOUD_TALK_ROOM_DISCOVERY_INTERVAL: float = Field(
        default=30.0, ge=1.0
    )
    MESSENGER_NEXTCLOUD_TALK_LONGPOLL_TIMEOUT: int = Field(default=30, ge=1)
    MESSENGER_ONE_BOT_PLATFORM: str = ""
    MESSENGER_ONE_BOT_SECRET_KEY: str = ""
    MESSENGER_MATRIX_HOMESERVER: str = ""
    MESSENGER_MATRIX_SYNC_TIMEOUT_MS: int = Field(default=30_000, ge=0)
    MESSENGER_TELEGRAM_POLL_TIMEOUT_S: int = Field(default=30, ge=1, le=50)
    MESSENGER_TELEGRAM_UPDATE_MAX_AGE_SECONDS: int = Field(default=300, ge=0)
    MESSENGER_WHATSAPP_GRAPH_URL: str = "https://graph.facebook.com"
    MESSENGER_WHATSAPP_GRAPH_VERSION: str = Field(default="v23.0", min_length=2)
    MESSENGER_WHATSAPP_APP_SECRET: str = ""
    MESSENGER_WHATSAPP_VERIFY_TOKEN: str = ""
    MESSENGER_WHATSAPP_WEBHOOK_MAX_BYTES: int = Field(
        default=1_000_000, ge=1_024, le=10_485_760
    )
    MESSENGER_WHATSAPP_HTTP_TIMEOUT_S: float = Field(
        default=30.0, ge=1.0, le=120.0
    )
    MESSENGER_CONTENT_MAX_MB: int = Field(default=1_000, ge=1, le=1_000)
    MESSENGER_VOICE_MAX_DURATION_MINUTES: int = Field(default=15, ge=1, le=120)
    MESSENGER_SESSION_MAX_MESSAGES: int = Field(default=40, ge=1, le=500)
    MESSENGER_SESSION_MAX_CHARS: int = Field(default=20_000, ge=1_000, le=500_000)

    @property
    def messenger_content_max_bytes(self) -> int:
        """Return the administrator-facing decimal-megabyte limit in bytes."""

        return self.MESSENGER_CONTENT_MAX_MB * 1_000_000

    @property
    def messenger_voice_max_duration_seconds(self) -> int:
        """Return the administrator-facing minute limit in seconds."""

        return self.MESSENGER_VOICE_MAX_DURATION_MINUTES * 60

    # Governed long-term memory and post-task capture.
    MEMORY_CONTEXT_ENABLED: bool = True
    MEMORY_CONTEXT_MAX_ITEMS: int = Field(default=8, ge=1, le=50)
    MEMORY_CONTEXT_MAX_CHARS: int = Field(default=12_000, ge=1_000, le=200_000)
    MEMORY_RECALL_CANDIDATE_LIMIT: int = Field(default=48, ge=8, le=200)
    MEMORY_RECALL_SEMANTIC_QUERY_MAX_CHARS: int = Field(
        default=1_500, ge=240, le=4_000
    )
    MEMORY_RECALL_SEMANTIC_WEIGHT: float = Field(default=0.45, ge=0.0, le=1.0)
    MEMORY_RECALL_LEXICAL_WEIGHT: float = Field(default=0.20, ge=0.0, le=1.0)
    MEMORY_RECALL_TOPIC_WEIGHT: float = Field(default=0.35, ge=0.0, le=1.0)
    MEMORY_RECALL_GRAPH_WEIGHT: float = Field(default=0.15, ge=0.0, le=1.0)
    MEMORY_RECALL_SUGGESTED_LINK_WEIGHT: float = Field(
        default=0.25, ge=0.0, le=1.0
    )
    MEMORY_RECALL_AUTHORITY_WEIGHT: float = Field(default=0.08, ge=0.0, le=1.0)
    MEMORY_RECALL_FRESHNESS_WEIGHT: float = Field(default=0.05, ge=0.0, le=1.0)
    MEMORY_RECALL_CENTRALITY_WEIGHT: float = Field(default=0.07, ge=0.0, le=1.0)
    MEMORY_RECALL_DIVERSITY_LAMBDA: float = Field(default=0.20, ge=0.0, le=1.0)
    MEMORY_FORGET_AFTER_DAYS: int = Field(default=0, ge=0, le=36_500)
    MEMORY_CAPTURE_ENABLED: bool = True
    MEMORY_CAPTURE_MIN_CHARS: int = Field(default=120, ge=20, le=20_000)
    MEMORY_AUTOMATION_POLL_SECONDS: float = Field(default=5.0, ge=0.5, le=300.0)
    MEMORY_AUTOMATION_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=50)
    MEMORY_DUPLICATE_MODE: Literal["off", "manual", "automatic"] = "manual"
    MEMORY_DUPLICATE_SIMILARITY_THRESHOLD: float = Field(
        default=0.92, ge=0.8, le=1.0
    )
    MEMORY_CONTRADICTION_MODE: Literal["off", "manual", "automatic"] = "manual"
    MEMORY_CONTRADICTION_SIMILARITY_THRESHOLD: float = Field(
        default=0.86, ge=0.8, le=1.0
    )
    MEMORY_AGING_MODE: Literal["off", "manual", "automatic"] = "manual"
    MEMORY_AGING_AFTER_DAYS: int = Field(default=365, ge=1, le=36_500)
    MEMORY_LINK_RECONCILIATION_TRIGGER_MODE: Literal[
        "manual_only",
        "after_dream",
        "scheduled",
        "after_dream_and_scheduled",
    ] = "after_dream_and_scheduled"
    MEMORY_LINK_RECONCILIATION_INTERVAL_HOURS: int = Field(
        default=24,
        ge=1,
        le=720,
    )

    # Opportunistic background maintenance. Dream work is sequential and preemptible.
    # The poll delay starts after an operation ends; it is not a fixed-rate window.
    DREAM_ENABLED: bool = True
    DREAM_ATTACHMENT_TEXT_ENABLED: bool = False
    DREAM_ATTACHMENT_DOCUMENT_ENABLED: bool = False
    DREAM_ATTACHMENT_IMAGE_ENABLED: bool = False
    DREAM_ATTACHMENT_VIDEO_ENABLED: bool = False
    DREAM_TOPIC_CREATION_MODE: Literal["forbid", "propose", "auto"] = "propose"
    DREAM_SKILL_LEARNING_MODE: Literal["off", "observe", "learn"] = "off"
    DREAM_SKILL_MIN_EVIDENCE: int = Field(default=3, ge=2, le=100)
    DREAM_SKILL_ACTIVATION_SCORE: float = Field(default=0.75, ge=0.5, le=0.99)
    DREAM_SKILL_MAX_ACTIVE: int = Field(default=20, ge=1, le=100)
    # Compatibility only for historical Memory experience nodes. New outcome
    # learning is owned by app.skill and never creates Memory items.
    DREAM_EXPERIENCE_MODE: Literal["off", "observe", "learn", "active"] = "off"
    DREAM_EXPERIENCE_MAX_ITEMS: int = Field(default=2, ge=1, le=10)
    DREAM_EXPERIENCE_MAX_CHARS: int = Field(default=4_000, ge=500, le=50_000)
    DREAM_POLL_SECONDS: float = Field(default=60.0, ge=1.0, le=3_600.0)
    DREAM_LEASE_SECONDS: int = Field(default=600, ge=60, le=7_200)
    # Hard execution budget per claim phase (prepare, apply). A claim that
    # exceeds it is cancelled and marked failed instead of wedging the single
    # sequential worker on an unbounded await (DB lock, storage, messenger).
    # It is clamped below the lease so an expired lease cannot be stolen from
    # an actively running claim.
    DREAM_CLAIM_TIMEOUT_SECONDS: float = Field(default=300.0, ge=10.0, le=7_200.0)
    DREAM_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=50)

    # General real-time voice settings.
    VOICE_ENABLED: bool = True
    VOICE_SAMPLE_RATE: int = 48_000
    VOICE_CHANNELS: int = 1
    VOICE_AUTO_ANSWER_ENABLED: bool = True
    VOICE_AUTO_ANSWER_POLL_INTERVAL: float = Field(default=2.0, ge=0.5)
    VOICE_AUTO_ANSWER_DISCOVERY_INTERVAL: float = Field(default=30.0, ge=5.0)

    # Task scheduler, retry, planning, budget, and collaboration limits.
    TASK_SCHEDULER_MAX_CONCURRENCY: int = Field(default=8, ge=1, le=10)
    TASK_SCHEDULER_LEASE_SECONDS: int = Field(default=120, ge=30, le=3_600)
    # Opt-in admission limits shared by a root task and its causal descendants.
    TASK_ROOT_MAX_TOKENS: int = Field(default=0, ge=0)
    TASK_ROOT_MAX_COST: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    TASK_ROOT_MAX_SECONDS: int = Field(default=0, ge=0)
    TASK_ROOT_RESERVE_TOKENS: int = Field(default=30_000, ge=1)
    TASK_ROOT_RESERVE_COST: float = Field(default=1.0, gt=0, allow_inf_nan=False)
    TASK_BUDGET_SHARE_GOAL: bool = False
    TASK_SCHEDULER_MAX_CONCURRENCY_PER_USER: int = Field(default=0, ge=0)
    TASK_SCHEDULER_FAIRNESS_SECONDS: int = Field(default=0, ge=0)
    INCIDENT_TRACE_RETENTION_DAYS: int = Field(default=0, ge=0)
    LLM_TRACE_RETENTION_DAYS: int = Field(default=0, ge=0)
    TASK_ACTION_MAX_ATTEMPTS: int = Field(default=3, ge=1, le=20)
    TASK_ACTION_RETRY_BASE_SECONDS: float = Field(default=2.0, ge=0.1, le=300.0)
    TASK_NETWORK_MAX_ATTEMPTS: int = Field(default=8, ge=2, le=30)
    TASK_NETWORK_RETRY_BASE_SECONDS: float = Field(
        default=30.0, ge=1.0, le=600.0
    )
    TASK_NETWORK_RETRY_MAX_SECONDS: float = Field(
        default=300.0, ge=10.0, le=3_600.0
    )
    # Stall deadline, rearmed by each durable Task checkpoint or semantic event.
    TASK_ACTION_TIMEOUT_SECONDS: int = Field(default=1_800, ge=30, le=86_400)
    TASK_TOOL_TIMEOUT_SECONDS: float = Field(default=300.0, ge=1.0, le=3_600.0)
    TASK_PLAN_MAX_DEPTH: int = Field(default=3, ge=1, le=10)
    TASK_PLAN_MAX_NODES: int = Field(default=24, ge=1, le=500)
    TASK_PLAN_MAX_LEAVES: int = Field(default=12, ge=1, le=250)
    TASK_AGENT_MAX_REQUESTS: int = Field(default=200, ge=1, le=500)
    TASK_AGENT_MAX_TOOL_CALLS: int = Field(default=5_000, ge=1, le=5_000)
    TASK_ASK_AGENT_TIMEOUT_SECONDS: int = Field(default=7_200, ge=60)
    TASK_ASK_AGENT_MAX_ROUNDS: int = Field(default=5, ge=1, le=50)

    # Business-process settings and n8n bridge configuration.
    PROCESS_ENGINE_DEFAULT: Literal["n8n"] = "n8n"
    PROCESS_FILE_REF_TTL_SECONDS: int = Field(default=3_600, ge=60)
    PROCESS_START_TIMEOUT_SECONDS: float = Field(default=15.0, ge=0.1)
    PROCESS_REFRESH_TIMEOUT_SECONDS: float = Field(default=5.0, ge=0.1)
    PROCESS_REFRESH_STALENESS_SECONDS: int = Field(default=30, ge=0)
    PROCESS_REFRESH_MAX_FAILURES: int = Field(default=10, ge=1)
    PROCESS_WAIT_MAX_SECONDS: int = Field(default=7_200, ge=60)
    PROCESS_START_MAX_RETRIES: int = Field(default=5, ge=1)
    PROCESS_START_RETRY_BACKOFF_SECONDS: float = Field(default=5.0, ge=0.1)
    PROCESS_IDEMPOTENCY_WINDOW_SECONDS: int = Field(default=300, ge=0)
    PROCESS_SANITIZE_MAX_BYTES: int = Field(default=64_000, ge=1_024)
    PROCESS_RETENTION_RAW_SNAPSHOT_DAYS: int = Field(default=30, ge=0)
    PROCESS_RETENTION_EVENTS_DAYS: int = Field(default=90, ge=0)
    PROCESS_RETENTION_OUTPUT_DAYS: int = Field(default=0, ge=0)
    PROCESS_RETENTION_RUN_DAYS: int = Field(default=0, ge=0)
    PROCESS_N8N_BASE_URL: str = ""
    PROCESS_N8N_API_TOKEN: str = ""
    PROCESS_N8N_WEBHOOK_BASE_URL: str = ""
    PROCESS_GALARIS_BASE_URL: str = ""
    PROCESS_N8N_WEBHOOK_AUTH_HEADER: str = Field(
        default="X-Galaris-Webhook-Token", min_length=1
    )
    PROCESS_N8N_WEBHOOK_AUTH_TOKEN: str = ""
    PROCESS_N8N_CALLBACK_AUTH_HEADER: str = Field(
        default="X-Galaris-Callback-Token", min_length=1
    )

    @field_validator(
        "PROCESS_N8N_BASE_URL",
        "PROCESS_N8N_WEBHOOK_BASE_URL",
        "PROCESS_GALARIS_BASE_URL",
    )
    @classmethod
    def validate_process_http_url(cls, value: str, info: ValidationInfo) -> str:
        """Reject non-URLs before a durable process reaches an engine worker."""
        normalized = value.strip().rstrip("/")
        if normalized and not normalized.startswith(("http://", "https://")):
            raise ValueError(f"{info.field_name} must start with http:// or https://")
        return normalized

    # External agent Harness availability.
    HARNESS_CLAUDE_AGENT_ENABLED: bool = True
    HARNESS_CODEX_ENABLED: bool = True
    HARNESS_DEEPSEEK_ENABLED: bool = True
    HARNESS_HERMES_ENABLED: bool = True

    # Search client settings.
    SEARCH_DEFAULT_LANGUAGE: str = "en"
    SEARCH_TIMEOUT: int = Field(default=10, ge=1)

    @field_validator("MESSENGER_ENABLED_CHANNELS", mode="before")
    @classmethod
    def validate_messenger_enabled_channels(cls, value: object) -> str:
        """Persist a unique subset of supported channels in canonical form."""

        channels = cls._messenger_channel_list(
            value,
            field_name="MESSENGER_ENABLED_CHANNELS",
        )
        unknown = set(channels).difference(SUPPORTED_MESSENGER_CHANNELS)
        if unknown:
            raise ValueError(
                "MESSENGER_ENABLED_CHANNELS contains unsupported channels: "
                + ", ".join(sorted(unknown))
            )
        return json.dumps(channels, separators=(",", ":"))

    @staticmethod
    def _messenger_channel_list(value: object, *, field_name: str) -> list[str]:
        """Validate the JSON-array shape shared by channel settings."""

        try:
            decoded: object = json.loads(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field_name} must be a JSON array") from exc
        if not isinstance(decoded, list):
            raise ValueError(f"{field_name} must be a JSON string array")
        raw_items = list(cast(list[object], decoded))
        if any(not isinstance(item, str) for item in raw_items):
            raise ValueError(f"{field_name} must be a JSON string array")
        channels = [item for item in raw_items if isinstance(item, str)]
        if len(channels) != len(set(channels)):
            raise ValueError(f"{field_name} must not contain duplicates")
        return channels

    @field_validator(
        "MESSENGER_ONE_BOT_SECRET_KEY",
        "MESSENGER_WHATSAPP_APP_SECRET",
        "MESSENGER_WHATSAPP_VERIFY_TOKEN",
    )
    @classmethod
    def validate_provider_secret(cls, value: str, info: ValidationInfo) -> str:
        """Enforce production lengths when an optional provider secret is set."""
        if bootstrap_settings.is_dev or not value:
            return value
        field_name = info.field_name
        minimum = 16 if field_name == "MESSENGER_WHATSAPP_VERIFY_TOKEN" else 32
        if len(value) < minimum:
            raise ValueError(f"{field_name} must contain at least {minimum} characters")
        return value


runtime_settings = RuntimeSettings()


__all__ = [
    "RuntimeSettings",
    "SUPPORTED_MESSENGER_CHANNELS",
    "runtime_settings",
]
