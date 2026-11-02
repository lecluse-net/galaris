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
        if not any("gh release create" in step.get("run", "") for step in job.get("steps", [])):
            continue
        needed = job.get("needs", [])
        needed = {needed} if isinstance(needed, str) else set(needed)
        assert gates & needed, f"{key} bypasses the release check"
        assert "always()" not in job.get("if", ""), "Publication cannot run after a failed prerequisite"
        checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
        assert checkout["with"]["ref"] == "${{ needs.preflight.outputs.commit }}", "Publish the qualified commit"


def test_required_quality_keeps_every_browser_qualification_mandatory():
    root = Path(__file__).resolve().parents[2]
    jobs = yaml.safe_load((root / ".github/workflows/quality.yml").read_text())["jobs"]
    browser_job = jobs["chat-e2e"]
    assert browser_job["strategy"]["matrix"]["browser"] == ["chromium", "firefox", "webkit"]
    assert browser_job["strategy"]["fail-fast"] is False
    assert not browser_job.get("continue-on-error", False)
    command = next(step["run"] for step in browser_job["steps"] if "make tests-e2e" in step.get("run", ""))
    assert "--project=${{ matrix.browser }}" in command
    assert "--repeat-each=3" in command
    assert "chat-e2e" in jobs["required"]["needs"]
    assert jobs["required"]["if"] == "always()"
