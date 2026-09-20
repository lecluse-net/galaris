"""Executor prompt defaults and immutable dataset run configuration."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

from core.params import Params, params_service

from app.agent.prompt_tree import PROMPT_TREE_SCHEMA

from .schemas import ExecutorPromptDefaultsRead, ExecutorPromptKind


_PARAM_BY_EXECUTOR: dict[ExecutorPromptKind, str] = {
    "task": Params.AI_EXECUTOR_SYSTEM_PROMPT,
    "conversation": Params.AI_CONVERSATION_EXECUTOR_SYSTEM_PROMPT,
    "voice": Params.AI_VOICE_EXECUTOR_SYSTEM_PROMPT,
}


async def default_suffix(executor: ExecutorPromptKind) -> str:
    """Read the current production Param used to initialize or reset a dataset."""

    return (await params_service.get(_PARAM_BY_EXECUTOR[executor]) or "").strip()


async def default_conversation_action_policy(executor: ExecutorPromptKind) -> str:
    """Read the production foreground-action policy for conversational executors."""

    if executor == "task":
        return ""
    return (
        await params_service.get_or_default(Params.AI_CONVERSATION_ACTION_POLICY)
        or ""
    ).strip()


async def read_defaults() -> ExecutorPromptDefaultsRead:
    return ExecutorPromptDefaultsRead(
        defaults={
            executor: await default_suffix(executor)
            for executor in _PARAM_BY_EXECUTOR
        }
    )


async def resolve_dataset_configuration(
    executor: ExecutorPromptKind,
    *,
    dataset_id: UUID,
    dataset_revision: int,
    dataset_name: str,
    prompt_suffix: str | None,
) -> dict[str, object]:
    """Freeze the dataset prompt once so workers never read mutable Params."""

    if prompt_suffix is None:
        effective = await default_suffix(executor)
        source = "production_param_fallback"
    else:
        effective = prompt_suffix.strip()
        source = "dataset"
    action_policy = await default_conversation_action_policy(executor)
    return {
        "executor": executor,
        "prompt_tree_schema": PROMPT_TREE_SCHEMA,
        "prompt_renderer": "markdown/v1",
        "prompt_suffix": effective,
        "prompt_source": source,
        "prompt_dataset_id": str(dataset_id),
        "prompt_dataset_name": dataset_name,
        "prompt_dataset_revision": dataset_revision,
        "prompt_suffix_sha256": hashlib.sha256(effective.encode("utf-8")).hexdigest(),
        "conversation_action_policy": action_policy,
        "conversation_action_policy_sha256": hashlib.sha256(
            action_policy.encode("utf-8")
        ).hexdigest(),
        "resolved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


__all__ = [
    "default_suffix",
    "default_conversation_action_policy",
    "read_defaults",
    "resolve_dataset_configuration",
]
