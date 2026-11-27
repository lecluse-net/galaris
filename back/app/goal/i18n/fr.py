"""French Goal runtime messages."""

default: dict[str, object] = {
    "goal_process": {
        "launch_privilege_required": "Vous devez avoir le droit de lancer des processus pour en choisir un pour un objectif.",
        "unavailable": "Le processus choisi est indisponible pour l’agent de l’objectif.",
        "admission_failed": "Le processus n’a pas pu démarrer. Vérifiez les droits de l’agent, l’événement de début et les entrées requises.",
        "outcomes": {
            "error": "L’exécution du processus a échoué.",
            "cancelled": "L’exécution du processus a été annulée.",
            "unavailable": "L’exécution du processus est indisponible.",
        },
    },
    "goal_retrospective": {
        "title": "Auto-apprentissage",
        "description": "Examiner le travail récent et améliorer ses compétences personnelles à partir de preuves observables.",
        "legacy_title": "Rétrospective hebdomadaire",
        "legacy_description": "Chaque semaine, examiner le travail récent et améliorer ses compétences personnelles à partir de preuves observables.",
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
        "answer_received": (
            "Réponse reçue pour l’objectif « ${goal} » (#${reference}). "
            "Suivi de l’objectif · galaris://goal/${goal_id}"
        ),
        "answer_completed": "L’objectif « ${goal} » est terminé. Suivi · galaris://goal/${goal_id}",
        "answer_processed": (
            "Le cycle de l’objectif « ${goal} » qui a reçu votre réponse est terminé. "
            "L’objectif reste actif. Suivi · galaris://goal/${goal_id}"
        ),
        "answer_paused": (
            "Votre réponse reste enregistrée. L’objectif « ${goal} » est en pause. "
            "Suivi · galaris://goal/${goal_id}"
        ),
        "answer_cycle_error": (
            "Le cycle de reprise de l’objectif « ${goal} » a échoué. Votre réponse reste enregistrée "
            "pour le prochain cycle. Suivi · galaris://goal/${goal_id}"
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
