default: dict[str, object] = {
    "conversation": {
        "task_source_request": "Original request",
        "task_execution_context": "Execution context",
        "delivery_resolution_conflict": "The delivery changed or verification evidence is insufficient. Refresh the details before trying again.",
        "round_not_found": "Conversation round not found.",
        "explicit_task_started": "It’s now running in the background. I’ll send the result here as soon as it is ready.",
        "direct_task_started": "I created and started the Task “${objective}”. I’ll post its result here when it finishes.",
        "task_directive_missing_objective": "Add an objective after the command to create the Task.",
        "task_directive_conflicting_route": "Choose exactly one of @exec, @plan, or @briefing for this Task.",
        "task_directive_conflicting_effort": "Choose either @standard or @high, and do not combine @standard with @plan or @briefing.",
        "task_stopped": "Stopped. The current Task will not continue.",
        "existing_file_resent": "I re-sent the existing file '${name}' without regenerating it.",
        "failure_notification": {
            "message": (
                "Sorry, I could not finish processing this message.\n\n"
                "Nature of the problem: ${reason}\n"
                "Error returned by the LLM: ${detail}\n\n"
                "You can retry with a new message."
            ),
            "missing_detail": "no technical detail was provided",
            "reasons": {
                "content_filter": "the AI provider blocked the response because of its safety filter.",
                "rate_limit": "the AI provider temporarily rejected the request because of a quota or rate limit.",
                "authentication": "access to the AI provider was rejected because of its authentication or permissions.",
                "timeout": "the AI service did not respond before the timeout expired.",
                "configuration": "the conversation model is missing, unavailable, or misconfigured.",
                "admission": "the request required a background Task or Process, but starting it failed.",
                "budget": "the agent execution limit was reached before a response could be finalized.",
                "incomplete_response": "the AI provider interrupted its response before it was complete.",
                "provider_unavailable": "the AI provider is temporarily unavailable or unreachable.",
                "internal": "an internal technical error interrupted processing.",
            },
        },
        "task_failure_notification": {
            "message": (
                "⚠️ A problem occurred while running the task “${label}”, and I could not "
                "complete it.\n\nCause: ${detail}"
            ),
        },
        "task_success_notification": {
            "missing_detail": "✅ The Task completed without a textual result.",
        },
    }
}
