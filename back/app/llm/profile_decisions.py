"""Optional closed choices shared by generative workflows and their text-only fallback."""

from uuid import UUID
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar

from . import llm_service
from .contracts import DecisionInferenceRequest
from .decision_contracts import ChoiceQuestion, DecisionResult
from .inference_execution import run_decision
from .provider_models import LLM
from .structured_service import StructuredInferenceResult


_explicit_models: ContextVar[tuple[LLM, LLM] | None] = ContextVar(
    "explicit_decision_models", default=None
)


@contextmanager
def use_decision_models(decision: LLM | None, text: LLM) -> Generator[None]:
    """Bind an explicitly frozen Lab candidate and writer; never enable fallback."""
    token = _explicit_models.set((decision, text) if decision is not None else None)
    try:
        yield
    finally:
        _explicit_models.reset(token)


async def run_profile_decision(
    *,
    text_llm: LLM | None,
    questions: dict[str, ChoiceQuestion],
    prompt: str,
    system_prompt: str,
    task_id: UUID | None,
    agent_id: int | None,
    purpose: str,
    model_field: str,
) -> StructuredInferenceResult[DecisionResult] | None:
    """Return None to retain the original text path when specialization is absent.

    A changed profile cannot bind a new decision model to an old text companion.
    Lab callers opt in explicitly; their text candidate never silently consults a
    different model from the live profile.
    """
    explicit = _explicit_models.get()
    if explicit is not None:
        decision, companion = explicit
        allow_fallback = False
    else:
        decision, companion, allow_fallback = await llm_service.get_decision_models_for_agent_id(
            agent_id,
            model_field,
        )
    if decision is None:
        return None
    if companion is None or (text_llm is not None and companion.id != text_llm.id):
        return None
    return await run_decision(
        DecisionInferenceRequest(
            llm_id=decision.id,
            fallback_llm_id=companion.id if allow_fallback else None,
            allow_text_fallback=allow_fallback,
            prompt=prompt,
            system_prompt=system_prompt,
            task_id=task_id,
            agent_id=agent_id,
            purpose=purpose,
            model_field=model_field,
            count_tokens_before_request=False,
            questions=questions,
        )
    )
