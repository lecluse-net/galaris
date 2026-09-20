"""English Goal runtime messages."""

default: dict[str, object] = {
    "goal_documents": {
        "folder": "Goals",
        "untitled": "Goal",
    },
    "goal_referrer": {
        "question_required": "The question for the referrer cannot be empty.",
        "question_too_long": "The question cannot exceed ${maximum} characters.",
        "goal_task_required": "This action requires an active Task belonging to a Goal.",
        "goal_not_active": "The Goal must be active before asking its referrer.",
        "human_required": "This Goal has no human Messenger referrer.",
        "already_waiting": "This Goal is already waiting for an answer from ${referrer}.",
        "wait_label": "Waiting for ${referrer}",
        "question_title": "Question about Goal “${goal}”",
        "question_sent": (
            "Question sent to ${referrer}. This Task is now waiting for the answer; reminders "
            "and any Goal pause are handled automatically."
        ),
        "reminder": (
            "🔔 **Reminder ${number}/${maximum} — Goal “${goal}”**\n\n"
            "${question}\n\nKeep reference #${reference} in your answer."
        ),
        "interaction_unavailable": (
            "The Messenger interaction waiting for the referrer's answer is unavailable."
        ),
        "resume_without_answer": (
            "The human referrer did not answer after ${count} reminder(s). "
            "The Goal was resumed manually with the available information."
        ),
    },
}
