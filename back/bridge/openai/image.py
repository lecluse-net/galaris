"""Native OpenAI Images API, including multipart image editing."""

import base64
import mimetypes

import httpx

from app.llm import ImageGenerationResult, NativeImageSize, ProviderConnection, nearest_image_size
from core.util import as_dict, as_list


def native_image_size(model: str, width: int, height: int) -> NativeImageSize:
    """Share best-effort OpenAI size selection between direct and routed generation."""
    if model.startswith("gpt-image-2"):
        candidates = (
            (w, h) for w in range(16, 3841, 16) for h in range(16, 3841, 16)
            if max(w, h) <= 3 * min(w, h) and 655_360 <= w * h <= 8_294_400
        )
        w, h = nearest_image_size(width, height, candidates)
    elif model.startswith("gpt-image-1"):
        w, h = nearest_image_size(width, height, [(1024, 1024), (1536, 1024), (1024, 1536)])
    elif model == "dall-e-2":
        w, h = nearest_image_size(width, height, [(256, 256), (512, 512), (1024, 1024)])
    elif model == "dall-e-3":
        w, h = nearest_image_size(width, height, [(1024, 1024), (1792, 1024), (1024, 1792)])
    else:
        return NativeImageSize(None, None, {})
    return NativeImageSize(w, h, {"size": f"{w}x{h}"})


class OpenAIImageGeneration:
    select_size = staticmethod(native_image_size)

    def prepare_request(
        self, connection: ProviderConnection, *, model: str, prompt: str,
        sources: list[tuple[bytes, str]], width: int, height: int,
    ) -> httpx.Request:
        body = {"model": model, "prompt": prompt, **self.select_size(model, width, height).options}
        if model == "dall-e-2" and len(sources) > 1:
            raise ValueError("dall-e-2 accepts only one source image")
        if model == "dall-e-3" and sources:
            raise ValueError("dall-e-3 does not support image editing")
        if not model.startswith("gpt-image-"):
            body["response_format"] = "b64_json"
        headers = {"Authorization": f"Bearer {connection.api_key}"} if connection.api_key else {}
        base = connection.base_url.rstrip("/")
        if sources:
            field = "image" if len(sources) == 1 else "image[]"
            files = [
                (field, (f"source-{index}{mimetypes.guess_extension(mime) or '.png'}", data, mime))
                for index, (data, mime) in enumerate(sources)
            ]
            return httpx.Request("POST", f"{base}/images/edits", headers=headers, data=body, files=files)
        return httpx.Request("POST", f"{base}/images/generations", headers=headers, json=body)

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
