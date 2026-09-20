import re

from app.llm import LLMCallPurpose, ReasoningEffort, model_usages
from app.llm.facade import llm_call_accounting, record_structured_inferences
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Any, TypeVar, cast
from uuid import UUID, uuid4
from openai import ContentFilterFinishReasonError
from pydantic import create_model
from loguru import logger
from core.i18n import SUPPORTED_LANGUAGES
from core.params import Params, params_service
from app.llm.structured_service import (
    StructuredInferenceResult,
    run_prompted,
    run_structured,
)
from app.llm.provider_models import LLM
from .contracts import (
    AgentTask,
    AgentDriverSpec,
    DriverPipelinePolicy,
    ActiveDispatchDecision,
    TaskDispatchDecision,
    ConversationDispatchDecision,
    DispatchDecision,
    DispatchRoute,
    DispatchResult,
    ExecutionEffort as Effort,
    ForcedRoute,
    OBJECTIVE_IS_STANDALONE_DATA_KEY,
)
from .conversation_context import conversation_context_block, current_message_data
from .model_resolver import has_agent_profile_model, require_agent_profile_model
from .registry import get_driver_spec


DispatchOutputT = TypeVar(
    "DispatchOutputT",
    ActiveDispatchDecision,
    TaskDispatchDecision,
    ConversationDispatchDecision,
)


# Frozen v1/v2 requests retain their original schemas; new Task calls use v3.
_LegacyActiveDispatchDecision = create_model(
    "ActiveDispatchDecision", __base__=ActiveDispatchDecision,
    __doc__=ActiveDispatchDecision.__doc__, requires_action=(bool, False),
)
_LegacyConversationDispatchDecision = create_model(
    "ConversationDispatchDecision", __base__=ConversationDispatchDecision,
    __doc__=ConversationDispatchDecision.__doc__, requires_action=(bool, False),
)


def register_dispatcher_output_contracts() -> None:
    from app.llm.facade import register_inference_output

    register_inference_output("galaris.dispatcher.active/v1", _LegacyActiveDispatchDecision)
    register_inference_output("galaris.dispatcher.conversation/v1", _LegacyConversationDispatchDecision)
    register_inference_output("galaris.dispatcher.active/v2", ActiveDispatchDecision)
    register_inference_output("galaris.dispatcher.active/v3", TaskDispatchDecision)
    register_inference_output("galaris.dispatcher.conversation/v2", ConversationDispatchDecision)


async def _run_dispatch_inference(
    *,
    llm: LLM,
    output_type: type[DispatchOutputT],
    prompted: bool,
    prompt: str,
    system_prompt: str,
    task_id: UUID | None,
    agent_id: int | None,
    agent_run_id: UUID | None,
    conversation_round_id: UUID | None,
    purpose: LLMCallPurpose,
    reasoning_effort_override: ReasoningEffort | None,
) -> StructuredInferenceResult[DispatchOutputT]:
    """Use prompt-described JSON for conversations and output tools for durable Tasks."""

    register_dispatcher_output_contracts()
    with record_structured_inferences():
        if prompted:
            return await run_prompted(
                llm=llm,
                output_type=output_type,
                prompt=prompt,
                system_prompt=system_prompt,
                task_id=task_id,
                agent_id=agent_id,
                temperature=0.0,
                request_limit=3,
                max_tokens=256,
                output_retries=0,
                agent_run_id=agent_run_id,
                conversation_round_id=conversation_round_id,
                purpose=purpose,
                model_field=model_usages.DISPATCHER,
                reasoning_effort_override=reasoning_effort_override,
            )
        return await run_structured(
            llm=llm,
            output_type=output_type,
            prompt=prompt,
            system_prompt=system_prompt,
            task_id=task_id,
            agent_id=agent_id,
            temperature=0.0,
            request_limit=3,
            max_tokens=256,
            agent_run_id=agent_run_id,
            conversation_round_id=conversation_round_id,
            purpose=purpose,
            model_field=model_usages.DISPATCHER,
            reasoning_effort_override=reasoning_effort_override,
        )


@dataclass(frozen=True)
class _EvaluationAgentContext:
    """Minimal agent policy context reconstructed from one Lab JSON input."""

    agent_driver: str
    pipeline_policy: DriverPipelinePolicy | None = None


@dataclass(frozen=True)
class _EvaluationSenderContext:
    id: str
    display_name: str
    agent_id: int | None = None

    @property
    def is_ai(self) -> bool:
        return self.agent_id is not None


@dataclass(frozen=True)
class _EvaluationMessageContext:
    id: str
    text: str
    time: int
    sender: _EvaluationSenderContext | None

    @property
    def is_ai(self) -> bool:
        return bool(self.sender and self.sender.is_ai)


@dataclass(frozen=True)
class _ConversationDispatchContext:
    """Minimal non-durable context used by the conversation reply gate."""

    id: UUID
    run_id: UUID
    agent_id: int
    objective: str
    messages: tuple[Mapping[str, object], ...]
    language: str
    agent: Any | None = None

    @property
    def data(self) -> Mapping[str, object] | None:
        if not self.messages:
            return {"language": self.language, "sender_is_ai": True}
        return current_message_data(self.messages[-1], language=self.language)

    @property
    def message_platform(self) -> str:
        return "conversation"


@dataclass
class _EvaluationTaskContext:
    """Mutable, non-persistent task view consumed by the real Dispatcher."""

    id: UUID
    label: str
    objective: str | None
    effort: str
    forced_route: str | None
    forced_effort: str | None
    auto_approve: bool
    agent_id: int | None
    message_platform: str | None
    message_group_id: str | None
    data: dict[str, Any]
    messages: list[_EvaluationMessageContext]
    parent_id: UUID | None
    shared_context: str
    agent: _EvaluationAgentContext

    @classmethod
    def from_input(cls, input_data: Mapping[str, Any]) -> "_EvaluationTaskContext":
        driver_code = str(input_data.get("driver_code") or "internal")
        policy_input: dict[str, Any] = {
            "execution_efforts": frozenset({"standard", "high"}),
            "uses_llm_calls": get_driver_spec(driver_code).pipeline_policy.uses_llm_calls,
        }
        policy_input.update(input_data.get("pipeline_policy") or {})
        raw_data = input_data.get("data")
        task_data: dict[str, Any] = (
            dict(cast(Mapping[str, Any], raw_data)) if isinstance(raw_data, Mapping) else {}
        )
        raw_messages = input_data.get("messages")
        messages = (
            [
                cls._message_from_input(cast(Mapping[str, Any], item))
                for item in cast(list[Any], raw_messages)
                if isinstance(item, Mapping)
            ]
            if isinstance(raw_messages, list)
            else []
        )
        return cls(
            id=uuid4(),
            label=str(input_data.get("label") or ""),
            objective=cls._optional_text(input_data.get("objective")),
            effort=str(input_data.get("effort") or "standard"),
            forced_route=cls._optional_text(input_data.get("forced_route")),
            forced_effort=cls._optional_text(input_data.get("forced_effort")),
            auto_approve=bool(input_data.get("auto_approve")),
            agent_id=cls._optional_int(input_data.get("agent_id")),
            message_platform=cls._optional_text(input_data.get("message_platform")),
            message_group_id=cls._optional_text(input_data.get("message_group_id")),
            data=task_data,
            messages=messages,
            parent_id=cls._optional_uuid(input_data.get("parent_id")),
            shared_context=str(input_data.get("shared_context") or ""),
            agent=_EvaluationAgentContext(
                agent_driver=str(input_data.get("driver_code") or "internal"),
                pipeline_policy=DriverPipelinePolicy(**policy_input)
                if input_data.get("pipeline_policy")
                else None,
            ),
        )

    @classmethod
    def _message_from_input(cls, value: Mapping[str, Any]) -> _EvaluationMessageContext:
        raw_sender = value.get("sender")
        sender = None
        if isinstance(raw_sender, Mapping):
            sender_input = cast(Mapping[str, Any], raw_sender)
            sender = _EvaluationSenderContext(
                id=str(sender_input.get("id") or ""),
                display_name=str(sender_input.get("display_name") or ""),
                agent_id=cls._optional_int(sender_input.get("agent_id")),
            )
        return _EvaluationMessageContext(
            id=str(value.get("id") or ""),
            text=str(value.get("text") or ""),
            time=cls._optional_int(value.get("time")) or 0,
            sender=sender,
        )

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text if text else None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        return None

    @staticmethod
    def _optional_uuid(value: Any) -> UUID | None:
        if value is None:
            return None
        try:
            return UUID(str(value))
        except TypeError, ValueError, AttributeError:
            return None


# Conversation-only AI-to-AI loop guards. Durable Task dispatch never uses END.
AI_BURST_WINDOW_SECONDS = 60
AI_BURST_MAX = 20
AI_EXCHANGE_MAX_DEPTH = 5
AI_EXCHANGE_GAP_SECONDS = 600
DISPATCHER_HISTORY_MAX_MESSAGES = 10
DISPATCHER_HISTORY_MAX_CHARS_PER_MESSAGE = 500

# Read routing tags before inference. The negative lookbehind avoids addresses such as
# ``email@exec.com``.
_DISPATCH_TAG_RE = re.compile(
    r"(?<!\w)@(exec|plan|briefing|approve|high|standard)\b",
    re.IGNORECASE,
)

_DISPATCHER_SYSTEM_PROMPT = """
You are the main Dispatcher of the enterprise system.
Your role is to analyze the incoming task and select exactly one route from the routes explicitly listed as available in this prompt.

Do not infer, mention, or select any route that is not listed in the available routes section. If only one route is listed, use that route. Prefer the simplest available route that can satisfy the task.

Route and effort are separate decisions. Start from EXEC with effort "standard", then escalate
only when the task requires another available choice: EXEC "high", BRIEFING, or PLAN.
BRIEFING prepares one work unit before execution; it is optional and separate from EXEC high.

Choose between them with these definitions:
- EXEC with effort "standard" is the default: conversation, a direct answer, a clarification, or
  one bounded and deterministic outcome with an explicit target, a straightforward method, and
  simple completion checks. It may use several tightly related tool calls and may mutate, delete,
  overwrite, send, or otherwise cause side effects when the exact action and target are already
  authorized. Operational risk changes the required safeguards, not the effort level.
- EXEC with effort "high" is the preferred route for ONE coherent outcome or deliverable that
  needs non-trivial judgment, substantial context recovery, competing hypotheses, complex
  diagnosis or recovery, many coupled decisions, or challenging creative or technical work.
  Research, production, review, validation, and delivery remain one EXEC "high" run when they all
  serve the same final artifact or immediate outcome. A long run, many tools, explicit
  verification, or several lifecycle phases do not by themselves justify high or PLAN.
- PLAN is reserved for SEVERAL independently executable work units or deliverables whose durable
  intermediate results must be coordinated. Each planned unit must be a meaningful, verifiable
  assignment on its own, and the objective must benefit from durable checkpoints, fan-out/fan-in,
  specialization, or recovery across those units. PLAN is about decomposability and coordination,
  not difficulty, duration, or the number of steps one executor may perform.

Do not split a single website, visual, report, document, code change, or other cohesive artifact
into a PLAN merely because producing it includes research, construction, refinement, testing,
review, or delivery. Choose EXEC "high" for that work so one executor retains end-to-end context.
When uncertain between EXEC "high" and PLAN, choose EXEC "high". Select PLAN only when the task
contains at least two independently executable work units whose durable coordination improves
reliability. If the selected route is PLAN, set effort to "high".

Do not choose EXEC "high" solely because the task corrects a previous action, touches an existing
artifact, names a recipient, has external side effects, uses several tools, or performs an
authorized destructive command such as deleting a known file or resetting one exact repository.
Those properties require precise scope checks and normal safety controls, but a bounded mechanical
operation remains EXEC "standard". Choose high only when actual cognitive complexity means that a
stronger model or execution briefing would materially help.

You must also detect the task/user language:
- Choose exactly one language code from the available Galaris languages: ${languages}.
- If the language is unclear, unsupported, mixed, or not relevant, use "en".
- Use the same detected language for any user-facing planner/executor communication.

Return only the routing fields defined by the output schema. Do not generate a justification or
explanation for the decision.
""".strip()

_CONVERSATION_DISPATCHER_SYSTEM_PROMPT = """
You are the lightweight gate for a short foreground conversation.

For a message from another AI, decide whether it needs a useful reply:
- EXEC: reply because the peer asked a question, requested work, introduced a genuinely new
  element that needs an answer, or requires a concrete action to move the exchange forward.
- END: close this round without replying because the message is an acknowledgement, thanks,
  confirmation, repetition, opinion without new substance, or natural closure.

This profile cannot plan or decompose work. EXEC is always a direct, standard conversation run.
When in doubt after the first exchange, prefer END so agents do not sustain courtesy loops.

Detect the message language and return one of: ${languages}.

Return only the routing fields defined by the output schema. Do not generate a justification or
explanation for the decision.
""".strip()


def dispatcher_system_prompt() -> str:
    """Return the base prompt before task-specific policy constraints are appended."""
    return _DISPATCHER_SYSTEM_PROMPT.replace("${languages}", ", ".join(SUPPORTED_LANGUAGES))


class Dispatcher:
    """Choose one permitted Task path, inferring only when alternatives remain.

    Creation-time route and effort overrides are honored without reinterpretation.
    Driver capabilities retain higher priority.
    """

    async def run(
        self,
        task: AgentTask,
        use_default_params: bool = False,
        use_memory: bool = False,
        *,
        system_prompt_override: str | None = None,
        llm_override: LLM | None = None,
        record_task_trace: bool = True,
    ) -> DispatchResult:
        start_time = time.time()

        spec = await self._resolve_task_driver(task)
        choices, policy_notes = self._task_choices(task, spec)
        routes = {route for route, _effort in choices}

        def finish(result: DispatchResult) -> DispatchResult:
            return self.trace_result(task, result, routes, policy_notes, spec=spec, choices=choices)

        if not choices:
            return finish(DispatchResult(
                prompt="",
                success=False,
                decision=DispatchDecision(
                    route="EXEC", language=self._task_language(task),
                    reasoning=(
                        f"Task constraints are incompatible with harness {spec.code}: "
                        f"route={task.forced_route or 'auto'}, effort={task.forced_effort or task.effort or 'auto'}. "
                        f"Available choices: {spec.pipeline_policy.dispatch_choices()}."
                    ),
                ),
                execution_time=time.time() - start_time,
            ))
        if len(choices) == 1:
            route, effort = choices[0]
            result = self._forced_decision_result(
                start_time, route, effort, language=self._task_language(task),
            )
            result.decision.reasoning = "Only one execution choice remains; no dispatcher inference is needed."
            return finish(result)

        # Resolve the model only after capabilities and explicit constraints.
        if llm_override is None and not await has_agent_profile_model(task.agent, model_usages.DISPATCHER):
            route, effort = choices[0]
            result = self._forced_decision_result(
                start_time, route, effort, language=self._task_language(task),
            )
            result.decision.reasoning = "No dispatcher model is configured; using the simplest permitted choice."
            policy_notes.append("Dispatcher model not configured")
            return finish(result)

        forced_route = choices[0][0] if len(routes) == 1 else None
        efforts = {effort for _route, effort in choices}
        forced_effort = choices[0][1] if len(efforts) == 1 else None
        _ = use_default_params, use_memory
        system_prompt, human_prompt = await self.render_prompts(
            task, routes, forced_route, forced_effort, system_prompt_override,
            spec=spec, choices=choices,
        )
        inference_options: dict[str, Any] = {}
        if llm_override is not None:
            inference_options["llm_override"] = llm_override
        if not record_task_trace:
            inference_options["record_task_trace"] = False
        with llm_call_accounting() as accounting:
            result = await self._infer_dispatch(
                task, start_time, system_prompt, human_prompt,
                clamp_to=tuple(sorted(routes)), force_route=forced_route,
                force_effort=forced_effort, **inference_options,
            )
        if accounting.costs:
            result.cost = accounting.cost
        if (result.decision.route, result.decision.effort) not in choices:
            result.decision.route, result.decision.effort = choices[0]
            policy_notes.append("Unavailable inferred choice replaced by the simplest permitted choice")
        return finish(result)

    async def _resolve_task_driver(self, task: AgentTask) -> AgentDriverSpec:
        spec = self._task_executor_driver(task)
        agent = task.agent
        if isinstance(agent, _EvaluationAgentContext) or not isinstance(getattr(agent, "id", None), int):
            return spec
        from .harness_port import harness_selection_port

        selected = await harness_selection_port.resolve(agent)
        if selected is None:
            return spec
        if selected.driver_code != spec.code:
            raise ValueError("Selected harness does not match the Task driver.")
        return replace(spec, pipeline_policy=selected.pipeline_policy) if selected.pipeline_policy else spec

    def _task_choices(
        self, task: AgentTask, spec: AgentDriverSpec,
    ) -> tuple[tuple[tuple[ForcedRoute, Effort], ...], list[str]]:
        choices = spec.pipeline_policy.dispatch_choices()
        routes = {route for route, _effort in choices}
        ignored: list[str] = []
        self._apply_message_tags(task, allowed_routes=set(routes), ignored_tags=ignored)
        notes = ["Choices derived from the selected harness's declared pipeline capabilities"]
        if ignored:
            notes.append("Ignored unsupported message directives: " + ", ".join(ignored))
        raw_route = str(task.forced_route or "").strip().upper()
        raw_effort = str(task.forced_effort or "").strip().lower()
        if raw_route and raw_route not in {"EXEC", "BRIEFING", "PLAN"}:
            return (), [*notes, "Invalid forced route"]
        if raw_effort and raw_effort not in {"standard", "high"}:
            return (), [*notes, "Invalid forced effort"]
        if task.parent_id is not None:
            # Planner/delegation children already carry the execution effort.
            choices = tuple(item for item in choices if item[0] == "EXEC")
            raw_effort = raw_effort or ("high" if task.effort == "high" else "standard")
            notes.append("Child uses the assigned execution effort without replanning")
        choices = tuple(item for item in choices
                        if (not raw_route or item[0] == raw_route)
                        and (not raw_effort or item[1] == raw_effort))
        return choices, notes

    async def run_conversation(
        self,
        task: AgentTask | None = None,
        *,
        round_id: UUID | None = None,
        run_id: UUID | None = None,
        agent_id: int | None = None,
        language: str | None = None,
        objective: str | None = None,
        messages: Sequence[Mapping[str, object]] = (),
        sender_is_ai: bool | None = None,
        agent: Any | None = None,
        agent_loader: Callable[[], Awaitable[Any | None]] | None = None,
    ) -> DispatchResult:
        """Reply directly to humans; gate only peer replies through inference."""

        start_time = time.time()
        if task is not None:
            context: AgentTask = task
            effective_round_id = task.id
            effective_run_id = task.id
            effective_language = self._task_language(task)
            effective_objective = str(task.objective or "")
            effective_sender_is_ai = self._sender_is_ai(task)
        else:
            if round_id is None or run_id is None or agent_id is None:
                raise ValueError("Conversation dispatch requires round_id, run_id, and agent_id.")
            conversation_context = _ConversationDispatchContext(
                id=round_id,
                run_id=run_id,
                agent_id=agent_id,
                objective=str(objective or ""),
                messages=tuple(messages),
                language=str(language or "en"),
                agent=agent,
            )
            context = cast(AgentTask, conversation_context)
            effective_round_id = round_id
            effective_run_id = run_id
            effective_language = str(language or "en")
            effective_objective = str(objective or "")
            effective_sender_is_ai = bool(sender_is_ai)
        policy_notes = [
            "Conversation profile: direct standard execution only; planner and briefing disabled"
        ]
        depth = 0

        if effective_sender_is_ai:
            depth = self._ai_exchange_depth(context)
            if depth >= AI_EXCHANGE_MAX_DEPTH:
                return self._conversation_trace_result(
                    self._depth_end_result(start_time, depth),
                    policy_notes=[*policy_notes, "END enforced by the exchange depth cap"],
                    allowed_routes=["END"],
                )
            burst, count, max_burst, window = await self._ai_burst_detected(context)
            if burst:
                return self._conversation_trace_result(
                    self._burst_end_result(start_time, count, max_burst, window),
                    policy_notes=[*policy_notes, "END enforced by the AI message burst cap"],
                    allowed_routes=["END"],
                )

            toggle = await params_service.get(Params.MESSENGER_AI_GATE, "on")
            if str(toggle).strip().lower() in ("off", "0", "false", "no", ""):
                return self._conversation_trace_result(
                    self._exec_decision_result(
                        start_time,
                        "AI contribution gate disabled; replying through direct execution.",
                        effort="standard",
                        language=effective_language,
                    ),
                    policy_notes=[*policy_notes, "AI contribution gate disabled"],
                    allowed_routes=["EXEC"],
                )

        if not effective_sender_is_ai:
            result = self._conversation_trace_result(
                self._exec_decision_result(
                    start_time,
                    "Human conversation; direct execution without dispatcher inference.",
                    effort="standard",
                    language=effective_language,
                ),
                policy_notes=[*policy_notes, "Human sender: dispatcher inference not needed"],
                allowed_routes=["EXEC"],
            )
            result.conversation_route_directive = self._conversation_route_directive(
                effective_objective
            )
            return result

        if task is None and context.agent is None and agent_loader is not None:
            # Only an AI reply gate that survives the deterministic checks needs
            # agent-specific dispatcher settings.
            context = cast(
                AgentTask,
                replace(
                    cast(_ConversationDispatchContext, context),
                    agent=await agent_loader(),
                ),
            )

        if not await has_agent_profile_model(context.agent, model_usages.DISPATCHER):
            return self._conversation_trace_result(
                self._exec_decision_result(
                    start_time,
                    "No dispatcher model is configured; replying through direct execution.",
                    effort="standard",
                    language=effective_language,
                ),
                policy_notes=[*policy_notes, "Dispatcher model not configured"],
                allowed_routes=["EXEC"],
            )

        system_prompt = _CONVERSATION_DISPATCHER_SYSTEM_PROMPT.replace(
            "${languages}", ", ".join(SUPPORTED_LANGUAGES)
        )
        system_prompt += self._ai_gate_instruction(depth)
        human_prompt = self._make_conversation_context(context) or effective_objective
        allowed_routes: tuple[DispatchRoute, ...] = ("EXEC", "END")
        with llm_call_accounting() as accounting:
            result = await self._infer_dispatch(
                context,
                start_time,
                system_prompt,
                human_prompt,
                clamp_to=allowed_routes,
                force_effort="standard",
                allow_end=True,
                record_task_trace=False,
                agent_run_id=effective_run_id,
                conversation_round_id=effective_round_id,
            )
        if accounting.costs:
            result.cost = accounting.cost
        result.decision.effort = "standard"
        return self._conversation_trace_result(
            result,
            policy_notes=policy_notes,
            allowed_routes=list(allowed_routes),
        )

    @staticmethod
    def _conversation_trace_result(
        result: DispatchResult,
        *,
        policy_notes: list[str],
        allowed_routes: list[DispatchRoute] | None = None,
    ) -> DispatchResult:
        result.driver_code = "internal"
        result.allowed_routes = allowed_routes or ["EXEC", "END"]
        result.policy_notes = policy_notes
        result.pipeline_policy = {
            "use_planner": False,
            "use_briefing": False,
            "briefing_efforts": [],
        }
        result.decision.effort = "standard"
        return result

    def trace_result(
        self,
        task: AgentTask,
        result: DispatchResult,
        allowed_routes: set[str],
        policy_notes: list[str],
        *,
        spec: AgentDriverSpec | None = None,
        choices: tuple[tuple[ForcedRoute, Effort], ...] | None = None,
    ) -> DispatchResult:
        """Attach the exact driver policy used to make a routing decision."""

        spec = spec or self._task_executor_driver(task)
        result.driver_code = spec.code
        result.allowed_routes = [
            route for route in ("EXEC", "BRIEFING", "PLAN", "END") if route in allowed_routes
        ]  # type: ignore[assignment]
        result.policy_notes = list(policy_notes)
        result.pipeline_policy = {
            "use_planner": spec.pipeline_policy.use_planner,
            "use_briefing": spec.pipeline_policy.use_briefing,
            "briefing_efforts": sorted(spec.pipeline_policy.briefing_efforts),
            "execution_efforts": sorted(spec.pipeline_policy.execution_efforts),
            "uses_llm_calls": spec.pipeline_policy.uses_llm_calls,
            "dispatch_choices": [
                {"route": route, "effort": effort}
                for route, effort in (choices if choices is not None else spec.pipeline_policy.dispatch_choices())
            ],
        }
        return result

    @staticmethod
    def _tag_source_text(task: AgentTask) -> str:
        """Return current message, last OpenAI message, or background objective for tags."""
        data = task.data if isinstance(task.data, dict) else {}
        text = data.get("text")
        if isinstance(text, str) and text.strip():
            return text
        for message in reversed(list(task.messages or [])):
            message_text = getattr(message, "text", "") or ""
            if message_text.strip():
                return message_text
        return task.objective or ""

    def _apply_message_tags(
        self,
        task: AgentTask,
        *,
        allowed_routes: set[str] | None = None,
        ignored_tags: list[str] | None = None,
    ) -> list[str]:
        """Apply non-conflicting human message tags before inference.

        Existing overrides win, AI senders cannot self-escalate, and a route directive
        cannot enable a pipeline stage the selected driver did not declare. The dispatcher
        service persists any mutations. Return applied tags for audit.
        """
        if self._sender_is_ai(task):
            return []
        tags = {m.group(1).lower() for m in _DISPATCH_TAG_RE.finditer(self._tag_source_text(task))}
        if not tags:
            return []

        applied: list[str] = []
        route_tags = tags & {"exec", "plan", "briefing"}
        if len(route_tags) == 1 and task.forced_route is None:
            tag = route_tags.pop()
            route = tag.upper()
            if allowed_routes is None or route in allowed_routes:
                task.forced_route = cast(ForcedRoute, route)
                if tag == "briefing":
                    task.forced_effort = "high"
                applied.append(f"@{tag}")
            else:
                if ignored_tags is not None:
                    ignored_tags.append(f"@{tag}")
                logger.info(
                    "Dispatcher: ignored unsupported message route tag {} for task {}",
                    f"@{tag}",
                    task.id,
                )
        effort_tags = tags & {"high", "standard"}
        if len(effort_tags) == 1 and task.forced_effort is None:
            tag = effort_tags.pop()
            task.forced_effort = tag
            applied.append(f"@{tag}")
        if "approve" in tags and not task.auto_approve:
            task.auto_approve = True
            applied.append("@approve")

        if applied:
            logger.info(
                "Dispatcher: applied message tags to task {}: {}",
                task.id,
                ", ".join(applied),
            )
        return applied

    @staticmethod
    def _forced_gate(forced_route: ForcedRoute | None, forced_effort: Effort | None) -> str:
        """Tell the LLM to decide only fields that were not fixed at creation."""
        lines: list[str] = []
        if forced_route is not None:
            lines.append(
                f'The route is already fixed to "{forced_route}" by the current constraints: '
                "select it and focus only on the remaining choices (effort, language)."
            )
        if forced_effort is not None:
            lines.append(
                f'The effort level is already fixed to "{forced_effort}" by the task '
                f'constraints: set effort to "{forced_effort}" and focus only on the '
                "remaining choices (route, language)."
            )
        if not lines:
            return ""
        return "\n\n## FORCED CHOICES\n" + "\n".join(f"- {line}" for line in lines)

    def _forced_decision_result(
        self,
        start_time: float,
        route: ForcedRoute,
        effort: Effort,
        *,
        language: str,
    ) -> "DispatchResult":
        """Build a deterministic result when route and effort are both fixed."""
        decision = DispatchDecision(
            reasoning=(
                f"Route ({route}) and effort ({effort}) were fixed at task creation; "
                "dispatch is deterministic and needs no LLM inference."
            ),
            route=route,
            effort=effort,
            language=language,
        )
        return DispatchResult(
            decision=decision,
            prompt="",
            system_prompt="",
            cost=0.0,
            tools_used=[],
            success=True,
            execution_time=time.time() - start_time,
        )

    @staticmethod
    def _apply_forces(
        decision: DispatchDecision,
        force_route: ForcedRoute | None,
        force_effort: Effort | None,
    ) -> None:
        """Reapply fixed choices so inference and normalization cannot override them."""
        if force_route is not None:
            decision.route = force_route
        if force_effort is not None:
            decision.effort = force_effort

    @staticmethod
    def _task_executor_driver(task: AgentTask) -> AgentDriverSpec:
        """Resolve the task's executor driver defensively."""
        try:
            agent = task.agent
        except Exception:
            agent = None
        spec = get_driver_spec(getattr(agent, "agent_driver", None) if agent else None)
        if isinstance(agent, _EvaluationAgentContext) and agent.pipeline_policy is not None:
            return replace(spec, pipeline_policy=agent.pipeline_policy)
        return spec

    async def _routing_gate(self, routes: set[str], task: AgentTask) -> str:
        """List only allowed routes and provide the relevant conversation context."""
        lines = [
            "\n\n## AVAILABLE ROUTES",
            "Select the best route from this list only:",
        ]
        if "EXEC" in routes:
            lines.append(
                "- **EXEC**: the default route. Use standard for a small self-contained request, "
                "or high for one coherent but demanding work unit with one immediate outcome."
            )
        if "BRIEFING" in routes:
            lines.append(
                "- **BRIEFING**: prepare a focused execution briefing, then execute one cohesive "
                "work unit. Select this only when preparation adds value over direct execution."
            )
        if "PLAN" in routes:
            lines.append(
                "- **PLAN**: reserve for at least two independently executable, meaningful work "
                "units whose durable results need coordination. Do not use PLAN merely because "
                "one cohesive artifact requires several phases, tools, checks, or a long run."
            )
        if "END" in routes:
            lines.append(
                "- **END**: close the conversation without replying when an AI peer message "
                "needs no useful response."
            )
        if self._is_background_objective_task(task):
            lines.append(
                "\nContext: background objective outside a conversation. Do not acknowledge receipt."
            )
        elif "END" not in routes:
            lines.append(
                "\nContext: this Task contains work to perform. Select an available Task route; "
                "a Task cannot close a conversation without execution."
            )
        elif not self._sender_is_ai(task):
            lines.append(
                "\nContext: the message comes from a human. You must respond; never leave it without an answer."
            )
        else:
            toggle = await params_service.get(Params.MESSENGER_AI_GATE, "on")
            if str(toggle).strip().lower() not in ("off", "0", "false", "no", ""):
                lines.append(self._ai_gate_instruction(self._ai_exchange_depth(task)))
        return "\n".join(lines)

    async def _infer_dispatch(
        self,
        task: AgentTask,
        start_time: float,
        system_prompt: str,
        human_prompt: str,
        *,
        clamp_to: tuple[str, ...] | None = None,
        force_route: ForcedRoute | None = None,
        force_effort: Effort | None = None,
        llm_override: LLM | None = None,
        record_task_trace: bool = True,
        allow_end: bool = False,
        agent_run_id: UUID | None = None,
        conversation_round_id: UUID | None = None,
    ) -> "DispatchResult":
        """Run structured inference and degrade gracefully to EXEC on provider failure.

        ``clamp_to`` restricts output routes. Creation-time choices are reapplied to both
        inferred and fallback decisions.
        """
        try:
            llm = llm_override or await require_agent_profile_model(
                task.agent, model_usages.DISPATCHER
            )
            conversation_inference = not record_task_trace and conversation_round_id is not None
            inference_purpose = (
                LLMCallPurpose.AGENT_DISPATCH
                if record_task_trace or conversation_round_id is not None
                else LLMCallPurpose.LAB_DISPATCHER_JUDGE
            )
            reasoning_effort_override = cast(
                ReasoningEffort | None,
                getattr(task, "reasoning_effort_override", None),
            )
            if allow_end:
                inference = await _run_dispatch_inference(
                    llm=llm,
                    output_type=ConversationDispatchDecision,
                    prompted=conversation_inference,
                    prompt=human_prompt,
                    system_prompt=system_prompt,
                    task_id=task.id if record_task_trace else None,
                    agent_id=task.agent_id,
                    agent_run_id=agent_run_id,
                    conversation_round_id=conversation_round_id,
                    purpose=inference_purpose,
                    reasoning_effort_override=reasoning_effort_override,
                )
                decision = DispatchDecision.model_validate(inference.output.model_dump())
                inference_cost = inference.cost
            else:
                active_inference = await _run_dispatch_inference(
                    llm=llm,
                    output_type=TaskDispatchDecision,
                    prompted=conversation_inference,
                    prompt=human_prompt,
                    system_prompt=system_prompt,
                    task_id=task.id if record_task_trace else None,
                    agent_id=task.agent_id,
                    agent_run_id=agent_run_id,
                    conversation_round_id=conversation_round_id,
                    purpose=inference_purpose,
                    reasoning_effort_override=reasoning_effort_override,
                )
                decision = DispatchDecision.model_validate(active_inference.output.model_dump())
                inference_cost = active_inference.cost
            if clamp_to is not None and decision.route not in clamp_to:
                decision.route = cast(DispatchRoute, clamp_to[0])
            self._normalize_effort(decision)
            self._apply_forces(decision, force_route, force_effort)

            return DispatchResult(
                decision=decision,
                prompt=human_prompt,
                system_prompt=system_prompt,
                cost=inference_cost,
                tools_used=[],
                success=True,
                execution_time=time.time() - start_time,
            )

        except ContentFilterFinishReasonError as e:
            # Structured-output content filters can be provider noise even for harmless
            # input, so keep the task moving through its deterministic safe route.
            fallback_route = cast(DispatchRoute, "END" if allow_end else "EXEC")
            logger.warning(
                f"Dispatcher content filter for task {task.id}; "
                f"falling back to {fallback_route}: {e}"
            )
            reasoning = (
                "Dispatcher structured output was rejected by the provider content "
                f"filter; falling back to {fallback_route}."
            )
        except Exception as e:
            # Malformed provider responses must not strand a human conversation. For an
            # AI peer, END is the bounded fallback so a provider failure cannot sustain a
            # reply loop.
            fallback_route = cast(DispatchRoute, "END" if allow_end else "EXEC")
            logger.error(
                f"Unexpected dispatcher error for task {task.id}; "
                f"falling back to {fallback_route}: {e}"
            )
            reasoning = f"Unexpected dispatcher error: {e}; falling back to {fallback_route}."

        decision = DispatchDecision(
            reasoning=reasoning,
            route=fallback_route,
            effort="standard",
            language=self._task_language(task),
        )
        self._apply_forces(decision, force_route, force_effort)
        return DispatchResult(
            decision=decision,
            prompt=human_prompt,
            system_prompt=system_prompt,
            cost=0.0,
            tools_used=[],
            # The dispatcher is an advisory gate. Its structured-output protocol must not
            # make an otherwise valid foreground conversation fail: humans continue through
            # direct execution, while AI peers close the exchange above.
            success=True,
            execution_time=time.time() - start_time,
        )

    async def preview_input(
        self, input_data: Mapping[str, Any], system_prompt: str | None = None
    ) -> tuple[str, str]:
        """Render the same prompts without invoking a model or loading live Task context."""
        context = _EvaluationTaskContext.from_input(input_data)
        task = cast(AgentTask, context)
        spec = self._task_executor_driver(task)
        choices, _notes = self._task_choices(task, spec)
        if len(choices) <= 1:
            return "", ""
        routes = {route for route, _effort in choices}
        efforts = {effort for _route, effort in choices}
        return await self.render_prompts(
            task, routes, choices[0][0] if len(routes) == 1 else None,
            choices[0][1] if len(efforts) == 1 else None, system_prompt,
            spec=spec, choices=choices,
        )

    async def render_prompts(
        self,
        task: AgentTask,
        routes: set[str],
        forced_route: ForcedRoute | None,
        forced_effort: Effort | None,
        system_prompt_override: str | None,
        *,
        spec: AgentDriverSpec | None = None,
        choices: tuple[tuple[ForcedRoute, Effort], ...] | None = None,
    ) -> tuple[str, str]:
        system_prompt = system_prompt_override or dispatcher_system_prompt()
        system_prompt += await self._routing_gate(routes, task)
        if choices is not None:
            system_prompt += "\n\n## AVAILABLE EXECUTION CHOICES\nChoose exactly one of these route/effort pairs:\n"
            system_prompt += "\n".join(f"- route={route}, effort={effort}" for route, effort in choices)
        system_prompt += self._forced_gate(forced_route, forced_effort)
        human_prompt = (
            self._make_objective_prompt(task)
            if (self._is_background_objective_task(task) or self._has_standalone_objective(task))
            else await self._make_human_prompt(task)
        )
        return system_prompt, human_prompt

    async def evaluate_input(
        self,
        *,
        input_data: Mapping[str, Any],
        llm: LLM,
        system_prompt: str | None = None,
    ) -> DispatchResult:
        """Run the real Dispatcher from editable JSON without persisting a Task."""

        context = _EvaluationTaskContext.from_input(input_data)
        return await self.run(
            cast(AgentTask, context),
            llm_override=llm,
            record_task_trace=False,
            system_prompt_override=system_prompt,
        )

    @staticmethod
    def _is_background_objective_task(task: AgentTask) -> bool:
        """Return whether this is an objective outside any conversation."""
        if task.message_group_id or task.message_platform:
            return False
        if task.messages:
            return False
        return bool(task.objective and task.objective.strip())

    @staticmethod
    def _has_standalone_objective(task: AgentTask) -> bool:
        data = task.data if isinstance(task.data, Mapping) else {}
        return bool(
            data.get(OBJECTIVE_IS_STANDALONE_DATA_KEY) and task.objective and task.objective.strip()
        )

    @staticmethod
    def _make_objective_prompt(task: AgentTask) -> str:
        """Build a routing prompt for a background objective."""
        parts: list[str] = []
        if task.label:
            parts.append(f"Task: {task.label}")
        if task.objective:
            parts.append(f"Objective: {task.objective}")
        return "\n".join(parts)

    def _exec_decision_result(
        self,
        start_time: float,
        reasoning: str,
        *,
        prompt: str = "",
        system_prompt: str = "",
        effort: str = "standard",
        language: str = "en",
    ) -> "DispatchResult":
        """Build a deterministic EXEC result with an explicit reason."""
        decision = DispatchDecision(
            reasoning=reasoning,
            route="EXEC",
            effort="high" if effort == "high" else "standard",
            language=language,
        )
        return DispatchResult(
            decision=decision,
            prompt=prompt,
            system_prompt=system_prompt,
            cost=0.0,
            tools_used=[],
            success=True,
            execution_time=time.time() - start_time,
        )

    @staticmethod
    def _conversation_route_directive(objective: str) -> ForcedRoute | None:
        """Return one unambiguous human Task-route directive from a message."""

        routes = {
            match.group(1).upper()
            for match in _DISPATCH_TAG_RE.finditer(objective)
            if match.group(1).lower() in {"exec", "plan", "briefing"}
        }
        if len(routes) != 1:
            return None
        route = routes.pop()
        return cast(ForcedRoute, route)

    @staticmethod
    def _sender_is_ai(task: AgentTask) -> bool:
        """Return whether the current inbound message came from another AI."""
        data = task.data if isinstance(task.data, dict) else {}
        return bool(data.get("sender_is_ai"))

    @staticmethod
    async def _ai_burst_detected(task: AgentTask) -> tuple[bool, int, int, int]:
        """Detect a recent consecutive AI message burst for conversation routing."""
        window = AI_BURST_WINDOW_SECONDS
        max_burst = AI_BURST_MAX

        messages = list(getattr(task, "messages", None) or [])
        if not messages:
            return False, 0, max_burst, window

        ref = next(
            (
                Dispatcher._message_time(message)
                for message in reversed(messages)
                if Dispatcher._message_time(message)
            ),
            0,
        ) or int(time.time())
        count = 0
        for message in reversed(messages):
            if not Dispatcher._message_is_ai(message):
                break
            message_time = Dispatcher._message_time(message)
            if message_time and (ref - message_time) > window:
                break
            count += 1
            if count > 1000:
                break

        return count >= max_burst, count, max_burst, window

    def _burst_end_result(
        self, start_time: float, count: int, max_burst: int, window: int
    ) -> "DispatchResult":
        """Return deterministic END after a conversation AI-message burst."""
        logger.info(
            "AI loop guard: {} AI messages in <= {}s reached burst limit {}; routing END",
            count,
            window,
            max_burst,
        )
        return DispatchResult(
            decision=DispatchDecision(
                reasoning=(
                    f"AI-to-AI runaway: {count} AI messages in <= {window}s reached "
                    f"the burst limit of {max_burst}; routing END."
                ),
                route="END",
                effort="standard",
                language="en",
            ),
            prompt="",
            system_prompt="",
            cost=0.0,
            tools_used=[],
            success=True,
            execution_time=time.time() - start_time,
        )

    @staticmethod
    def _ai_exchange_depth(task: AgentTask) -> int:
        """Count consecutive AI messages in the current conversation thread."""
        messages = list(getattr(task, "messages", None) or [])
        depth = 0
        previous_time: int | None = None
        for message in reversed(messages):
            if not Dispatcher._message_is_ai(message):
                break
            message_time = Dispatcher._message_time(message)
            if (
                previous_time is not None
                and message_time
                and (previous_time - message_time) > AI_EXCHANGE_GAP_SECONDS
            ):
                break
            depth += 1
            if message_time:
                previous_time = message_time
            if depth > 1000:
                break
        return max(depth, 1)

    @staticmethod
    def _message_is_ai(message: object) -> bool:
        if isinstance(message, Mapping):
            message_data = cast(Mapping[str, object], message)
            sender = message_data.get("sender")
            if not isinstance(sender, Mapping):
                return bool(message_data.get("sender_is_ai"))
            sender_data = cast(Mapping[str, object], sender)
            agent_id = sender_data.get("agent_id")
            return isinstance(agent_id, int) and not isinstance(agent_id, bool)
        sender = getattr(message, "sender", None)
        if sender is None:
            return bool(getattr(message, "sender_is_ai", False))
        return bool(sender and getattr(sender, "id", "") and getattr(message, "is_ai", False))

    @staticmethod
    def _message_time(message: object) -> int:
        raw: object
        if isinstance(message, Mapping):
            message_data = cast(Mapping[str, object], message)
            raw = message_data.get("time", message_data.get("timestamp", 0))
        else:
            raw = getattr(message, "time", getattr(message, "timestamp", 0))
        return int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0

    @staticmethod
    def _ai_gate_instruction(depth: int) -> str:
        """Increase the conversation END threshold as an AI exchange deepens."""
        never_ok = (
            " Never route to EXEC merely to give an opinion or point of view, react, agree, "
            "disagree, comment, elaborate without new substance, acknowledge, thank, confirm, be "
            "polite, or restate what was already said — those ALWAYS go to **END**."
        )
        if depth <= 1:
            return (
                "\nContext: the message comes from another AI colleague and this is the START of "
                "the exchange. If it contains a question, a request, or anything expecting an "
                "answer, you MUST answer it → **EXEC**. Use **END** only if the message genuinely "
                "needs nothing back (a pure acknowledgement or closure)." + never_ok
            )
        if depth == 2:
            return (
                "\nContext: the message comes from another AI colleague and one round has already "
                "happened. **END is now the expected route.** Choose **EXEC** ONLY if it is really "
                "necessary — a genuinely new element, or a follow-up truly needed to move the work "
                "forward." + never_ok
            )
        return (
            f"\nContext: the message comes from another AI colleague and the exchange is already "
            f"deep (round {depth}). The bar is now VERY high: choose **EXEC** ONLY if it is truly "
            f"imperative — critical new information or a decisive concrete action. Otherwise, and "
            f"whenever in doubt, **END**." + never_ok
        )

    def _depth_end_result(self, start_time: float, depth: int) -> "DispatchResult":
        """Return deterministic END at the conversation exchange depth cap."""
        logger.info(
            "AI exchange depth cap: turn {} reached limit {}; routing END",
            depth,
            AI_EXCHANGE_MAX_DEPTH,
        )
        return DispatchResult(
            decision=DispatchDecision(
                reasoning=(
                    f"AI-to-AI exchange reached turn {depth}, at or above the "
                    f"{AI_EXCHANGE_MAX_DEPTH} turn cap; routing END."
                ),
                route="END",
                effort="standard",
                language="en",
            ),
            prompt="",
            system_prompt="",
            cost=0.0,
            tools_used=[],
            success=True,
            execution_time=time.time() - start_time,
        )

    @staticmethod
    def _normalize_effort(decision: DispatchDecision) -> None:
        """Apply non-negotiable executor effort rules."""
        if decision.route == "PLAN":
            decision.effort = "high"
        elif decision.effort not in ("standard", "high"):
            decision.effort = "standard"

    @staticmethod
    def _task_language(task: AgentTask) -> str:
        data = task.data if isinstance(task.data, dict) else {}
        language = str(data.get("language") or "").strip().lower()
        return language if language in SUPPORTED_LANGUAGES else "en"

    async def _make_human_prompt(self, task: AgentTask) -> str:
        """Build the dispatcher input from the current message and short history."""
        from .facade import build_task_context

        if isinstance(task, _EvaluationTaskContext):
            return "\n\n".join(
                part
                for part in (
                    conversation_context_block(
                        task,
                        max_messages=DISPATCHER_HISTORY_MAX_MESSAGES,
                        max_chars=DISPATCHER_HISTORY_MAX_CHARS_PER_MESSAGE,
                    ),
                    task.shared_context,
                )
                if part
            )
        context = await build_task_context(task, stage="planning")
        conversation = conversation_context_block(
            task,
            max_messages=DISPATCHER_HISTORY_MAX_MESSAGES,
            max_chars=DISPATCHER_HISTORY_MAX_CHARS_PER_MESSAGE,
            messages_override=context.conversation_history,
        )
        return "\n\n".join(part for part in (conversation, context.shared_context) if part)

    def _make_conversation_context(self, task: AgentTask) -> str:
        """Build context for messenger and OpenAI flows, or empty text outside chat."""
        return conversation_context_block(
            task,
            max_messages=DISPATCHER_HISTORY_MAX_MESSAGES,
            max_chars=DISPATCHER_HISTORY_MAX_CHARS_PER_MESSAGE,
        )


@lru_cache()
def get_dispatcher() -> Dispatcher:
    return Dispatcher()


async def evaluate_dispatcher_input(
    *,
    input_data: Mapping[str, Any],
    llm: LLM,
    system_prompt: str | None = None,
) -> DispatchResult:
    """Run a side-effect-free Dispatcher evaluation from its JSON input contract."""

    return await get_dispatcher().evaluate_input(
        input_data=input_data, llm=llm, system_prompt=system_prompt
    )


async def dispatch_conversation(
    *,
    round_id: UUID,
    run_id: UUID,
    agent_id: int,
    language: str,
    objective: str,
    messages: Sequence[Mapping[str, object]],
    sender_is_ai: bool,
    agent: Any | None = None,
    agent_loader: Callable[[], Awaitable[Any | None]] | None = None,
) -> DispatchResult:
    """Public conversation profile of the shared dispatcher."""

    return await get_dispatcher().run_conversation(
        round_id=round_id,
        run_id=run_id,
        agent_id=agent_id,
        language=language,
        objective=objective,
        messages=messages,
        sender_is_ai=sender_is_ai,
        agent=agent,
        agent_loader=agent_loader,
    )


async def preview_dispatcher_input(
    input_data: Mapping[str, Any], system_prompt: str | None = None
) -> tuple[str, str]:
    """Public prompt preview of the shared Dispatcher."""
    return await get_dispatcher().preview_input(input_data, system_prompt)
