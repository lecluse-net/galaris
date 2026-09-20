from core.params import RuntimeSettings
from core.settings import settings


def test_environment_cannot_override_harness_preferences(monkeypatch):
    monkeypatch.setenv("HARNESS_MANAGER_URL", "https://ignored.example.test")
    monkeypatch.setenv("HARNESS_MANAGER_SECRET", "ignored")
    configured = RuntimeSettings()
    assert configured.HARNESS_MANAGER_URL == "http://host.docker.internal:8485"
    assert configured.HARNESS_MANAGER_SECRET == ""


def test_harness_api_override_keeps_public_origin_unchanged(monkeypatch):
    monkeypatch.setattr(settings, "APP_HOST", "https://public.example.test")
    configured = RuntimeSettings(HARNESS_MANAGER_GALARIS_API_URL="http://backend:8000/api/")
    assert settings.APP_API_URL == "https://public.example.test/api"
    assert configured.HARNESS_API_URL == "http://backend:8000/api"


def test_remote_harness_keeps_public_fallback_when_override_is_empty():
    assert RuntimeSettings().HARNESS_API_URL == settings.APP_API_URL
