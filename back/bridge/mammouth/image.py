"""Image generation/editing uses chat/completions, not an Images endpoint."""

import base64

import httpx

from app.llm import ImageGenerationResult, NativeImageSize, ProviderConnection
from core.util import as_dict, as_list

from .protocol import MammouthProtocol


class MammouthImageGeneration:
    def select_size(self, model: str, width: int, height: int) -> NativeImageSize:
        # Mammouth publishes no portable pixel-size parameter for chat image generation.
        return NativeImageSize(None, None, {})

    def prepare_request(
        self, connection: ProviderConnection, *, model: str, prompt: str,
        sources: list[tuple[bytes, str]], width: int, height: int,
    ) -> httpx.Request:
        if not connection.api_key:
            raise ValueError("A Mammouth API key is required.")
        content: list[dict[str, object]] = [{"type": "text", "text": (
            f"Generate an image. {prompt}\nPreferred dimensions: {width}x{height} pixels."
        )}]
        for data, mime in sources:
            if mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
                raise ValueError("Unsupported reference image type for Mammouth.")
            content.append({"type": "image_url", "image_url": {
                "url": f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
            }})
        return httpx.Request(
            "POST", f"{MammouthProtocol().base_url(connection)}/chat/completions",
            headers={"Authorization": f"Bearer {connection.api_key}"},
            json={"model": model, "stream": False, "messages": [{"role": "user", "content": content}]},
        )

    def read_response(self, response: httpx.Response) -> ImageGenerationResult:
        payload = as_dict(response.json())
        choices = as_list(payload.get("choices"))
        message = as_dict(as_dict(choices[0]).get("message")) if choices else {}
        images = as_list(message.get("images"))
        url = as_dict(as_dict(images[0]).get("image_url")).get("url") if images else None
        if not isinstance(url, str) or not url.startswith("data:"):
            raise ValueError("Mammouth returned no inline image.")
        header, separator, encoded = url.partition(",")
        mime = header.removeprefix("data:").removesuffix(";base64")
        if not separator or not header.endswith(";base64") or mime not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise ValueError("Mammouth returned an unsupported image encoding.")
        if not encoded or len(encoded) > 48_000_000:
            raise ValueError("Mammouth returned an empty or oversized image.")
        return ImageGenerationResult(base64.b64decode(encoded, validate=True), mime, as_dict(payload.get("usage")))
