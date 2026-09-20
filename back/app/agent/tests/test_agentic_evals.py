"""Dispatcher evaluations through the SDK and durable API, with provider HTTP replaced."""

from dataclasses import dataclass
import json
import time
from typing import cast

import pytest
from pydantic_evals import Case, Dataset
from pydantic_evals.evaluators import Equals

from app.agent.contracts import DispatchDecision, ForcedRoute
from app.agent.dispatcher import Dispatcher
from tests import conftest as protocols
from tests import test_inference_lifecycle as lifecycle
from tests.test_dispatcher_inference import dispatch_context

runtime = lifecycle.runtime
responses_sse = protocols.responses_sse


@dataclass(frozen=True)
class DispatchEvalInput:
    model_route: str
    allowed_routes: tuple[str, ...]
    forced_route: ForcedRoute | None = None


@pytest.mark.asyncio
async def test_dispatcher_validates_structured_output(runtime) -> None:
    db, llm, requests, mode = runtime
    context, options, _, _ = await dispatch_context(db, "task")
    mode.update(
        structured=True,
        outputs=[json.dumps({"route": "EXEC", "effort": "standard", "language": "fr"})],
    )
    result = await Dispatcher()._infer_dispatch(
        context,
        time.time(),
        "Route the request.",
        "Answer the request.",
        clamp_to=("EXEC", "PLAN"),
        llm_override=llm,
        **options,
    )

    assert result.success is True
    assert result.decision == DispatchDecision(
        reasoning="",  # Inferred routing deliberately excludes generated prose.
        route="EXEC",
        effort="standard",
        language="fr",
    )
    assert len(requests) == 1
    assert requests[0]["tools"]
    assert "route" in requests[0]["tools"][0]["function"]["parameters"]["required"]


@pytest.mark.asyncio
async def test_dispatcher_behavior_dataset(runtime) -> None:
    db, llm, requests, mode = runtime
    dataset: Dataset[DispatchEvalInput, str, None] = Dataset(
        name="dispatcher-routing-contract",
        cases=[
            Case(
                name="plan_allowed",
                inputs=DispatchEvalInput("PLAN", ("EXEC", "PLAN")),
                evaluators=(Equals("PLAN"),),
            ),
            Case(
                name="forced_execution_wins",
                inputs=DispatchEvalInput("PLAN", ("EXEC", "PLAN"), "EXEC"),
                evaluators=(Equals("EXEC"),),
            ),
        ],
    )

    async def run_case(inputs: DispatchEvalInput) -> str:
        context, options, _, _ = await dispatch_context(db, "task")
        output = json.dumps(
            {
                "reasoning": "Decision controlled by the harness.",
                "route": inputs.model_route,
                "effort": "standard",
                "language": "fr",
            }
        )
        mode.update(structured=True, outputs=[output] * (len(requests) + 1))
        result = await Dispatcher()._infer_dispatch(
            context,
            time.time(),
            "Route the request.",
            "Evaluation request.",
            clamp_to=inputs.allowed_routes,
            force_route=inputs.forced_route,
            llm_override=llm,
            **options,
        )
        return cast(str, result.decision.route)

    report = await dataset.evaluate(run_case, progress=False, max_concurrency=1)
    averages = report.averages()
    assert averages is not None
    assert averages.assertions == 1.0
    assert len(requests) == len(dataset.cases)
