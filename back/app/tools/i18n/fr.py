"""French messages for tool discovery and search."""

default: dict[str, object] = {
    "tools": {
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
        "list_failed": "Impossible de lister les outils MCP.",
        "list_heading": "Vos outils MCP, classés par outil applicatif :",
        "inactive_connection": "connexion inactive",
        "unavailable": "indisponible",
        "introspection_error": "Erreur d’introspection : ${error}",
        "introspection_failed": "Le serveur MCP externe n’a pas pu être inspecté.",
        "none_available": "Aucun outil n’est actuellement disponible.",
        "present_in_run": "présent dans cette exécution",
        "absent_from_run": "absent de cette exécution ; nécessite un nouveau contexte d’exécution compatible",
        "availability_hint": (
            "Ce catalogue contient uniquement les fonctions qui vous sont actuellement autorisées. "
            "Une autorisation n’ajoute pas d’outils à une exécution existante. Utilisez uniquement "
            "les outils exposés par votre runtime ; sans indication de présence, leur disponibilité "
            "n’est pas vérifiée. load_capability charge seulement les capacités déjà enregistrées "
            "par le runtime. Le navigateur, la recherche web et l’accès HTTPS aux fichiers sont "
            "des capacités distinctes."
        ),
        "call_failure": (
            "Échec de l’outil « ${name} ».\n"
            "Cause : ${reason}\n"
            "Type technique : ${error_type}.\n"
            "Action suivante : ${hint}\n"
            "Référence d’erreur : ${reference}"
        ),
        "call_failure_reasons": {
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
            "system_read_only": "Ce service système obligatoire est en lecture seule et toujours actif.",
            "tool_not_found": "Outil ${tool_id} introuvable",
            "tool_exists_code": "L’outil « ${code} » existe déjà",
            "invalid_yaml": "YAML invalide",
            "invalid_tool_definition": "La définition de l’outil est invalide",
            "password_default_forbidden": (
                "Les paramètres de connexion de type mot de passe ne peuvent pas définir "
                "de valeur partagée par défaut : ${fields}"
            ),
            "secret_placeholder_without_value": (
                "La valeur non lisible ${field} n’a aucune valeur existante à conserver"
            ),
            "yaml_mapping_required": "Le YAML doit contenir un objet associatif",
            "code_missing": "Champ « code » manquant",
            "tool_exists": "Un outil nommé « ${code} » existe déjà",
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
            "tool_configuration_error": "Outil « ${code} » : ${error}",
        },
    },
}
