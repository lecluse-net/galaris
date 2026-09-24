"""Canonical OpenAI-compatible model-catalog handler."""
import httpx
from typing import List, Optional, Dict, Any
from .base import BaseLLMHandler, LLMModelInfo
from core.util import as_dict, as_list

TOKENS_PER_MILLION = 1_000_000.0

# Five application modalities in model-column order.
MODALITY_NAMES = ("text", "image", "file", "video", "audio")


def _modalities_to_flags(architecture: Any) -> Dict[str, bool]:
    """Convert a protocol extension block into directional modality flags."""
    arch = as_dict(architecture)
    inputs = {str(m).lower() for m in as_list(arch.get("input_modalities"))}
    outputs = {str(m).lower() for m in as_list(arch.get("output_modalities"))}

    flags: Dict[str, bool] = {}
    for name in MODALITY_NAMES:
        flags[f"input_{name}"] = name in inputs
        flags[f"output_{name}"] = name in outputs
    return flags


class OpenAICompatibleHandler(BaseLLMHandler):
    """
    Handler for providers exposing an OpenAI-compatible ``/models`` endpoint.
    """

    async def list_models(
        self,
        base_url: str,
        api_key: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> List[LLMModelInfo]:
        """
        Fetch models through the OpenAI-compatible ``/models`` endpoint.

        Args:
            base_url: API base URL.
            api_key: Optional authentication key.
            extra_headers: Provider-specific headers.

        Returns:
            Available models.
        """
        url = f"{self._clean_base_url(base_url)}/models"
        headers: Dict[str, str] = {
            "Content-Type": "application/json",
        }

        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        headers.update(extra_headers or {})

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=30.0)
            response.raise_for_status()
            data: Any = response.json()

        return self.parse_models(data)

    def parse_models(self, data: Any) -> List[LLMModelInfo]:
        """Normalize a standard or provider-extended model-list payload."""
        # Standard OpenAI format: { "data": [ { "id": "...", "object": "model", ... } ] }
        raw_models: List[Any] = (
            as_list(data)
            if isinstance(data, list)
            else as_list(as_dict(data).get("data"))
        )
        models_data: List[Dict[str, Any]] = [
            as_dict(item) for item in raw_models if isinstance(item, dict)
        ]

        models: List[LLMModelInfo] = []
        for model_data in models_data:
            model_info = self._parse_model(model_data)
            if model_info:
                models.append(model_info)

        return models

    def _parse_model(self, model_data: Dict[str, Any]) -> Optional[LLMModelInfo]:
        """
        Parse OpenAI-compatible model data.

        Args:
            model_data: Raw model data.

        Returns:
            Parsed model information, or ``None`` when invalid.
        """
        model_id = model_data.get("id", "")
        if not model_id:
            return None

        # Extract optional protocol extensions exposed by some compatible servers.
        metadata: Dict[str, Any] = model_data
        pricing = self._parse_pricing(metadata.get("pricing"))

        # Parse I/O modalities when an architecture block is available.
        arch = as_dict(metadata.get("architecture"))
        modalities = (
            _modalities_to_flags(arch)
            if arch.get("input_modalities") or arch.get("output_modalities")
            else None
        )
        inputs = {str(value).lower() for value in as_list(arch.get("input_modalities"))}
        outputs = {str(value).lower() for value in as_list(arch.get("output_modalities"))}
        service_capabilities: List[str] = []
        if "decisions" in outputs:
            service_capabilities.append("decision")
        if "embeddings" in outputs:
            service_capabilities.append("embedding")
        if "image" in outputs:
            service_capabilities.append("image_generation")
        if "transcription" in outputs:
            service_capabilities.append("transcription")
        if outputs.intersection({"speech", "audio"}):
            service_capabilities.append("speech")
        if "image" in inputs and "text" in outputs:
            service_capabilities.append("vision")
        if "text" in outputs:
            service_capabilities.append("chat")

        return LLMModelInfo(
            id=model_id,
            name=metadata.get("name") or model_id,
            description=metadata.get("description"),
            context_length=metadata.get("context_length"),
            pricing=pricing,
            modalities=modalities,
            metadata_source="provider",
            service_capabilities=service_capabilities,
        )

    def _parse_pricing(self, pricing: Any) -> Optional[Dict[str, Any]]:
        if isinstance(pricing, list):
            lines = [as_dict(item) for item in as_list(pricing) if isinstance(item, dict)]
            return {"lines": lines} if lines else None
        if not isinstance(pricing, dict):
            return None

        pricing_dict = as_dict(pricing)
        parsed: Dict[str, Any] = {}
        if "prompt" in pricing_dict:
            parsed["input"] = float(pricing_dict.get("prompt") or 0.0) * TOKENS_PER_MILLION
        if "completion" in pricing_dict:
            parsed["output"] = float(pricing_dict.get("completion") or 0.0) * TOKENS_PER_MILLION

        cached_input = next(
            (
                pricing_dict[key]
                for key in ("input_cache_read", "prompt_cache_read", "cache_read")
                if pricing_dict.get(key) is not None
            ),
            None,
        )
        if cached_input is not None:
            parsed["cached_input"] = float(cached_input) * TOKENS_PER_MILLION

        cache_write = next(
            (
                pricing_dict[key]
                for key in ("input_cache_write", "prompt_cache_write", "cache_write")
                if pricing_dict.get(key) is not None
            ),
            None,
        )
        if cache_write is not None:
            parsed["cache_write"] = float(cache_write) * TOKENS_PER_MILLION

        return parsed or pricing_dict
