"""French file-sharing messages exposed to agents."""

default: dict[str, object] = {
    "file_share": {
        "operations": {
            "sign_in": "connexion",
            "upload": "téléversement",
            "download": "téléchargement",
            "webdav_upload": "téléversement WebDAV",
            "webdav_download": "téléchargement WebDAV",
            "share_creation": "création du partage",
        },
        "upload_failed": "Échec du téléversement via ${tool_code} : ${error}",
        "affine_upload_path": (
            "Échec du téléversement AFFiNE : précisez le workspace au début de destination "
            "(par exemple entreprise/mon_fichier)."
        ),
        "upload_ok": "Fichier téléversé via ${tool_code} (${service}, ${size} octets) : ${location}",
        "download_failed": "Échec du téléchargement via ${tool_code} : ${error}",
        "affine_download_path": (
            "Échec du téléchargement AFFiNE : précisez le workspace au début de remote "
            "(par exemple entreprise/<clé>)."
        ),
        "download_ok": "Fichier téléchargé via ${tool_code} (${service}, ${size} octets) : ${location}",
        "destination_required": "Échec du transfert : dest_path est requis.",
        "transfer_ok": (
            "Fichier transféré ${source} -> ${destination} (${size} octets) : ${location}"
        ),
        "transfer_failed": "Échec du transfert ${source} -> ${destination} : ${error}",
        "targets_failed": "Échec de la liste des services de fichiers : ${error}",
        "no_targets": (
            "Aucun service de fichiers n’est connecté à votre compte. Demandez à un "
            "administrateur d’activer une connexion de partage de fichiers."
        ),
        "targets_heading": "Services de fichiers connectés (valeur pour tool_code) :",
        "messenger_label": "Votre messagerie",
        "messenger_description": "Transport interne : fichiers échangés via votre messagerie.",
        "errors": {
            "required_parameter": (
                "Service « ${service} » : le paramètre requis « ${parameter} » n’a pas été "
                "fourni (paramètre de connexion associé : « ${connection_parameter} »)."
            ),
            "connection_not_found": (
                "Aucune connexion « file_share/${tool_code} » active n’est configurée pour "
                "l’agent ${agent_id}."
            ),
            "service_connection_not_found": (
                "Aucune connexion « file_share/${service} » active n’est configurée pour "
                "l’agent ${agent_id}."
            ),
            "messenger_not_configured": (
                "Aucun service de messagerie n’est configuré pour l’agent ${agent_id}."
            ),
            "nextcloud_only": "Le partage est pris en charge uniquement par Nextcloud.",
            "unknown_bridge": (
                "Bridge de partage de fichiers inconnu : « ${service} ». Disponibles : "
                "${available}."
            ),
            "messaging_target_required": (
                "La cible de messagerie est absente ; indiquez un room_id ou u:<user_id> "
                "pour un message direct."
            ),
            "room_required": (
                "Un room_id est requis pour rechercher une pièce jointe de messagerie."
            ),
            "attachment_not_found": (
                "La pièce jointe « ${attachment} » est introuvable dans les messages récents "
                "du salon ${room_id}."
            ),
            "operation_failed": (
                "Échec de l’opération ${operation} sur ${service} (statut=${status}) : ${detail}"
            ),
            "folder_creation_failed": (
                "Échec de la création du dossier Nextcloud « ${path} » (statut=${status}) : "
                "${detail}"
            ),
            "affine_workspace_required": (
                "Le workspace AFFiNE est absent ; placez-le au début du chemin "
                "(par exemple « entreprise/mon_fichier »)."
            ),
            "affine_session_cookie_missing": (
                "La connexion AFFiNE n’a renvoyé aucun cookie de session. Vérifiez l’adresse "
                "e-mail, le mot de passe et l’endpoint de connexion."
            ),
            "affine_graphql_failed": (
                "Échec du téléversement GraphQL AFFiNE : ${error}"
            ),
            "affine_blob_key_missing": (
                "La réponse de téléversement AFFiNE ne contient aucune clé de blob."
            ),
            "grav_target_required": (
                "Le téléversement Grav ne possède aucune page cible. Utilisez "
                "destination='page/fichier.ext' ou configurez le paramètre facultatif "
                "default_page."
            ),
        },
    },
}
