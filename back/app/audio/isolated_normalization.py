"""Cancellable process boundary for opportunistic media decoding."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys
from typing import cast

from .audio_service import AudioChunk, AudioConversionFailed, TRANSCRIPTION_CHUNK_SECONDS


async def normalize_for_transcription_chunks_isolated(
    source: Path, destination_dir: Path, *, chunk_seconds: int = TRANSCRIPTION_CHUNK_SECONDS,
) -> list[AudioChunk]:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.audio.isolated_normalization",
        str(source.resolve()), str(destination_dir.resolve()), str(chunk_seconds),
        cwd=Path(__file__).resolve().parents[2],
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        async with asyncio.timeout(120):
            output, _ = await process.communicate()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode != 0:
        raise AudioConversionFailed("Audio decoding failed or exceeded its resource limits")
    result = cast(dict[str, object], json.loads(output))
    if "error" in result:
        raise AudioConversionFailed(str(result["error"]))
    chunks = cast(list[dict[str, str | int | float]], result["chunks"])
    return [AudioChunk(
        destination_dir / str(chunk["name"]), int(chunk["index"]),
        float(chunk["start"]), float(chunk["end"]),
    ) for chunk in chunks]


if __name__ == "__main__":
    import resource
    from .audio_service import normalize_for_transcription_chunks

    resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (110, 110))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024 * 1024, 32 * 1024 * 1024))
    try:
        decoded = asyncio.run(normalize_for_transcription_chunks(
            Path(sys.argv[1]), Path(sys.argv[2]), chunk_seconds=int(sys.argv[3]),
        ))
        response: dict[str, object] = {"chunks": [
            {"name": chunk.path.name, "index": chunk.index, "start": chunk.start_seconds, "end": chunk.end_seconds}
            for chunk in decoded
        ]}
    except Exception as exc:
        response = {"error": str(exc)}
    sys.stdout.write(json.dumps(response))
