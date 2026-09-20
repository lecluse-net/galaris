"""English catalog for task scheduling and administration."""

default: dict[str, object] = {
    "task_collab": {
        "request_label": "Request to ${peer}",
        "late_complement": (
            "📩 Follow-up — **${peer}** eventually replied after the deadline:\n\n${answer}"
        ),
        "late_complement_with_question": (
            "📩 Follow-up — **${peer}** eventually replied after the deadline to “${question}”:\n\n${answer}"
        ),
        "peer_failed": "The peer could not process the request because their task failed.",
        "empty_response": "(empty response)",
        "no_response": "no response",
        "peer": "the peer",
        "timeout": "No response from ${peer} before the deadline.",
        "resume_prompt": (
            "Results from delegated or requested work follow. Some may be empty, failed, or "
            "late; only report issues that matter to the requester. Synthesize these results "
            "and answer the requester now. Do not repeat or delegate requests that have already "
            "been resolved:"
        ),
    },
    "task_mcp": {
        "self_delegation": (
            "Self-delegation rejected: you are already the target agent. Perform the objective "
            "in the current task instead of calling task_run on yourself."
        ),
        "agent_not_found": "Delegation target Agent ${agent_id} does not exist.",
        "already_terminal": "The task is already terminal.",
        "task_not_found": "Task not found: ${task_id}",
        "selector_required": "task_get requires task_id or uuid",
        "invalid_uuid": "Invalid Task URI or UUID: ${task_id}",
        "ambiguous_uuid_prefix": "Ambiguous UUID prefix: ${task_id}",
        "root_only": "task_stop can only stop a level-one root task.",
        "self_stop": "Self-stop rejected: the target is the current task.",
        "stopped_by": "Task permanently stopped by ${stopper}.",
        "stopped_by_with_reason": "Task permanently stopped by ${stopper}. Reason: ${reason}",
        "stopped_count": "Task permanently stopped (${count} task(s) marked ERROR).",
        "paused_delegation": (
            "Your task is paused. You cannot create a child task until it is resumed."
        ),
        "round_limit": (
            "The delegation-cycle limit has been reached. Conclude with the results already "
            "available instead of creating more child tasks."
        ),
    },
    "task_scheduler": {
        "budget_exhausted": "Admission deferred: ${reason}. The task will resume when capacity is available; existing results are preserved.",
        "budget_user_capacity": "owner concurrent task limit reached",
        "budget_time": "elapsed time limit reached",
        "budget_tokens": "token capacity exhausted, including active reservations",
        "budget_cost": "cost capacity exhausted, including active reservations",
        "budget_cycle": "cyclic causal lineage requires review",
        "action_failed": "The action returned a failed result.",
        "interactive_slot_reserved": "Interactive slot reserved; action was not started.",
        "interrupted_after_children": "Execution stopped after creating child tasks.",
        "failed_after_attempts": "Failed after ${count} attempt(s): ${error}",
        "orphan_recovered": "Automatically recovered an orphaned EXEC task.",
        "orphan_unsafe": (
            "The orphaned EXEC task was not replayed because an earlier attempt used tools."
        ),
    },
    "task_api": {
        "errors": {
            "not_found": "Task not found",
            "cannot_restart": "The task cannot be started again from status ${status}.",
            "paused": "The task is paused. Use resume before starting it again.",
            "revision_conflict": "Expected revision ${expected}; current revision is ${current}.",
            "modified_concurrently": "Task ${task_id} was modified by another transaction.",
            "immutable_fields": "Fields cannot be changed after the task starts: ${fields}",
            "action_running": "An action is currently running on this task.",
            "active_delete": "Task ${task_id} is active. Cancel it before deleting it.",
            "cancelled_by_user": "Task cancelled by a user.",
            "force_terminated_by_user": "Task force-terminated by a user.",
            "retained": "Task ${task_id} is still required by an active operation and cannot be deleted.",
        },
    },
}
