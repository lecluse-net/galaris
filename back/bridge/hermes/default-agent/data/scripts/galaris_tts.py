"""Small standard-library TTS adapter for providers not built into Hermes."""

from __future__ import annotations

import argparse
import base64
import html
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


def _post(url: str, body: bytes, headers: dict[str, str]) -> bytes:
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=90) as response:
            return response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"TTS HTTP {exc.code}: {detail}") from exc


def _google(text: str, voice: str) -> bytes:
    api_key = os.environ.get("GOOGLE_CLOUD_TTS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_CLOUD_TTS_API_KEY is missing")
    language_code = "-".join(voice.split("-")[:2])
    payload = {
        "input": {"text": text},
        "voice": {"languageCode": language_code, "name": voice},
        "audioConfig": {"audioEncoding": "MP3"},
    }
    raw = _post(
        "https://texttospeech.googleapis.com/v1/text:synthesize?" + urlencode({"key": api_key}),
        json.dumps(payload).encode("utf-8"),
        {"Content-Type": "application/json"},
    )
    return base64.b64decode(json.loads(raw)["audioContent"])


def _azure(text: str, voice: str) -> bytes:
    api_key = os.environ.get("AZURE_SPEECH_KEY", "").strip()
    region = os.environ.get("AZURE_SPEECH_REGION", "").strip()
    if not api_key or not region:
        raise RuntimeError("AZURE_SPEECH_KEY and AZURE_SPEECH_REGION are required")
    language = "-".join(voice.split("-")[:2])
    ssml = (
        f'<speak version="1.0" xml:lang="{html.escape(language)}">'
        f'<voice name="{html.escape(voice)}">{html.escape(text)}</voice></speak>'
    )
    return _post(
        f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1",
        ssml.encode("utf-8"),
        {
            "Content-Type": "application/ssml+xml",
            "Ocp-Apim-Subscription-Key": api_key,
            "X-Microsoft-OutputFormat": "audio-24khz-48kbitrate-mono-mp3",
            "User-Agent": "Galaris-Hermes-TTS",
        },
    )


def _elevenlabs(text: str, voice: str, model: str) -> bytes:
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY is missing")
    base_url = os.environ.get(
        "GALARIS_ELEVENLABS_TTS_BASE_URL",
        "https://api.elevenlabs.io/v1",
    ).strip().rstrip("/")
    payload = {
        "text": text,
        "model_id": model or "eleven_multilingual_v2",
    }
    return _post(
        f"{base_url}/text-to-speech/{quote(voice, safe='')}?"
        + urlencode({"output_format": "mp3_44100_128"}),
        json.dumps(payload).encode("utf-8"),
        {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--provider",
        required=True,
        choices=("google-cloud-tts", "azure-speech", "elevenlabs"),
    )
    parser.add_argument("--voice", required=True)
    parser.add_argument("--model", default="")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    text = Path(args.input).read_text(encoding="utf-8")
    if args.provider == "google-cloud-tts":
        audio = _google(text, args.voice)
    elif args.provider == "azure-speech":
        audio = _azure(text, args.voice)
    else:
        audio = _elevenlabs(text, args.voice, args.model)
    Path(args.output).write_bytes(audio)


if __name__ == "__main__":
    main()
