"""Secret-free identity of selected decision and fallback resources."""

import hashlib
import json

from .provider_models import LLM


def model_binding(llm: LLM) -> str:
    value = {
        "model": llm.llm_name, "provider": llm.llm_provider_id,
        "endpoint": llm.provider.base_url, "catalog_code": llm.provider.catalog_code,
        "configuration": llm.provider.configuration, "capabilities": llm.service_capabilities,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()
