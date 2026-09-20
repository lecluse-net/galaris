"""French Hermes bridge messages."""

default = {
    "hermes": {
        "tool_completed": "Terminé.",
        "tool_running": "En cours d'exécution…",
        "kanban_completed_without_summary": (
            "Hermès a terminé la tâche Kanban sans résumé de passation."
        ),
        "approval_default_description": "commande potentiellement dangereuse",
        "approval_reason": "Raison",
        "approval_command": "Commande",
        "approval_title": "Approbation requise",
        "approval_once": "Approuver une fois",
        "approval_session": "Approuver pour cette session",
        "approval_deny": "Refuser",
        "approval_auto_granted": "Approbation accordée automatiquement (auto_approve).",
        "approval_auto_failed": "L'approbation automatique Hermès a échoué.",
        "approval_agent_denied": "Approbation refusée : le demandeur est un agent, pas un humain. Activez auto_approve pour l'autoriser.",
        "approval_request_sent": "Demande d'approbation envoyée dans la conversation.",
        "approval_no_channel": "Approbation Hermès refusée automatiquement, car aucun canal de messagerie n'est disponible.",
        "errors": {
            "agent_not_found": "Agent introuvable.",
            "wrong_driver": "Cet agent n’utilise pas le driver Hermès.",
            "no_runtime": "Cet agent ne possède aucune instance Hermès.",
            "mcp_url_required": "APP_HOST est requis pour le proxy LLM Hermès",
            "agent_code_missing": "L’agent ${agent_id} ne possède aucun code configuré.",
            "model_missing": "Aucun modèle effectif n’est configuré pour l’agent Hermès ${agent_code}",
            "system_token_missing": "Le jeton système Hermès manque pour l’agent ${agent_code}",
            "template_missing": "Répertoire default-agent introuvable : ${path}",
            "configuration_incomplete": (
                "La configuration Hermès de l’agent ${agent_code} est incomplète "
                "(url, api_key, model)."
            ),
            "connect_failed": "Échec de la connexion à Hermès : ${error}",
            "run_events_http": "Les événements du run Hermès ont renvoyé HTTP ${status} : ${error}",
            "run_id_missing": "Hermès /v1/runs n’a renvoyé aucun run_id",
            "run_not_found": "Hermès ne connaît plus le run ${run_id} ; il ne peut pas être repris.",
            "run_ended": "Le run Hermès s’est terminé avec le statut ${status}.",
            "execution_failed": "Erreur : ${error}",
            "session_create_failed": (
                "Erreur : impossible de créer la session Hermès « ${session_id} » (${error}). "
                "L’instance peut ne pas prendre en charge /api/sessions et nécessiter une mise à jour."
            ),
            "run_start_failed": "Erreur : impossible de lancer le run Hermès (${error}).",
            "generic": "Erreur Hermès",
            "llm_interrupted": "Appel LLM interrompu avec le statut ${status}.",
            "terminal_result_missing": (
                "Le driver Hermès n’a produit aucun résultat final."
            ),
            "kanban_transport_invalid": (
                "Transport Kanban Hermès non pris en charge : ${transport}."
            ),
            "kanban_task_id_invalid": "Identifiant de tâche Kanban Hermès invalide.",
            "kanban_board_unsupported": (
                "Tableau Kanban Hermès non pris en charge : ${board}."
            ),
            "kanban_configuration_incomplete": (
                "La configuration d’exécution Kanban Hermès est incomplète."
            ),
            "kanban_management_unsupported": (
                "Le gestionnaire générique de harnais n’expose pas les commandes "
                "Kanban Hermès. Les nouveaux runs Hermès utilisent l’API directe streamée."
            ),
            "kanban_terminal_failure": (
                "Le Kanban Hermès s’est terminé avec le statut ${status} : ${reason}"
            ),
            "path_empty": "Le chemin est vide.",
            "path_traversal": "La traversée de chemin est interdite : ${path}",
            "path_invalid": "Chemin invalide : ${path}",
            "path_outside_root": "L’accès hors de ${root} est interdit : ${path}",
            "filename_missing": "Nom de fichier absent sous ${root} : ${path}",
            "cancel_run_not_active": (
                "Aucun run Hermès actif n’est enregistré pour ${run_id}."
            ),
        },
    }
}
