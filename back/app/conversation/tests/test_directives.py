from app.conversation.directives import (
    available_chat_directives,
    parse_direct_task_directive,
)


def test_task_directives_combine_in_any_order() -> None:
    directive = parse_direct_task_directive(
        "  Construis @high la scène @task 3D @approve @plan  "
    )

    assert directive is not None
    assert directive.objective == "Construis la scène 3D"
    assert directive.forced_route == "PLAN"
    assert directive.forced_effort == "high"
    assert directive.auto_approve is True
    assert directive.error is None


def test_briefing_directive_forces_briefing_before_execution() -> None:
    directive = parse_direct_task_directive("@task @briefing Vas-y, fais-le")

    assert directive is not None
    assert directive.objective == "Vas-y, fais-le"
    assert directive.forced_route == "BRIEFING"
    assert directive.forced_effort == "high"
    assert directive.briefing_requested is True


def test_plan_directive_implies_a_direct_task() -> None:
    directive = parse_direct_task_directive("@plan Construis la scène 3D.")

    assert directive is not None
    assert directive.objective == "Construis la scène 3D."
    assert directive.forced_route == "PLAN"
    assert directive.forced_effort == "high"


def test_non_task_text_remains_in_the_conversation_dispatch_path() -> None:
    assert parse_direct_task_directive("Explique les commandes disponibles.") is None


def test_task_directive_is_recognized_at_the_end_of_the_objective() -> None:
    directive = parse_direct_task_directive("Calcule 5 + 5 @high @task")

    assert directive is not None
    assert directive.objective == "Calcule 5 + 5"
    assert directive.forced_effort == "high"


def test_reasoning_effort_directive_implies_a_direct_task() -> None:
    directive = parse_direct_task_directive("@effort Analyse ce rapport")

    assert directive is not None
    assert directive.objective == "Analyse ce rapport"
    assert directive.error is None


def test_hidden_task_control_is_recognized_from_message_metadata() -> None:
    directive = parse_direct_task_directive(
        "Analyse ce rapport",
        task_requested=True,
    )

    assert directive is not None
    assert directive.objective == "Analyse ce rapport"
    assert directive.error is None


def test_task_directive_reports_conflicts_without_model_interpretation() -> None:
    route_conflict = parse_direct_task_directive("@task @exec @plan Fais ça")
    effort_conflict = parse_direct_task_directive("@standard @task @high Fais ça")
    missing = parse_direct_task_directive("@task @plan")
    incompatible = parse_direct_task_directive("@task @briefing @standard Fais ça")

    assert route_conflict is not None and route_conflict.error == "conflicting_route"
    assert effort_conflict is not None and effort_conflict.error == "conflicting_effort"
    assert missing is not None and missing.error == "missing_objective"
    assert incompatible is not None and incompatible.error == "conflicting_effort"


def test_exec_and_plan_are_catalogued_only_for_internal_driver() -> None:
    assert available_chat_directives("internal") == (
        "task",
        "exec",
        "plan",
        "standard",
        "high",
        "effort",
        "approve",
    )
    assert available_chat_directives("hermes") == (
        "task",
        "standard",
        "high",
        "effort",
        "approve",
    )
