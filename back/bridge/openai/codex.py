"""ChatGPT/Codex bridge services exposed through app.llm contracts."""

from __future__ import annotations

from typing import Any

from app.llm.capabilities import AICapability
from app.llm.handlers import LLMModelInfo
from app.llm.provider_facade import (
    ChatStreamAdapter,
    ManagedRuntimeCredential,
    PreparedChatRequest,
    ProviderConnection,
    ProviderQuota,
    ResponsesOperation,
)

from . import codex_oauth
from .codex_quota import get_quota
from .codex_responses import (
    CodexSSEAdapter,
    chat_completions_to_responses,
    responses_to_chat_completion,
)


class CodexBridge:
    stream_only = True

    async def get_quota(self, provider_id: int) -> ProviderQuota:
        return await get_quota(provider_id)

    async def list_resources(
        self,
        connection: ProviderConnection,
        capability: AICapability,
    ) -> list[LLMModelInfo]:
        if capability != "chat" or connection.id is None:
            return []
        provider = await codex_oauth.get_provider(connection.id)
        if provider is None:
            return []
        return await codex_oauth.list_models(provider)

    async def start_device_login(self, provider_id: int) -> dict[str, Any]:
        return await codex_oauth.start_device_login(provider_id)

    async def poll_device_login(
        self,
        provider_id: int,
        *,
        device_auth_id: str,
        user_code: str,
    ) -> dict[str, Any]:
        return await codex_oauth.poll_device_login(
            provider_id,
            device_auth_id=device_auth_id,
            user_code=user_code,
        )

    async def disconnect(self, provider_id: int) -> None:
        await codex_oauth.disconnect(provider_id)

    async def get_runtime_credential(
        self,
        provider_id: int,
    ) -> ManagedRuntimeCredential:
        """Return fresh external-auth material without sharing the refresh token."""

        access_token = await codex_oauth.get_access_token(provider_id)
        account_id = codex_oauth.account_id(access_token)
        if account_id is None:
            raise RuntimeError("The connected ChatGPT account has no Codex account identifier.")
        return ManagedRuntimeCredential(
            auth_mode="chatgpt",
            secret=access_token,
            account_id=account_id,
            plan_type=codex_oauth.plan_type(access_token),
        )

    async def prepare_request(
        self,
        provider_id: int,
        connection: ProviderConnection,
        body: dict[str, Any],
        *,
        force_refresh: bool = False,
        force_stream: bool = False,
    ) -> PreparedChatRequest:
        token = await codex_oauth.get_access_token(
            provider_id,
            force_refresh=force_refresh,
        )
        forwarded = chat_completions_to_responses(body)
        if force_stream:
            forwarded["stream"] = True
        return PreparedChatRequest(
            endpoint=f"{connection.base_url.rstrip('/')}/responses",
            headers=codex_oauth.codex_request_headers(token),
            body=forwarded,
        )

    async def prepare_responses_request(
        self,
        provider_id: int,
        connection: ProviderConnection,
        body: dict[str, Any],
        *,
        operation: ResponsesOperation = "create",
        force_refresh: bool = False,
    ) -> PreparedChatRequest:
        """Forward an already-native Responses request without lossy conversion."""

        token = await codex_oauth.get_access_token(
            provider_id,
            force_refresh=force_refresh,
        )
        suffix = "/responses/compact" if operation == "compact" else "/responses"
        forwarded = dict(body)
        if operation == "create":
            # Codex requires SSE even when the internal caller wants a final JSON result.
            forwarded["stream"] = True
            # Match the Chat adapter: Codex rejects output caps and sampling settings,
            # including the default temperature supplied by structured callers (Goals).
            for parameter in ("max_output_tokens", "temperature", "top_p"):
                forwarded.pop(parameter, None)
        return PreparedChatRequest(
            endpoint=f"{connection.base_url.rstrip('/')}{suffix}",
            headers=codex_oauth.codex_request_headers(token),
            body=forwarded,
        )

    def normalize_response(
        self,
        payload: dict[str, Any],
        *,
        model: str,
    ) -> dict[str, Any]:
        return responses_to_chat_completion(payload, model=model)

    def create_stream_adapter(self, model: str) -> ChatStreamAdapter | None:
        return CodexSSEAdapter(model)
