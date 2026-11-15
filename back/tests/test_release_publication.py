"""Every automated source publication requires a successful release check."""

from pathlib import Path

import yaml


def test_every_automated_publication_depends_on_the_release_check():
    root = Path(__file__).resolve().parents[2]
    workflow = yaml.safe_load((root / ".github/workflows/publish-release.yml").read_text())
    jobs = workflow["jobs"]
    gates = {key for key, job in jobs.items()
             if any("make release-check" in step.get("run", "") for step in job.get("steps", []))}
    assert gates, "Publication must have a mandatory release check"
    for key, job in jobs.items():
        if not any(action in step.get("run", "")
                   for step in job.get("steps", [])
                   for action in ("gh release create", "gh release upload", "gh release edit")):
            continue
        needed = job.get("needs", [])
        needed = {needed} if isinstance(needed, str) else set(needed)
        assert gates & needed, f"{key} bypasses the release check"
        assert "always()" not in job.get("if", ""), "Publication cannot run after a failed prerequisite"
        checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
        assert checkout["with"]["ref"] == "${{ needs.preflight.outputs.commit }}", "Publish the qualified commit"
        assert "desktop" in needed, "Source and desktop artifacts must be qualified together"


def test_desktop_builds_are_qualified_and_published_as_one_complete_release():
    root = Path(__file__).resolve().parents[2]
    jobs = yaml.safe_load((root / ".github/workflows/publish-release.yml").read_text())["jobs"]
    desktop = jobs["desktop"]
    assert desktop["needs"] == "preflight"
    platforms = desktop["strategy"]["matrix"]["os"]
    assert any(platform.startswith("ubuntu-") for platform in platforms)
    assert any(platform.startswith("windows-") for platform in platforms)
    assert not any("npm test" in step.get("run", "") or "test:desktop" in step.get("run", "")
                   for step in desktop["steps"]), "Functional quality must remain separate from source publication"
    checkout = next(step for step in desktop["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ needs.preflight.outputs.commit }}"
    build = next(step for step in desktop["steps"] if "electron-builder" in step.get("run", ""))
    assert "--publish never" in build["run"]
    assert "extraMetadata.version" in build["run"]
    assert build["env"]["DESKTOP_VERSION"] == "${{ inputs.tag || github.ref_name }}"
    assert "runner.os == 'Windows' && '1'" in build["env"]["DESKTOP_REQUIRE_SIGNING"]
    publication = next(step["run"] for step in jobs["publish"]["steps"] if "gh release create" in step.get("run", ""))
    assert "--draft" in publication
    assert publication.index("gh release upload") < publication.index("gh release edit")
    assert "--draft=false" in publication


def test_full_quality_keeps_all_browsers_and_requires_explicit_opt_in():
    root = Path(__file__).resolve().parents[2]
    jobs = yaml.safe_load((root / ".github/workflows/quality.yml").read_text())["jobs"]
    browser_job = jobs["chat-e2e"]
    assert browser_job["strategy"]["matrix"]["browser"] == ["chromium", "firefox", "webkit"]
    assert browser_job["strategy"]["fail-fast"] is False
    assert not browser_job.get("continue-on-error", False)
    command = next(step["run"] for step in browser_job["steps"] if "make tests-e2e" in step.get("run", ""))
    assert "--project=${{ matrix.browser }}" in command
    assert "chat-e2e" in jobs["required"]["needs"]
    assert jobs["required"]["if"] == "always()"
    for key in ("providers", "backend-tests", "frontend-components", "chat-e2e", "restore"):
        assert "workflow_dispatch" in jobs[key]["if"]
        assert "inputs.full == true" in jobs[key]["if"]
        assert not jobs[key].get("continue-on-error", False)


def test_security_gate_contains_only_security_scans():
    root = Path(__file__).resolve().parents[2]
    jobs = yaml.safe_load((root / ".github/workflows/security.yml").read_text())["jobs"]
    assert set(jobs["required"]["needs"]) == {"source", "images"}
    assert all(not jobs[key].get("continue-on-error", False) for key in ("source", "images"))
