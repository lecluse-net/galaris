"""Provider for an operator-configured OpenAI Messages compatible Harness."""

from __future__ import annotations

from app.agent import Agent
from .agent_driver import OPENAI_MESSAGES_DRIVER

from .contracts import (
    HarnessAction,
    HarnessCapability,
    HarnessProvisioningRequest,
    HarnessProvisioningResult,
)


async def validate_configuration(
    *,
    base_url: str | None,
    token: str | None,
    model: str | None,
) -> HarnessProvisioningResult:
    """Validate one shared OpenAI Messages catalogue entry."""

    normalized_url, models = await probe_configuration(
        base_url=base_url,
        token=token,
    )
    selected_model = model
    if selected_model is None:
        if len(models) != 1:
            raise ValueError(
                "The Harness exposes multiple models; select one explicitly."
                if models
                else "The Harness did not expose any model."
            )
        selected_model = models[0]
    elif selected_model not in models:
        raise ValueError(f"The Harness does not expose model {selected_model!r}.")
    return HarnessProvisioningResult(
        base_url=normalized_url,
        model=selected_model,
        capabilities=provider.capabilities(),
    )


async def probe_configuration(
    *,
    base_url: str | None,
    token: str | None,
) -> tuple[str, list[str]]:
    """Test the endpoint and return its normalized URL and advertised models."""

    if not base_url:
        raise ValueError("An OpenAI Messages Harness requires a base URL.")
    from .openai_client import OpenAIHarnessClient, normalize_base_url

    normalized_url = normalize_base_url(base_url)
    client = OpenAIHarnessClient(base_url=normalized_url, token=token)
    models = await client.list_models()
    if not models:
        raise ValueError("The Harness did not expose any model.")
    return normalized_url, models


class OpenAIMessagesProvider:
    pipeline_policy = OPENAI_MESSAGES_DRIVER.pipeline_policy
    code = "openai_messages"
    driver_code = "openai_messages"
    label = "OpenAI Messages"
    containerized = False
    enabled_param: str | None = None
    max_parallel_tasks = 1

    def capabilities(self) -> frozenset[HarnessCapability]:
        return frozenset({"execute", "streaming"})

    async def provision(
        self,
        agent: Agent,
        request: HarnessProvisioningRequest,
        *,
        token: str | None,
    ) -> HarnessProvisioningResult:
        del agent
        validated = await validate_configuration(
            base_url=request.base_url,
            token=token,
            model=request.model,
        )
        # Coordinates and secrets remain on the shared catalogue entry. The per-agent
        # assignment only records lifecycle and provider-generated runtime overrides.
        return HarnessProvisioningResult(capabilities=validated.capabilities)

    async def deprovision(
        self,
        agent: Agent,
        request: HarnessProvisioningRequest,
    ) -> None:
        del agent, request

    async def status(self, agent: Agent) -> str:
        del agent
        return "configured"

    async def run_action(self, agent: Agent, action: HarnessAction) -> str:
        del agent, action
        raise RuntimeError("This Harness does not expose lifecycle supervision.")

    async def logs(self, agent: Agent, lines: int) -> list[str]:
        del agent, lines
        raise RuntimeError("This Harness does not expose runtime logs.")


provider = OpenAIMessagesProvider()

__all__ = [
    "OpenAIMessagesProvider",
    "probe_configuration",
    "provider",
    "validate_configuration",
]
