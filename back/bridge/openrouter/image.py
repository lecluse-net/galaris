"""OpenRouter's dedicated Images API with explicit pixel dimensions."""

import base64
import json

import httpx

from app.llm import ImageGenerationResult, ProviderConnection, resolve_image_size
from core.util import as_dict, as_list


class OpenRouterImageGeneration:
    select_size = staticmethod(resolve_image_size)

    def prepare_resolution_fallback(
        self, request: httpx.Request, response: httpx.Response,
    ) -> httpx.Request | None:
        """Let the eligible endpoint choose its tier when routing rejects resolution.

        Account guardrails can exclude endpoints supporting the model's theoretical
        maximum. Only the explicit capability rejection is safe to retry: generation
        has not started, and all provider preferences and reference images stay intact.
        """
        if response.status_code != 400:
            return None
        try:
            error = as_dict(as_dict(response.json()).get("error"))
            body = as_dict(json.loads(request.content))
        except ValueError:
            return None
        metadata = as_dict(error.get("metadata"))
        if (
            metadata.get("failed_routing_step") != "Filter by Image Capabilities"
            or "resolution: not supported." not in str(error.get("message", ""))
            or "resolution" not in body
        ):
            return None
        del body["resolution"]
        headers = dict(request.headers)
        headers.pop("content-length", None)
        return httpx.Request(request.method, request.url, headers=headers, json=body)

    def prepare_request(
        self, connection: ProviderConnection, *, model: str, prompt: str,
        sources: list[tuple[bytes, str]], width: int, height: int,
    ) -> httpx.Request:
        # `size` is normalized by OpenRouter and need not preserve exact pixels.
        # Use the model author's constraints and native ratio/tier when registered.
        size = self.select_size(model, width, height)
        body: dict[str, object] = {"model": model, "prompt": prompt, **size.options}
        if sources:
            body["input_references"] = [
                {"type": "image_url", "image_url": {
                    "url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
                }}
                for data, mime in sources
            ]
        headers = {"Authorization": f"Bearer {connection.api_key}"} if connection.api_key else {}
        return httpx.Request(
            "POST", f"{connection.base_url.rstrip('/')}/images", headers=headers, json=body,
        )

    def read_response(self, response: httpx.Response) -> ImageGenerationResult:
        payload = as_dict(response.json())
        rows = as_list(payload.get("data"))
        first = as_dict(rows[0]) if rows else {}
        encoded = first.get("b64_json")
        if not isinstance(encoded, str) or not encoded:
            raise ValueError("The image provider returned no base64 image")
        return ImageGenerationResult(
            base64.b64decode(encoded, validate=True),
            str(first.get("media_type") or "image/png"),
            as_dict(payload.get("usage")),
        )
