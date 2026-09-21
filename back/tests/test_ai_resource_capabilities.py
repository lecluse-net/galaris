"""Tests for capability-based AI resource discovery metadata."""

from app.llm.capabilities import infer_capabilities, with_capability
from app.llm.handlers import LLMModelInfo
from app.llm.provider_catalog import get_provider_profile


def test_specialized_models_are_not_classified_as_chat() -> None:
    whisper = LLMModelInfo(id="openai/whisper-large-v3")
    embedding = LLMModelInfo(id="openai/text-embedding-3-small")
    image = LLMModelInfo(id="google/gemini-3.1-flash-image")

    assert infer_capabilities(whisper) == ["transcription"]
    assert infer_capabilities(embedding) == ["embedding"]
    assert infer_capabilities(image) == ["image_generation"]


def test_provider_reported_multimodality_keeps_multiple_capabilities() -> None:
    model = LLMModelInfo(
        id="multimodal-chat",
        modalities={
            "input_text": True,
            "input_image": True,
            "output_text": True,
        },
    )

    assert infer_capabilities(model) == ["vision", "chat"]


def test_capability_defaults_are_directional_witnesses() -> None:
    transcription = with_capability(LLMModelInfo(id="scribe_v2"), "transcription")
    speech = with_capability(LLMModelInfo(id="voice-model"), "speech")

    assert transcription.modalities is not None
    assert transcription.modalities["input_audio"] is True
    assert transcription.modalities["output_text"] is True
    assert speech.modalities is not None
    assert speech.modalities["input_text"] is True
    assert speech.modalities["output_audio"] is True
    # A default for one service must not fabricate refusals for unknown inputs.
    assert "input_image" not in speech.modalities
    assert "input_file" not in transcription.modalities

    refused = with_capability(LLMModelInfo(
        id="restricted-model", modalities={"input_image": False},
    ), "vision")
    assert refused.modalities["input_image"] is False

    from app.llm.provider_router import _model_info_response

    # Public discovery must keep STT and TTS directional when unknown fields
    # are filled for clients that expect a complete boolean object.
    stt_response = _model_info_response(transcription)
    tts_response = _model_info_response(speech)
    assert stt_response.modalities.input_text is False
    assert tts_response.modalities.output_text is False
    assert "output_text" not in tts_response.known_modalities


def test_legacy_whisper_audio_output_does_not_turn_it_into_tts() -> None:
    whisper = LLMModelInfo(
        id="openai/whisper-large-v3",
        modalities={"input_audio": True, "output_text": True, "output_audio": True},
    )

    assert infer_capabilities(whisper) == ["transcription"]


def test_audio_provider_profiles_expose_driver_capabilities() -> None:
    elevenlabs = get_provider_profile("elevenlabs")
    google = get_provider_profile("google-cloud-tts")
    azure = get_provider_profile("azure-speech")

    assert elevenlabs is not None
    assert elevenlabs.capabilities == ("speech", "transcription", "music_generation", "sound_generation")
    assert google is not None
    assert google.capabilities == ("speech",)
    assert azure is not None
    assert azure.capabilities == ("speech",)
    assert azure.configuration_fields[0].key == "region"
