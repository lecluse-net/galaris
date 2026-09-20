"""The operator command must preserve verdicts, dry-run intent and safe diagnostics."""

from datetime import datetime, timezone
from io import StringIO
from unittest.mock import AsyncMock

from loguru import logger
import pytest

from core.dbadmin import __main__ as cli
from core.dbadmin.contracts import DbAdminMode, DbAdminResult, DbAdminVerdict


@pytest.mark.parametrize("verdict", list(DbAdminVerdict))
@pytest.mark.parametrize("arguments,mode,dry_run", [
    ([], None, False),
    (["synchronize", "--mode", "test", "--dry-run"], DbAdminMode.TEST, True),
])
def test_command_preserves_sync_intent_and_fatal_exit_code(monkeypatch, verdict, arguments, mode, dry_run):
    now = datetime.now(timezone.utc)
    sync = AsyncMock(return_value=DbAdminResult(
        run_id="operator-check", mode=mode or DbAdminMode.TEST, verdict=verdict,
        started_at=now, finished_at=now, scope_fingerprint="scope", target_fingerprint="target",
    ))
    monkeypatch.setattr(cli, "synchronize_database", sync)
    assert cli.main(arguments) == (1 if verdict is DbAdminVerdict.FATAL else 0)
    sync.assert_awaited_once_with(mode=mode, dry_run=dry_run)


@pytest.mark.parametrize("outcome", ["summary", "missing", "error"])
def test_status_is_read_only_and_reports_absence_or_failure_without_credentials(monkeypatch, outcome):
    sync = AsyncMock()
    monkeypatch.setattr(cli, "synchronize_database", sync)
    monkeypatch.setattr(cli.settings, "POSTGRES_PASSWORD", "private-test-password")
    lookup = AsyncMock(return_value={"verdict": "converged"} if outcome == "summary" else None)
    if outcome == "error":
        lookup.side_effect = RuntimeError("connection failed: private-test-password\x00")
    monkeypatch.setattr(cli, "latest_summary", lookup)
    output = StringIO()
    sink = logger.add(output, format="{message}")
    try:
        assert cli.main(["status", "--latest"]) == (0 if outcome == "summary" else 1)
    finally:
        logger.remove(sink)
    lookup.assert_awaited_once()
    sync.assert_not_awaited()
    assert "private-test-password" not in output.getvalue()
    assert "\x00" not in output.getvalue()
    if outcome == "summary":
        assert "converged" in output.getvalue()


def test_invalid_mode_cannot_start_synchronization(monkeypatch):
    sync = AsyncMock()
    monkeypatch.setattr(cli, "synchronize_database", sync)
    with pytest.raises(SystemExit) as raised:
        cli.main(["synchronize", "--mode", "typo"])
    assert raised.value.code == 2
    sync.assert_not_awaited()
