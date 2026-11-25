"""French messages for tool discovery and search."""

default: dict[str, object] = {
    "approval_preview": {
        "first_name": "Prénom",
        "last_name": "Nom de famille",
        "job_title": "Intitulé du poste",
        "job_description": "Fiche de poste",
        "personality": "Personnalité",
        "code": "Code de l’agent",
        "target_agent_id": "Identifiant de l’agent",
        "title_id": "Identifiant de la civilité",
        "user_id": "Identifiant du responsable",
        "team_ids": "Identifiants des équipes",
        "agent_driver": "Harnais",
        "profile_id": "Identifiant du profil",
        "fallback_profile_id": "Identifiant du profil de secours",
        "voice": "Voix",
        "weekdays": "Jours",
        "start_time": "Début",
        "end_time": "Fin",
        "days": {"0": "lundi", "1": "mardi", "2": "mercredi", "3": "jeudi", "4": "vendredi", "5": "samedi", "6": "dimanche"},
        "external_tool": "Appeler « ${function} » sur ${service}",
        "external_resource": "Lire la ressource « ${function} » sur ${service}",
        "external_prompt": "Consulter le modèle d’instructions « ${function} » sur ${service}",
        "unknown_service": "le service connecté",
        "unknown_action": "Examiner une demande d’autorisation",
        "runtime_command": "Exécuter une commande avec ${runtime}",
        "runtime_files": "Appliquer des changements aux fichiers avec ${runtime}",
        "runtime_read": "Lire des fichiers avec ${runtime}",
        "runtime_other": "Exécuter l’action « ${function} » avec ${runtime}",
        "runtime_generic": "le harnais de l’agent",
        "once": "Cette décision concerne uniquement l’action décrite ici.",
        "goal_create_explanation": "Si l’objectif est actif, son premier cycle sera planifié dès sa création.",
        "goal_tracking_explanation": "Le nouveau texte de suivi figure ci-dessous.",
        "goal_update_explanation": "Les champs ci-dessous indiquent les modifications proposées.",
        "title": "Titre",
        "name": "Nom",
        "goal_id": "Objectif",
        "agent_id": "Agent chargé de l’objectif",
        "referrer_display_name": "Référent",
        "service_code": "Code du Service",
        "account_email": "Adresse du compte",
        "referrer_user_id": "Identifiant du référent",
        "expected_revision": "Révision de référence",
        "cycle_delay_seconds": "Intervalle entre les cycles, en secondes",
        "referrer_max_reminders": "Nombre maximal de relances du référent",
        "schedule_enabled": "Plage horaire personnalisée activée",
        "schedule": "Plage horaire",
        "active": "Objectif actif",
        "uri": "Ressource",
        "message": "Message",
        "room_id": "Conversation",
        "recipient": "Destinataire",
        "calendar_id": "Agenda",
        "event_id": "Événement",
        "task_id": "Tâche",
        "objective": "Objectif de la tâche",
        "process_code": "Processus",
        "workflow_id": "Processus",
        "run_id": "Exécution",
        "changes": "Modifications proposées",
        "actions": {
            "agent_create": "Créer un agent",
            "agent_update": "Modifier un agent",
            "agent_delete": "Supprimer un agent",
            "goal_create": "Créer un objectif",
            "goal_update": "Modifier un objectif",
            "goal_pause": "Mettre un objectif en pause",
            "goal_resume": "Reprendre un objectif",
            "goal_complete": "Marquer un objectif comme terminé",
            "goal_delete": "Supprimer un objectif",
            "goal_update_suivi": "Remplacer le texte de suivi d’un objectif",
            "goal_run_now": "Lancer un cycle d’objectif dès que possible",
            "task_run": "Lancer une tâche",
            "task_stop": "Arrêter une tâche",
            "process_start": "Lancer un processus",
            "process_create": "Créer un processus",
            "process_update": "Modifier la définition d’un processus",
            "process_share": "Modifier les droits d’accès à un processus",
            "process_run_cancel": "Arrêter une exécution de processus",
            "file_create": "Créer un fichier ou une ressource",
            "file_write": "Remplacer le contenu d’une ressource",
            "file_edit": "Modifier une partie du contenu",
            "file_append": "Ajouter du contenu à une ressource",
            "file_copy": "Copier une ressource",
            "file_move": "Déplacer une ressource",
            "file_rename": "Renommer une ressource",
            "file_delete": "Supprimer la ressource indiquée",
            "file_to_pdf": "Convertir une ressource en PDF et enregistrer le résultat",
            "calendar_create_event": "Créer un événement dans un agenda",
            "calendar_update_event": "Modifier un événement dans un agenda",
            "calendar_delete_event": "Supprimer un événement de l’agenda",
            "calendar_action_set": "Programmer une action autour d’un événement",
            "messenger_room_send_message": "Envoyer un message dans la conversation indiquée",
            "messenger_send_message_to_user": "Envoyer un message au destinataire indiqué",
            "messenger_send_audio_message": "Envoyer un message vocal",
            "messenger_send_file_to_user": "Envoyer un fichier au destinataire indiqué",
            "messenger_room_send_file": "Envoyer un fichier dans la conversation indiquée",
            "topic_create": "Créer un dossier thématique",
            "topic_update": "Modifier un dossier thématique",
            "topic_item_move": "Déplacer un élément vers un autre dossier thématique",
            "topic_merge": "Fusionner des dossiers thématiques",
            "topic_split": "Scinder un dossier thématique",
        },
        "send_mail": "Envoyer un e-mail",
        "process_mail": "Autoriser la lecture et le traitement de cet e-mail",
        "sender": "Expéditeur",
        "run_function": "Utiliser la fonction ${function}",
        "to": "Destinataires", "cc": "Copie", "bcc": "Copie cachée",
        "subject": "Objet", "body": "Message", "html_body": "Version HTML (texte source)",
        "description": "Description", "tracking_content": "Suivi",
        "reply_to": "Adresse de réponse", "attachments": "Pièces jointes",
        "command": "Commande", "cwd": "Dossier de travail", "path": "Chemin",
        "url": "Adresse web", "content": "Contenu", "destination": "Destination", "source": "Source",
        "yes": "Oui", "no": "Non",
        "truncated": "Aperçu abrégé. Ouvrez la demande dans Permissions pour consulter le contenu complet avant de décider.",
    },
    "services": {
        "deletion_changed": "Les données liées à ce service ont changé. Vérifiez le nouveau bilan avant de confirmer à nouveau.",
        "no_search_results": "Aucun résultat trouvé.",
        "summary": "Résumé : ${content}...",
        "search_unavailable": (
            "Erreur : le service de recherche est indisponible. Vérifiez que SearXNG fonctionne."
        ),
        "search_failed": "Échec de la recherche : le service n'a pas fourni de réponse exploitable.",
        "search_timeout": "Échec de la recherche : le délai de réponse du service est dépassé.",
        "search_http_failed": "Échec de la recherche : le service a répondu HTTP ${status}.",
        "search_partial": "Résultats partiels : ${engines} moteur(s) indisponible(s), ${discarded} entrée(s) inexploitable(s). Les sources ci-dessous restent utilisables ; la couverture est incomplète.",
        "search_degraded": "Recherche dégradée : ${engines} moteur(s) indisponible(s), ${discarded} entrée(s) inexploitable(s). Aucune source exploitable reçue ; cela ne permet pas de conclure à l'absence de sources pertinentes.",
        "list_failed": "Impossible de lister les services MCP.",
        "list_heading": "Vos outils MCP, classés par service applicatif :",
        "inactive_connection": "connexion inactive",
        "unavailable": "indisponible",
        "introspection_error": "Erreur d’introspection : ${error}",
        "introspection_failed": "Le serveur MCP externe n’a pas pu être inspecté.",
        "none_available": "Aucun service n’est actuellement disponible.",
        "present_in_run": "présent dans cette exécution",
        "absent_from_run": "absent de cette exécution ; nécessite un nouveau contexte d’exécution compatible",
        "availability_hint": (
            "Ce catalogue contient uniquement les fonctions qui vous sont actuellement autorisées. "
            "Une autorisation n’ajoute pas d’outils à une exécution existante. Utilisez uniquement "
            "les services exposés par votre runtime ; sans indication de présence, leur disponibilité "
            "n’est pas vérifiée. load_capability charge seulement les capacités déjà enregistrées "
            "par le runtime. Le navigateur, la recherche web et l’accès HTTPS aux fichiers sont "
            "des capacités distinctes."
        ),
        "call_failure": (
            "Échec de le service « ${name} ».\n"
            "Cause : ${reason}\n"
            "Type technique : ${error_type}.\n"
            "Action suivante : ${hint}\n"
            "Référence d’erreur : ${reference}"
        ),
        "call_failure_reasons": {
            "scope_clarification": "Cette cible est hors du périmètre d’exécution autorisé.",
            "scope_denied": "Le périmètre d’exécution est invalide, périmé ou n’autorise plus cette action.",
            "actionable": "L’opération a été refusée avec une erreur métier actionnable.",
            "invalid_arguments": (
                "Les arguments ou l’état courant de la ressource ont été refusés."
            ),
            "not_found": (
                "Une ressource, un identifiant, un fichier ou un répertoire demandé n’existe pas."
            ),
            "already_exists": "La destination ou la ressource existe déjà.",
            "permission_denied": (
                "L’opération n’est pas autorisée ou la destination n’est pas inscriptible."
            ),
            "permission_denied_http": "Le service distant a refusé l’accès (HTTP 403).",
            "authentication": "Le service distant a refusé l’authentification.",
            "unsupported": "Ce provider ne prend pas en charge l’opération demandée.",
            "timeout": "L’opération a dépassé son délai maximal configuré.",
            "connection": "Le service distant ou le transport n’a pas pu être joint.",
            "capacity": (
                "Une limite de taille, de quota ou d’espace disponible a été atteinte."
            ),
            "rate_limited": "Le service distant a limité la fréquence des appels.",
            "provider": "Le provider distant a refusé l’opération ou rencontré une erreur.",
            "unexpected": "Une erreur interne inattendue s’est produite.",
        },
        "call_failure_http": "Le service distant a retourné HTTP ${status} : ${reason}",
        "call_failure_hints": {
            "scope_clarification": (
                "Aucun effet n’a eu lieu. Ne réessayez pas sur cette cible avec d’autres arguments ou un autre outil. "
                "Le demandeur doit autoriser explicitement son URI exacte par un amendement de la tâche racine. "
                "Si cette tâche est terminée, elle ne peut plus être amendée : demandez une nouvelle tâche autorisant explicitement les cibles restantes. "
                "Si cette étape exige l’action, signalez BLOCKED avec la cible et l’autorisation manquante ; "
                "ne créez pas de document de remplacement pour contourner la restriction."
            ),
            "scope_denied": (
                "Aucun effet n’a eu lieu. Ne réessayez pas en changeant les arguments ou les services. "
                "Inspectez la tâche actuelle et replanifiez selon son périmètre autorisé courant ; "
                "arrêtez et signalez le blocage si le refus persiste."
            ),
            "actionable": "Appliquez la correction indiquée dans la cause avant de réessayer.",
            "invalid_arguments": (
                "Relisez le schéma de la fonction et corrigez formats, identifiants, bornes "
                "ou options incompatibles avant de réessayer."
            ),
            "not_found": (
                "Listez ou inspectez les ressources concernées afin d’obtenir un identifiant "
                "existant exact avant de réessayer."
            ),
            "not_found_file": (
                "Vérifiez l’URI exacte avec file_info ou listez son parent avec file_list "
                "avant de réessayer."
            ),
            "not_found_file_create": (
                "Le répertoire parent de destination est introuvable. Listez le parent prévu "
                "avec file_list, corrigez l’URI, puis réessayez une fois."
            ),
            "already_exists": (
                "Inspectez la ressource existante puis choisissez un autre identifiant ou "
                "l’opération explicite de mise à jour."
            ),
            "already_exists_file": (
                "Utilisez d’abord file_info, puis choisissez un autre chemin ou file_write "
                "uniquement si le remplacement est voulu."
            ),
            "permission_denied": (
                "Vérifiez la connexion active, les autorisations de l’agent, les droits du "
                "provider et les capacités de la destination ; ne réessayez pas à l’identique."
            ),
            "permission_denied_http": (
                "Vérifiez les conditions d’accès du service distant ou choisissez une autre "
                "source autorisée. Ce refus ne prouve pas un manque de droits dans Galaris "
                "et peut provenir d’une protection antibot ; ne réessayez pas à l’identique."
            ),
            "authentication": (
                "Vérifiez que la connexion est active et que ses identifiants sont valides ; "
                "ne réessayez pas à l’identique."
            ),
            "unsupported": (
                "Consultez les capacités annoncées par le provider et choisissez une "
                "opération prise en charge."
            ),
            "timeout": (
                "Vérifiez la disponibilité du service et la taille de l’entrée ; réessayez "
                "au plus une fois si l’opération peut être répétée sans risque."
            ),
            "connection": (
                "Vérifiez l’état du provider ou de la connexion avant de réessayer."
            ),
            "capacity": (
                "Réduisez le contenu ou libérez/augmentez le quota concerné avant de réessayer."
            ),
            "rate_limited": (
                "Attendez la fin du délai imposé par le provider avant un nouvel appel."
            ),
            "provider": (
                "Inspectez l’état du provider ou de la connexion et utilisez la référence "
                "d’erreur pour le diagnostic serveur."
            ),
            "unexpected": (
                "Ne répétez pas le même appel à l’aveugle ; transmettez la référence d’erreur "
                "pour le diagnostic serveur."
            ),
        },
        "mcp_test_tools_available": "${count} fonction(s) MCP disponible(s)",
        "mcp_test_connection_error": "Le serveur MCP externe n’a pas pu être joint.",
        "mcp_test_configuration_failed": "La configuration MCP est invalide.",
        "mcp_test_dns_summary": "Le nom d’hôte du serveur MCP ne peut pas être résolu.",
        "mcp_test_tcp_summary": "L’adresse est résolue, mais le port du serveur MCP est inaccessible.",
        "mcp_test_tls_summary": "Le port est accessible, mais la négociation TLS a échoué.",
        "mcp_test_process_failed": "Le processus MCP stdio n’a pas pu être démarré.",
        "mcp_test_authentication_failed": "Le serveur MCP est accessible, mais l’authentification a été refusée.",
        "mcp_test_authorization_failed": "Le serveur MCP est accessible, mais les identifiants ou leurs autorisations ont été refusés.",
        "mcp_test_endpoint_failed": "Le serveur répond, mais le chemin MCP est introuvable.",
        "mcp_test_protocol_failed": "Le serveur répond, mais la négociation du protocole MCP a échoué.",
        "mcp_test_timeout": "Le serveur MCP n’a pas répondu avant le délai du test.",
        "mcp_test_server_failed": "Le serveur MCP est accessible, mais il a retourné une erreur interne.",
        "mcp_test_server_creation_failed": "Le client MCP n’a pas pu être construit à partir de cette configuration.",
        "mcp_test_configuration_detail": "Configuration refusée : ${detail}",
        "mcp_test_configuration_valid": "Configuration valide : transport ${transport}, authentification ${auth_type}.",
        "mcp_test_network_not_applicable_stdio": "DNS, TCP et TLS ne s’appliquent pas au transport stdio.",
        "mcp_test_process_pending": "Le processus stdio sera lancé pendant la négociation MCP.",
        "mcp_test_url_invalid": "L’URL doit utiliser HTTP ou HTTPS et contenir un nom d’hôte valide.",
        "mcp_test_dns_timeout": "La résolution DNS de ${host} a expiré.",
        "mcp_test_dns_failed": "La résolution DNS de ${host} a échoué.",
        "mcp_test_dns_no_address": "${host} ne possède aucune adresse IPv4 ou IPv6 utilisable.",
        "mcp_test_dns_success": "${host} est résolu vers : ${addresses}.",
        "mcp_test_tcp_timeout": "La connexion TCP au port ${port} a expiré.",
        "mcp_test_tcp_failed": "Aucune adresse résolue n’accepte une connexion TCP sur le port ${port}.",
        "mcp_test_tcp_success": "Connexion TCP établie avec ${address}:${port}.",
        "mcp_test_tls_not_used": "TLS n’est pas utilisé par cette URL HTTP.",
        "mcp_test_tls_timeout": "La négociation TLS avec ${host} a expiré.",
        "mcp_test_tls_failed": "La négociation TLS ou la validation du certificat de ${host} a échoué.",
        "mcp_test_tls_success": "Négociation TLS réussie et certificat de ${host} validé.",
        "mcp_test_auth_not_verified": "Les identifiants sont configurés, mais aucune réponse applicative n’a permis de les vérifier.",
        "mcp_test_auth_not_configured": "Aucune authentification n’est configurée.",
        "mcp_test_protocol_not_attempted": "La négociation MCP n’a pas été tentée à cause de l’échec réseau précédent.",
        "mcp_test_auth_rejected": "Le serveur a retourné HTTP 401 : authentification refusée.",
        "mcp_test_authorization_rejected": "Le serveur a retourné HTTP 403 : identifiants ou autorisations refusés.",
        "mcp_test_process_started": "Le processus MCP stdio a démarré et répondu.",
        "mcp_test_auth_accepted": "La négociation MCP a réussi avec les identifiants configurés.",
        "mcp_test_protocol_success": "Initialisation et négociation du protocole MCP réussies.",
        "mcp_test_discovery_success": "${count} fonction(s) annoncée(s) par le serveur.",
        "errors": {
            "internal_export_forbidden": "Les services internes à Galaris ne peuvent pas être exportés.",
            "legacy_mail_namespace": "Ce service migré conserve l’espace de compatibilité mail://. Créez un service nommé pour le fournisseur afin d’ajouter un partage de fichiers ou une autre messagerie.",
            "system_read_only": "Ce service système obligatoire est en lecture seule et toujours actif.",
            "mcp_auth_change_confirmation": "Rouvrez le Service et confirmez le changement d’authentification MCP pour effacer les anciens identifiants.",
            "tool_not_found": "Service ${service_id} introuvable",
            "tool_exists_code": "Le service « ${code} » existe déjà",
            "invalid_yaml": "YAML invalide",
            "invalid_tool_definition": "La définition du service est invalide",
            "invalid_resource_service_code": (
                "Le nom technique d’un service avec partage de fichiers ou messagerie doit commencer "
                "par une lettre minuscule et ne contenir que des lettres minuscules, des chiffres "
                "et les caractères +, . ou -. Remplacez les _ et les espaces par des tirets "
                "(exemple : partage-fichiers)."
            ),
            "password_default_forbidden": (
                "Les paramètres de connexion de type mot de passe ne peuvent pas définir "
                "de valeur partagée par défaut : ${fields}"
            ),
            "secret_placeholder_without_value": (
                "La valeur non lisible ${field} n’a aucune valeur existante à conserver"
            ),
            "yaml_mapping_required": "Le YAML doit contenir un objet associatif",
            "code_missing": "Champ « code » manquant",
            "tool_exists": "Un service nommé « ${code} » existe déjà",
            "stdio_command_missing": "La commande stdio n’est pas définie",
            "unsupported_mcp_type": "Type MCP non pris en charge : ${type}",
            "server_creation_failed": "Impossible de créer le serveur MCP",
            "connection_reference_missing": (
                "Le paramètre de connexion « ${parameter} » est requis par la configuration MCP"
            ),
            "basic_auth_parameters_required": (
                "L’authentification Basic requiert les paramètres « ${login_parameter} » et "
                "« ${password_parameter} »"
            ),
            "auth_token_missing": (
                "Authentification ${auth_type} : aucun jeton disponible "
                "(paramètre=« ${parameter} », jeton statique=${static_token_state})"
            ),
            "static_token_set": "défini",
            "static_token_absent": "absent",
            "tool_configuration_error": "Service « ${code} » : ${error}",
        },
    },
}
