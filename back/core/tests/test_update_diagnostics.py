"""Critical updates retain actionable evidence without secrets or local variables."""

import json
from core import update_diagnostics


def test_update_diagnostics_preserve_primary_and_cleanup_failures(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(update_diagnostics, "DIAGNOSTIC_ROOT", tmp_path / "diagnostics")
    monkeypatch.setenv("SYNTHETIC_SECRET_TOKEN", "synthetic-private-credential")
    try:
        try:
            raise RuntimeError("Couldn't find PID field in ps output; synthetic-private-credential")
        except RuntimeError:
            raise OSError("Synthetic cleanup failed: password='private words'")
    except OSError as error:
        path = update_diagnostics.record_update_failure(error, connection_id=123,
            details={"command": "docker top synthetic-runtime -eo comm", "exit_code": 1})
    assert path is not None
    report = json.loads(path.read_text())
    assert report["connection_id"] == 123
    assert [cause["type"] for cause in report["causes"]] == ["OSError", "RuntimeError"]
    assert "Couldn't find PID field" in report["causes"][1]["message"]
    assert report["causes"][1]["locations"]
    assert report["details"]["exit_code"] == 1
    assert "private" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert not capsys.readouterr().err


def test_diagnostic_storage_failure_is_explicit_and_preserves_the_cause(tmp_path, monkeypatch, capsys):
    target = tmp_path / "not-a-directory"
    target.write_text("Synthetic unrelated file")
    monkeypatch.setattr(update_diagnostics, "DIAGNOSTIC_ROOT", target)
    assert update_diagnostics.record_update_failure(ValueError("Synthetic original failure")) is None
    output = capsys.readouterr().err
    assert "diagnostic storage failed" in output
    assert "Synthetic original failure" in output
    assert target.read_text() == "Synthetic unrelated file"


def test_diagnostic_retention_is_bounded_and_symlinks_are_refused(tmp_path, monkeypatch):
    root = tmp_path / "diagnostics"
    root.mkdir()
    for index in range(101):
        (root / f"update-20000101-{index:03}.json").write_text("Synthetic old diagnostic")
    unrelated = root / "unrelated.json"
    unrelated.write_text("Synthetic unrelated data")
    monkeypatch.setattr(update_diagnostics, "DIAGNOSTIC_ROOT", root)
    path = update_diagnostics.record_update_failure(RuntimeError("Synthetic failure"))
    assert path is not None and path.is_file()
    assert len(list(root.glob("update-*.json"))) == 100
    assert unrelated.read_text() == "Synthetic unrelated data"
    link = tmp_path / "link"
    link.symlink_to(root, target_is_directory=True)
    monkeypatch.setattr(update_diagnostics, "DIAGNOSTIC_ROOT", link)
    assert update_diagnostics.record_update_failure(RuntimeError("Synthetic failure")) is None
