import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.llm import media_facade
from app.llm.media_contracts import MediaResult


@pytest.mark.asyncio
@pytest.mark.parametrize("valid", [True, False])
async def test_video_text_fallback_probes_the_source_before_specialist_inference(tmp_path, monkeypatch, valid):
    path = tmp_path / "synthetic.mp4"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=32x32:r=1",
        "-t", "1", "-pix_fmt", "yuv420p", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    _, error = await process.communicate()
    assert process.returncode == 0, error.decode()
    if not valid:
        path.write_bytes(b"synthetic invalid media")
    provider = SimpleNamespace(validate=Mock(), analyze=AsyncMock(return_value=MediaResult("success", text="Synthetic video scene")))
    selected = SimpleNamespace(model="synthetic-video", provider=provider, connection=object())
    monkeypatch.setattr(media_facade, "resolve_media_resource", AsyncMock(return_value=selected))
    start = AsyncMock(return_value=uuid4())
    finish = AsyncMock()
    monkeypatch.setattr(media_facade, "start_media_call", start)
    monkeypatch.setattr(media_facade, "finish_media_call", finish)
    if valid:
        assert await media_facade.analyze_input_video(path, "video/mp4", agent_id=7) == "Synthetic video scene"
        provider.analyze.assert_awaited_once()
        finish.assert_awaited_once()
    else:
        with pytest.raises((ValueError, TypeError)):
            await media_facade.analyze_input_video(path, "video/mp4", agent_id=7)
        start.assert_not_awaited()
        provider.analyze.assert_not_awaited()
