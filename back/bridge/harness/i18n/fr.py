"""French harness manager messages."""

default = {
    "harness": {
        "errors": {
            "secret_missing": "Configurez le secret partagé dans Préférences > Harnais.",
            "secret_invalid": "HARNESS_MANAGER_SECRET est invalide : ${error}",
            "unreachable": "Le harness manager est injoignable.",
            "http_error": "Le harness manager a renvoyé ${status} pour ${method} ${path}",
            "decrypt_failed": "Impossible de déchiffrer « ${filepath} » pour l’instance « ${instance_id} ».",
        }
    }
}
