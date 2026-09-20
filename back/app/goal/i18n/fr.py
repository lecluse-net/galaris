"""French Goal runtime messages."""

default: dict[str, object] = {
    "goal_documents": {
        "folder": "Objectifs",
        "untitled": "Objectif",
    },
    "goal_referrer": {
        "question_required": "La question au référent ne peut pas être vide.",
        "question_too_long": "La question ne peut pas dépasser ${maximum} caractères.",
        "goal_task_required": "Cette action nécessite une tâche active appartenant à un objectif.",
        "goal_not_active": "L’objectif doit être actif pour interroger son référent.",
        "human_required": "Cet objectif n’a pas de référent humain Messenger.",
        "already_waiting": "Une réponse de ${referrer} est déjà attendue pour cet objectif.",
        "wait_label": "Réponse attendue de ${referrer}",
        "question_title": "Question concernant l’objectif « ${goal} »",
        "question_sent": (
            "Question envoyée à ${referrer}. Cette tâche attend maintenant sa réponse ; "
            "les relances et la pause éventuelle de l’objectif sont gérées automatiquement."
        ),
        "reminder": (
            "🔔 **Relance ${number}/${maximum} — objectif « ${goal} »**\n\n"
            "${question}\n\nRépondez en conservant la référence #${reference}."
        ),
        "interaction_unavailable": (
            "L’interaction Messenger qui attendait la réponse du référent est indisponible."
        ),
        "resume_without_answer": (
            "Le référent humain n’a pas répondu après ${count} relance(s). "
            "L’objectif a été repris manuellement avec les informations disponibles."
        ),
    },
}
