"""French image-service messages."""

default: dict[str, object] = {
    "image": {
        "generated": "Image générée (${width} × ${height} pixels, ${size} octets) : ${location}",
        "generation_failed": (
            "Échec de la génération d’image : ${error} Aucune image générée n’a été livrée. "
            "Expliquez cette limitation. Sans accord explicite de l’utilisateur, ne remplacez "
            "pas l’image par un dessin SVG ou du code, ne la redimensionnez ni ne la recadrez, "
            "et ne changez pas son format. L’ajustement de taille native est automatique "
            "et ne constitue pas une erreur. N’annoncez pas un succès si la génération a échoué."
        ),
        "generation_unavailable": "L’image n’a pas pu être générée ou enregistrée.",
        "description_failed": "Échec de la description d’image : ${error}",
        "default_description": (
            "Décrivez cette image en détail, notamment son contenu, le texte visible et les "
            "éléments remarquables."
        ),
        "prompt_required": "La génération d’image nécessite un prompt non vide.",
        "generation_model_missing": "Aucun modèle de génération d’image n’est configuré dans le profil courant.",
        "vision_model_missing": "Aucun modèle d’analyse d’image compatible n’est configuré dans le profil courant.",
        "unsupported_analysis_mime": "image_read accepte uniquement une image ; type MIME reçu : ${mime}.",
        "model_returned_no_image": "Le modèle n’a renvoyé aucune image.",
        "model_returned_no_description": "Le modèle de vision n’a renvoyé aucune description.",
        "proxy_streaming_response": "Le proxy LLM a renvoyé une réponse en streaming inattendue pour ${kind}.",
        "proxy_invalid_response": "Réponse du proxy LLM invalide pour le modèle « ${model} ».",
        "proxy_non_object": "La réponse du proxy LLM pour le modèle « ${model} » n’est pas un objet.",
        "provider_rejected": "Le fournisseur ${kind} a rejeté le modèle « ${model} » (${status}) : ${detail}",
    },
}
