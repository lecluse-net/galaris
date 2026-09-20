import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from core.settings import Settings


@pytest.mark.parametrize("host,expected_status", [
    ("public.example.test", 200),
    ("localhost:8000", 200),
    ("127.0.0.1:8000", 200),
    ("backend:8000", 200),
    ("custom-back:8000", 200),
    ("custom-front:8484", 200),
    ("internal.example.test:8000", 200),
    ("192.0.2.10:8000", 200),
    ("alias.example.test", 200),
    ("unknown.example.test", 400),
    ("public.example.test.attacker.test", 400),
    ("manager.example.test:8485", 400),
])
def test_production_backend_accepts_known_addresses_only(host, expected_status, monkeypatch):
    from core.params import middleware, runtime_settings

    configured = Settings(
        APP_ENV="prod", APP_NAME="custom",
        APP_HOST="https://public.example.test:8443",
        BACK_ALLOWED_HOSTS=" 192.0.2.10, alias.example.test, ,alias.example.test ",
    )
    monkeypatch.setattr(middleware, 'settings', configured)
    monkeypatch.setattr(runtime_settings, 'HARNESS_MANAGER_GALARIS_API_URL', 'http://internal.example.test:8000/api/')
    app = Starlette(
        routes=[Route("/", lambda request: PlainTextResponse("ok"))],
        middleware=[Middleware(middleware.RuntimeTrustedHostMiddleware)],
    )
    with TestClient(app) as client:
        response = client.get("/", headers={
            "Host": host, "X-Forwarded-Host": "public.example.test",
        })
    assert response.status_code == expected_status
    assert len(configured.ALLOWED_HOSTS) == len(set(configured.ALLOWED_HOSTS))


def test_production_hosts_keep_explicit_wildcard_and_empty_internal_url():
    configured = Settings(
        APP_ENV="prod", APP_HOST="https://public.example.test",
        HARNESS_MANAGER_GALARIS_API_URL="", BACK_ALLOWED_HOSTS="",
    )
    assert "public.example.test" in configured.ALLOWED_HOSTS
    assert "" not in configured.ALLOWED_HOSTS
    assert "*" not in configured.ALLOWED_HOSTS
    configured.BACK_ALLOWED_HOSTS = "*"
    assert "*" in configured.ALLOWED_HOSTS


def test_database_credentials_roundtrip_reserved_characters():
    configured = Settings(APP_ENV="test", POSTGRES_USER="user@:/", POSTGRES_PASSWORD="secret@:/?#%", POSTGRES_DB="test")
    url = make_url(configured.DATABASE_URL)
    assert url.username == "user@:/"
    assert url.password == "secret@:/?#%"


@pytest.mark.parametrize("environment", ["prod", "demo", "preprod", "pp", "test", "custom", "DEV", ""])
@pytest.mark.parametrize("name", ["ENCRYPTION_MASTER_KEY"])
def test_secrets_validate_resolved_environment(monkeypatch, environment, name):
    monkeypatch.setenv("APP_ENV", "test")
    values = dict(APP_ENV=environment, ENCRYPTION_MASTER_KEY="b" * 32)
    values[name] = "weak-but-16-chars"
    with pytest.raises(ValidationError, match=name):
        Settings(**values)


def test_development_keeps_explicit_development_defaults():
    settings = Settings(APP_ENV="dev", ENCRYPTION_MASTER_KEY="")
    assert settings.ENCRYPTION_MASTER_KEY == ""


@pytest.mark.parametrize("environment", ["dev", "prod", "pp", "test", "demo", "custom", "DEV", ""])
def test_only_dev_enables_development(environment):
    configured = Settings(APP_ENV=environment)
    assert configured.APP_ENV == environment
    assert configured.is_dev is (environment == "dev")
    assert ("*" in configured.ALLOWED_HOSTS) is configured.is_dev


def test_environment_defaults_to_prod(monkeypatch):
    monkeypatch.delenv("APP_ENV", raising=False)
    configured = Settings(_env_file=None)
    assert configured.APP_ENV == "prod"
    assert configured.is_dev is False


@pytest.mark.parametrize("environment", ["dev", "prod", "pp", "test", "demo", "custom"])
@pytest.mark.parametrize("name,minimum", [
    ("MESSENGER_ONE_BOT_SECRET_KEY", 32),
    ("MESSENGER_WHATSAPP_APP_SECRET", 32),
    ("MESSENGER_WHATSAPP_VERIFY_TOKEN", 16),
])
def test_optional_provider_secrets_are_protected_outside_dev(monkeypatch, environment, name, minimum):
    from core.settings import settings
    from core.params.runtime_settings import RuntimeSettings

    monkeypatch.setattr(settings, "APP_ENV", environment)
    assert getattr(RuntimeSettings(**{name: ""}), name) == ""
    assert getattr(RuntimeSettings(**{name: "a" * minimum}), name) == "a" * minimum
    if environment == "dev":
        assert getattr(RuntimeSettings(**{name: "weak"}), name) == "weak"
    else:
        with pytest.raises(ValidationError, match=name):
            RuntimeSettings(**{name: "weak"})
