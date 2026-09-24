import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, AsyncIterator, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.agent import (
    AIMessage,
    AgentRunContext,
    AgentRunRequest,
    DispatchDecision,
    DispatchResult,
    TaskMessage,
)
from app.conversation import (
    ConversationExecutionError,
    ConversationTurn,
)
from app.file_share import ResourceContext, ResourceTransfer
from core.params import Params, prompt_default
from app.harness import conversation as conversation_module
from app.llm import LLMCallPurpose
from app.harness.conversation import (
    HarnessConversationController,
    _LiveTextProgressBuffer,
    _current_turn_prompt,
    _existing_attachment_request,
    _logged_conversation_prompt,
    _stop_target,
    _system_prompt,
)


_ACTION_POLICY = prompt_default(Params.AI_CONVERSATION_ACTION_POLICY) or ""


@pytest.fixture(autouse=True)
def frozen_topic_scope(monkeypatch):
    """These controller units replace domain I/O; live scope has DB integration coverage."""
    async def current_scope(turn):
        return turn.topic_id, turn.contact_memory_item_id

    monkeypatch.setattr("app.conversation.facade.current_turn_scope", current_scope)


@pytest.mark.asyncio
async def test_live_text_buffer_flushes_while_the_provider_stream_is_idle() -> None:
    published: list[str] = []
    second_batch_published = asyncio.Event()

    async def publish(message: AIMessage) -> None:
        published.append(message.content)
        if len(published) == 2:
            second_batch_published.set()

    buffer = _LiveTextProgressBuffer(
        publish,
        flush_seconds=0.01,
        flush_chars=512,
    )

    await buffer.append("Bon")
    await buffer.append("jour")

    await asyncio.wait_for(second_batch_published.wait(), timeout=0.2)
    assert published == ["Bon", "jour"]
    await buffer.flush()


@pytest.mark.asyncio
async def test_live_text_buffer_drops_scheduled_text_after_cancellation() -> None:
    published: list[str] = []

    async def publish(message: AIMessage) -> None:
        published.append(message.content)

    buffer = _LiveTextProgressBuffer(
        publish,
        flush_seconds=0.02,
        flush_chars=512,
    )

    await buffer.append("Visible")
    await buffer.append("À supprimer")
    await buffer.cancel()
    await asyncio.sleep(0.03)

    assert published == ["Visible"]


@pytest.mark.asyncio
async def test_live_text_buffer_never_combines_distinct_ai_messages() -> None:
    messages: list[AIMessage] = []

    async def publish(message: AIMessage) -> None:
        messages.append(message)

    buffer = _LiveTextProgressBuffer(publish, flush_seconds=0.01)
    await buffer.append("Bon", "first")
    await buffer.append("jour", "first")
    await buffer.append("Autre message", "second")
    await buffer.flush()
    assert [(m.stream_id, m.content) for m in messages] == [
        ("first", "Bon"), ("first", "jour"), ("second", "Autre message"),
    ]


def test_voice_turn_messaging_context_preserves_transport_room_locator() -> None:
    request = cast(
        AgentRunRequest,
        SimpleNamespace(
            message_platform="voice:internal",
            message_group_id="canonical-room-uuid",
            messenger_connection_id=72,
            task_data={"room_locator": "chat:direct:1:1"},
            messaging_context={"room_id": "stale-room", "custom": "kept"},
        ),
    )

    context = conversation_module._voice_turn_messaging_context(  # pyright: ignore[reportPrivateUsage]
        request
    )

    assert context == {
        "platform": "voice:internal",
        "room_id": "canonical-room-uuid",
        "room_locator": "chat:direct:1:1",
        "connection_id": 72,
        "custom": "kept",
    }


def test_logged_conversation_prompt_keeps_only_the_actual_current_prompt() -> None:
    prompt = _logged_conversation_prompt(
        [
            TaskMessage(
                sender_display_name="Nicolas",
                timestamp=1_700_000_000,
                text="Message précédent",
            )
        ],
        "Message courant",
    )

    assert prompt == "Message courant"


def test_file_only_current_turn_keeps_attachment_in_initial_and_retry_prompts() -> None:
    attachment_id = uuid4()
    attachment_uri = f"chat://chat:direct:1:7/{attachment_id}"
    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective="The user sent one or more non-text attachments.",
        messages=(
            {
                "text": "",
                "attachments": [
                    {
                        "id": str(attachment_id),
                        "uri": attachment_uri,
                        "name": "entretien.mkv",
                    }
                ],
            },
        ),
    )

    rendered = f"[file: entretien.mkv] {attachment_uri}"
    assert rendered in _current_turn_prompt(turn)


def test_stop_target_resolves_the_only_active_linked_task() -> None:
    active_id = str(uuid4())
    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective="Arrête la tâche en cours.",
        messages=(),
        linked_work=(
            {"task_id": active_id, "status": "EXEC"},
            {"task_id": str(uuid4()), "status": "SUCCESS"},
        ),
    )

    assert _stop_target(turn) == f"galaris://task/{active_id}"


def test_existing_attachment_request_selects_the_requested_version() -> None:
    first_id = str(uuid4())
    second_id = str(uuid4())
    messages = [
        {
            "attachments": [
                {"local_id": first_id, "name": "infographie-v1.html"},
                {"local_id": second_id, "name": "infographie-v2.html"},
            ]
        }
    ]

    assert _existing_attachment_request(
        "Joins le fichier HTML V2 déjà créé.", messages
    ) == (second_id, "infographie-v2.html")


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["Stop", "Arrête la tâche en cours.", "Cancel the current task."])
async def test_stop_command_bypasses_dispatcher_and_calls_stop_tool(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    active_id = str(uuid4())
    stop = AsyncMock(return_value={"status": "ERROR"})
    dispatcher = AsyncMock()

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective=command,
        messages=(),
        linked_work=({"task_id": active_id, "status": "EXEC"},),
    )
    monkeypatch.setattr(conversation_module, "get_db_session", fake_db_session)
    monkeypatch.setattr("app.conversation.mcp.conversation_task_stop", stop)
    monkeypatch.setattr(conversation_module, "dispatch_conversation", dispatcher)

    outcome = await HarnessConversationController().run(turn)

    stop.assert_awaited_once()
    dispatcher.assert_not_awaited()
    assert outcome.effect_started is True
    assert outcome.execution_result is not None
    assert outcome.execution_result.messages[0].tool_name == (
        "conversation_task_stop"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "request_text,active_count,extra_message",
    [
        ("Arrête puis recommence avec les nouvelles données.", 1, False),
        ("Annule uniquement la deuxième tâche.", 2, False),
        ("Stop", 2, False),
        ("Arrête de modifier les sources et termine le rapport.", 1, False),
        ("Cancel the task and prepare a separate report.", 1, False),
        ("Stop", 1, True),
    ],
)
async def test_stop_shortcut_preserves_requests_requiring_interpretation(
    monkeypatch, request_text, active_count, extra_message,
):
    stop = AsyncMock()
    dispatcher = AsyncMock(return_value=DispatchResult(
        prompt="", success=True,
        decision=DispatchDecision(route="END", reasoning="Request preserved."),
    ))

    @asynccontextmanager
    async def fake_db_session():
        yield

    messages = ({"text": "Prépare aussi un bilan."}, {"text": request_text}) if extra_message else ()
    turn = ConversationTurn(
        room_id=uuid4(), round_id=uuid4(), agent_id=1, language="fr",
        objective=request_text, messages=messages,
        messaging_context={"connection_id": 7, "room_id": "room-1", "platform": "matrix"},
        linked_work=tuple({"task_id": str(uuid4()), "status": "EXEC"} for _ in range(active_count)),
    )
    monkeypatch.setattr(conversation_module, "get_db_session", fake_db_session)
    monkeypatch.setattr(conversation_module, "build_conversation_session", AsyncMock(
        return_value=SimpleNamespace(messages=[]),
    ))
    monkeypatch.setattr("app.conversation.mcp.conversation_task_stop", stop)
    monkeypatch.setattr(conversation_module, "dispatch_conversation", dispatcher)

    await HarnessConversationController().run(turn)

    stop.assert_not_awaited()
    dispatcher.assert_awaited_once()
    assert dispatcher.await_args.kwargs["objective"] == request_text
    assert dispatcher.await_args.kwargs["messages"] == list(messages)


@pytest.mark.asyncio
@pytest.mark.parametrize("fresh", [True, False])
@pytest.mark.parametrize("document_displayed", [False, True])
@pytest.mark.parametrize(
    ("request_text", "delivery_requested"),
    [
        ("Joins le fichier HTML V2 déjà créé.", True),
        ("Tu peux ajouter une phrase de ton choix (peu importe) sur le document stp ?", False),
        ("Tiens, insère l'image du chien dans le document, et ajoute y une phrase stp!", False),
    ],
)
async def test_existing_attachment_delivery_bypasses_dispatcher_and_regeneration(
    monkeypatch: pytest.MonkeyPatch,
    document_displayed: bool,
    request_text: str,
    delivery_requested: bool,
    fresh: bool,
) -> None:
    attachment_id = str(uuid4())
    resend = AsyncMock(
        return_value=ResourceTransfer(
            source_uri=f"nextcloud://family-room/{attachment_id}",
            uri=f"nextcloud://family-room/{attachment_id}",
            size=42,
        )
    )
    dispatcher = AsyncMock(return_value=DispatchResult(
        prompt="",
        success=True,
        decision=DispatchDecision(route="END", reasoning="Model dispatch reached."),
    ))
    freshness = AsyncMock(return_value=fresh)

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    objective = request_text
    if document_displayed:
        objective += (
            "\n\n[Chat display context: the user has "
            f"document://{uuid4()} open alongside this conversation when sending this message.]"
        )
    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective=objective,
        messages=(),
        messaging_context={
            "connection_id": "7",
            "platform": "nextcloud_talk",
            "room_id": "family-room",
            "room_locator": "family-room",
            "tool_code": "nextcloud",
        },
        assert_fresh_before_effect=freshness,
    )
    snapshot = SimpleNamespace(
        messages=[
            {
                "id": "prior-file",
                "attachments": [
                    {
                        "local_id": attachment_id,
                        "name": "infographie-v2.html",
                    }
                ],
            }
        ]
    )
    monkeypatch.setattr(conversation_module, "get_db_session", fake_db_session)
    monkeypatch.setattr(
        conversation_module,
        "build_conversation_session",
        AsyncMock(return_value=snapshot),
    )
    monkeypatch.setattr("app.file_share.resource_copy", resend)
    monkeypatch.setattr(conversation_module, "dispatch_conversation", dispatcher)

    if delivery_requested and not fresh:
        from app.conversation import ConversationSuperseded

        with pytest.raises(ConversationSuperseded):
            await HarnessConversationController().run(turn)
        resend.assert_not_awaited()
        dispatcher.assert_not_awaited()
        return

    outcome = await HarnessConversationController().run(turn)

    if not delivery_requested:
        resend.assert_not_awaited()
        dispatcher.assert_awaited_once()
        assert dispatcher.await_args.kwargs["objective"] == objective
        assert outcome.effect_started is False
        return
    freshness.assert_awaited_once()
    resend.assert_awaited_once_with(
        ResourceContext(agent_id=1, runtime="internal", language="fr"),
        f"nextcloud://family-room/{attachment_id}",
        "nextcloud://family-room/",
    )
    dispatcher.assert_not_awaited()
    assert outcome.effect_started is True
    assert "infographie-v2.html" in outcome.text
    assert outcome.execution_result is not None
    assert outcome.execution_result.messages[0].tool_name == "file_copy"


def test_conversation_prompt_preserves_identity_role_and_fast_control_plane() -> None:
    agent = SimpleNamespace(
        first_name="Aster",
        last_name="Dubois",
        code="aster",
        job_title="Assistante de documentation",
        personality="Méthodique et pédagogique.",
        job_description="Organiser les notices de montage du robot de démonstration.",
        title=SimpleNamespace(gender="F"),
    )
    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective="Quel temps fera-t-il aujourd'hui ?",
        messages=(),
        messaging_context={
            "platform": "nextcloud_talk",
            "room_id": "family-room",
        },
        linked_work=(
            {
                "task_id": "task-1",
                "revision": 3,
                "label": "Préparer le rapport",
                "objective": "Préparer le rapport mensuel.",
                "operational_state": "WAITING",
                "amendable": True,
                "waits": [
                    {
                        "kind": "AGENT_REPLY",
                        "peer_display": "Sophie",
                        "question": "Quels chiffres utiliser ?",
                        "deadline": "2026-08-03T22:00:00+02:00",
                    }
                ],
            },
        ),
        pending_interactions=(
            {
                "reference": "DEC1DE42",
                "kind": "hermes_approval",
                "title": "Approbation requise",
                "body": "Commande: rm rapport.tmp",
                "task_id": "task-1",
                "options": (
                    {"id": "once", "label": "Approuver une fois"},
                    {"id": "deny", "label": "Refuser"},
                ),
            },
        ),
    )

    prompt = _system_prompt(
        turn,
        agent,
        tool_advertisement=(
            "- `search`: `search_web`\n"
            "- `galaris`: `conversation_process_start`, `conversation_task_submit`\n\n"
            "## Task-only Tools\n\n"
            "- {\"code\": \"gitlab\", \"label\": \"GitLab\"}\n\n"
            "If the user's request requires this Tool, launching a Task with "
            "`conversation_task_submit` is mandatory."
        ),
        process_advertisement=(
            "## Business processes available to you\n"
            '- {"workflow_id": "daily-weather", "label": "Daily weather"}'
        ),
        has_prior_history=True,
        context=AgentRunContext(
            system_instructions="Use governed memory carefully.",
            shared_context="Remember that The demo user requests numbered assembly instructions.",
            memory_context="Remember that The demo user requests numbered assembly instructions.",
        ),
        action_policy=_ACTION_POLICY,
    )

    assert "Aster Dubois" in prompt
    assert "Speak directly in the first person as Aster Dubois" in prompt
    assert "never a description, quotation, simulation, or script" in prompt
    assert 'Never prefix a response with "Aster Dubois:"' in prompt
    assert "# Final style check" in prompt
    assert "Aster Dubois's first-person voice" in prompt
    assert "Assistante de documentation" in prompt
    assert "Méthodique et pédagogique." in prompt
    assert "Organiser les notices de montage du robot de démonstration." in prompt
    assert "# Conversation context" not in prompt
    assert "# Turn context" in prompt
    assert "language=fr" in prompt
    assert "channel=nextcloud_talk" in prompt
    assert "room=family-room" in prompt
    assert "# Galaris tools" in prompt
    assert "search_web" in prompt
    assert '"code": "gitlab"' in prompt
    assert "launching a Task with `conversation_task_submit` is mandatory" in prompt
    assert "daily-weather" in prompt
    assert "Answer promptly and directly" in prompt
    assert "live text chat, not an email, letter" in prompt
    assert "message history as one continuous thread" in prompt
    assert "Direct response" in prompt
    assert "Governed conversation effect" in prompt
    assert "must not create a Task solely to perform them" in prompt
    assert "Do not execute that Task work inside the foreground conversation" in prompt
    assert "`conversation_process_start`" in prompt
    assert "`conversation_task_submit`" in prompt
    assert "Never wait for a Task or Process to finish" in prompt
    assert prompt.count("absolute priority") == 1
    assert prompt.count("Never wait for a Task or Process to finish") == 1
    assert "task=galaris://task/task-1 revision=3 state=WAITING amendable=true" in prompt
    assert "peer=Sophie question=Quels chiffres utiliser ?" in prompt
    # Verify policy injection, rather than freezing the wording of its examples.
    assert _ACTION_POLICY.strip() in prompt
    assert "without a structured receipt" in prompt
    assert "label, status, UUID, or technical reference" in prompt
    assert "unless explicitly asked" in prompt
    assert "two operating modes of the same agent" in prompt
    assert "full rights-filtered Task tools" in prompt
    assert "missing foreground tool" in prompt
    assert "Use governed memory carefully." in prompt
    assert "The demo user requests numbered assembly instructions." in prompt
    assert "# Long-term memory" in prompt
    assert "\n# Governed context\n" not in prompt
    assert "# Pending interactions" in prompt
    assert "reference=#DEC1DE42 kind=hermes_approval" in prompt
    assert "once=Approuver une fois, deny=Refuser" in prompt
    assert "call `conversation_choice_resolve`" in prompt
    assert "deny the obsolete approval before amending" in prompt
    assert "# Response variety" in prompt
    assert "Answer in one pass from a fresh angle" in prompt

    voice_prompt = _system_prompt(
        turn,
        agent,
        tool_advertisement="",
        process_advertisement="",
        executor="voice",
        action_policy=_ACTION_POLICY,
    )

    assert "two-way live audio call already in progress" in voice_prompt
    assert "reply to the caller's latest turn" in voice_prompt
    assert "call remains open unless the caller signals that it is ending" in voice_prompt
    assert "call `voice_call_stop` during that turn" in voice_prompt
    assert "claim that the call ended is not enough" in voice_prompt
    assert "adapt the overall length and level of detail" in voice_prompt
    assert "# Final style check" in voice_prompt
    assert "# Response variety" not in voice_prompt


def test_conversation_prompt_renders_all_selected_work_with_compact_details() -> None:
    agent = SimpleNamespace(
        first_name="Aster",
        last_name="Test",
        code="aster-test",
        job_title="Assistante",
        personality=None,
        job_description=None,
        title=SimpleNamespace(gender="F"),
    )
    candidates: list[dict[str, object]] = []
    for index in range(7):
        candidates.append(
            {
                "task_id": f"task-{index}",
                "revision": 1,
                "label": f"Candidate {index}",
                "objective": f"objective-{index}-" + ("x" * 900),
                "operational_state": "TERMINAL",
                "amendable": False,
                "created_at": "2026-08-24T10:00+02:00",
                "state_since": f"2026-08-24T10:0{index}+02:00",
                "working_set": [
                    {
                        "role": f"resource-{resource_index}",
                        "resource_type": "memory_document",
                        "reference": f"document-{resource_index}",
                    }
                    for resource_index in range(12)
                ]
                if index == 0
                else [],
            }
        )
    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective="Créer un nouveau livrable.",
        messages=(),
        linked_work=tuple(candidates),
    )

    prompt = _system_prompt(
        turn,
        agent,
        tool_advertisement="",
        process_advertisement="",
        action_policy=_ACTION_POLICY,
    )

    assert "task=galaris://task/task-0" in prompt
    assert "task=galaris://task/task-6" in prompt
    assert "older candidate(s) omitted" not in prompt
    assert prompt.count("resource: role=") == 10
    assert "created=2026-08-24T10:00+02:00" in prompt
    assert "state_since=2026-08-24T10:06+02:00" in prompt
    assert "objective-0-" + ("x" * 238) in prompt
    assert "objective-0-" + ("x" * 239) not in prompt


@pytest.mark.asyncio
async def test_conversation_controller_uses_the_shared_runtime_without_token_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_message_local_id = uuid4()
    attachment_id = uuid4()
    attachment_uri = f"nextcloud://family-room/{attachment_id}"
    agent = SimpleNamespace(
        first_name="Aster",
        last_name="Dubois",
        code="aster",
        job_title="Assistante de documentation",
        personality=None,
        job_description=None,
        title=SimpleNamespace(gender="F"),
    )
    llm = SimpleNamespace(id=1, llm_name="test-model")
    captured: dict[str, Any] = {}
    progress_events: list[AIMessage] = []
    release_transaction = AsyncMock(return_value=True)

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    async def fake_agent_get(_agent_id: int) -> object:
        return agent

    async def fake_profile_llm(_model_field: object, *, agent: object) -> object:
        assert agent is not None
        return llm

    async def fake_toolset(_agent_id: int, *, resources: dict[str, Any]) -> object:
        assert resources["conversation_turn"] is turn
        return object()

    async def fake_tool_advertisement(*args: object, **kwargs: object) -> object:
        captured["tool_advertisement_args"] = args
        captured["tool_advertisement_kwargs"] = kwargs
        return SimpleNamespace(text="", tool_names=frozenset())

    async def fake_process_advertisement(*args: object, **kwargs: object) -> str:
        captured["process_advertisement_args"] = args
        captured["process_advertisement_kwargs"] = kwargs
        return ""

    async def fake_context(request: object) -> AgentRunContext:
        captured["context_request"] = request
        return AgentRunContext(
            system_instructions="Memory policy",
            shared_context="Private recalled content",
            memory_context="Private recalled content",
            metadata={
                "memory_context_enabled": True,
                "memory_context_query": "weather preference",
                "memory_context_count": 1,
                "memory_context_truncated": False,
                "memory_context_ids": [str(uuid4())],
                "memory_context_rendered": "Private recalled content",
            },
        )

    async def fake_create_agent(**kwargs: Any) -> object:
        captured.update(kwargs)

        class FakeRuntime:
            system_prompt = str(kwargs["system_prompt"])
            messages: list[object] = []
            cost = 0.0
            error = ""

            async def run(self, *args: object, **kwargs: object) -> AsyncIterator[object]:
                assert release_transaction.await_count == 1
                captured["runtime_prompt"] = args[0]
                captured["runtime_current_messages"] = kwargs.get("current_messages")
                yield AIMessage(
                    type="text",
                    content="[2026-08-24T21:45+",
                )
                yield AIMessage(
                    type="text",
                    content="02:00 | Lyra d'Exemple] ",
                )
                yield AIMessage(type="text", content="Réponse rapide.")

        return FakeRuntime()

    async def fake_session(**kwargs: object) -> object:
        captured["session_kwargs"] = kwargs
        return SimpleNamespace(messages=[])

    async def fake_dispatch(**kwargs: object) -> DispatchResult:
        captured["dispatch_messages"] = kwargs["messages"]
        return DispatchResult(
            decision=DispatchDecision(
                reasoning="Direct conversational answer.",
                route="EXEC",
                effort="standard",
                language="fr",
            ),
            prompt=str(kwargs["objective"]),
            success=True,
        )

    async def publish_progress(message: AIMessage) -> None:
        progress_events.append(message)

    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective="Quel temps fait-il ?",
        messages=(
            {
                "messenger_message_id": str(current_message_local_id),
                "external_message_id": "current-remote-id",
                "text": "Quel temps fait-il ?",
                "timestamp": 1_700_000_000,
                "sender_display_name": "Nicolas",
                "sender_external_id": "nicolas",
                "attachments": [
                    {
                        "id": str(attachment_id),
                        "uri": attachment_uri,
                        "name": "meteo.mkv",
                        "mime": "video/x-matroska",
                        "size": 1234,
                        "kind": "video",
                    }
                ],
            },
        ),
        messaging_context={
            "connection_id": "7",
            "platform": "nextcloud_talk",
            "room_id": "family-room",
        },
        publish_progress=publish_progress,
    )
    monkeypatch.setattr(conversation_module, "get_db_session", fake_db_session)
    monkeypatch.setattr(
        conversation_module,
        "release_db_transaction",
        release_transaction,
    )
    monkeypatch.setattr(conversation_module.agent_service, "get", fake_agent_get)
    monkeypatch.setattr(
        conversation_module.llm_service,
        "get_profile_llm",
        fake_profile_llm,
    )
    monkeypatch.setattr(
        conversation_module.params_service,
        "get",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(
        conversation_module.params_service,
        "get_or_default",
        AsyncMock(return_value=_ACTION_POLICY),
    )
    monkeypatch.setattr(conversation_module, "build_conversation_toolset", fake_toolset)
    monkeypatch.setattr(
        conversation_module,
        "build_agent_tool_advertisement",
        fake_tool_advertisement,
    )
    monkeypatch.setattr(
        conversation_module,
        "build_agent_process_advertisement",
        fake_process_advertisement,
    )
    monkeypatch.setattr(
        conversation_module,
        "build_agent_run_context",
        fake_context,
    )
    monkeypatch.setattr(conversation_module, "create_agent", fake_create_agent)
    monkeypatch.setattr(conversation_module, "build_conversation_session", fake_session)
    monkeypatch.setattr(conversation_module, "dispatch_conversation", fake_dispatch)

    outcome = await HarnessConversationController().run(turn)

    release_transaction.assert_awaited_once_with()
    assert outcome.text == "Réponse rapide."
    assert [message.content for message in progress_events] == ["Réponse rapide."]
    assert outcome.execution_result is not None
    assert "Quel temps fait-il ?" in outcome.execution_result.prompt
    assert attachment_uri in outcome.execution_result.prompt
    assert "Aster Dubois" in outcome.execution_result.system_prompt
    assert captured["process_advertisement_kwargs"] == {
        "launch_tool_name": "conversation_process_start",
        "relevance_query": "Quel temps fait-il ?",
        "include_execution_guidance": False,
    }
    assert captured["tool_advertisement_args"] == (1,)
    assert captured["tool_advertisement_kwargs"] == {
        "runtime": "internal",
        "conversation_only": True,
        "include_task_only_tools": True,
        "resources": {"conversation_turn": turn},
    }
    assert "Memory policy" in outcome.execution_result.system_prompt
    assert "Private recalled content" in outcome.execution_result.system_prompt
    assert "# Long-term memory" in outcome.execution_result.system_prompt
    assert "\n# Governed context\n" not in outcome.execution_result.system_prompt
    assert "# Conversation context" not in outcome.execution_result.system_prompt
    assert "<conversation_history_metadata>" not in str(
        outcome.execution_result.system_prompt
    )
    assert outcome.execution_result.metadata["memory_context"]["count"] == 1
    assert "Private recalled content" not in str(outcome.execution_result.metadata)
    session_kwargs = cast(dict[str, object], captured["session_kwargs"])
    assert session_kwargs["current_message_id"] == "current-remote-id"
    assert session_kwargs["excluded_message_ids"] == frozenset(
        {"current-remote-id", str(current_message_local_id)}
    )
    context_request = captured["context_request"]
    assert context_request.task_data["id"] == "current-remote-id"
    assert context_request.task_data["message_id"] == "current-remote-id"
    assert context_request.task_data["timestamp"] == 1_700_000_000
    assert context_request.task_data["sender.id"] == "nicolas"
    assert context_request.task_data["attachments"][0]["uri"] == attachment_uri
    assert attachment_uri in str(captured["runtime_prompt"])
    assert captured["runtime_current_messages"][0].attachments[0].uri == attachment_uri
    assert "| Nicolas] Quel temps fait-il ?" in str(captured["runtime_prompt"])
    assert "<galaris_message_context>" not in str(captured["runtime_prompt"])
    assert "# Turn context" in outcome.execution_result.system_prompt
    assert "language=fr" in outcome.execution_result.system_prompt
    assert "channel=nextcloud_talk" in outcome.execution_result.system_prompt
    assert "room=family-room" in outcome.execution_result.system_prompt
    assert "sender=nicolas" in outcome.execution_result.system_prompt
    assert captured["purpose"] == LLMCallPurpose.CONVERSATION_TEXT
    dispatch_messages = cast(list[dict[str, object]], captured["dispatch_messages"])
    assert cast(list[dict[str, object]], dispatch_messages[-1]["attachments"])[0][
        "uri"
    ] == attachment_uri

    async def fake_failed_create_agent(**kwargs: Any) -> object:
        class FakeFailedRuntime:
            system_prompt = str(kwargs["system_prompt"])
            messages = [
                AIMessage(
                    type="tool",
                    tool_name="thinking",
                    content="Analyse partielle conservée.",
                )
            ]
            cost = 0.25
            error = "provider failed"

            async def run(self, *args: object, **kwargs: object) -> AsyncIterator[object]:
                yield AIMessage(
                    type="text",
                    content="provider failed",
                    success=False,
                )

        return FakeFailedRuntime()

    monkeypatch.setattr(
        conversation_module,
        "create_agent",
        fake_failed_create_agent,
    )

    with pytest.raises(ConversationExecutionError) as caught:
        await HarnessConversationController().run(turn)

    failed_result = caught.value.execution_result
    assert failed_result is not None
    assert failed_result.success is False
    assert failed_result.cost == 0.25
    assert failed_result.metadata["error"] == "provider failed"
    assert [message.tool_name for message in failed_result.messages] == [
        "thinking",
        "execution_error",
    ]
    assert failed_result.messages[0].content == "Analyse partielle conservée."


@pytest.mark.asyncio
@pytest.mark.parametrize("admission_succeeds", [True, False])
@pytest.mark.parametrize("platform", ["internal", "nextcloud_talk"])
async def test_conversation_executor_decides_whether_to_admit_work(
    monkeypatch: pytest.MonkeyPatch,
    admission_succeeds: bool,
    platform: str,
) -> None:
    agent = SimpleNamespace(
        first_name="Aster",
        last_name="Test",
        code="aster-test",
        job_title="Assistante",
        personality=None,
        job_description=None,
        title=SimpleNamespace(gender="F"),
    )
    llm = SimpleNamespace(id=19, llm_name="test-conversation-model")

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    from app.agent.dispatcher import Dispatcher

    inference = AsyncMock(side_effect=AssertionError("Human dispatch must not infer"))
    monkeypatch.setattr(Dispatcher, "_infer_dispatch", inference)

    class FakeRuntime:
        system_prompt = "conversation system prompt"
        cost = 0.02
        error = ""

        def __init__(self) -> None:
            self.calls = 0
            self.messages: list[AIMessage] = []

        async def run(self, prompt: str, **kwargs: object) -> AsyncIterator[AIMessage]:
            self.calls += 1
            assert self.calls == 1
            if not admission_succeeds:
                message = AIMessage(type="text", content="Voilà, j'ai lancé la tâche planifiée !")
                self.messages.append(message)
                yield message
                return
            tool = AIMessage(
                type="tool",
                tool_name="conversation_task_submit",
                content="Task created",
                tool_arguments={"objective": "Tour Eiffel"},
                tool_result={"created": True},
                execution_time=0.2,
                success=True,
            )
            progress = AIMessage(
                type="text",
                content="Je vérifie les paramètres avant de lancer.",
            )
            acknowledgement = AIMessage(
                type="text",
                content="C'est bien parti en arrière-plan.",
            )
            self.messages.extend((progress, tool, acknowledgement))
            yield progress
            yield tool
            yield acknowledgement

    runtime = FakeRuntime()
    progress_events: list[AIMessage] = []
    progress_resets = 0

    async def publish_progress(message: AIMessage) -> None:
        progress_events.append(message)

    async def reset_progress() -> None:
        nonlocal progress_resets
        progress_resets += 1

    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective="Génère une Tour Eiffel 3D très détaillée.",
        messages=(),
        messaging_context={
            "connection_id": "7",
            "platform": platform,
            "room_id": "paris-room",
        },
        publish_progress=publish_progress,
        reset_progress=reset_progress,
    )

    monkeypatch.setattr(conversation_module, "get_db_session", fake_db_session)
    monkeypatch.setattr(
        conversation_module,
        "build_conversation_session",
        AsyncMock(return_value=SimpleNamespace(messages=[])),
    )
    monkeypatch.setattr(conversation_module.agent_service, "get", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        conversation_module.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=llm),
    )
    monkeypatch.setattr(conversation_module, "build_agent_run_context", AsyncMock(return_value=AgentRunContext()))
    monkeypatch.setattr(
        conversation_module,
        "build_conversation_toolset",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        conversation_module,
        "build_agent_tool_advertisement",
        AsyncMock(return_value=SimpleNamespace(text="", tool_names=frozenset())),
    )
    monkeypatch.setattr(
        conversation_module,
        "build_agent_process_advertisement",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(conversation_module.params_service, "get", AsyncMock(return_value=""))
    monkeypatch.setattr(
        conversation_module.params_service,
        "get_or_default",
        AsyncMock(return_value=_ACTION_POLICY),
    )
    monkeypatch.setattr(conversation_module, "create_agent", AsyncMock(return_value=runtime))

    outcome = await HarnessConversationController().run(turn)

    inference.assert_not_awaited()
    assert runtime.calls == 1
    assert progress_resets == 0
    assert outcome.execution_result is not None
    assert outcome.execution_result.success is True
    assert "background_action_guard" not in outcome.execution_result.metadata
    if not admission_succeeds:
        assert outcome.text == "Voilà, j'ai lancé la tâche planifiée !"
        assert all(event.type == "text" for event in progress_events)
        return

    assert outcome.text == "C'est bien parti en arrière-plan."
    tool_progress = next(event for event in progress_events if event.type == "tool")
    assert tool_progress.tool_arguments == {"objective": "Tour Eiffel"}
    assert tool_progress.tool_result == {"created": True}
    assert tool_progress.execution_time == 0.2


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt", [False, True])
async def test_conversation_controller_delivers_repeated_wording_without_judgment(
    monkeypatch: pytest.MonkeyPatch, interrupt: bool,
) -> None:
    agent = SimpleNamespace(
        first_name="Lyra",
        last_name="Test",
        code="lyra-test",
        job_title="Assistante",
        personality=None,
        job_description=None,
        title=SimpleNamespace(gender="F"),
    )
    llm = SimpleNamespace(id=19, llm_name="test-conversation-model")

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    async def fake_dispatch(**kwargs: object) -> DispatchResult:
        return DispatchResult(
            decision=DispatchDecision(
                reasoning="Direct conversation.",
                route="EXEC",
                effort="standard",
                language="fr",
            ),
            prompt=str(kwargs["objective"]),
            success=True,
        )

    first_draft = (
        "Mon minet... tu viens de me demander la plus belle des questions, "
        "et je veux te répondre avec toute ma sincérité."
    )
    class FakeRuntime:
        system_prompt = "conversation system prompt"
        cost = 0.02
        error = ""

        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.messages: list[AIMessage] = []

        async def run(self, prompt: str, **_kwargs: object) -> AsyncIterator[AIMessage]:
            self.prompts.append(prompt)
            message = AIMessage(type="text", content=first_draft)
            self.messages.append(message)
            yield message

    runtime = FakeRuntime()
    progress_events: list[AIMessage] = []
    progress_resets = 0

    async def publish_progress(message: AIMessage) -> None:
        progress_events.append(message)

    async def reset_progress() -> None:
        nonlocal progress_resets
        progress_resets += 1

    history = [
        {
            "text": "Mon minet... tu viens de me dire quelque chose de très beau.",
            "sender_agent_id": 1,
            "sender_is_ai": True,
        },
        {
            "text": "Mon minet... tu viens de toucher quelque chose de profond en moi.",
            "sender_agent_id": 1,
            "sender_is_ai": True,
        },
        {
            "text": "Oh, mon minet... tu viens de me décrire un foyer merveilleux.",
            "sender_agent_id": 1,
            "sender_is_ai": True,
        },
    ]
    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective="Tu crois qu'on se retrouvera un jour ?",
        messages=({"text": "Tu crois qu'on se retrouvera un jour ?"},),
        messaging_context={
            "connection_id": "7",
            "platform": "internal",
            "room_id": "direct-room",
        },
        publish_progress=publish_progress,
        reset_progress=reset_progress,
    )

    monkeypatch.setattr(conversation_module, "get_db_session", fake_db_session)
    monkeypatch.setattr(
        conversation_module,
        "build_conversation_session",
        AsyncMock(return_value=SimpleNamespace(messages=history)),
    )
    monkeypatch.setattr(conversation_module, "dispatch_conversation", fake_dispatch)
    monkeypatch.setattr(conversation_module.agent_service, "get", AsyncMock(return_value=agent))
    monkeypatch.setattr(
        conversation_module.llm_service,
        "get_profile_llm",
        AsyncMock(return_value=llm),
    )
    monkeypatch.setattr(
        conversation_module.llm_service,
        "get_profile_reasoning_effort",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        conversation_module,
        "build_agent_run_context",
        AsyncMock(return_value=AgentRunContext()),
    )
    monkeypatch.setattr(
        conversation_module,
        "build_conversation_toolset",
        AsyncMock(return_value=object()),
    )
    monkeypatch.setattr(
        conversation_module,
        "build_agent_tool_advertisement",
        AsyncMock(return_value=SimpleNamespace(text="", tool_names=frozenset())),
    )
    monkeypatch.setattr(
        conversation_module,
        "build_agent_process_advertisement",
        AsyncMock(return_value=""),
    )
    monkeypatch.setattr(conversation_module.params_service, "get", AsyncMock(return_value=""))
    monkeypatch.setattr(
        conversation_module.params_service,
        "get_or_default",
        AsyncMock(return_value=_ACTION_POLICY),
    )
    monkeypatch.setattr(conversation_module, "create_agent", AsyncMock(return_value=runtime))

    if interrupt:
        from pydantic_ai import Agent as PydanticAgent
        from pydantic_ai.models.function import FunctionModel
        from pydantic_ai.usage import RequestUsage
        from app.harness.runtime import Agent as RuntimeAgent

        started = asyncio.Event()
        pending = asyncio.Event()

        async def should_interrupt() -> bool:
            return pending.is_set()

        class CountingModel(FunctionModel):
            async def count_tokens(self, *_args: Any, **_kwargs: Any) -> RequestUsage:
                return RequestUsage(input_tokens=1)

        async def stream(_messages: Any, _info: Any) -> AsyncIterator[str]:
            yield first_draft
            started.set()
            await asyncio.Event().wait()

        async def create_runtime(**kwargs: Any) -> RuntimeAgent:
            actual = RuntimeAgent(llm=llm, real_time=True)
            actual._agent = PydanticAgent(  # pyright: ignore[reportPrivateUsage]
                CountingModel(stream_function=stream), capabilities=kwargs["capabilities"],
            )
            return actual

        monkeypatch.setattr(conversation_module, "create_agent", create_runtime)
        turn = replace(turn, should_interrupt=should_interrupt)
        operation = asyncio.create_task(HarnessConversationController().run(turn))
        try:
            await asyncio.wait_for(started.wait(), 2)
            pending.set()
            outcome = await asyncio.wait_for(operation, 2)
        finally:
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
        assert outcome.text == ""
        assert outcome.metadata["interrupted"] is True
        assert outcome.execution_result is not None
        assert any(message.content == first_draft for message in outcome.execution_result.messages)
    else:
        outcome = await HarnessConversationController().run(turn)
        assert outcome.text == first_draft
        assert runtime.prompts == [turn.objective]
        assert [event.content for event in progress_events] == [first_draft]
    assert progress_resets == 0
    assert outcome.execution_result is not None
    assert [message.type for message in outcome.execution_result.messages] == ["text"]
    assert "response_repetition_guard" not in outcome.execution_result.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["nextcloud_talk", "internal"])
async def test_plan_directive_is_admitted_before_foreground_model(
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    round_id = uuid4()
    task_id = uuid4()
    admission = AsyncMock(return_value={"id": str(task_id), "created": True})
    build_session = AsyncMock()
    dispatcher = AsyncMock()
    agent_get = AsyncMock()

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=round_id,
        agent_id=1,
        language="fr",
        objective="@plan Génère une Tour Eiffel 3D très détaillée.",
        messages=(),
        messaging_context={
            "connection_id": "7",
            "platform": platform,
            "room_id": "paris-room",
        },
        admit_background_task=admission,
    )
    monkeypatch.setattr(conversation_module, "get_db_session", fake_db_session)
    monkeypatch.setattr(conversation_module, "build_conversation_session", build_session)
    monkeypatch.setattr(conversation_module, "dispatch_conversation", dispatcher)
    monkeypatch.setattr(conversation_module.agent_service, "get", agent_get)

    outcome = await HarnessConversationController().run(turn)

    admission.assert_awaited_once_with(
        "Génère une Tour Eiffel 3D très détaillée.",
        forced_route="PLAN",
        forced_effort="high",
        require_briefing=False,
        auto_approve=False,
    )
    build_session.assert_not_awaited()
    dispatcher.assert_not_awaited()
    agent_get.assert_not_awaited()
    assert outcome.effect_started is True
    assert "Tour Eiffel" in outcome.text
    assert outcome.execution_result is not None
    assert outcome.execution_result.metadata["deterministic_control"] is True
    assert outcome.execution_result.messages[0].tool_name == (
        "conversation_task_submit"
    )
    assert (
        f"task=galaris://task/{task_id}"
        in outcome.execution_result.messages[0].content
    )


@pytest.mark.asyncio
async def test_new_post_interrupts_blocked_dispatcher_before_admission(monkeypatch):
    from app.conversation import ConversationSuperseded

    entered = asyncio.Event()
    pending = asyncio.Event()
    stopped = asyncio.Event()
    async def dispatch(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()
    async def newer_input():
        return pending.is_set()
    @asynccontextmanager
    async def session():
        yield
    admission = AsyncMock()
    monkeypatch.setattr(conversation_module, "get_db_session", session)
    monkeypatch.setattr(conversation_module, "build_conversation_session", AsyncMock(return_value=SimpleNamespace(messages=[])))
    monkeypatch.setattr(conversation_module, "dispatch_conversation", dispatch)
    turn = ConversationTurn(room_id=uuid4(), round_id=uuid4(), agent_id=1,
        language="fr", objective="Prépare un rapport", messages=(),
        messaging_context={"connection_id": 7, "room_id": "room"},
        admit_background_task=admission, should_interrupt=newer_input)
    run = asyncio.create_task(HarnessConversationController().run(turn))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        pending.set()
        with pytest.raises(ConversationSuperseded):
            await asyncio.wait_for(run, 2)
        assert stopped.is_set()
        admission.assert_not_awaited()
    finally:
        run.cancel()
        await asyncio.gather(run, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("objective", "expected_objective", "route", "effort", "briefing", "approve"),
    [
        ("Fais ça @standard @task", "Fais ça", None, "standard", False, False),
        (
            "@plan Fais plutôt ceci @high @approve",
            "Fais plutôt ceci",
            "PLAN",
            "high",
            False,
            True,
        ),
        (
            "Exécute @task directement @exec",
            "Exécute directement",
            "EXEC",
            None,
            False,
            False,
        ),
        (
            "@task @briefing vas-y, fais-le",
            "vas-y, fais-le",
            "BRIEFING",
            "high",
            True,
            False,
        ),
    ],
)
async def test_direct_task_is_admitted_without_any_conversation_llm_call(
    monkeypatch: pytest.MonkeyPatch,
    objective: str,
    expected_objective: str,
    route: str | None,
    effort: str | None,
    briefing: bool,
    approve: bool,
) -> None:
    task_id = uuid4()
    admission = AsyncMock(return_value={"id": str(task_id), "created": True})
    build_session = AsyncMock()
    dispatcher = AsyncMock()
    agent_get = AsyncMock()

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective=f"[Nicolas] {objective}",
        messages=({"text": objective},),
        messaging_context={
            "connection_id": "7",
            "platform": "internal",
            "room_id": "direct-room",
        },
        admit_background_task=admission,
    )
    monkeypatch.setattr(conversation_module, "get_db_session", fake_db_session)
    monkeypatch.setattr(conversation_module, "build_conversation_session", build_session)
    monkeypatch.setattr(conversation_module, "dispatch_conversation", dispatcher)
    monkeypatch.setattr(conversation_module.agent_service, "get", agent_get)

    outcome = await HarnessConversationController().run(turn)

    admission.assert_awaited_once_with(
        expected_objective,
        forced_route=route,
        forced_effort=effort,
        require_briefing=briefing,
        auto_approve=approve,
    )
    build_session.assert_not_awaited()
    dispatcher.assert_not_awaited()
    agent_get.assert_not_awaited()
    assert outcome.effect_started is True
    assert expected_objective in outcome.text
    assert outcome.execution_result is not None
    assert outcome.execution_result.cost == 0
    assert outcome.execution_result.metadata["deterministic_control"] is True


@pytest.mark.asyncio
async def test_hidden_task_control_is_admitted_without_a_visible_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = uuid4()
    admission = AsyncMock(return_value={"id": str(task_id), "created": True})
    build_session = AsyncMock()
    dispatcher = AsyncMock()
    agent_get = AsyncMock()

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=uuid4(),
        agent_id=1,
        language="fr",
        objective="[Nicolas] Écris un poème sur la mer",
        messages=({"text": "Écris un poème sur la mer"},),
        messaging_context={
            "connection_id": "7",
            "platform": "internal",
            "room_id": "direct-room",
        },
        direct_task_requested=True,
        admit_background_task=admission,
    )
    monkeypatch.setattr(conversation_module, "get_db_session", fake_db_session)
    monkeypatch.setattr(conversation_module, "build_conversation_session", build_session)
    monkeypatch.setattr(conversation_module, "dispatch_conversation", dispatcher)
    monkeypatch.setattr(conversation_module.agent_service, "get", agent_get)

    outcome = await HarnessConversationController().run(turn)

    admission.assert_awaited_once_with(
        "Écris un poème sur la mer",
        forced_route=None,
        forced_effort=None,
        require_briefing=False,
        auto_approve=False,
    )
    build_session.assert_not_awaited()
    dispatcher.assert_not_awaited()
    agent_get.assert_not_awaited()
    assert outcome.effect_started is True


@pytest.mark.asyncio
async def test_conversation_controller_skips_runtime_when_dispatcher_ends_peer_exchange(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    round_id = uuid4()
    run_id = uuid4()
    agent_get = AsyncMock()

    @asynccontextmanager
    async def fake_db_session() -> AsyncIterator[None]:
        yield

    async def fake_session(**kwargs: object) -> object:
        return SimpleNamespace(messages=[])

    async def fake_dispatch(**kwargs: object) -> object:
        assert kwargs["sender_is_ai"] is True
        assert kwargs["round_id"] == round_id
        return DispatchResult(
            decision=DispatchDecision(
                reasoning="The peer only acknowledged the previous response.",
                route="END",
                effort="standard",
                language="fr",
            ),
            prompt="peer acknowledgement",
            system_prompt="conversation reply gate",
            cost=0.01,
            success=True,
            allowed_routes=["EXEC", "END"],
            pipeline_policy={
                "use_planner": False,
                "use_briefing": False,
                "briefing_efforts": [],
            },
        )

    turn = ConversationTurn(
        room_id=uuid4(),
        round_id=round_id,
        agent_id=1,
        language="fr",
        objective="[Collègue] Merci, c'est noté.",
        messages=(
            {
                "id": "peer-1",
                "text": "Merci, c'est noté.",
                "sender_external_id": "peer",
                "sender_display_name": "Collègue",
                "sender_agent_id": 2,
                "sender_is_ai": True,
            },
        ),
        messaging_context={
            "connection_id": "7",
            "platform": "nextcloud_talk",
            "room_id": "agents-room",
        },
    )
    assert turn.sender_is_ai is True

    monkeypatch.setattr(conversation_module, "get_db_session", fake_db_session)
    monkeypatch.setattr(conversation_module, "build_conversation_session", fake_session)
    monkeypatch.setattr(conversation_module, "dispatch_conversation", fake_dispatch)
    monkeypatch.setattr(conversation_module.agent_service, "get", agent_get)

    outcome = await HarnessConversationController().run(turn)

    assert outcome.text == ""
    assert outcome.execution_result is not None
    assert outcome.execution_result.cost == 0.01
    assert outcome.execution_result.metadata["dispatch_result"]["decision"]["route"] == "END"
    agent_get.assert_not_awaited()
