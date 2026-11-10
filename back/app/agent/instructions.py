"""Compose administrable operating knowledge with each executor's instructions."""

from core.params import Params, params_service

from .prompt_tree import ExecutorKind


async def executor_instructions(executor: ExecutorKind) -> str:
    """Resolve current settings; an explicit empty operating prompt disables it.

    Executor-specific instructions remain last. Lab datasets freeze this complete
    value so experiments never depend on later changes to either parameter.
    """
    specific = {
        "task": Params.AI_EXECUTOR_SYSTEM_PROMPT,
        "conversation": Params.AI_CONVERSATION_EXECUTOR_SYSTEM_PROMPT,
        "voice": Params.AI_VOICE_EXECUTOR_SYSTEM_PROMPT,
    }[executor]
    common = await params_service.get_or_default(Params.AI_GALARIS_OPERATING_PROMPT)
    addition = await params_service.get_or_default(specific)
    return "\n\n".join(value.strip() for value in (common, addition) if value and value.strip())
