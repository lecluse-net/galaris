from bridge.codex.stream_trace import CodexStreamTrace


def test_commentary_becomes_thinking_and_final_answer_stays_separate() -> None:
    trace = CodexStreamTrace()

    final_delta, thinking = trace.record_agent_delta(
        "comment-1",
        "Je vérifie",
        phase="commentary",
    )
    completed = trace.complete_agent_item(
        "comment-1",
        "Je vérifie les contrats.",
        phase="commentary",
    )
    streamed_final, final_thinking = trace.record_agent_delta(
        "final-1",
        "Terminé.",
        phase="final_answer",
    )
    trace.complete_agent_item("final-1", "Terminé.", phase="final_answer")

    deferred, final_text, final_was_streamed = trace.finish()

    assert final_delta == ""
    assert thinking == {
        "type": "tool",
        "tool_name": "thinking",
        "content": "Je vérifie",
        "success": True,
        "stream_id": "codex:agent:comment-1",
    }
    assert [message["content"] for message in completed] == [" les contrats."]
    assert completed[0]["stream_id"] == thinking["stream_id"]
    assert streamed_final == "Terminé."
    assert final_thinking is None
    assert deferred == []
    assert final_text == "Terminé."
    assert final_was_streamed is True


def test_unphased_agent_messages_keep_only_the_last_as_final() -> None:
    trace = CodexStreamTrace()

    trace.record_agent_delta("first", "Inspection en cours.")
    trace.complete_agent_item("first", "Inspection en cours.")
    trace.record_agent_delta("last", "Résultat final.")
    trace.complete_agent_item("last", "Résultat final.")

    messages, final_text, final_was_streamed = trace.finish()

    assert [message["content"] for message in messages] == ["Inspection en cours."]
    assert final_text == "Résultat final."
    assert final_was_streamed is False


def test_earlier_final_phased_message_is_preserved_as_thinking() -> None:
    trace = CodexStreamTrace()
    trace.record_agent_delta("premature", "Je vais inspecter.", phase="final_answer")
    trace.complete_agent_item("premature", "Je vais inspecter.", phase="final_answer")
    trace.record_agent_delta("actual", "Inspection terminée.", phase="final_answer")
    trace.complete_agent_item("actual", "Inspection terminée.", phase="final_answer")

    messages, final_text, final_was_streamed = trace.finish()

    assert [message["content"] for message in messages] == ["Je vais inspecter."]
    assert final_text == "Inspection terminée."
    assert final_was_streamed is True


def test_reasoning_summary_is_emitted_once_as_thinking() -> None:
    trace = CodexStreamTrace()
    first = trace.record_reasoning_delta("reasoning-1", 0, "Comparer ")
    second = trace.record_reasoning_delta("reasoning-1", 0, "les options.")

    completed = trace.complete_reasoning_item("reasoning-1")
    deferred, _, _ = trace.finish()

    assert first is not None
    assert second is not None
    assert first["content"] == "Comparer "
    assert second["content"] == "les options."
    assert first["stream_id"] == second["stream_id"]
    assert completed == []
    assert deferred == []


def test_reasoning_summary_sections_are_distinct_thinking_blocks() -> None:
    trace = CodexStreamTrace()
    first = trace.record_reasoning_delta(
        "reasoning-1",
        0,
        "Inspecter les contrats.",
    )
    second = trace.record_reasoning_delta(
        "reasoning-1",
        1,
        "Vérifier les tests.",
    )

    completed = trace.complete_reasoning_item(
        "reasoning-1",
        ("Inspecter les contrats.", "Vérifier les tests."),
    )

    assert first is not None
    assert second is not None
    assert first["stream_id"] != second["stream_id"]
    assert completed == []


def test_divergent_completion_never_replaces_an_observed_fragment() -> None:
    trace = CodexStreamTrace()
    live = trace.record_reasoning_delta(
        "reasoning-1",
        0,
        "Première observation.",
    )

    completed = trace.complete_reasoning_item(
        "reasoning-1",
        ("Texte de complétion différent.",),
    )

    assert live is not None
    assert [message["content"] for message in [live, *completed]] == [
        "Première observation.",
        "Texte de complétion différent.",
    ]
    assert live["stream_id"] != completed[0]["stream_id"]


def test_late_revision_is_appended_as_a_new_block_after_prior_emission() -> None:
    trace = CodexStreamTrace()
    first = trace.complete_reasoning_item("reasoning-1", ("Première version.",))
    revision = trace.complete_reasoning_item("reasoning-1", ("Version révisée.",))

    assert [message["content"] for message in first] == ["Première version."]
    assert [message["content"] for message in revision] == ["Version révisée."]
    assert first[0]["stream_id"] != revision[0]["stream_id"]
    assert trace.finish()[0] == []


def test_anonymous_commentary_items_never_share_or_replace_content() -> None:
    trace = CodexStreamTrace()
    _, first = trace.record_agent_delta(
        "",
        "Première réflexion.",
        phase="commentary",
    )
    assert trace.complete_agent_item(
        "",
        "Première réflexion.",
        phase="commentary",
    ) == []
    _, second = trace.record_agent_delta(
        "",
        "Deuxième réflexion.",
        phase="commentary",
    )
    assert trace.complete_agent_item(
        "",
        "Deuxième réflexion.",
        phase="commentary",
    ) == []

    assert first is not None
    assert second is not None
    assert [message["content"] for message in [first, second]] == [
        "Première réflexion.",
        "Deuxième réflexion.",
    ]
    assert first["stream_id"] != second["stream_id"]
