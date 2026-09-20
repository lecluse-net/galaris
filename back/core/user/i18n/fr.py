"""French user and authentication messages."""

default = {
    "user_api": {
        "logged_out": "Déconnexion réussie",
        "errors": {
            "last_administrator": "Conservez au moins un administrateur actif avant de retirer cet accès.",
            "protected_admin_role": "Le rôle administrateur intégré et ses privilèges ne peuvent pas être supprimés ou renommés.",
            "account_in_use": "Ce compte possède encore des ressources, y compris des agents archivés. Réaffectez-les avant de le supprimer.",
            "incorrect_credentials": "Adresse e-mail ou mot de passe incorrect",
            "account_disabled": "Votre compte a été désactivé",
            "account_locked": "Trop de tentatives ont échoué. Réessayez plus tard",
            "mfa_required": "Saisissez votre code d’authentification",
            "invalid_mfa_code": "Code d’authentification invalide ou déjà utilisé",
            "invalid_or_expired_token": "Jeton invalide ou expiré",
            "malformed_token": "Jeton mal formé : adresse e-mail absente",
            "user_not_found": "Utilisateur introuvable",
            "not_authenticated": "Authentification requise",
            "registration_closed": "L’inscription publique est fermée",
            "token_not_found": "Jeton introuvable",
            "email_registered": "Cette adresse e-mail est déjà inscrite : ${email}",
            "email_in_use": "Cette adresse e-mail est déjà utilisée : ${email}",
            "avatar_not_found": "Avatar introuvable",
            "invalid_avatar_type": "Type d’avatar non pris en charge. Types autorisés : ${types}",
            "invalid_avatar_content": "Le fichier sélectionné n’est pas une image valide prise en charge",
            "avatar_too_large": "L’avatar ne doit pas dépasser 5 Mo",
        },
    },
}
