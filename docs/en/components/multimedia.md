<p align="right"><a href="../../fr/components/multimedia.md">Français</a> · <strong>English</strong></p>

# Multimedia

The optional Multimedia Service provides `audio_read`, `video_read`, `sound_generate`,
`music_generate`, and `video_generate`. Speech transcription, Voice conversations,
text and images retain their existing configuration and Services.

## Configuration

1. Configure a provider and its API key in LLM preferences.
2. Add resources from the provider's capability catalog.
3. Select resources in the **Multimedia** section of the agent's effective LLM profile.
4. Check the agent's **Multimedia** connection, created automatically and active by default.
   Saved deactivations are preserved; the Service's conversation mode requires explicit enabling.
   Functions without a compatible resource remain absent from the MCP catalog.

An agent with a custom profile uses that profile exclusively. Empty fields do not fall back
to the global profile. MCP catalogs and execution check the current connection, capability,
provider and selected resource.

Durable generation belongs to `app.multimedia`, with its own worker and checkpoints;
it creates no Process run.

| Capability | Providers |
|---|---|
| Sound/music analysis | OpenRouter and Mammouth AI audio-input models |
| Video analysis | OpenRouter and Mammouth AI video-input models |
| Sound effects | ElevenLabs, SunoAPI.org `sound:V5` service resource |
| Music generation | Eleven Music, Lyria through OpenRouter, SunoAPI.org |
| Video generation | OpenRouter video models, Seedance through BytePlus LAS |

SunoAPI.org is a third-party provider, separate from a Suno subscription and Suno Platform.
Configure its own key and a public HTTPS Galaris callback base (`APP_HOST`). This integration
uses `https://api.sunoapi.org/api/v1`. Callback payloads do not change generations;
authenticated provider polling controls their state.

The catalogue's **Suno** preset connects to the [official Suno MCP](https://help.suno.com/en/articles/14551425)
over HTTP. Save the Service, then [connect the Suno account with OAuth](../admin/service-administration.md)
from the Connection. Generations use the account's credits and appear in its Suno library.
Retrieving a file through this connector and delivering it through Galaris still need verification.

## Agent workflow

Analysis accepts a canonical file `uri` and a `prompt`. Files remain in their original Service;
temporary materialization is limited to 32 MiB and 20 minutes, validated by FFprobe.

`video_read` also accepts `subtitles_uri` and `language`. It first uses the supplied SRT/WebVTT
file, then embedded text subtitles, then the agent profile's transcription model. Its result
separates visual analysis from `transcript`, including provenance, timestamps and coverage
warnings; a bounded excerpt also reaches the video model. Without audio or an available
transcript, visual analysis remains possible with a warning. Burned-in captions are not
extracted through OCR. YouTube page URLs use `audio_transcribe`, which also handles longer
recordings or a complete saved transcript. See the [multimedia workflow](../user/README.md).

Generation accepts a `prompt` and a writable binary-file collection `destination` ending in `/`.
Use a collection returned by `file_list`. The `document://` root is unsuitable; a document
attachment collection is suitable. A console requires an active connection.
It returns a durable `generation_id` and `run_id`. Poll `multimedia_get_run`; completed files appear in
`output.files[].uri` and the Task working set. A run only succeeds after canonical file creation.
Up to four files of 100 MiB each are supported.

Use the same `invocation_key` only to retry one invocation. A new invocation creates a new
generation even with the same prompt. A submission whose response is lost remains `unknown`.
Once the provider has confirmed a generation identifier, a temporary polling or download
failure moves the generation to `waiting` and Galaris resumes tracking without resubmitting it.
An interrupted remote file write returns `delivery_unknown` whenever the outcome is uncertain.
Check the destination before retrying delivery.
Private database delivery receipts retain bytes until canonical delivery, then erase them.

Options are provider-specific. ElevenLabs effects last up to 30 seconds and music starts at
3 seconds. SunoAPI custom mode accepts lyrics, style and title; Lyria receives musical and
lyrical instructions. Seedance validates supported durations, ratios and resolutions.
Unsupported options are rejected. Costs absent from provider responses are marked unknown.
A cancellation confirmed by BytePlus or OpenRouter is shown as `cancelled`, with an unknown
cost if the provider does not report one. Requesting remote cancellation remains unavailable.

With BytePlus Seedance, `video_generate` accepts `first_frame_uri` and, when a first frame is
supplied, `last_frame_uri`. Use canonical URIs for still JPEG or PNG files up to 5 MB each,
with each side between 300 and 6,000 pixels and a width-to-height ratio of 0.4 to 2.5.
Galaris verifies access and content again before submission and returns the roles and
SHA-256 hashes in `reference_frames`.

With Eleven Music, `music_generate` accepts a `composition` object. Each item in `sections`
specifies `name`, `duration_ms` (3,000 to 120,000), and optional `lyrics` (one string per line),
`styles`, and `avoid_styles`. Both style lists are also available at plan level. Use `prompt`
for the overall direction, with a 200-character limit. Total duration is limited to 600 seconds.
Supply styles, timing, and lyrics inside the plan in place of the top-level music options.

## Installation and validation

The backend image requires FFmpeg/FFprobe. Rebuild older images, then use `make sync-db` in
development or the normal `make update` production workflow. Tests with simulated transports cover
generation, polling failures, recovery, and composition plans. Real-account access and billing
require separate verification. Personas, remixes, and other reference media remain extensions.

Contract sources: [OpenRouter audio](https://openrouter.ai/docs/guides/overview/multimodal/audio),
[OpenRouter video](https://openrouter.ai/docs/guides/overview/multimodal/video-generation),
[SunoAPI.org](https://docs.sunoapi.org/suno-api/generate-music),
[Eleven Music](https://elevenlabs.io/docs/api-reference/music/compose),
[BytePlus LAS](https://docs.byteplus.com/en/docs/byteplus_las/video_gen_enhanced).
