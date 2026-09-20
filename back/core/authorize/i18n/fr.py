"""French authorization API messages."""

default = {
    "authorize_api": {
        "errors": {
            "privilege_code_exists": "Ce code de privilège existe déjà",
            "privilege_not_found": "Privilège introuvable",
            "role_code_exists": "Ce code de rôle existe déjà",
            "role_not_found": "Rôle introuvable",
            "assignment_exists": "Cette affectation existe déjà",
            "assignment_not_found": "Affectation introuvable",
            "not_authenticated": "Authentification requise",
            "route_not_declared": "L’autorisation de cette route n’est pas configurée",
            "inactive_user": "Utilisateur inactif",
            "missing_privilege": "Privilège manquant : ${privileges}",
            "assertion_denied": "Accès refusé par la règle d’autorisation",
            "role_not_owned": "Ce rôle ne vous est pas attribué",
            "own_assignments_only": "Vous ne pouvez modifier que vos propres affectations",
            "list_exists": "Une liste portant ce nom existe déjà",
            "list_not_found": "Liste introuvable",
        },
    },
}
