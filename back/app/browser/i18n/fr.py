"""Messages français du navigateur."""

default: dict[str, object] = {
    "browser": {
        "permission_question": "Autoriser le navigateur de cet agent à effectuer un accès ${action} vers ${origin} ? Cette décision couvre tous les chemins de cette destination et sera mémorisée pour cet agent.",
        "all_sites_permission_question": "Toujours autoriser le navigateur de cet agent à accéder à tous les sites sans nouvelle demande d’autorisation de site ? Cela couvre tous les domaines, protocoles, ports, chemins, méthodes HTTP configurées et WebSocket. Les filtres réseau, les refus explicites et les permissions distinctes du réseau local restent applicables. Révoquez cet accord dans les permissions mémorisées.",
        "errors": {
            "invalid_url": "L’URL est invalide. Utilisez une URL HTTP(S) sans identifiants intégrés.",
            "invalid_viewport": (
                "Le viewport doit mesurer entre 320 et 3840 pixels CSS de large et "
                "entre 240 et 2160 pixels CSS de haut."
            ),
            "session_not_found": "Cette session de navigation est indisponible ou n’appartient plus à cette tâche.",
            "capacity_reached": "Le navigateur a atteint sa capacité. Fermez une session existante ou réessayez plus tard.",
            "unavailable": "Le service de navigation isolé est indisponible.",
            "failed": "L’opération de navigation a échoué (${code}).",
        },
        "closed": "Session de navigation ${session_id} fermée.",
    }
}
