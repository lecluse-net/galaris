"""One native decision per Goal cycle, with no text inference or text fallback."""

from uuid import UUID

from app.llm import LLM, LLMCallPurpose, StructuredInferenceResult, model_usages
from app.llm.facade import ChoiceQuestion, DecisionInferenceRequest, run_decision

from .facade import goal_tracking_system_prompt
from .schemas import GoalDecision
from .cycle_context import goal_cycle_work_instructions, goal_judgement_runtime_instructions


async def evaluate_goal(
    *, llm: LLM, prompt: str, system_prompt: str,
    task_id: UUID | None, agent_id: int | None,
    purpose: str = LLMCallPurpose.GOAL_TRACKING,
) -> StructuredInferenceResult[GoalDecision]:
    """Keep the specialist even when the profile allows text fallback elsewhere."""
    questions = {"action": ChoiceQuestion(
        instructions="Judge the original Goal against the supplied observations, not the author's success claim.",
        criteria={
            "CONTINUE": "At least one original criterion remains unmet or unverified. This includes blockers, failed work, unknown methods and waiting dependencies. Preserve scheduled reassessment; never pause or claim completion.",
            "STOP": "Every original completion criterion is satisfied by explicit observable evidence. No required work, verification or human decision remains. Mere activity or an author's success claim is insufficient.",
        },
    )}
    inference = await run_decision(DecisionInferenceRequest(
        llm_id=llm.id, fallback_llm_id=None, allow_text_fallback=False,
        questions=questions, prompt=prompt,
        system_prompt=system_prompt + "\n\n" + goal_judgement_runtime_instructions(),
        task_id=task_id, agent_id=agent_id, purpose=purpose,
        model_field=model_usages.DECISION, request_limit=1,
        count_tokens_before_request=False,
    ))
    inference.output.validate_questions(questions)
    return StructuredInferenceResult(
        output=GoalDecision.model_validate({"action": inference.output.answers["action"].choice}),
        cost=inference.cost, messages=inference.messages,
    )


__all__ = ["GoalDecision", "evaluate_goal", "goal_tracking_system_prompt", "goal_cycle_work_instructions"]
