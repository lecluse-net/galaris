from types import SimpleNamespace
from dataclasses import replace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import AgentRunContext
from app.conversation import ConversationTurn
from app.conversation import task_objective
from app.llm import LLMCallPurpose, StructuredOutputRetry, model_usages
from core.params import Params
from core.util import visible_text


def _turn() -> ConversationTurn:
    return ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=7,
        language="fr",
        objective="@task vas-y, fais-le",
        messages=(
            {
                "external_message_id": "previous",
                "text": "Prépare le rapport et conserve le HTML.",
                "sender_external_id": "nicolas",
                "sender_display_name": "Nicolas",
                "attachments": [
                    {
                        "local_id": str(uuid4()),
                        "name": "chiffres.xlsx",
                        "uri": "matrix://room/chiffres.xlsx",
                    }
                ],
            },
            {
                "external_message_id": "current",
                "text": "@task vas-y, fais-le",
                "sender_external_id": "nicolas",
                "sender_display_name": "Nicolas",
            },
        ),
        messaging_context={
            "connection_id": 19,
            "platform": "matrix",
            "room_id": "room-1",
        },
        linked_work=(
            {
                "task_id": str(uuid4()),
                "revision": 2,
                "status": "SUCCESS",
                "label": "Rapport existant",
                "objective": "Produire le rapport HTML.",
                "working_set": [
                    {
                        "role": "output",
                        "resource_type": "document",
                        "reference": "document://report/current",
                        "revision": "3",
                    }
                ],
            },
        ),
        reasoning_effort_override="xhigh",
    )


@pytest.mark.parametrize("source, origin", [
    ("Garde exactement <script>exemple()</script> & les valeurs < 7.\nExporte en CSV.", "text"),
    ("Oui, fais-le avec ces restrictions.", "text"),
    ("[file: mesures.csv] matrix://room/mesures.csv", "text"),
    (None, "voice"),
])
def test_task_keeps_original_request_separate_from_incomplete_context(source, origin):
    turn = replace(_turn(), source_request=source, origin=origin)
    context = "<p>Utiliser le catalogue fictif ; conserver les filtres demandés auparavant.</p>"

    objective = task_objective.compose_task_objective(turn, context)

    expected_source = source if source is not None else turn.objective
    assert expected_source in visible_text(objective)
    assert visible_text(context) in visible_text(objective)
    assert "<script>" not in objective
    # Fallback callers, especially voice, must not quote their entire history as a new request.
    assert "Prépare le rapport et conserve le HTML." not in visible_text(objective)


@pytest.mark.asyncio
async def test_task_fields_use_standard_model_and_complete_conversation_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = _turn()
    agent = SimpleNamespace(
        id=7,
        code="alice",
        first_name="Alice",
        last_name="Agent",
        agent_driver="internal",
        title=SimpleNamespace(gender="F"),
        personality=None,
        job_description=None,
        job_title="Analyste",
    )
    llm = SimpleNamespace(id=42)
    get_agent = AsyncMock(return_value=agent)
    get_llm = AsyncMock(return_value=llm)
    get_prompt = AsyncMock(
        return_value=task_objective.built_in_task_objective_system_prompt()
    )
    build_context = AsyncMock(
        return_value=AgentRunContext(
            # A context provider may deliberately return no Messenger history when its
            # contact scope is unresolved. The frozen admitted turn must still survive.
            conversation_history=(),
            memory_context="Le rapport doit également être livré en PDF.",
            continuity_context="Ressource active: document://report/current",
        )
    )
    inference = SimpleNamespace(
        output=SimpleNamespace(
            label="Mise à jour du rapport",
            objective=(
                "Mettre à jour document://report/current avec les chiffres de "
                "matrix://room/chiffres.xlsx, conserver le HTML et produire le PDF."
            ),
        ),
        cost=0.125,
    )
    run = AsyncMock(return_value=inference)
    monkeypatch.setattr(task_objective, "get_agent_record", get_agent)
    monkeypatch.setattr(task_objective.llm_service, "get_profile_llm", get_llm)
    monkeypatch.setattr(task_objective.params_service, "get_or_default", get_prompt)
    monkeypatch.setattr(task_objective, "build_agent_run_context", build_context)
    monkeypatch.setattr(task_objective, "run_structured", run)

    label, objective, cost = await task_objective.generate_task_fields(
        turn,
        label_hint="Rapport",
        objective_hint="vas-y, fais-le",
    )

    assert label == "Mise à jour du rapport"
    assert "matrix://room/chiffres.xlsx" in objective
    assert cost == 0.125
    get_llm.assert_awaited_once_with(model_usages.EXECUTOR, agent=agent)
    get_prompt.assert_awaited_once_with(Params.AI_TASK_OBJECTIVE_SYSTEM_PROMPT)
    request = build_context.await_args.args[0]
    assert request.contact_memory_item_id == turn.contact_memory_item_id
    assert request.fallback_history == turn.messages
    assert request.task_data["room_id"] == "room-1"
    assert request.task_data["sender.user_id"] == "nicolas"
    assert request.task_data["sender.nickname"] == "Nicolas"
    kwargs = run.await_args.kwargs
    assert kwargs["llm"] is llm
    assert kwargs["conversation_round_id"] == turn.round_id
    assert kwargs["purpose"] == LLMCallPurpose.CONVERSATION_TASK_OBJECTIVE
    assert kwargs["reasoning_effort_override"] == "xhigh"
    assert "@task vas-y, fais-le" in kwargs["prompt"]
    assert "vas-y, fais-le" in kwargs["prompt"]
    assert "Prépare le rapport et conserve le HTML." in kwargs["prompt"]
    assert "Le rapport doit également être livré en PDF." in kwargs["prompt"]
    assert "document://report/current" in kwargs["prompt"]
    assert "matrix://room/chiffres.xlsx" in kwargs["prompt"]
    system_prompt = " ".join(kwargs["system_prompt"].split())
    assert "automatically returns the terminal result" in system_prompt
    assert "not work to add to the objective" in system_prompt
    assert "only when the user explicitly requested it as the work itself" in system_prompt
    assert "Never infer such an action" in system_prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_origin", ["absent", "request", "history", "hint", "continuity"])
async def test_task_fields_reject_model_invented_resource_references(
    monkeypatch: pytest.MonkeyPatch,
    reference_origin: str,
) -> None:
    turn = _turn()
    probe = "https://example.test/robots.txt"
    inspected = "https://example.test/metadata-only"
    source = "https://example.test/research"
    produced = "https://example.test/published-report"
    attachment = f"document://{uuid4()}/attachments/{uuid4()}"
    linked = dict(turn.linked_work[0])
    linked["working_set"] = [*linked["working_set"],
        {"role": "probe", "resource_type": "artifact", "reference": probe,
         "metadata": {"last_operation": "file_read"}},
        {"role": "inspection", "resource_type": "artifact", "reference": inspected,
         "metadata": {"last_operation": "file_info"}},
        {"role": "source", "resource_type": "artifact", "reference": source,
         "metadata": {"last_operation": "file_read"}},
        {"role": "published", "resource_type": "artifact", "reference": produced,
         "metadata": {"last_operation": "file_info", "produced": True}},
        {"role": "attachment", "resource_type": "artifact", "reference": attachment,
         "metadata": {"last_operation": "file_info"}},
    ]
    turn = replace(turn, linked_work=(linked,), objective=(
        f"Analyse aussi {probe}" if reference_origin == "request" else turn.objective
    ))
    agent = SimpleNamespace(
        id=7,
        code="alice",
        first_name="Alice",
        last_name="Agent",
        agent_driver="internal",
        title=None,
        personality=None,
        job_description=None,
        job_title=None,
    )
    monkeypatch.setattr(task_objective, "get_agent_record", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        task_objective.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=SimpleNamespace(id=42)),
    )
    monkeypatch.setattr(
        task_objective.params_service,
        "get_or_default",
        AsyncMock(return_value="Custom Task objective prompt"),
    )
    monkeypatch.setattr(
        task_objective,
        "build_agent_run_context",
        AsyncMock(return_value=AgentRunContext(
            conversation_history=(
                (*turn.messages, {"text": f"Diagnostic précédent : {probe}", "sender_is_ai": True})
                if reference_origin == "history" else turn.messages
            ),
            continuity_context=f"Diagnostic précédent : {probe}" if reference_origin == "continuity" else "",
        )),
    )

    async def inspect_validator(**kwargs: object) -> SimpleNamespace:
        validator = kwargs["output_validator"]
        assert callable(validator)
        output = task_objective._GeneratedTaskFields(  # pyright: ignore[reportPrivateUsage]
            label="Rapport",
            objective="Modifier document://invented/resource.",
        )
        with pytest.raises(StructuredOutputRetry):
            validator(output)
        assert source in kwargs["prompt"]
        assert produced in kwargs["prompt"]
        assert attachment in kwargs["prompt"]
        assert inspected not in kwargs["prompt"]
        assert "document://report/current" in kwargs["prompt"]
        probe_output = task_objective._GeneratedTaskFields(label="Probe", objective=f"Read {probe}")
        if reference_origin != "absent":
            # Reference validation proves provenance, not relevance. Free-text
            # history/hints remain available; do not silently redact their content.
            assert probe in kwargs["prompt"]
            assert validator(probe_output) == probe_output
        else:
            assert probe not in kwargs["prompt"]
            with pytest.raises(StructuredOutputRetry):
                validator(probe_output)
        # Filtering the preparation projection must leave the audit ledger intact.
        assert len(turn.linked_work[0]["working_set"]) == 6
        return SimpleNamespace(
            output=task_objective._GeneratedTaskFields(  # pyright: ignore[reportPrivateUsage]
                label="Rapport",
                objective="Utiliser matrix://room/chiffres.xlsx.",
            ),
            cost=0.0,
        )

    monkeypatch.setattr(task_objective, "run_structured", inspect_validator)

    await task_objective.generate_task_fields(
        turn,
        label_hint="Rapport",
        objective_hint=f"Vérifier {probe}" if reference_origin == "hint" else "vas-y",
    )


@pytest.mark.asyncio
async def test_empty_task_objective_prompt_uses_repository_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_prompt = AsyncMock(return_value=" \n ")
    monkeypatch.setattr(task_objective.params_service, "get_or_default", get_prompt)

    resolved = await task_objective.task_objective_system_prompt()

    assert resolved == task_objective.built_in_task_objective_system_prompt()
    get_prompt.assert_awaited_once_with(Params.AI_TASK_OBJECTIVE_SYSTEM_PROMPT)
