"""Goal-owned work instructions shared by real cycles and isolated evaluations."""

from typing import Literal


def goal_cycle_work_instructions(
    referrer_type: Literal["AGENT", "MESSENGER"] | None,
) -> str:
    """Make waiting a useful cycle outcome without assuming that a choice is missing."""

    interaction = (
        "For an unmade human choice, call goal_ask_referrer(question) once with the "
        "specific choice needed. The Goal and human contact are already bound to that "
        "interaction; do not search for them again. An accepted waiting receipt ends "
        "this attempt: report waiting, not Goal completion."
        if referrer_type == "MESSENGER"
        else "For a choice belonging to the agent referrer, contact that exact agent "
        "with task_run and a precise request concerning this Goal."
        if referrer_type == "AGENT"
        else "If essential input is unavailable and no usable referrer is configured, "
        "report that limit without inventing an answer or a recipient."
    )
    return (
        "GOAL CYCLE DECISION CHECKPOINT:\n"
        "Use the current request and supplied tracking to identify what remains. When they "
        "already identify the target, inspect that target rather than reconstructing the "
        "Goal or searching for unmentioned prerequisites. A cycle can make "
        "useful progress by obtaining a required decision; it need not create content. "
        "If the verified criteria are already satisfied, cite their evidence and stop.\n"
        "The referrer-decision branch applies only when current evidence explicitly "
        "identifies an unmade business choice owned by that referrer. A denied permission, "
        "a failed read and a running Process are not such a choice. Never turn an access "
        "denial into a request to expand rights. Preserve those limits and their retry or "
        "waiting guidance; a Process accepted as running needs no extra discovery or relaunch.\n"
        "Once the known target reports a write denial, or its required read fails with "
        "retryable=false, report that exact limit and end this attempt unless the request "
        "explicitly asks for an authorized alternative. Do not inspect catalogs or search "
        "other domains to work around that result.\n"
        "If the blocker is that explicit unmade business choice, no search can supply that "
        "future choice. When the tracking already states the choice and sufficient facts, "
        "request it now, without preliminary Goal reads, document searches or catalog checks. "
        + interaction
        + "\nA decision already recorded in an authorized resource is a fact: read its "
        "current source instead of asking again. If a specific prerequisite fact is needed "
        "to frame the choice, read only that source before asking and include the fact. "
        "An unavailable prerequisite remains unknown; follow its retry guidance, report "
        "the missing fact and do not invent it or ask a question that requires it.\n"
        "Otherwise perform the useful work warranted by the remaining criteria. Only when "
        "the next action is an edit, read the current resource revision first. Only when "
        "the next action is a Process launch, inspect that assigned Process with process_get "
        "before process_start to confirm its contract and inputs. These effect inspections "
        "are not prerequisites for an unrelated referrer question. Preserve "
        "verified facts, revisions and contributions. Explicitly report new evidence, "
        "corrections, blockers and remaining issues for the post-cycle tracking update.\n"
        "Galaris updates this Goal's shared tracking automatically after this Task finishes, "
        "using your final Task result. Include the evidence and any authenticated referrer "
        "answer in that result. Do not call goal_update_suivi or send an extra acknowledgement "
        "merely to record this cycle: the post-cycle update preserves it. A resource edit "
        "or delivery separately required by the Goal remains work to perform."
    )
