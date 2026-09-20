default = {
    "webhook": {
        "task": {
            "objective": "Traiter le webhook de ${source} pour ${agent_name}",
            "label": "Webhook ${source}",
            "created": "Tâche créée avec succès pour le webhook ${source}",
        },
        "errors": {
            "invalid_payload": "Le contenu du webhook doit être du texte UTF-8 ou un objet JSON.",
            "body_too_large": "Le contenu du webhook dépasse la limite de 1 Mio.",
            "tool_name_required": "Le champ tool_name est obligatoire",
            "tool_not_found": "Outil « ${tool_name} » introuvable",
            "listener_missing": "L’outil « ${tool_name} » ne possède aucune configuration d’écoute avec connection_key",
            "required_field_missing": "Le champ obligatoire « ${field} » manque dans les données du webhook",
            "connection_not_found": "Aucune connexion active trouvée pour l’outil « ${tool_name} » avec ${key}=${value}",
            "connection_without_agent": "Une connexion a été trouvée, mais aucun agent ne lui est associé",
        },
    }
}
