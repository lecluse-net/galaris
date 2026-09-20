"""French connection API messages."""

default = {
    "connection_api": {
        "errors": {
            "not_found": "Connexion introuvable",
            "not_found_by_id": "Connexion ${connection_id} introuvable",
            "duplicate": "Une connexion existe déjà pour l’agent ${agent_id} et l’outil ${tool_id}",
            "parameter_for_connection_not_found": "Le paramètre « ${parameter} » est introuvable pour la connexion ${connection_id}",
            "parameter_not_found": "Paramètre « ${parameter} » introuvable",
            "body_id_mismatch": "L’identifiant de connexion ${body_id} du corps ne correspond pas à celui de l’URL (${url_id})",
            "tool_not_found": "Outil ${tool_id} introuvable",
            "tool_not_found_generic": "Outil introuvable",
            "no_mcp": "L’outil ${tool_id} ne possède aucune configuration MCP",
            "server_creation_failed": "Impossible de créer le serveur MCP",
            "connection_error": "Le service externe n’a pas pu être joint",
            "inactive": "La connexion est inactive",
            "no_functions": "Ce connecteur n’expose aucune fonction",
        },
        "tools_available": "${count} outil(s) disponible(s)",
    },
}
