"""xAI REST Responses compatibility owned by the provider bridge."""

from __future__ import annotations

from typing import Any, cast

from app.llm import (
    PreparedChatRequest,
    ProviderConnection,
    ResponsesOperation,
)


class XAIResponsesTransport:
    """Prepare xAI create and compaction requests without OpenAI-only fields."""

    async def prepare_responses_request(
        self,
        provider_id: int,
        connection: ProviderConnection,
        body: dict[str, Any],
        *,
        operation: ResponsesOperation = "create",
        force_refresh: bool = False,
    ) -> PreparedChatRequest:
        del provider_id, force_refresh
        forwarded = dict(body)
        if operation == "compact" and (
            instructions := forwarded.pop("instructions", None)
        ):
            raw_input = forwarded.get("input")
            input_items: list[Any] = (
                list(cast(list[Any], raw_input)) if isinstance(raw_input, list) else []
            )
            if isinstance(raw_input, str):
                input_items.append({"role": "user", "content": raw_input})
            forwarded["input"] = [
                {"role": "system", "content": str(instructions)},
                *input_items,
            ]
        headers = {"Content-Type": "application/json"}
        if connection.api_key:
            headers["Authorization"] = f"Bearer {connection.api_key}"
        suffix = "/responses/compact" if operation == "compact" else "/responses"
        return PreparedChatRequest(
            endpoint=f"{connection.base_url.rstrip('/')}{suffix}",
            headers=headers,
            body=forwarded,
        )


__all__ = ["XAIResponsesTransport"]
