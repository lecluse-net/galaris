"""Run inside the disposable code-executor image with namespace capabilities."""

import asyncio
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

import runtime


class SandboxTests(unittest.TestCase):
    def test_real_mounts_preserve_agent_writes_and_confine_both_editor_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            home = base / "home" / "developer"
            repository = home / "project"
            other = home / "private-project"
            repository.mkdir(parents=True)
            other.mkdir()
            (other / "private.txt").write_text("synthetic unrelated file")
            source = repository / "source.txt"
            source.write_text("agent version")
            for path in (home, repository, source):
                os.chown(path, 20000, 20000)
            for editable in (False, True):
                with self.subTest(editable=editable):
                    profile = base / ("edit" if editable else "read") / "profile"
                    command, descriptors = runtime.sandbox_command(
                        home, repository, [], profile, 20000, 20000, editable,
                    )
                    script = profile / "probe.py"
                    script.write_text(
                        "import os, pathlib, socket\n"
                        "assert os.getuid() == 20000\n"
                        f"source = pathlib.Path({str(source)!r})\n"
                        "assert source.read_text() == 'agent version'\n"
                        f"assert not pathlib.Path({str(other)!r}).exists()\n"
                        "assert not pathlib.Path('/run/galaris-code/token').exists()\n"
                        f"editable = {editable!r}\n"
                        "try:\n"
                        "    source.write_text('human version')\n"
                        "except OSError:\n"
                        "    assert not editable\n"
                        "else:\n"
                        "    assert editable\n"
                        "pathlib.Path('/profile/unsaved.txt').write_text('draft')\n"
                        "print('sandbox-ok')\n"
                    )
                    command = command[:command.index("/usr/bin/code-server")] + ["/usr/bin/python3", "/profile/probe.py"]
                    try:
                        result = subprocess.run(command, pass_fds=descriptors, capture_output=True, text=True, timeout=15)
                    finally:
                        for descriptor in descriptors:
                            os.close(descriptor)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), "sandbox-ok")
                    self.assertEqual(source.read_text(), "human version" if editable else "agent version")
                    # The agent retains its filesystem write access while consultation is confined.
                    source.write_text("agent version")


class EditorTests(unittest.IsolatedAsyncioTestCase):
    async def test_broker_reuses_profiles_refuses_eviction_and_discards_only_explicitly(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            home = base / "homes" / "developer"
            repository = home / "project"
            repository.mkdir(parents=True)
            source = repository / "source.txt"
            source.write_text("synthetic source")
            for path in (home, repository, source):
                os.chown(path, 20000, 20000)
            token = base / "token"
            token.write_text("synthetic-private-broker-token-0001")
            state = base / "state"
            with patch.object(runtime, "HOME_ROOT", home.parent), patch.object(runtime, "STATE_ROOT", state), \
                 patch.object(runtime, "TOKEN_PATH", token), patch.object(runtime, "MAX_USER_SESSIONS", 1), \
                 patch.object(runtime, "MAX_RETAINED_PROFILES", 2), \
                 patch.object(runtime, "editors", {}):
                app = web.Application(middlewares=[runtime.authenticate])
                app.cleanup_ctx.append(runtime.lifetime)
                app.router.add_post("/sessions", runtime.open_editor)
                app.router.add_delete("/sessions/{session}", runtime.close_editor)
                app.router.add_post("/sessions/{session}/navigate", runtime.navigate)
                identifier = str(uuid4())
                payload = {"session": identifier, "home": str(home), "root": str(repository), "git_paths": [],
                    "root_identity": f"{repository.stat().st_dev}:{repository.stat().st_ino}", "git_identities": [], "mode": "edit"}
                async with TestClient(TestServer(app), headers={"Authorization": "Bearer " + token.read_text()}) as client:
                    response = await client.post("/sessions", json=payload)
                    self.assertEqual(response.status, 200, await response.text())
                    process = runtime.editors[identifier].process
                    profile = state / "sessions" / identifier / "profile"
                    self.assertFalse((profile / "navigation.json").exists())
                    (profile / "synthetic-draft").write_text("unsaved synthetic content")
                    from profiles import archive_profile
                    with self.assertRaisesRegex(RuntimeError, "still uses retained profiles"):
                        archive_profile(state, identifier, base / "live-profile.tar.gz", retire=True)
                    self.assertTrue((profile / "synthetic-draft").exists())
                    self.assertEqual((await client.post("/sessions", json=payload)).status, 200)
                    self.assertIs(runtime.editors[identifier].process, process)
                    self.assertEqual((await client.post("/sessions", json={**payload, "mode": "read"})).status, 409)
                    self.assertEqual((await client.post("/sessions", json={**payload, "session": str(uuid4())})).status, 429)
                    await client.delete("/sessions/" + identifier)
                    self.assertTrue((profile / "synthetic-draft").exists())
                    self.assertIsNotNone(process.returncode)
                    # Stopped profiles do not consume this Unix account's active quota.
                    second = str(uuid4())
                    self.assertEqual((await client.post("/sessions", json={**payload, "session": second})).status, 200)
                    await client.delete("/sessions/" + second)
                    self.assertEqual((await client.post("/sessions", json={**payload, "session": str(uuid4())})).status, 429)
                    # Resuming a retained profile preserves buffers and drops old display requests.
                    runtime.write_navigation(profile, 20000, 20000, {"view": "changes"})
                    self.assertEqual((await client.post("/sessions", json=payload)).status, 200)
                    self.assertFalse((profile / "navigation.json").exists())
                    self.assertEqual((profile / "synthetic-draft").read_text(), "unsaved synthetic content")
                    marker = base / "synthetic-upgrade"
                    marker.touch()
                    with patch.object(runtime, "UPGRADE_LOCK_PATH", str(marker)):
                        self.assertEqual((await client.post("/sessions", json=payload)).status, 503)
                        self.assertEqual((await client.post("/sessions", json={**payload, "session": str(uuid4())})).status, 503)
                    self.assertEqual((profile / "synthetic-draft").read_text(), "unsaved synthetic content")
                    await client.delete("/sessions/" + identifier + "?discard=true")
                    self.assertFalse(profile.exists())
                    self.assertEqual(source.read_text(), "synthetic source")

    async def test_diagnostics_remain_bounded_and_navigation_cannot_overwrite_a_symlink_target(self):
        import io
        stream = asyncio.StreamReader()
        stream.feed_data(b"x" * (3 * 1024 * 1024) + b"synthetic final diagnostic")
        stream.feed_eof()
        output = io.BytesIO()
        await runtime.bounded_log(stream, output)
        self.assertLessEqual(len(output.getvalue()), 1024 * 1024)
        self.assertTrue(output.getvalue().endswith(b"synthetic final diagnostic"))
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            profile = base / "profile"
            profile.mkdir()
            protected = base / "synthetic-protected-file"
            protected.write_text("must remain unchanged")
            (profile / "navigation.json").symlink_to(protected)
            runtime.write_navigation(profile, 20000, 20000, {"view": "changes"})
            self.assertEqual(protected.read_text(), "must remain unchanged")
            self.assertFalse((profile / "navigation.json").is_symlink())
            false_profile = base / "false-profile"
            false_profile.symlink_to(profile, target_is_directory=True)
            with self.assertRaises(OSError):
                runtime.write_navigation(false_profile, 20000, 20000, {"view": "files"})

    async def test_real_code_server_starts_on_the_same_repository_and_closes(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            home = base / "home" / "developer"
            repository = home / "project"
            repository.mkdir(parents=True)
            for path in (home, repository):
                os.chown(path, 20000, 20000)
            profile = base / "session" / "profile"
            command, descriptors = runtime.sandbox_command(home, repository, [], profile, 20000, 20000, True)
            try:
                process = await asyncio.create_subprocess_exec(
                    *command, pass_fds=descriptors, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT, start_new_session=True,
                )
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)
            try:
                async with asyncio.timeout(40):
                    while not (profile / "editor.sock").exists():
                        if process.returncode is not None:
                            self.fail((await process.stdout.read()).decode())
                        await asyncio.sleep(0.1)
                from aiohttp import ClientSession, UnixConnector
                async with ClientSession(connector=UnixConnector(path=str(profile / "editor.sock"))) as client:
                    async with client.get("http://localhost/healthz") as response:
                        self.assertEqual(response.status, 200)
                    async with client.get("http://localhost/") as response:
                        self.assertEqual(response.status, 200)
                        self.assertIn("workbench", await response.text())
            finally:
                if process.returncode is None:
                    os.killpg(process.pid, 15)
                    await process.wait()


if __name__ == "__main__":
    unittest.main()
