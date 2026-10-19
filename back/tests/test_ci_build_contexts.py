"""CI builds supply the local sources bundled by the backend Dockerfile."""

import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml


@pytest.mark.parametrize("pipeline", ["github-quality", "github-security", "gitlab-security"])
def test_ci_backend_builds_supply_all_local_contexts(tmp_path, pipeline):
    root = Path(__file__).resolve().parents[2]
    if pipeline == "github-quality":
        workflow = yaml.safe_load((root / ".github/workflows/quality.yml").read_text())
        command = next(step["run"] for step in workflow["jobs"]["static"]["steps"]
                       if step.get("name") == "Build backend quality image")
    elif pipeline == "github-security":
        workflow = yaml.safe_load((root / ".github/workflows/security.yml").read_text())
        command = next(step["run"] for step in workflow["jobs"]["images"]["steps"]
                       if step.get("name") == "Build shipped image")
    else:
        workflow = yaml.safe_load((root / ".gitlab-ci.yml").read_text())
        command = "\n".join(workflow["images"]["script"])

    # Execute the actual build command, replacing Docker and the separate scanner.
    capture = tmp_path / "build-arguments"
    docker = tmp_path / "docker"
    docker.write_text('#!/bin/sh\nif [ "$1" = build ]; then printf "%s\\0" "$@" > "$BUILD_CAPTURE"; fi\n')
    docker.chmod(0o755)
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin/security-check.sh").write_text("exit 0\n")
    result = subprocess.run(["bash", "-euc", command], cwd=tmp_path, capture_output=True, text=True,
                            env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}",
                                 "BUILD_CAPTURE": str(capture), "BUILD_CONTEXT": "back",
                                 "CI_JOB_ID": "synthetic-build-contract"})
    assert result.returncode == 0, result.stderr
    arguments = capture.read_text().rstrip("\0").split("\0")
    contexts = {}
    for index, argument in enumerate(arguments):
        if index and arguments[index - 1] == "--build-context":
            name, path = argument.split("=", 1)
            contexts[name] = path
        elif argument.startswith("--build-context="):
            name, path = argument.removeprefix("--build-context=").split("=", 1)
            contexts[name] = path

    dockerfile = (root / "back/Dockerfile").read_text()
    stages = set(re.findall(r"^FROM .* AS (\S+)", dockerfile, re.MULTILINE | re.IGNORECASE))
    local_sources = set(re.findall(r"--from=([A-Za-z0-9_-]+)(?:\s|$)", dockerfile)) - stages
    assert local_sources <= contexts.keys(), f"{pipeline} omits backend sources: {local_sources - contexts.keys()}"
    assert all((root / contexts[name]).is_dir() for name in local_sources)
