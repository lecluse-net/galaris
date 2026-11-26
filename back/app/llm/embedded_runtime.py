"""Scoped gateway credentials for embedded runtime inference."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import ClassVar, Self
from uuid import UUID

from cryptography.fernet import InvalidToken
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.contracts import ExecutionEffort
from core.util import get_encryption_service

from .purposes import LLMCallPurpose
from .provider_facade import ReasoningEffort


EMBEDDED_ROUND_TOKEN_PREFIX = "galaris-round-v1."
EMBEDDED_TASK_TOKEN_PREFIX = "galaris-task-v1."
EMBEDDED_DEEP_TOKEN_PREFIX = "galaris-deep-v1."
EMBEDDED_TOKEN_PREFIXES = (EMBEDDED_ROUND_TOKEN_PREFIX, EMBEDDED_TASK_TOKEN_PREFIX, EMBEDDED_DEEP_TOKEN_PREFIX)


class EmbeddedRequestLimitExceeded(ValueError):
    """The logical execution has used its provider request allowance."""


class _EmbeddedInference(BaseModel, ABC):
    model_config = ConfigDict(frozen=True, extra="forbid")
    token_prefix: ClassVar[str]
    payload_prefix: ClassVar[str]

    agent_id: int = Field(gt=0)
    attempt_id: UUID
    run_id: UUID
    model_id: int = Field(gt=0)
    model_code: str = Field(min_length=1)
    reasoning_effort: ReasoningEffort | None = None
    request_limit: int | None = Field(default=None, ge=1)

    @property
    @abstractmethod
    def purpose(self) -> LLMCallPurpose:
        """Purpose of the runtime's model loop, distinct from auxiliary inference."""

    @abstractmethod
    async def authorize(self) -> int | None:
        """Resolve the requester from the live owner of this inference."""

    def credential(self) -> str:
        payload = self.payload_prefix + self.model_dump_json()
        return self.token_prefix + get_encryption_service().encrypt(payload)

    @classmethod
    def _decode(cls, credential: str) -> Self:
        try:
            token = credential.removeprefix(cls.token_prefix)
            if token == credential:
                raise PermissionError("Invalid embedded inference credential.")
            payload = get_encryption_service().decrypt(token)
            if not payload.startswith(cls.payload_prefix):
                raise PermissionError("Invalid embedded inference credential.")
            return cls.model_validate_json(payload.removeprefix(cls.payload_prefix))
        except (InvalidToken, ValidationError, ValueError) as exc:
            raise PermissionError("Invalid embedded inference credential.") from exc

    @classmethod
    async def authenticate(cls, credential: str) -> tuple[Self, int | None]:
        origin = cls._decode(credential)
        return origin, await origin.authorize()


class EmbeddedRoundInference(_EmbeddedInference):
    token_prefix = EMBEDDED_ROUND_TOKEN_PREFIX
    payload_prefix = "galaris:embedded-round:v1:"

    round_id: UUID
    driver_code: str = Field(min_length=1)
    audio: bool = False

    @property
    def purpose(self) -> LLMCallPurpose:
        return LLMCallPurpose.CONVERSATION_AUDIO if self.audio else LLMCallPurpose.CONVERSATION_TEXT

    @property
    def correlation_ref(self) -> str:
        return f"round:{self.round_id}:attempt:{self.attempt_id}"

    async def authorize(self) -> int | None:
        from app.conversation import authorize_round_inference

        return await authorize_round_inference(
            self.round_id, self.attempt_id, self.agent_id, run_id=self.run_id, audio=self.audio,
            driver_code=self.driver_code, model_id=self.model_id, model_code=self.model_code,
            reasoning_effort=self.reasoning_effort, request_limit=self.request_limit,
        )


class EmbeddedTaskInference(_EmbeddedInference):
    token_prefix = EMBEDDED_TASK_TOKEN_PREFIX
    payload_prefix = "galaris:embedded-task:v1:"

    task_id: UUID
    executor_profile_effort: ExecutionEffort | None = None

    @property
    def purpose(self) -> LLMCallPurpose:
        return LLMCallPurpose.AGENT_EXEC

    @property
    def correlation_ref(self) -> str:
        return f"task:{self.task_id}:attempt:{self.attempt_id}"

    async def authorize(self, *, model_loop: bool = False) -> int | None:
        from app.task.facade import authorize_task_inference

        return await authorize_task_inference(
            self.task_id, self.attempt_id, self.agent_id, run_id=self.run_id,
            model_id=self.model_id, model_code=self.model_code, reasoning_effort=self.reasoning_effort,
            executor_profile_effort=self.executor_profile_effort, model_loop=model_loop,
        )


class EmbeddedDeepInference(_EmbeddedInference):
    token_prefix = EMBEDDED_DEEP_TOKEN_PREFIX
    payload_prefix = "galaris:embedded-deep:v1:"

    session_id: UUID

    @property
    def purpose(self) -> LLMCallPurpose:
        return LLMCallPurpose.CONVERSATION_DEEP

    @property
    def correlation_ref(self) -> str:
        return f"deep:{self.session_id}:submission:{self.run_id}"

    async def authorize(self) -> int:
        from app.conversation import authorize_embedded_deep_inference

        return await authorize_embedded_deep_inference(
            self.session_id, self.run_id, self.agent_id, claim_id=self.attempt_id,
            model_id=self.model_id, model_code=self.model_code, reasoning_effort=self.reasoning_effort,
            request_limit=self.request_limit,
        )


EmbeddedInferenceOrigin = EmbeddedRoundInference | EmbeddedTaskInference | EmbeddedDeepInference


@dataclass(frozen=True)
class EmbeddedLineage:
    source_kind: str
    source_id: UUID
    task_id: UUID | None = None
    task_attempt_id: UUID | None = None
    round_id: UUID | None = None
    deep_session_id: UUID | None = None


def embedded_lineage(origin: EmbeddedInferenceOrigin) -> EmbeddedLineage:
    if isinstance(origin, EmbeddedTaskInference):
        return EmbeddedLineage("task", origin.task_id, task_id=origin.task_id, task_attempt_id=origin.attempt_id)
    if isinstance(origin, EmbeddedRoundInference):
        return EmbeddedLineage("conversation_round", origin.round_id, round_id=origin.round_id)
    return EmbeddedLineage("deep_submission", origin.run_id, deep_session_id=origin.session_id)


def bind_embedded_call(
    origin: EmbeddedInferenceOrigin, *, agent_id: int | None, agent_run_id: UUID | None,
    task_id: UUID | None, task_attempt_id: UUID | None, conversation_round_id: UUID | None,
    process_run_id: UUID | None, deep_session_id: UUID | None = None,
) -> EmbeddedLineage:
    lineage = embedded_lineage(origin)
    if any(given is not None and given != expected for given, expected in (
        (agent_id, origin.agent_id), (agent_run_id, origin.run_id), (task_id, lineage.task_id),
        (task_attempt_id, lineage.task_attempt_id), (conversation_round_id, lineage.round_id),
        (deep_session_id, lineage.deep_session_id),
    )) or (process_run_id is not None and lineage.task_id is None):
        raise PermissionError("The call lineage conflicts with the admitted embedded attempt.")
    return lineage


_MEDIA_PURPOSES = frozenset({
    LLMCallPurpose.IMAGE_ANALYSIS, LLMCallPurpose.AUDIO_TRANSCRIPTION, "multimedia.video_read",
})
_media_inference_origin: ContextVar[EmbeddedInferenceOrigin | None] = ContextVar("embedded_media_inference_origin", default=None)


def current_media_inference_origin(purpose: str | None) -> EmbeddedInferenceOrigin | None:
    return _media_inference_origin.get() if purpose in _MEDIA_PURPOSES else None


@asynccontextmanager
async def embedded_media_inference(origin: EmbeddedInferenceOrigin) -> AsyncGenerator[None]:
    """Bind server-side attachment analysis to the attempt that requested it."""
    from .subscription_policy import current_execution_authority, llm_execution_scope

    requester = await origin.authorize()
    lineage = embedded_lineage(origin)
    previous = current_execution_authority()
    token = _media_inference_origin.set(origin)
    try:
        with llm_execution_scope(
            requester_user_id=requester, source_kind=lineage.source_kind, source_id=str(lineage.source_id),
            messenger_origin=lineage.task_id is None or (previous is not None and previous.messenger_origin),
            api_token_label=previous.api_token_label if previous is not None else None,
        ):
            yield
    finally:
        _media_inference_origin.reset(token)


async def authenticate_embedded_inference(
    credential: str,
) -> tuple[EmbeddedInferenceOrigin, int | None]:
    if credential.startswith(EMBEDDED_ROUND_TOKEN_PREFIX):
        return await EmbeddedRoundInference.authenticate(credential)
    if credential.startswith(EMBEDDED_DEEP_TOKEN_PREFIX):
        return await EmbeddedDeepInference.authenticate(credential)
    return await EmbeddedTaskInference.authenticate(credential)
