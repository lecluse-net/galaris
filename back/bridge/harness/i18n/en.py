"""English harness manager messages."""

default = {
    "harness": {
        "errors": {
            "secret_missing": "Configure the shared secret in Preferences > Harnesses.",
            "secret_invalid": "HARNESS_MANAGER_SECRET is invalid: ${error}",
            "unreachable": "The harness manager is unreachable.",
            "http_error": "The harness manager returned ${status} for ${method} ${path}",
            "decrypt_failed": "Unable to decrypt '${filepath}' for harness instance '${instance_id}'.",
        }
    }
}
