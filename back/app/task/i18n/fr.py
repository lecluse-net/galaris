"""French i18n catalog for task scheduling and administration."""

default: dict[str, object] = {
    "task_collab": {
        "request_label": "Demande à ${peer}",
        "late_complement": (
            "📩 Complément — **${peer}** a finalement répondu après le délai :\n\n${answer}"
        ),
        "late_complement_with_question": (
            "📩 Complément — **${peer}** a finalement répondu après le délai à « ${question} » :\n\n${answer}"
        ),
        "peer_failed": "Le collègue n’a pas pu traiter la demande car sa tâche a échoué.",
        "empty_response": "(réponse vide)",
        "no_response": "aucune réponse",
        "peer": "le collègue",
        "timeout": "Aucune réponse de ${peer} avant l’expiration du délai.",
        "resume_prompt": (
            "Voici les résultats des travaux délégués ou demandés. Certains peuvent être vides, "
            "en échec ou tardifs ; ne signalez au demandeur que les problèmes qui comptent. "
            "Synthétisez maintenant ces résultats et répondez au demandeur. Ne répétez pas et "
            "ne déléguez pas à nouveau les demandes déjà résolues :"
        ),
    },
    "task_mcp": {
        "self_delegation": (
            "Auto-délégation refusée : vous êtes déjà l’agent cible. Exécutez l’objectif dans "
            "la tâche courante au lieu d’appeler task_run sur vous-même."
        ),
        "agent_not_found": "L’agent cible ${agent_id} de la délégation n’existe pas.",
        "already_terminal": "La tâche est déjà terminée.",
        "task_not_found": "Tâche introuvable : ${task_id}",
        "selector_required": "task_get nécessite task_id ou uuid",
        "invalid_uuid": "URI ou UUID de Task invalide : ${task_id}",
        "ambiguous_uuid_prefix": "Préfixe d’UUID ambigu : ${task_id}",
        "root_only": "task_stop ne peut arrêter qu’une tâche racine de niveau 1.",
        "self_stop": "Auto-arrêt refusé : la cible est la tâche courante.",
        "stopped_by": "Tâche arrêtée définitivement par ${stopper}.",
        "stopped_by_with_reason": "Tâche arrêtée définitivement par ${stopper}. Motif : ${reason}",
        "stopped_count": "Tâche arrêtée définitivement (${count} tâche(s) marquée(s) ERROR).",
        "paused_delegation": (
            "Votre tâche est en pause. Vous ne pouvez pas créer de sous-tâche avant sa reprise."
        ),
        "round_limit": (
            "La limite des cycles de délégation est atteinte. Concluez avec les résultats déjà "
            "disponibles au lieu de créer de nouvelles sous-tâches."
        ),
    },
    "task_scheduler": {
        "budget_exhausted": "Admission différée : ${reason}. La tâche reprendra lorsque la capacité sera disponible ; les résultats existants sont conservés.",
        "budget_user_capacity": "limite de tâches simultanées du propriétaire atteinte",
        "budget_time": "limite de temps écoulé atteinte",
        "budget_tokens": "capacité de jetons épuisée, réservations actives comprises",
        "budget_cost": "capacité de coût épuisée, réservations actives comprises",
        "budget_cycle": "une boucle dans la filiation des tâches nécessite une vérification",
        "action_failed": "L’action a renvoyé un résultat en échec.",
        "interactive_slot_reserved": "Créneau interactif réservé ; l’action n’a pas été lancée.",
        "interrupted_after_children": "L’exécution s’est arrêtée après la création de sous-tâches.",
        "failed_after_attempts": "Échec après ${count} tentative(s) : ${error}",
        "orphan_recovered": "Une tâche EXEC orpheline a été reprise automatiquement.",
        "orphan_unsafe": (
            "La tâche EXEC orpheline n’a pas été rejouée car une tentative précédente a utilisé des outils."
        ),
    },
    "task_api": {
        "errors": {
            "not_found": "Tâche introuvable",
            "cannot_restart": "La tâche ne peut pas être redémarrée depuis le statut ${status}.",
            "paused": "La tâche est en pause. Reprenez-la avant de la redémarrer.",
            "revision_conflict": "Révision ${expected} attendue ; la révision courante est ${current}.",
            "modified_concurrently": "La tâche ${task_id} a été modifiée par une autre transaction.",
            "immutable_fields": "Ces champs ne peuvent plus être modifiés après le démarrage de la tâche : ${fields}",
            "action_running": "Une action est actuellement en cours sur cette tâche.",
            "active_delete": "La tâche ${task_id} est active. Annulez-la avant de la supprimer.",
            "cancelled_by_user": "Tâche annulée par un utilisateur.",
            "force_terminated_by_user": "Tâche terminée de force par un utilisateur.",
            "retained": "La tâche ${task_id} est encore nécessaire à une opération en cours et ne peut pas être supprimée.",
        },
    },
}
