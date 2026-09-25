"""French OpenAI bridge messages."""

default: dict[str, object] = {
    "llm_api": {
        "codex": {
            "quota_unavailable": "Les limites d’usage ChatGPT sont temporairement indisponibles.",
            "provider_not_found": "Fournisseur LLM introuvable.",
            "not_codex_provider": "Ce fournisseur n’utilise pas l’authentification OpenAI Codex.",
            "credentials_invalid": "Les identifiants Codex enregistrés sont illisibles. Reconnectez ce fournisseur.",
            "access_token_missing": "OpenAI n’a pas renvoyé de jeton d’accès Codex.",
            "auth_unreachable": "Impossible de contacter l’authentification OpenAI : ${error}",
            "login_rate_limited": "OpenAI limite temporairement les demandes de connexion. Réessayez dans quelques instants.",
            "device_request_rejected": "OpenAI a refusé la demande de code de connexion.",
            "device_response_incomplete": "La réponse OpenAI ne contient pas les informations de connexion attendues.",
            "poll_unreachable": "Impossible de vérifier la connexion OpenAI : ${error}",
            "poll_rate_limited": "OpenAI limite temporairement les vérifications de connexion.",
            "login_expired": "Le code de connexion a expiré ou a été refusé.",
            "authorization_incomplete": "La réponse d’autorisation OpenAI est incomplète.",
            "exchange_unreachable": "Impossible de finaliser la connexion OpenAI : ${error}",
            "exchange_rate_limited": "OpenAI limite temporairement les connexions Codex. Réessayez dans quelques instants.",
            "exchange_rejected": "OpenAI a refusé l’échange du code de connexion.",
            "refresh_token_missing": "La session Codex a expiré. Reconnectez ce fournisseur avec ChatGPT.",
            "refresh_unreachable": "Impossible de rafraîchir la session Codex : ${error}",
            "codex_rate_limited": "La limite Codex est temporairement atteinte. Les identifiants restent valides.",
            "refresh_failed": "Le rafraîchissement de la session Codex a échoué.",
            "not_connected": "Ce fournisseur Codex n’est pas connecté. Connectez-le avec ChatGPT.",
            "models_unreachable": "Impossible de récupérer les modèles Codex : ${error}",
            "models_rejected": "OpenAI a refusé la liste des modèles Codex.",
            "stream_incomplete": "Le flux Codex s’est interrompu avant sa réponse finale.",
            "transcription_unsupported": "Le fournisseur OpenAI Codex ne propose pas de transcription audio.",
        }
    }
}
