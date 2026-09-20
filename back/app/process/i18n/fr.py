default = {
    "process": {
        "tracking": "Processus lancé. Identifiant de suivi Galaris : ${run_id}.",
        "summary": {
            "queued": "Le processus est en file d’attente.",
            "running": "Le processus est en cours.",
            "waiting": "Le processus attend un événement externe ou humain.",
            "success": "Le processus s’est terminé avec succès.",
            "error": "Le processus s’est terminé en erreur.",
            "cancelling": "L’annulation du processus est en cours.",
            "cancelled": "Le processus a été annulé.",
            "unknown": "L’état du processus n’a pas pu être déterminé.",
        },
        "await_label": "Attente du processus ${label}",
        "await_objective": "Attendre la fin du processus ${label} (${run_id}).",
        "await_success": "Le processus ${label} est terminé avec le statut ${status}. Résultat : ${output}",
        "await_error": "Le processus ${label} est terminé avec le statut ${status}. Erreur : ${error}",
        "await_timeout": "Le délai d’attente du processus ${label} est dépassé. Le run continue et reste consultable avec l’identifiant ${run_id}.",
        "recommendation_retry": "Vérifier la configuration et les données d’entrée avant de relancer.",
        "recommendation_engine": "Vérifier la disponibilité et les identifiants du moteur de processus.",
        "fake_engine_available": "Moteur de processus factice disponible.",
        "n8n": {
            "invalid_api_response": "Cette adresse ne renvoie pas une liste de l’API n8n.",
            "api_key_missing": "La clé API n8n n’est pas configurée.",
            "api_url_missing": "L’URL de l’API n8n n’est pas configurée.",
            "cancel_api_unavailable": (
                "Cette instance n8n n’expose pas l’annulation des exécutions dans son API publique."
            ),
            "invalid_webhook_url": "URL de webhook n8n invalide.",
            "workflow_webhook_missing": "Le workflow ne configure aucun webhook n8n.",
            "webhook_execution_id_missing": (
                "Le webhook n8n n’a renvoyé aucun identifiant d’exécution "
                "(executionId, execution_id ou id)."
            ),
            "execution_id_unknown": "L’identifiant d’exécution n8n est inconnu.",
            "api_available": "API n8n disponible ; ${count} workflow(s) découvert(s).",
            "execution_error": "Erreur d’exécution n8n",
        },
        "errors": {
            "not_allowed": "Le processus ${process_code} n’est pas autorisé pour cet agent.",
            "run_not_visible": "Le run demandé est introuvable ou n’est pas visible par cet agent.",
            "start_failed": "Le processus ${process_code} n’a pas pu être lancé : ${reason}",
            "resource_not_found": "Ressource introuvable",
            "process_not_found": "Processus introuvable",
            "run_not_found": "Exécution introuvable.",
            "file_not_found": "Fichier introuvable",
            "agent_not_found": "Agent introuvable.",
            "tool_not_found": "Outil de processus introuvable.",
            "already_linked": "Ce processus du moteur est déjà lié à Galaris.",
            "workflow_without_agent": "Workflow Galaris introuvable ou sans agent associé.",
            "wrong_workflow": "L’exécution n’appartient pas au workflow indiqué.",
            "resource_uri_invalid": "URI de ressource fichier invalide : ${uri}",
            "resource_too_large": "Le fichier ${uri} dépasse la limite de processus de ${max_bytes} octets.",
            "active_run_delete": "Une exécution active doit se terminer ou être annulée avant sa suppression.",
            "invalid_callback_token": "Jeton de callback invalide.",
            "retry_terminal_only": "Seules les exécutions en échec ou annulées peuvent être relancées.",
            "definition_not_found": "Définition de processus introuvable.",
            "correlation_not_found": "Exécution corrélée introuvable.",
            "correlated_process_denied": "Cet agent n’est pas autorisé à utiliser le processus corrélé.",
            "invalid_file_token": "Jeton de fichier invalide.",
            "file_reference_expired": "La référence du fichier a expiré.",
            "file_wrong_run": "Ce fichier n’appartient pas à l’exécution.",
            "engine_code_required": "Un moteur de processus doit posséder un code.",
            "engine_not_configured": "Moteur de processus non configuré : ${code}",
            "workflow_not_allowed": (
                "Le workflow n’est pas autorisé pour cet agent : ${workflow_id}"
            ),
            "engine_process_id_missing": (
                "La définition ne possède aucun identifiant de processus moteur."
            ),
            "engine_rejected": "Le moteur de processus a refusé l’exécution.",
            "engine_timeout": "La connexion au moteur de processus a expiré.",
        },
    }
}
