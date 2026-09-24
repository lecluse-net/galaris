"""OpenRouter Decisions API (not Chat Completions)."""

import httpx

from app.llm.facade import (
    ChoiceQuestion, DecisionUnavailable, ProviderDecisionResponse,
    ProviderConnection, ProviderAuthenticationError,
)
from core.util import read_response


class OpenRouterDecisions:
    async def decide(
        self, connection: ProviderConnection, *, model: str, state: str,
        questions: dict[str, ChoiceQuestion], timeout_seconds: float | None,
    ) -> ProviderDecisionResponse:
        base = connection.base_url.rstrip("/").removesuffix("/v1")
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False) as client:
                async with client.stream(
                    "POST", f"{base}/alpha/decisions",
                    headers={"Authorization": f"Bearer {connection.api_key or ''}"},
                    json={"model": model, "state": state,
                          "questions": {key: item.model_dump() for key, item in questions.items()}},
                ) as response:
                    if response.status_code in {401, 403}:
                        raise ProviderAuthenticationError(
                            "Decision provider refused access.", status_code=response.status_code,
                        )
                    if response.status_code == 402:
                        raise ProviderAuthenticationError(
                            "Decision provider budget is exhausted.", status_code=402,
                        )
                    if not response.is_success:
                        raise DecisionUnavailable(f"Decision provider returned HTTP {response.status_code}.")
                    body = await read_response(response, max_bytes=2_000_000)
            return ProviderDecisionResponse.model_validate_json(body)
        except (httpx.HTTPError, ValueError) as exc:
            raise DecisionUnavailable(f"Decision provider failed: {type(exc).__name__}.") from exc
