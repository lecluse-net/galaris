<p align="right"><a href="../../fr/components/multimedia.md">Français</a> · <strong>English</strong></p>

# Multimedia

The optional Multimedia Tool provides `audio_read`, `video_read`, `sound_generate`,
`music_generate`, and `video_generate`. Speech transcription, Voice conversations,
text and images retain their existing configuration and Tools.

## Configuration

1. Configure a provider and its API key in LLM preferences.
2. Add resources from the provider's capability catalog.
3. Select resources in the **Multimedia** section of the agent's effective LLM profile.
4. Enable the agent's **Multimedia** connection, created automatically and disabled by default.

An agent with a custom profile uses that profile exclusively. Empty fields do not fall back
to the global profile. MCP catalogs and execution check the current connection, capability,
provider and selected resource.

| Capability | Providers |
|---|---|
| Sound/music analysis | OpenRouter and Mammouth AI audio-input models |
| Video analysis | OpenRouter and Mammouth AI video-input models |
| Sound effects | ElevenLabs, SunoAPI.org `sound:V5` service resource |
| Music generation | Eleven Music, Lyria through OpenRouter, SunoAPI.org |
| Video generation | OpenRouter video models, Seedance through BytePlus LAS |

SunoAPI.org is a third-party provider, separate from Suno Platform. Configure its own key
and a public HTTPS Galaris callback base (`PROCESS_GALARIS_BASE_URL`, otherwise `APP_HOST`).
Callbacks only acknowledge receipt; authenticated provider polling controls task state.

## Agent workflow

Analysis accepts a canonical file `uri` and a `prompt`. Files remain in their original Tool;
temporary materialization is limited to 32 MB and 20 minutes, validated by FFprobe.

Generation accepts a `prompt` and a writable binary-file collection `destination` ending in `/`.
It returns a durable Process `run_id`. Poll `process_get_run`; completed files appear in
`output.files[].uri` and the Task working set. A run only succeeds after canonical file creation.
Up to four files of 100 MB each are supported.

Use the same `invocation_key` only to retry one invocation. A new invocation creates a new
generation even with the same prompt. An ambiguous provider response never causes automatic
resubmission. An interrupted remote file creation requires checking the destination before retrying.
Private database delivery receipts retain bytes until canonical delivery, then erase them.

Options are provider-specific. Exact lyrics are supported through SunoAPI custom mode;
Lyria receives lyrical instructions. Unsupported options are rejected. Costs absent from provider
responses are marked unknown. Remote cancellation is not advertised without provider confirmation.

## Installation and validation

The backend image requires FFmpeg/FFprobe. Rebuild older images, then use `make sync-db` in
development or the normal `make update` production workflow. Tests use mocked provider transports;
real-account access and billing require separate qualification. Personas, remixes, generation
reference media and ElevenLabs composition plans are not exposed yet.

Contract sources: [OpenRouter audio](https://openrouter.ai/docs/guides/overview/multimodal/audio),
[OpenRouter video](https://openrouter.ai/docs/guides/overview/multimodal/video-generation),
[SunoAPI.org](https://docs.sunoapi.org/suno-api/generate-music),
[Eleven Music](https://elevenlabs.io/docs/api-reference/music/compose),
[BytePlus LAS](https://docs.byteplus.com/en/docs/byteplus_las/video_gen_enhanced).
