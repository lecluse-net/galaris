"""Gemini native image dimensions mapped to exact documented ratio/size combinations."""

import base64
from urllib.parse import quote

import httpx

from app.llm import ImageDimensionsError, ImageGenerationResult, NativeImageSize, ProviderConnection, nearest_image_size
from core.util import as_dict, as_list

# https://ai.google.dev/gemini-api/docs/generate-content/image-generation
# Values are provider outputs, not mathematical aspect-ratio approximations.
_FLASH_25 = {
    "1:1": (1024, 1024), "2:3": (832, 1248), "3:2": (1248, 832),
    "3:4": (864, 1184), "4:3": (1184, 864), "4:5": (896, 1152),
    "5:4": (1152, 896), "9:16": (768, 1344), "16:9": (1344, 768),
    "21:9": (1536, 672),
}
_GEMINI_3_1K = {
    "1:1": (1024, 1024), "2:3": (848, 1264), "3:2": (1264, 848),
    "3:4": (896, 1200), "4:3": (1200, 896), "4:5": (928, 1152),
    "5:4": (1152, 928), "9:16": (768, 1376), "16:9": (1376, 768),
    "21:9": (1584, 672),
}
_FLASH_31_EXTRA = {
    "1:4": (512, 2048), "4:1": (2048, 512),
    "1:8": (384, 3072), "8:1": (3072, 384),
}


def _native_image_configs(model: str) -> dict[tuple[int, int], dict[str, str]]:
    """Enumerate the model's native output sizes and API configurations."""
    name = model.removeprefix("models/")
    sizes: dict[tuple[int, int], dict[str, str]] = {}
    if name.startswith("gemini-2.5-flash-image"):
        sizes = {size: {"aspectRatio": ratio} for ratio, size in _FLASH_25.items()}
    elif name.startswith(("gemini-3-pro-image", "gemini-3.1-pro-image", "gemini-3.1-flash")):
        if "image" not in name:
            raise ImageDimensionsError(f"Native image dimensions are not supported for {model}")
        base_sizes = dict(_GEMINI_3_1K)
        tiers = (1, 2, 4)
        if name.startswith("gemini-3.1-flash"):
            base_sizes.update(_FLASH_31_EXTRA)
            if "lite" in name:
                tiers = (1,)
        for ratio, (base_width, base_height) in base_sizes.items():
            for tier in tiers:
                sizes[(base_width * tier, base_height * tier)] = {
                    "aspectRatio": ratio, "imageSize": f"{tier}K",
                }
        if name.startswith("gemini-3.1-flash") and "lite" not in name:
            for ratio, (base_width, base_height) in base_sizes.items():
                # 512px tier is exactly half of the documented 1K output.
                sizes[(base_width // 2, base_height // 2)] = {
                    "aspectRatio": ratio, "imageSize": "512",
                }
    else:
        raise ImageDimensionsError(f"Native pixel dimensions are not supported for Gemini model {model}")
    return sizes


def native_image_size(model: str, width: int, height: int) -> NativeImageSize:
    """Choose the nearest native size covering the request, including for routers."""
    try:
        configs = _native_image_configs(model)
    except ImageDimensionsError:
        return NativeImageSize(None, None, {})
    w, h = nearest_image_size(width, height, configs)
    config = configs[(w, h)]
    return NativeImageSize(w, h, {
        "aspect_ratio": config["aspectRatio"],
        "resolution": config.get("imageSize", "1K"),
    })


def native_image_config(model: str, width: int, height: int) -> dict[str, str]:
    size = native_image_size(model, width, height)
    if size.width is None or size.height is None:
        return {}
    return _native_image_configs(model)[(size.width, size.height)]


class GeminiImageGeneration:
    select_size = staticmethod(native_image_size)

    def prepare_request(
        self, connection: ProviderConnection, *, model: str, prompt: str,
        sources: list[tuple[bytes, str]], width: int, height: int,
    ) -> httpx.Request:
        config = native_image_config(model, width, height)
        parts: list[dict[str, object]] = [{"text": prompt}]
        parts.extend({"inlineData": {
            "mimeType": mime, "data": base64.b64encode(data).decode("ascii"),
        }} for data, mime in sources)
        base = connection.base_url.rstrip("/").removesuffix("/openai")
        name = quote(model.removeprefix("models/"), safe="")
        return httpx.Request(
            "POST", f"{base}/models/{name}:generateContent",
            headers={"x-goog-api-key": connection.api_key} if connection.api_key else {},
            json={
                "contents": [{"role": "user", "parts": parts}],
                "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": config},
            },
        )

    def read_response(self, response: httpx.Response) -> ImageGenerationResult:
        payload = as_dict(response.json())
        usage = as_dict(payload.get("usageMetadata"))
        for candidate in as_list(payload.get("candidates")):
            content = as_dict(as_dict(candidate).get("content"))
            for part in as_list(content.get("parts")):
                item = as_dict(part)
                if item.get("thought"):
                    continue
                inline = as_dict(item.get("inlineData") or item.get("inline_data"))
                encoded = inline.get("data")
                if isinstance(encoded, str) and encoded:
                    return ImageGenerationResult(
                        base64.b64decode(encoded, validate=True),
                        str(inline.get("mimeType") or inline.get("mime_type") or "image/png"),
                        {
                            "prompt_tokens": usage.get("promptTokenCount", 0),
                            "completion_tokens": usage.get("candidatesTokenCount", 0),
                            "total_tokens": usage.get("totalTokenCount", 0),
                        },
                    )
        raise ValueError("Gemini returned no image")
