"""Keep the privileged scenario API confined to an ephemeral test deployment."""
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_browser_stack_has_no_live_credentials_or_external_network():
    compose = yaml.safe_load((ROOT / "compose.e2e.yaml").read_text())
    assert compose["networks"]["default"]["internal"] is True
    for name, service in compose["services"].items():
        assert "env_file" not in service
        assert "ports" not in service
        assert service.get("network_mode") == ("service:frontend" if name == "runner" else None)
        for volume in service.get("volumes", []):
            assert volume in {
                "./back:/repo/back:ro", "${GALARIS_E2E_ARTIFACT_DIR:-./artifacts/e2e}:/artifacts",
                "./front/core/util/sanitizeHtml.ts:/front/core/util/sanitizeHtml.ts:ro",
                "pwa-site:/usr/share/nginx/html", "pwa-site:/pwa-site",
            }
    assert compose["volumes"] == {"pwa-site": None}
    env = compose["services"]["backend"]["environment"]
    assert (env["APP_ENV"], env["POSTGRES_DB"], env["POSTGRES_HOST"]) == ("test", "test_db", "db-e2e")


@pytest.mark.parametrize("overrides", [
    {"APP_ENV": "dev"},
    {"APP_ENV": "prod"},
    {"POSTGRES_DB": "galaris"},
    {"POSTGRES_HOST": "postgres"},
])
def test_scenario_server_refuses_any_non_e2e_database(overrides):
    env = {
        **os.environ,
        "APP_ENV": "test", "POSTGRES_DB": "test_db", "POSTGRES_HOST": "db-e2e",
        **overrides,
    }
    result = subprocess.run(
        [sys.executable, "-c", "import tests.e2e_app"],
        env=env, capture_output=True, text=True, timeout=20,
    )
    assert result.returncode != 0
    assert "Browser fixtures require the isolated" in result.stderr


def test_simultaneous_backend_suites_have_distinct_cleanup_targets(tmp_path):
    docker = tmp_path / "docker"
    docker.write_text(
        '#!/bin/bash\n'
        'printf "%s\\n" "$*" >> "$TEST_DOCKER_LOG"\n'
        'case " $* " in *" run "*) exit 7 ;; esac\n'
    )
    docker.chmod(0o755)
    processes = []
    for index in range(2):
        log = tmp_path / f"commands-{index}"
        process = subprocess.Popen(
            ["bash", str(ROOT / "bin/test-back.sh"), "tests/test_health.py"],
            env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "TEST_DOCKER_LOG": str(log)},
        )
        processes.append((process, log))
    projects = []
    for process, log in processes:
        assert process.wait(timeout=10) == 7, "Cleanup must preserve the failing test exit status"
        commands = [line.split() for line in log.read_text().splitlines()]
        project_names = {command[command.index("-p") + 1] for command in commands}
        assert len(project_names) == 1
        assert "down" in commands[-1]
        assert sum("down" in command for command in commands) == 1
        projects.append(project_names.pop())
    assert projects[0] != projects[1]
