"""English linguistic data for LLM routing."""

ACTION_KEYWORDS: tuple[str, ...] = (
    "analyze",
    "call",
    "check",
    "create",
    "delete",
    "deploy",
    "execute",
    "export",
    "fetch",
    "find",
    "fix",
    "import",
    "install",
    "publish",
    "run",
    "search",
    "summarize",
    "update",
)

default: dict[str, object] = {
    "personal_speech": {
        "user_unavailable": "This user is no longer available.",
        "profile_unavailable": "This LLM profile is no longer available.",
        "voice_unavailable": "Choose an active speech voice in your personal preferences.",
        "transcription_unavailable": "Configure an active transcription model in your LLM profile.",
        "empty_document": "This document contains no text to read.",
        "invalid_offset": "The reading offset is beyond the document text.",
        "invalid_audio": "The recording is empty or its audio format is unsupported.",
        "audio_too_large": "The recording exceeds the 20 MiB limit.",
        "provider_failed": "The voice service could not process the request. Check your voice configuration.",
    },
    "llm_api": {
        "unknown_provider": "Unknown",
        "model_installed": "Model ${model_name} installed successfully",
        "model_deleted": "Model ${model_name} deleted successfully",
        "client_disconnected": "Client disconnected during streaming",
        "errors": {
            "provider_quota_unsupported": "This provider does not expose subscription usage limits.",
            "inference_not_found": "Inference not found.",
            "inference_attempt_not_found": "Inference attempt not found.",
            "inference_runtime_required": "Use the correlated runtime gateway for runtime work.",
            "inference_agent_not_found": "Agent not found.",
            "provider_not_found": "Provider ${provider_id} not found",
            "provider_inactive": "Provider ${provider_name} is inactive",
            "subscription_confirmation_required": "Explicit confirmation of personal ChatGPT subscription use is required before using or connecting this provider",
            "subscription_owner_required": "Select the Galaris user who owns the ChatGPT subscription before enabling or connecting this provider",
            "subscription_owner_invalid": "The ChatGPT subscription owner must be an active Galaris user",
            "subscription_owner_unsupported": "A subscription owner can only be set for the ChatGPT provider",
            "subscription_user_mismatch": "This ChatGPT subscription is reserved for its Galaris owner. Use an OpenAI API provider for other users",
            "subscription_messenger_unlinked": "This Messenger identity is not linked to the ChatGPT subscription owner in My profile",
            "subscription_requester_unknown": "This call cannot be attributed to the ChatGPT subscription owner. Use an OpenAI API provider or work linked to an authorized user",
            "provider_install_unsupported": "Provider ${provider_name} does not support model installation",
            "provider_delete_unsupported": "Provider ${provider_name} does not support model deletion",
            "model_id_required": "model_id is required",
            "metadata_fetch_failed": "Could not fetch model metadata: ${error}",
            "llm_not_found": "LLM ${llm_id} not found",
            "llm_code_not_found": "LLM '${llm_id}' not found",
            "models_fetch_failed": "Could not fetch provider models: ${error}",
            "transcription_models_fetch_failed": "Could not fetch transcription models: ${error}",
            "install_failed": "Could not install the model: ${error}",
            "delete_failed": "Could not delete the model: ${error}",
            "call_not_found": "LLM call not found",
            "inference_call_protected": "This call belongs to a saved inference. Its history and costs must be preserved.",
            "invalid_llm_token": "Invalid or missing LLM token",
            "code_in_use": "LLM code '${code}' is already in use",
            "invalid_profile_model_id": "Invalid LLM ID in profile field '${model_field}': '${value}'. The ID must be an integer.",
            "code_required": "The LLM code is required",
            "model_required": "An LLM model is required",
            "provider_for_llm_not_found": "Provider for LLM '${llm_code}' not found",
            "invalid_proxy_model": (
                "The model must be a Galaris identifier in the form 'llm-<id>'"
            ),
            "task_not_found": "Task ${task_id} not found",
            "managed_runtime_task_required": (
                "A managed runtime LLM call must be attached to a Galaris Task"
            ),
            "task_wrong_runtime_agent": (
                "Task ${task_id} is not assigned to runtime agent ${agent_id}"
            ),
            "provider_connection_error": "Provider connection error: ${error}",
            "profile_not_found": "Profile ${profile_id} not found",
            "profile_label_required": "The profile label is required",
            "profile_label_too_long": "The profile label cannot exceed 100 characters",
            "profile_label_in_use": "A profile named '${label}' already exists",
            "last_profile_delete_forbidden": (
                "Cannot delete the last profile: at least one profile must always exist"
            ),
            "profile_param_invalid": (
                "Field '${parameter}' is not a model field of an LLM profile"
            ),
            "profile_value_invalid": (
                "Invalid model value for '${parameter}': ${value}"
            ),
        },
        "connection": {
            "success": "Connected successfully to ${provider_name}",
            "failed": "Connection failed",
            "http_error": "HTTP error ${status}",
            "invalid_key": "The API key is invalid or expired",
            "access_denied": "Access denied; check provider permissions",
            "endpoint_not_found": "Endpoint not found; check the URL",
            "server_error": "Provider server error",
            "cannot_connect": "Could not connect to the server; check the URL",
            "timeout": "The request timed out; the server did not respond",
        },
    },
    "anthropic_api": {
        "errors": {
            "invalid_request": "Invalid Anthropic request",
            "messages_required": (
                "The \"messages\" array is required by the Anthropic API"
            ),
            "stream_interrupted": (
                "The provider stream was interrupted during generation"
            ),
        },
    },
}
