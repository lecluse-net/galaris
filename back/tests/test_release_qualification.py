import hashlib
import json

import pytest

from scripts.release_qualification import validate_promotion, validate_upgrade


def bundle(tmp_path):
    (tmp_path / "SOURCE_COMMIT").write_text("a" * 40)
    (tmp_path / "IMAGE_IDS").write_text("sha256:candidate galaris-release-back:test\n")
    evidence = {"candidate_image": "sha256:candidate", "previous_image": "sha256:previous",
                "convergence": "passed", "restoration": "passed", "tests_commit": "source", "tests_sha256": "test-content"}
    (tmp_path / "UPGRADE_QUALIFICATION.json").write_text(json.dumps(evidence))
    qualification = {"images": {"galaris-release-back:test": "sha256:candidate"},
                     "upgrade_sha256": hashlib.sha256((tmp_path / "UPGRADE_QUALIFICATION.json").read_bytes()).hexdigest()}
    (tmp_path / "QUALIFICATION.json").write_text(json.dumps(qualification))
    return evidence


def test_promotion_requires_the_qualified_previous_image(tmp_path):
    bundle(tmp_path)
    validate_promotion(tmp_path, "sha256:previous")
    validate_promotion(tmp_path, "sha256:candidate")
    with pytest.raises(ValueError, match="Installed backend"):
        validate_promotion(tmp_path, "sha256:another-version")


def test_changed_candidate_and_modified_evidence_cannot_reuse_qualification(tmp_path):
    evidence = bundle(tmp_path)
    (tmp_path / "IMAGE_IDS").write_text("sha256:other galaris-release-back:test\n")
    with pytest.raises(ValueError, match="candidate backend"):
        validate_upgrade(tmp_path)
    bundle(tmp_path)
    evidence["tests_sha256"] = "changed"
    (tmp_path / "UPGRADE_QUALIFICATION.json").write_text(json.dumps(evidence))
    with pytest.raises(ValueError, match="changed after"):
        validate_promotion(tmp_path, "sha256:previous")


def test_working_tree_evidence_cannot_be_promoted(tmp_path):
    bundle(tmp_path)
    (tmp_path / "SOURCE_COMMIT").write_text("working-tree qualification")
    with pytest.raises(ValueError, match="not a committed release"):
        validate_promotion(tmp_path, "sha256:previous")
