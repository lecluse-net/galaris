default: dict[str, object] = {
    "conversation": {
        "task_source_request": "Demande originale",
        "task_execution_context": "Contexte d’exécution",
        "delivery_resolution_conflict": "La livraison a changé ou la justification est insuffisante. Actualisez le détail avant de réessayer.",
        "round_not_found": "Tour de conversation introuvable.",
        "explicit_task_started": "C’est lancé en arrière-plan. Je te transmettrai le résultat ici dès qu’il sera prêt.",
        "direct_task_started": "J’ai créé et lancé la tâche « ${objective} ». Je publierai son résultat ici dès qu’elle sera terminée.",
        "task_directive_missing_objective": "Ajoute un objectif après la commande pour créer la tâche.",
        "task_directive_conflicting_route": "Choisis exactement un mode parmi @exec, @plan ou @briefing pour cette tâche.",
        "task_directive_conflicting_effort": "Choisis soit @standard, soit @high, et ne combine pas @standard avec @plan ou @briefing.",
        "task_stopped": "C’est arrêté. La tâche en cours ne continuera pas.",
        "existing_file_resent": "Voilà, j’ai renvoyé le fichier existant « ${name} » sans le régénérer.",
        "failure_notification": {
            "message": (
                "Désolé, je n’ai pas pu terminer le traitement de ce message.\n\n"
                "Nature du problème : ${reason}\n"
                "Erreur renvoyée par le LLM : ${detail}\n\n"
                "Vous pouvez réessayer avec un nouvel envoi."
            ),
            "missing_detail": "aucun détail technique n’a été fourni",
            "reasons": {
                "content_filter": "le fournisseur d’IA a bloqué la réponse à cause de son filtre de sécurité.",
                "rate_limit": "le fournisseur d’IA a refusé temporairement la requête à cause d’un quota ou d’une limite de débit.",
                "authentication": "l’accès au fournisseur d’IA a été refusé à cause de son authentification ou de ses autorisations.",
                "timeout": "le service d’IA n’a pas répondu avant l’expiration du délai.",
                "configuration": "le modèle de conversation est absent, indisponible ou mal configuré.",
                "admission": "le travail demandé nécessitait une tâche ou un processus en arrière-plan, mais son lancement a échoué.",
                "budget": "la limite d’exécution de l’agent a été atteinte avant qu’une réponse puisse être finalisée.",
                "incomplete_response": "le fournisseur d’IA a interrompu sa réponse avant qu’elle soit complète.",
                "provider_unavailable": "le fournisseur d’IA est temporairement indisponible ou inaccessible.",
                "internal": "une erreur technique interne a interrompu le traitement.",
            },
        },
        "task_failure_notification": {
            "message": (
                "⚠️ Un problème s’est produit pendant la tâche « ${label} » et je n’ai "
                "pas pu la terminer.\n\nCause : ${detail}"
            ),
        },
        "task_success_notification": {
            "missing_detail": "✅ La tâche est terminée, sans résultat textuel.",
        },
    }
}
