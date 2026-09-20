import base64
from io import BytesIO

import pytest
from PIL import Image

from app.llm.image_trace import compact_request_images, compact_trace_images


def _image_data_url(width: int, height: int) -> str:
    output = BytesIO()
    Image.new("RGB", (width, height), "#e53935").save(output, format="PNG")
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


@pytest.mark.parametrize(
    ("source_size", "preview_size"),
    [
        ((1600, 900), (320, 180)),
        ((900, 1600), (135, 240)),
        ((320, 200), (320, 200)),
    ],
)
def test_compact_request_images_stores_bounded_jpeg_without_distortion(
    source_size: tuple[int, int],
    preview_size: tuple[int, int],
) -> None:
    original_url = _image_data_url(*source_size)
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": "Analyse cette image"},
            {"type": "image_url", "image_url": {"url": original_url}},
        ],
    }]

    compacted = compact_request_images(messages)
    preview_url = compacted[0]["content"][1]["image_url"]["url"]

    assert messages[0]["content"][1]["image_url"]["url"] == original_url
    assert preview_url.startswith("data:image/jpeg;base64,")
    preview_bytes = base64.b64decode(preview_url.partition(",")[2])
    with Image.open(BytesIO(preview_bytes)) as preview:
        assert preview.format == "JPEG"
        assert preview.size == preview_size


def test_compact_request_images_never_keeps_an_invalid_full_data_url() -> None:
    messages = [{
        "role": "user",
        "content": [{
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,not-valid-base64"},
        }],
    }]

    compacted = compact_request_images(messages)

    assert compacted[0]["content"][0]["image_url"]["url"] == ""


def test_compact_trace_images_replaces_images_embedded_in_text_and_tool_results() -> None:
    original_url = _image_data_url(1600, 900)
    trace = {
        "response_text": f"Avant ![aperçu]({original_url}) après",
        "tool_calls": [{
            "id": "call-image",
            "result": {"image": original_url},
        }],
    }

    compacted = compact_trace_images(trace)
    response_text = compacted["response_text"]
    response_preview = response_text.removeprefix("Avant ![aperçu](").removesuffix(") après")
    tool_preview = compacted["tool_calls"][0]["result"]["image"]

    assert original_url not in response_text
    assert response_text.startswith("Avant ![aperçu](data:image/jpeg;base64,")
    assert response_text.endswith(") après")
    assert tool_preview.startswith("data:image/jpeg;base64,")
    for preview_url in (response_preview, tool_preview):
        preview_bytes = base64.b64decode(preview_url.partition(",")[2])
        with Image.open(BytesIO(preview_bytes)) as preview:
            assert preview.format == "JPEG"
            assert preview.size == (320, 180)


def test_compact_trace_images_drops_an_invalid_embedded_data_url() -> None:
    invalid_url = "data:image/png;base64,not-valid-base64"

    compacted = compact_trace_images(f"avant {invalid_url} après")

    assert compacted == "avant  après"
    assert invalid_url not in compacted
