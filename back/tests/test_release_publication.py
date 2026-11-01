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
