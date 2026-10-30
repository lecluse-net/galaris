"""Exhaustive parameter policy; the frontend contract is generated from it."""

import json
from collections.abc import Iterable
from pathlib import Path


PARAMETER_DOMAINS: dict[str, tuple[str, str]] = {
    "system": ("PARAMS_ACCESS", "PARAMS_EDIT"),
    **{name: (f"{prefix}_ACCESS", f"{prefix}_EDIT") for name, prefix in {
        "language": "LANGUAGE_CONFIG", "messaging": "MESSAGING_CONFIG",
        "memory": "MEMORY_CONFIG", "voice": "VOICE_CONFIG", "audio": "AUDIO_CONFIG",
        "process": "PROCESS_CONFIG", "tasks": "TASK_CONFIG", "search": "SEARCH_CONFIG",
        "janus": "JANUS_CONFIG", "instructions": "INSTRUCTION_CONFIG", "logs": "LOG_CONFIG",
        "browser": "BROWSER_CONFIG", "goals": "GOAL_CONFIG", "harnesses": "HARNESS_CONFIG",
        "profiles": "LLM_PROFILE",
    }.items()},
    # The existing writer configures Dream; supervision keeps its separate scope.
    "dream": ("DREAM_CONFIG_ACCESS", "DREAM_EDIT"),
}


def parameter_domain(name: str) -> str:
    if name in {"AUTH_SECRET_KEY", "WEB_PUSH_VAPID_KEYS", "galaris.agent_id"}:
        return "internal"
    if name in {"ALLOW_USER_REGISTRATION", "HTTP_RATE_LIMIT_PER_MINUTE"}:
        return "system"
    if name in {"DEFAULT_LANGUAGE", "LOCALIZATION"}:
        return "language"
    if name.startswith("BROWSER_"):
        return "browser"
    if name.startswith(("DREAM_", "MEMORY_LINK_RECONCILIATION_")) or name in {
        "ai.topic-classification-system-prompt", "ai.topic-continuity-system-prompt",
        "ai.topic-resolution-system-prompt", "ai.memory-extraction-system-prompt",
    }:
        return "dream"
    if name.startswith(("MEMORY_", "MESSENGER_SESSION_")):
        return "memory"
    if name.startswith(("MESSENGER_", "GALARIS_INTERNAL_MESSENGER_", "WEB_PUSH_", "messenger.")):
        return "messaging"
    if name.startswith("VOICE_"):
        return "voice"
    if name.startswith("audio."):
        return "audio"
    if name.startswith("PROCESS_"):
        return "process"
    if name.startswith("TASK_") or name in {
        "LLM_CALL_TIMEOUT_MINUTES", "ai.task-objective-system-prompt", "ai.planner-system-prompt",
    }:
        return "tasks"
    if name in {"ai.executor-system-prompt", "ai.conversation-executor-system-prompt",
                "ai.voice-executor-system-prompt", "ai.conversation-action-policy"}:
        return "instructions"
    if name.startswith("SEARCH_"):
        return "search"
    if name in {"LOGFIRE_TOKEN", "INCIDENT_TRACE_RETENTION_DAYS", "LLM_TRACE_RETENTION_DAYS"}:
        return "logs"
    if name == "PYDANTIC_AI_BINARY_INPUT_MAX_BYTES" or name.startswith(("HARNESS_MANAGER_", "harness.", "hermes.default.")):
        return "harnesses"
    if name in {"goal.runtime.settings", "ai.goal-tracking-system-prompt"}:
        return "goals"
    if name == "janus.aliases":
        return "janus"
    if name == "llm_profile_id":
        return "profiles"
    raise ValueError(f"Parameter has no functional authorization policy: {name}")


def parameter_privileges(name: str, *, write: bool = False) -> tuple[str, ...]:
    domain = parameter_domain(name)
    if domain == "internal":
        return ()
    read, edit = PARAMETER_DOMAINS[domain]
    return (edit,) if write else (read, edit)


PARAMETER_READ_PRIVILEGES = tuple(dict.fromkeys(code for pair in PARAMETER_DOMAINS.values() for code in pair))
PARAMETER_WRITE_PRIVILEGES = tuple(pair[1] for pair in PARAMETER_DOMAINS.values())


def generate_parameter_access_file(names: Iterable[str], path: Path) -> None:
    """Keep all UI fields on the same fail-closed policy as the API."""
    policies = {name: parameter_privileges(name) for name in sorted(set(names))}
    public = {name: pair for name, pair in policies.items() if pair}
    content = "// Generated from core.params.access. Do not edit manually.\n"
    content += "export const parameterAccess: Record<string, readonly string[]> = "
    content += json.dumps(public, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
