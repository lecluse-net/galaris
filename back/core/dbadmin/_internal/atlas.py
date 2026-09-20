"""The only runtime boundary allowed to invoke Atlas."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, quote_plus
from uuid import uuid4

from loguru import logger
from sqlalchemy import text
from sqlalchemy.engine import URL

from core import settings
from core.database import engine

from ..contracts import DbAdminFatalError
from ..scope import DbAdminDdlFilters


_SCHEMA_REFERENCE = re.compile(
    r"\b(?:CREATE|ALTER|DROP)\s+(?:TABLE|TYPE|VIEW|SCHEMA|INDEX)\s+"
    r"(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:ONLY\s+)?"
    r'(?:(?:"(?P<quoted>[A-Za-z_][A-Za-z0-9_]*)"|'
    r"(?P<plain>[A-Za-z_][A-Za-z0-9_]*))\.)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class AtlasApplyResult:
    plan: str
    changed: bool


def _atlas_database_url(schema: str) -> str:
    return URL.create(
        "postgresql",
        username=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        host=settings.POSTGRES_HOST,
        port=settings.POSTGRES_PORT,
        database=settings.POSTGRES_DB,
        query={
            "sslmode": "disable", "search_path": schema, "connect_timeout": "10",
            "options": f"-c statement_timeout={int(settings.DBADMIN_COMMAND_TIMEOUT_SECONDS * 1000)} -c lock_timeout={settings.DB_LOCK_TIMEOUT_MS}",
        },
    ).render_as_string(hide_password=False)


def _scrub(message: str) -> str:
    return _redact_credentials(message)[-8_000:]


def _redact_credentials(message: str) -> str:
    # Errors may echo a percent-encoded DSN rather than the raw password.
    scrubbed = message
    password = settings.POSTGRES_PASSWORD
    if password:
        for variant in sorted({password, quote(password, safe=""), quote_plus(password)}, key=len, reverse=True):
            scrubbed = scrubbed.replace(variant, "***")
    return re.sub(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://)[^\s/@]+@", r"\1***@", scrubbed)


def _bounded_plan(plan: str) -> str:
    scrubbed = _redact_credentials(plan)
    if len(scrubbed) <= 12_000:
        return scrubbed
    return scrubbed[:6_000] + "\n... Atlas plan truncated ...\n" + scrubbed[-6_000:]


def _validate_plan_scope(plan: str, scope: DbAdminDdlFilters) -> None:
    scope.validate()
    invalid = sorted(
        {
            match.group("quoted") or match.group("plain") or ""
            for match in _SCHEMA_REFERENCE.finditer(plan)
            if (match.group("quoted") or match.group("plain")) != "public"
        }
    )
    if invalid:
        raise DbAdminFatalError(
            "Atlas planned operations outside public: " + ", ".join(invalid)
        )


async def _run_atlas(*arguments: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "atlas",
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=os.environ.copy(),
    )
    stdout, stderr = await _communicate(process)
    rendered_stdout = stdout.decode(errors="replace")
    rendered_stderr = stderr.decode(errors="replace")
    if process.returncode != 0:
        details = _scrub(rendered_stderr or rendered_stdout)
        raise DbAdminFatalError(f"Atlas failed with exit code {process.returncode}: {details}")
    return rendered_stdout


async def _communicate(process: asyncio.subprocess.Process) -> tuple[bytes, bytes]:
    try:
        async with asyncio.timeout(settings.DBADMIN_COMMAND_TIMEOUT_SECONDS):
            return await process.communicate()
    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()


async def _materialize_target(target_path: Path, dev_schema: str) -> None:
    env = os.environ.copy()
    env["PGPASSWORD"] = settings.POSTGRES_PASSWORD
    env["PGCONNECT_TIMEOUT"] = "10"
    env["PGOPTIONS"] = (
        f"-c search_path={dev_schema},public "
        f"-c statement_timeout={int(settings.DBADMIN_COMMAND_TIMEOUT_SECONDS * 1000)} "
        f"-c lock_timeout={settings.DB_LOCK_TIMEOUT_MS}"
    )
    process = await asyncio.create_subprocess_exec(
        "psql",
        "--host",
        settings.POSTGRES_HOST,
        "--port",
        str(settings.POSTGRES_PORT),
        "--username",
        settings.POSTGRES_USER,
        "--dbname",
        settings.POSTGRES_DB,
        "--set",
        "ON_ERROR_STOP=1",
        "--quiet",
        "--file",
        str(target_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await _communicate(process)
    if process.returncode != 0:
        details = _scrub(
            stderr.decode(errors="replace") or stdout.decode(errors="replace")
        )
        raise DbAdminFatalError(
            f"Could not materialize Atlas target (exit {process.returncode}): {details}"
        )


async def apply_target(
    target_sql: str,
    *,
    scope: DbAdminDdlFilters,
    dry_run: bool = False,
    preserve_data: bool = False,
) -> AtlasApplyResult:
    """Plan, validate, and optionally apply one public-schema target."""

    scope.validate()
    dev_schema = f"dbadmin_dev_{uuid4().hex}"
    target_path: Path | None = None
    try:
        async with engine.begin() as connection:
            await connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            # UUID generated here, never a user-supplied SQL identifier.
            await connection.execute(text(f'CREATE SCHEMA "{dev_schema}"'))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".sql", prefix="dbadmin-target-", delete=False
        ) as target_file:
            target_file.write(target_sql)
            target_path = Path(target_file.name)

        await _materialize_target(target_path, dev_schema)

        common_arguments = (
            "schema",
            "apply",
            "--url",
            _atlas_database_url("public"),
            "--to",
            _atlas_database_url(dev_schema),
            "--lock-timeout",
            "60s",
        )
        if preserve_data:
            common_arguments += (
                "--config", Path(__file__).with_name("expand.hcl").as_uri(),
                "--env", "expand",
            )
        plan = await _run_atlas(*common_arguments, "--dry-run")
        _validate_plan_scope(plan, scope)
        changed = "no changes to be made" not in plan.lower()
        if changed:
            logger.info("Atlas public-schema plan contains changes")
            if dry_run:
                logger.info("Atlas dry-run plan:\n{}", _bounded_plan(plan))
            else:
                logger.debug("Atlas public-schema plan:\n{}", _bounded_plan(plan))
        else:
            logger.info("Atlas public schema is already converged")
        if not dry_run and changed:
            await _run_atlas(*common_arguments, "--auto-approve")
        return AtlasApplyResult(plan=plan, changed=changed)
    finally:
        if target_path is not None:
            target_path.unlink(missing_ok=True)
        try:
            async with engine.begin() as connection:
                # Same locally generated UUID as the CREATE above.
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{dev_schema}" CASCADE'))  # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
        except Exception as exc:
            logger.error(
                "Could not remove Atlas development schema {}: {}",
                dev_schema,
                _scrub(str(exc)),
            )
