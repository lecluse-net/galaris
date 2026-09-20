from pathlib import Path
from typing import Any

import yaml


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _compose(path: str) -> dict[str, Any]:
    content = yaml.safe_load((REPOSITORY_ROOT / path).read_text(encoding="utf-8"))
    assert isinstance(content, dict)
    return content


def test_root_compose_files_use_the_preferred_names() -> None:
    current_names = (
        "compose.yaml",
        "compose.override.yaml.example",
        "compose.dev.yaml",
        "compose.postgres.yaml",
        "compose.test.yaml",
        "compose.turn.yaml",
    )
    legacy_names = (
        "docker-compose.yaml",
        "docker-compose.override.yaml.example",
        "docker-compose.dev.yaml",
        "docker-compose.postgres.yaml",
        "docker-compose.ssh-executor.yaml",
        "docker-compose.ssh-executor.dev.yaml",
        "docker-compose.test.yaml",
        "docker-compose.turn.yaml",
        "compose.ssh-executor.yaml",
    )

    assert all((REPOSITORY_ROOT / name).is_file() for name in current_names)
    assert all(not (REPOSITORY_ROOT / name).exists() for name in legacy_names)

    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    install_script = (REPOSITORY_ROOT / "bin/install.sh").read_text(encoding="utf-8")

    for name in (
        "compose.yaml",
        "compose.dev.yaml",
        "compose.postgres.yaml",
        "compose.turn.yaml",
    ):
        assert f"-f {name}" in makefile
    assert "mv docker-compose.override.yaml compose.override.yaml" in install_script


def test_base_services_share_the_named_galaris_network() -> None:
    compose = _compose("compose.yaml")
    services = compose["services"]
    networks = compose["networks"]

    assert compose["name"] == "${APP_NAME:-galaris}"
    assert isinstance(services, dict)
    assert isinstance(networks, dict)
    assert "app_net" not in networks
    assert "postgres" not in services
    assert "ssh-executor" in services
    assert "host.docker.internal:host-gateway" in services["backend"]["extra_hosts"]
    assert networks["galaris_net"] == {"name": "${APP_NAME:-galaris}-net"}
    assert networks["executor_net"] == {
        "name": "${APP_NAME:-galaris}-executor-net",
        "internal": True,
    }

    for service_name in ("backend", "frontend", "search"):
        service = services[service_name]
        assert isinstance(service, dict)
        assert "galaris_net" in service["networks"]

    env_example = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "HARNESS_MANAGER_DOCKER_NETWORK=" not in env_example
    assert "HARNESS_MANAGER_DOCKER_NETWORK" not in networks["executor_net"]["name"]


def test_backend_test_stack_uses_and_removes_only_its_default_network() -> None:
    compose = _compose("compose.test.yaml")
    script = (REPOSITORY_ROOT / "bin/test-back.sh").read_text(encoding="utf-8")

    assert compose["name"] == "${APP_NAME:-galaris}-tests"
    assert set(compose["services"]) == {"backend", "db-test"}
    assert "networks" not in compose
    assert all(
        "networks" not in service
        for service in compose["services"].values()
    )
    assert "container_name" not in compose["services"]["db-test"]
    assert "-f compose.test.yaml" in script
    assert "-f compose.yaml" not in script
    assert "-f compose.dev.yaml" not in script
    assert "down --remove-orphans" in script
    assert "rm --stop --force db-test" not in script


def test_optional_infrastructure_and_persistent_volume_wiring() -> None:
    base = _compose("compose.yaml")
    override = _compose("compose.override.yaml.example")
    postgres = _compose("compose.postgres.yaml")
    development = _compose("compose.dev.yaml")

    base_backend = base["services"]["backend"]
    base_search = base["services"]["search"]
    override_backend = override["services"]["backend"]
    override_executor = override["services"]["ssh-executor"]
    override_volumes = override["volumes"]
    postgres_service = postgres["services"]["postgres"]
    postgres_backend = postgres["services"]["backend"]
    executor_service = base["services"]["ssh-executor"]

    assert isinstance(base_backend, dict)
    assert isinstance(base_search, dict)
    assert isinstance(override_backend, dict)
    assert isinstance(override_executor, dict)
    assert isinstance(override_volumes, dict)
    assert isinstance(postgres_service, dict)
    assert isinstance(postgres_backend, dict)
    assert isinstance(executor_service, dict)

    assert "browser_credentials" in base["volumes"]
    assert "browser_credentials:/run/galaris-browser:ro" in base_backend["volumes"]
    browser = base["services"]["browser-executor"]
    assert "browser_credentials:/run/galaris-browser:ro" in browser["volumes"]
    initializer = base["services"]["browser-secrets"]
    assert initializer["network_mode"] == "none"
    assert "env_file" not in initializer
    assert "environment" not in initializer
    assert "browser_credentials:/run/galaris-browser" in initializer["volumes"]
    for consumer in (browser, base_backend):
        assert consumer["depends_on"]["browser-secrets"]["condition"] == "service_completed_successfully"
    # Search JSON is required even when an existing operator override only adds a network.
    assert base_search["volumes"] == [
        "./data/search/settings.yml:/etc/searxng/settings.yml:ro",
        "./data/search/limiter.toml:/etc/searxng/limiter.toml:ro",
    ]
    assert override_backend["volumes"] == ["galaris_data:/data"]
    assert override_executor["volumes"] == ["galaris_data:/data"]
    assert override_volumes["galaris_data"] == {
        "name": "${APP_NAME:-galaris}_data"
    }
    assert set(override_volumes) == {"galaris_data"}
    assert postgres_service["volumes"] == [
        "postgres_data:/var/lib/postgresql/data"
    ]
    assert "galaris_net" in postgres_service["networks"]
    assert postgres_backend["depends_on"]["postgres"] == {
        "condition": "service_healthy"
    }
    assert set(postgres["volumes"]) == {"postgres_data"}
    assert "volumes" not in executor_service
    assert "profiles" not in executor_service
    assert all(
        volume != "./data:/data"
        for volume in development["services"]["backend"]["volumes"]
    )


def test_deployment_configuration_exposes_only_operator_settings() -> None:
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    env_example = (REPOSITORY_ROOT / ".env.example").read_text(encoding="utf-8")
    settings = (REPOSITORY_ROOT / "back/core/settings.py").read_text(
        encoding="utf-8"
    )

    # Actual selection, defaults and reinstallation are exercised by make tests-update.
    assert "POSTGRES_MODE=embedded" in env_example
    assert "# Allowed: embedded, external, disabled." in env_example
    assert "POSTGRES_HOST=postgres" in env_example
    assert "BRIDGE_HARNESS_GALARIS_URL" not in env_example
    assert "BRIDGE_HARNESS_GALARIS_URL" not in settings
    assert "def APP_API_URL(self) -> str:" in settings
    assert "SSH_EXECUTOR_MODE" not in env_example
    assert "SSH_EXECUTOR_MODE" not in makefile
    for constant in (
        "GALARIS_SKILLS_ROOT",
        "GALARIS_MEMORY_ROOT",
        "GALARIS_INTERNAL_MESSENGER_ROOT",
        "GALARIS_THUMBNAIL_ROOT",
        "BROWSER_EXECUTOR_URL",
        "ALGORITHM",
        "AUTH_TOKEN_EXPIRE_MINUTES",
        "AUTH_REFRESH_TOKEN_EXPIRE_DAYS",
        "AUTH_REFRESH_TOKEN_REUSE_GRACE_SECONDS",
        "AUTH_REFRESH_COOKIE_NAME",
        "AUTH_LOGIN_LOCKOUT_THRESHOLD",
        "AUTH_LOGIN_LOCKOUT_BASE_SECONDS",
        "AUTH_LOGIN_LOCKOUT_MAX_SECONDS",
    ):
        assert f"{constant}=" not in env_example
        assert f"{constant}: ClassVar[" in settings
    assert "APP_LABEL=" not in env_example
    assert "APP_VERSION=" not in env_example
    assert "APP_DEBUG=" not in env_example
    assert "DEV_BACK_HOST" not in env_example
    assert "DEV_BACK_PORT" not in env_example
    assert "DEV_BACK_HOST" not in makefile
    assert "DEV_BACK_PORT" not in makefile
    assert "docker compose exec" not in makefile
    assert "docker compose run" not in makefile
    assert 'POSTGRES_HOST: str = "postgres"' in settings


def test_embedded_executor_stores_everything_under_application_data() -> None:
    compose = _compose("compose.yaml")
    backend_environment = compose["services"]["backend"]["environment"]
    executor = (REPOSITORY_ROOT / "ssh-executor/executord.py").read_text(
        encoding="utf-8"
    )
    entrypoint = (REPOSITORY_ROOT / "ssh-executor/entrypoint.sh").read_text(
        encoding="utf-8"
    )
    sshd = (REPOSITORY_ROOT / "ssh-executor/sshd_config").read_text(
        encoding="utf-8"
    )
    manager = (REPOSITORY_ROOT / "back/app/console/manager.py").read_text(
        encoding="utf-8"
    )
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

    assert (
        "GALARIS_EXECUTOR_CONTROL_SOCKET=/data/ssh-executor/run/control.sock"
        in backend_environment
    )
    assert "ssh-executor" in compose["services"]
    assert 'DATA_ROOT = Path("/data/ssh-executor")' in executor
    assert 'STATE_ROOT = DATA_ROOT / "state"' in executor
    assert 'CONTROL_SOCKET = DATA_ROOT / "run" / "control.sock"' in executor
    assert 'HOME_ROOT = DATA_ROOT / "home"' in executor
    assert "/data/ssh-executor/state/authorized_keys" in entrypoint
    assert '"/data/ssh-executor/run/control.sock"' in manager
    assert "/var/lib/galaris-executor" not in sshd
    assert "/data/ssh-executor/state/host_keys" in sshd
    assert "/data/ssh-executor/state/authorized_keys" in sshd
    assert "tar -czf - /data/ssh-executor" in makefile


def test_production_image_prepares_the_named_data_volume() -> None:
    dockerfile = (REPOSITORY_ROOT / "back/Dockerfile").read_text(encoding="utf-8")

    assert "mkdir -p /data" in dockerfile
    assert "chown app:app /data" in dockerfile


def test_application_identity_and_version_are_build_owned() -> None:
    compose = (REPOSITORY_ROOT / "compose.yaml").read_text(encoding="utf-8")
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    backend_dockerfile = (REPOSITORY_ROOT / "back/Dockerfile").read_text(
        encoding="utf-8"
    )
    frontend_settings = (REPOSITORY_ROOT / "front/core/settings.ts").read_text(
        encoding="utf-8"
    )

    assert "VITE_APP_LABEL" not in compose
    assert "VITE_APP_VERSION" not in compose
    assert "VITE_APP_DEBUG" not in compose
    assert "readonly APP_LABEL = 'Galaris'" in frontend_settings
    assert "override GALARIS_BUILD_VERSION := $(shell git describe" in makefile
    assert 'RUN printf \'%s\\n\' "$GALARIS_BUILD_VERSION"' in backend_dockerfile
