"""Resolve admission provenance independently of the physical transport.

Conversation ancestry is audit evidence, not a right to dialogue capacity. Both
the durable queue and the physical-call gateway must use the same resolution.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from .purposes import LLMCallPurpose

if TYPE_CHECKING:
    from .subscription_policy import LLMExecutionAuthority


class AdmissionClass(IntEnum):
    VOICE = 0
    TEXT = 1
    BACKGROUND = 2


class AdmissionSource(StrEnum):
    VOICE_DIALOGUE = "voice_dialogue"
    TEXT_DIALOGUE = "text_dialogue"
    TASK = "task"
    BACKGROUND = "background"


@dataclass(frozen=True)
class AdmissionContext:
    source: AdmissionSource
    priority: AdmissionClass
    owner: str | None


def admission_context(
    purpose: str | None,
    *,
    task_id: UUID | None = None,
    conversation_round_id: UUID | None = None,
    agent_run_id: UUID | None = None,
    media_generation_id: UUID | None = None,
    process_run_id: UUID | None = None,
    authority: LLMExecutionAuthority | None = None,
    agent_id: int | None = None,
    requester_user_id: int | None = None,
    round_is_voice: bool = False,
    voice_dialogue: bool = False,
) -> AdmissionContext:
    """Keep Task ownership ahead of its conversation of origin.

    Live STT precedes round creation and supplies ``voice_dialogue`` internally.
    Background owners use durable work first, then trusted source provenance,
    then the agent or requester. Source ancestry and caller-provided correlation
    labels never promote an operation to dialogue capacity or grant rights.
    """
    if task_id is not None:
        return AdmissionContext(AdmissionSource.TASK, AdmissionClass.BACKGROUND, str(task_id))
    owner = str(conversation_round_id or agent_run_id) if conversation_round_id or agent_run_id else None
    if owner is None:
        if media_generation_id is not None:
            owner = f"media:{media_generation_id}"
        elif process_run_id is not None:
            owner = f"process:{process_run_id}"
        elif authority is not None and authority.source_kind and authority.source_id:
            owner = "source:" + json.dumps((authority.source_kind, authority.source_id), separators=(",", ":"))
        elif agent_id is not None:
            owner = f"agent:{agent_id}"
        else:
            requester = requester_user_id or (authority.requester_user_id if authority else None)
            if requester is not None:
                owner = f"user:{requester}"
    if voice_dialogue or (conversation_round_id is not None and round_is_voice):
        return AdmissionContext(AdmissionSource.VOICE_DIALOGUE, AdmissionClass.VOICE, owner)
    if conversation_round_id is not None:
        return AdmissionContext(AdmissionSource.TEXT_DIALOGUE, AdmissionClass.TEXT, owner)
    if purpose == LLMCallPurpose.CONVERSATION_AUDIO:
        return AdmissionContext(AdmissionSource.VOICE_DIALOGUE, AdmissionClass.VOICE, owner)
    if purpose in {
        LLMCallPurpose.CONVERSATION_TEXT,
        LLMCallPurpose.CONVERSATION_TASK_OBJECTIVE,
        LLMCallPurpose.CONVERSATION_PROCESS_ADMISSION,
    }:
        return AdmissionContext(AdmissionSource.TEXT_DIALOGUE, AdmissionClass.TEXT, owner)
    return AdmissionContext(AdmissionSource.BACKGROUND, AdmissionClass.BACKGROUND, owner)
