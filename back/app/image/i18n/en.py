"""English image-service messages."""

default: dict[str, object] = {
    "image": {
        "generated": "Image generated (${width} × ${height} pixels, ${size} bytes): ${location}",
        "generation_failed": (
            "Image generation failed: ${error} No generated image was delivered. "
            "Report the limitation. Do not replace it with SVG/code artwork, resize, crop, "
            "or change format without explicit user approval. Native size adjustment is "
            "automatic and is not an error. Do not claim success when generation failed."
        ),
        "generation_unavailable": "The image could not be generated or saved.",
        "description_failed": "Image description failed: ${error}",
        "default_description": (
            "Describe this image in detail, including its content, visible text, and notable elements."
        ),
        "prompt_required": "Image generation requires a non-empty prompt.",
        "generation_model_missing": "No image-generation model is configured in the current profile.",
        "vision_model_missing": "No compatible image-analysis model is configured in the current profile.",
        "unsupported_analysis_mime": "image_read accepts images only; received MIME type: ${mime}.",
        "model_returned_no_image": "The model returned no image.",
        "model_returned_no_description": "The vision model returned no description.",
        "proxy_streaming_response": "The LLM proxy returned an unexpected streaming response for ${kind}.",
        "proxy_invalid_response": "Invalid LLM proxy response for model '${model}'.",
        "proxy_non_object": "The LLM proxy response for model '${model}' is not an object.",
        "provider_rejected": "The ${kind} provider rejected model '${model}' (${status}): ${detail}",
    },
}
