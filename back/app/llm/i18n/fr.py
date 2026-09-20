"""French language data used for LLM routing."""

ACTION_KEYWORDS: tuple[str, ...] = (
    "analyse",
    "appelle",
    "cherche",
    "corrige",
    "crée",
    "cree",
    "déploie",
    "exécute",
    "exporte",
    "importe",
    "installe",
    "lance",
    "mets à jour",
    "met à jour",
    "modifie",
    "publie",
    "récupère",
    "recupere",
    "résume",
    "supprime",
    "trouve",
    "vérifie",
    "verifie",
)

default: dict[str, object] = {
    "personal_speech": {
        "user_unavailable": "Cet utilisateur n’est plus disponible.",
        "profile_unavailable": "Ce profil LLM n’est plus disponible.",
        "voice_unavailable": "Choisissez une voix de synthèse active dans vos préférences personnelles.",
        "transcription_unavailable": "Configurez un modèle de transcription actif dans votre profil LLM.",
        "empty_document": "Ce document ne contient aucun texte à lire.",
        "invalid_offset": "La position de lecture dépasse le texte du document.",
        "invalid_audio": "L’enregistrement est vide ou son format audio n’est pas pris en charge.",
        "audio_too_large": "L’enregistrement dépasse la limite de 20 Mio.",
        "provider_failed": "Le service vocal n’a pas pu traiter la demande. Vérifiez votre configuration vocale.",
    },
    "llm_api": {
        "unknown_provider": "Inconnu",
        "model_installed": "Modèle ${model_name} installé avec succès",
        "model_deleted": "Modèle ${model_name} supprimé avec succès",
        "client_disconnected": "Le client s’est déconnecté pendant le streaming",
        "errors": {
            "inference_not_found": "Inférence introuvable.",
            "inference_attempt_not_found": "Tentative d’inférence introuvable.",
            "inference_runtime_required": "Utilisez la passerelle du runtime pour les appels liés à une exécution.",
            "inference_agent_not_found": "Agent introuvable.",
            "provider_not_found": "Fournisseur ${provider_id} introuvable",
            "provider_inactive": "Le fournisseur ${provider_name} est inactif",
            "subscription_confirmation_required": "La confirmation explicite de l’usage personnel de l’abonnement ChatGPT est obligatoire avant d’utiliser ou de connecter ce fournisseur",
            "subscription_owner_required": "Sélectionnez l’utilisateur Galaris titulaire de l’abonnement ChatGPT avant d’activer ou de connecter ce fournisseur",
            "subscription_owner_invalid": "Le titulaire de l’abonnement ChatGPT doit être un utilisateur Galaris actif",
            "subscription_owner_unsupported": "Un titulaire d’abonnement ne peut être défini que pour le fournisseur ChatGPT",
            "subscription_user_mismatch": "Cet abonnement ChatGPT est réservé à son titulaire Galaris. Utilisez un fournisseur OpenAI API pour les autres utilisateurs",
            "subscription_messenger_unlinked": "Cette identité Messenger n’est pas associée au titulaire de l’abonnement ChatGPT dans « Mon profil »",
            "subscription_requester_unknown": "Impossible d’attribuer cet appel au titulaire de l’abonnement ChatGPT. Utilisez un fournisseur OpenAI API ou une exécution liée à un utilisateur autorisé",
            "provider_install_unsupported": "Le fournisseur ${provider_name} ne prend pas en charge l’installation de modèles",
            "provider_delete_unsupported": "Le fournisseur ${provider_name} ne prend pas en charge la suppression de modèles",
            "model_id_required": "Le champ model_id est obligatoire",
            "metadata_fetch_failed": "Impossible de récupérer les métadonnées du modèle : ${error}",
            "llm_not_found": "Modèle LLM ${llm_id} introuvable",
            "llm_code_not_found": "Modèle LLM « ${llm_id} » introuvable",
            "models_fetch_failed": "Impossible de récupérer les modèles du fournisseur : ${error}",
            "transcription_models_fetch_failed": "Impossible de récupérer les modèles de transcription : ${error}",
            "install_failed": "Impossible d’installer le modèle : ${error}",
            "delete_failed": "Impossible de supprimer le modèle : ${error}",
            "call_not_found": "Appel LLM introuvable",
            "inference_call_protected": "Cet appel appartient à une inférence enregistrée. Son historique et ses coûts doivent être conservés.",
            "invalid_llm_token": "Jeton LLM absent ou invalide",
            "code_in_use": "Le code LLM « ${code} » est déjà utilisé",
            "invalid_profile_model_id": "Identifiant LLM invalide dans le champ de profil « ${model_field} » : « ${value} ». L’identifiant doit être un entier.",
            "code_required": "Le code LLM est obligatoire",
            "model_required": "Un modèle LLM est obligatoire",
            "provider_for_llm_not_found": "Le fournisseur du modèle LLM « ${llm_code} » est introuvable",
            "invalid_proxy_model": (
                "Le modèle doit être un identifiant Galaris au format « llm-<id> »"
            ),
            "task_not_found": "Tâche ${task_id} introuvable",
            "managed_runtime_task_required": (
                "Un appel LLM de runtime géré doit être rattaché à une tâche Galaris"
            ),
            "task_wrong_runtime_agent": (
                "La tâche ${task_id} n’est pas attribuée à l’agent runtime ${agent_id}"
            ),
            "provider_connection_error": (
                "Erreur de connexion au fournisseur : ${error}"
            ),
            "profile_not_found": "Profil ${profile_id} introuvable",
            "profile_label_required": "Le libellé du profil est obligatoire",
            "profile_label_too_long": "Le libellé du profil ne peut pas dépasser 100 caractères",
            "profile_label_in_use": "Un profil nommé « ${label} » existe déjà",
            "last_profile_delete_forbidden": (
                "Impossible de supprimer le dernier profil : au moins un profil doit toujours exister"
            ),
            "profile_param_invalid": (
                "Le champ « ${parameter} » n’est pas un champ de modèle d’un profil LLM"
            ),
            "profile_value_invalid": (
                "Valeur de modèle invalide pour « ${parameter} » : ${value}"
            ),
        },
        "connection": {
            "success": "Connexion réussie à ${provider_name}",
            "failed": "Échec de la connexion",
            "http_error": "Erreur HTTP ${status}",
            "invalid_key": "La clé API est invalide ou expirée",
            "access_denied": "Accès refusé ; vérifiez les permissions du fournisseur",
            "endpoint_not_found": "Endpoint introuvable ; vérifiez l’URL",
            "server_error": "Erreur du serveur du fournisseur",
            "cannot_connect": "Impossible de joindre le serveur ; vérifiez l’URL",
            "timeout": "Le délai de la requête est dépassé ; le serveur n’a pas répondu",
        },
    },
    "anthropic_api": {
        "errors": {
            "invalid_request": "Requête Anthropic invalide",
            "messages_required": (
                "Le tableau « messages » est obligatoire pour l’API Anthropic"
            ),
            "stream_interrupted": (
                "Le flux du fournisseur s’est interrompu pendant la génération"
            ),
        },
    },
}
