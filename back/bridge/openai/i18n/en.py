"""English OpenAI bridge messages."""

default: dict[str, object] = {
    "llm_api": {
        "codex": {
            "provider_not_found": "LLM provider not found.",
            "not_codex_provider": "This provider does not use OpenAI Codex authentication.",
            "credentials_invalid": "The saved Codex credentials cannot be read. Reconnect this provider.",
            "access_token_missing": "OpenAI did not return a Codex access token.",
            "auth_unreachable": "Could not contact OpenAI authentication: ${error}",
            "login_rate_limited": "OpenAI is temporarily limiting login requests. Try again shortly.",
            "device_request_rejected": "OpenAI rejected the login-code request.",
            "device_response_incomplete": "The OpenAI response does not contain the expected login information.",
            "poll_unreachable": "Could not check the OpenAI login: ${error}",
            "poll_rate_limited": "OpenAI is temporarily limiting login checks.",
            "login_expired": "The login code expired or was rejected.",
            "authorization_incomplete": "The OpenAI authorization response is incomplete.",
            "exchange_unreachable": "Could not complete the OpenAI login: ${error}",
            "exchange_rate_limited": "OpenAI is temporarily limiting Codex logins. Try again shortly.",
            "exchange_rejected": "OpenAI rejected the login-code exchange.",
            "refresh_token_missing": "The Codex session expired. Reconnect this provider with ChatGPT.",
            "refresh_unreachable": "Could not refresh the Codex session: ${error}",
            "codex_rate_limited": "The Codex limit has been reached temporarily. The credentials remain valid.",
            "refresh_failed": "The Codex session refresh failed.",
            "not_connected": "This Codex provider is not connected. Connect it with ChatGPT.",
            "models_unreachable": "Could not retrieve Codex models: ${error}",
            "models_rejected": "OpenAI rejected the Codex model list request.",
            "stream_incomplete": "The Codex stream ended before its final response.",
            "transcription_unsupported": "The OpenAI Codex provider does not support audio transcription.",
        }
    }
}
