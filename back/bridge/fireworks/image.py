"""Fireworks synchronous diffusion models with explicit width and height."""

from urllib.parse import quote

import httpx

from app.llm import ImageGenerationResult, NativeImageSize, ProviderConnection, nearest_image_size

_PIXEL_MODELS = {
    "accounts/fireworks/models/playground-v2-5-1024px-aesthetic",
    "accounts/fireworks/models/japanese-stable-diffusion-xl",
    "accounts/fireworks/models/playground-v2-1024px-aesthetic",
    "accounts/fireworks/models/stable-diffusion-xl-1024-v1-0",
    "accounts/fireworks/models/SSD-1B",
}

# Native SDXL output buckets; do not invent arbitrary dimensions at model limits.
# https://platform.stability.ai/docs/api-reference (SDXL 1.0)
_NATIVE_SIZES = (
    (1024, 1024), (1152, 896), (896, 1152), (1216, 832), (832, 1216),
    (1344, 768), (768, 1344), (1536, 640), (640, 1536),
)


class FireworksImageGeneration:
    def select_size(self, model: str, width: int, height: int) -> NativeImageSize:
        if model not in _PIXEL_MODELS:
            raise ValueError(f"Native pixel dimensions are not supported for Fireworks model {model}")
        w, h = nearest_image_size(width, height, _NATIVE_SIZES)
        return NativeImageSize(w, h, {})

    def prepare_request(
        self, connection: ProviderConnection, *, model: str, prompt: str,
        sources: list[tuple[bytes, str]], width: int, height: int,
    ) -> httpx.Request:
        if model not in _PIXEL_MODELS:
            raise ValueError(f"Native pixel dimensions are not supported for Fireworks model {model}")
        if sources:
            raise ValueError("Fireworks native pixel generation does not support reference images")
        size = self.select_size(model, width, height)
        headers = {"Accept": "image/png"}
        if connection.api_key:
            headers["Authorization"] = f"Bearer {connection.api_key}"
        return httpx.Request(
            "POST", f"{connection.base_url.rstrip('/')}/image_generation/{quote(model, safe='/')}",
            headers=headers,
            json={"prompt": prompt, "width": size.width, "height": size.height, "samples": 1},
        )

    def read_response(self, response: httpx.Response) -> ImageGenerationResult:
        mime = response.headers.get("content-type", "").partition(";")[0]
        if not mime.startswith("image/"):
            raise ValueError("Fireworks returned no image")
        return ImageGenerationResult(response.content, mime)
