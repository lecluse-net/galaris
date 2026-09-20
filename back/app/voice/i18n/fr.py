"""French voice-call messages exposed to agents."""

default: dict[str, object] = {
    "voice": {
        "initial_greeting": "allo?",
        "disabled": "Le mode audio est désactivé sur ce serveur (VOICE_ENABLED=false).",
        "room_required": "Impossible de lancer l’appel : room_id est requis.",
        "agent_missing": "Impossible de lancer l’appel : agent introuvable.",
        "already_active": (
            "Un appel vocal est déjà actif pour ce salon. call_id=${call_id}, room_id=${room_id}."
        ),
        "started": (
            "Appel vocal lancé en arrière-plan. call_id=${call_id}, room_id=${room_id}."
        ),
        "start_failed": "Échec du lancement de l’appel vocal : ${error}",
        "stopped": "Appel vocal arrêté.",
        "call_missing": "Aucun appel actif avec ce call_id.",
        "none_to_stop": "Aucun appel vocal actif à arrêter.",
        "stopped_count": "${count} appel(s) vocal(aux) arrêté(s).",
        "stop_failed": "Échec de l’arrêt de l’appel vocal : ${error}",
        "none_active": "Aucun appel vocal actif.",
        "call_line": (
            "- call_id=${call_id} room_id=${room_id} transport=${transport_kind}"
        ),
        "provider_missing": "Aucun fournisseur d’appel vocal n’est enregistré pour ${provider}.",
        "no_conversation_start": "Aucune conversation active ; impossible de lancer un appel vocal.",
        "no_conversation_stop": "Aucune conversation active ; impossible d’arrêter un appel vocal.",
        "no_conversation": "Aucune conversation active.",
        "conversation_not_found": "Conversation vocale introuvable.",
        "connection_not_found": "Connexion ${connection_id} introuvable",
        "connection_wrong_agent": "La connexion ${connection_id} n’appartient pas à cet agent",
        "connection_inactive": "La connexion ${connection_id} est inactive",
        "connection_not_talk": "La connexion ${connection_id} n’est pas une connexion Nextcloud Talk",
        "room_connection_missing": "Aucune connexion Nextcloud Talk active de l’agent ${agent_id} ne voit le salon ${room_id}",
        "talk_connection_missing": "Aucune connexion Nextcloud Talk active n’existe pour cet agent",
        "manager_room_required": "room_id est requis",
        "manager_room_too_long": "room_id ne doit pas dépasser 512 caractères",
        "pulse_playback_unavailable": "pacat n’a pas exposé son entrée standard.",
        "pulse_capture_unavailable": "parec n’a pas exposé sa sortie standard.",
        "pulse_capture_stopped": "parec s’est arrêté (${status}) : ${error}",
    },
}
