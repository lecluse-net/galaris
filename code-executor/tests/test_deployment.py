"""The deployed controller preserves credentials, profiles and loopback isolation."""

import json
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout, redirect_stderr

import deploy


class DeploymentTests(unittest.TestCase):
    def test_docker_failures_do_not_expose_subprocess_output(self):
        for arguments, reason in [
            (("info",), "docker_access"),
            (("compose", "version"), "compose_unavailable"),
            (("exec", "synthetic-runtime", "bwrap"), "user_namespaces"),
            (("compose", "up"), "docker_command_failed"),
        ]:
            result = subprocess.CompletedProcess(arguments, 1, "Synthetic private output", "Synthetic private credential")
            def run(*args, **kwargs):
                kwargs["stderr"].write(b"Couldn't find PID field in ps output; token=synthetic-private-credential")
                return result
            with self.subTest(reason=reason), patch.object(deploy.subprocess, "run", side_effect=run):
                with self.assertRaises(RuntimeError) as failure:
                    deploy.docker(*arguments)
                self.assertEqual(deploy.FAILURE_REASONS[str(failure.exception)], reason)
                self.assertNotIn("Synthetic private", str(failure.exception))
                self.assertEqual(failure.exception.details["exit_code"], 1)
                self.assertIn("Couldn't find PID field", failure.exception.details["stderr"])
                self.assertNotIn("synthetic-private-credential", failure.exception.details["stderr"])
                self.assertIn("docker " + arguments[0], failure.exception.details["command"])

    def test_cli_reports_only_recognized_failure_reasons(self):
        for message, reason in [
            ("End existing editor sessions before updating the editor", "sessions_active"),
            ("Docker daemon access failed", "docker_access"),
            ("Synthetic private credential and remote output", "unknown"),
        ]:
            with self.subTest(reason=reason), patch.object(deploy, "main", side_effect=RuntimeError(message)):
                stdout, stderr = io.StringIO(), io.StringIO()
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(deploy.run(), 1)
                report = json.loads(stdout.getvalue())
                self.assertEqual(report["error"], reason)
                self.assertEqual(report["diagnostic"][0]["type"], "RuntimeError")
                self.assertTrue(report["diagnostic"][0]["locations"])
                self.assertNotIn(message, stderr.getvalue())

    def test_unexpected_failures_and_cleanup_failures_keep_both_causes(self):
        def main():
            try:
                raise deploy.DockerCommandError("Docker access, Compose or the code-server build failed",
                    ("top", "synthetic-runtime", "-eo", "comm"), 1,
                    stderr="Couldn't find PID field in ps output; password='synthetic secret'")
            except RuntimeError:
                raise TypeError("Synthetic cleanup failed; token=synthetic-token")
        with patch.object(deploy, "main", side_effect=main):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                self.assertEqual(deploy.run(), 1)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["error"], "unknown")
        self.assertEqual([item["type"] for item in report["diagnostic"]], ["TypeError", "DockerCommandError"])
        self.assertIn("Couldn't find PID field", stdout.getvalue())
        self.assertNotIn("synthetic secret", stdout.getvalue())
        self.assertNotIn("synthetic-token", stdout.getvalue())

    def test_deployment_and_retry_reuse_the_private_service_and_do_not_mount_sibling_homes(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "developer"
            bundle = home / ".galaris/code-editor/bundle-synthetic"
            bundle.mkdir(parents=True)
            (bundle / "Dockerfile").write_text("Synthetic packaged runtime")
            os.chown(home, 20000, 20000)
            root = bundle.parent
            records = []
            exists = False
            labels = {}
            active_editor = False
            paused = False
            fail_verification = False

            def docker(*arguments, **kwargs):
                nonlocal exists, labels, paused
                records.append(arguments)
                if arguments[0] == "ps":
                    return "synthetic-container" if exists else ""
                if arguments[0] == "inspect":
                    return json.dumps([{"Image": "sha256:synthetic-retained-image", "Config": {"Labels": labels}, "State": {"Running": True, "Paused": paused},
                        "NetworkSettings": {"Ports": {"8766/tcp": [{"HostIp": "127.0.0.1", "HostPort": "32123"}]}}}])
                if arguments[0] == "top":
                    self.assertTrue(paused)
                    # Docker needs PID to filter the host ps result to this container.
                    # Real Docker rejects '-eo comm' with "Couldn't find PID field".
                    if arguments[2:] != ("-eo", "pid,comm"):
                        raise RuntimeError("Docker access, Compose or the code-server build failed")
                    return "PID COMMAND\n101 tini\n102 python3\n" + ("103 node\n" if active_editor else "")
                if arguments[0] in ("pause", "unpause"):
                    paused = arguments[0] == "pause"
                if arguments[0] == "exec" and fail_verification:
                    raise RuntimeError("Synthetic namespace failure")
                if arguments[:2] == ("compose", "-p"):
                    specification = json.loads((bundle / "compose.json").read_text())
                    runtime = specification["services"]["runtime"]
                    labels = runtime["labels"]
                    self.assertIn(f"{home}:{home}", runtime["volumes"])
                    self.assertNotIn(f"{home.parent}:{home.parent}", runtime["volumes"])
                    self.assertEqual(runtime["ports"], [{"target": 8766, "host_ip": "127.0.0.1", **({"published": 32123} if exists else {})}])
                    self.assertFalse(any("docker.sock" in mount for mount in runtime["volumes"]))
                    paused = False
                    exists = True
                return ""

            with patch.object(deploy.os, "getuid", return_value=20000), patch.object(deploy.os, "getgid", return_value=20000), \
                 patch.object(deploy, "docker", side_effect=docker), patch.object(deploy, "probe", return_value={"ready": True}):
                first = deploy.deploy(bundle, home)
                token = (root / "credential").read_text()
                second = deploy.deploy(bundle, home)
                self.assertFalse(first["already_installed"])
                self.assertTrue(second["already_installed"])
                self.assertEqual((root / "credential").read_text(), token)
                self.assertNotIn(token, json.dumps(first))
                self.assertEqual((root / "credential").stat().st_mode & 0o777, 0o600)
                self.assertEqual(sum(call[:2] == ("compose", "-p") for call in records), 1)
                active_editor = True
                self.assertFalse(deploy.deploy(bundle, home, check_only=True, require_existing=True)["update_required"])
                self.assertTrue(deploy.deploy(bundle, home, upgrade=True, require_existing=True)["already_installed"])
                self.assertFalse(paused)
                self.assertEqual(sum(call[:2] == ("compose", "-p") for call in records), 1)
                (bundle / "Dockerfile").write_text("A changed runtime")
                self.assertTrue(deploy.deploy(bundle, home, check_only=True, require_existing=True)["update_required"])
                with self.assertRaisesRegex(RuntimeError, "preserve its sessions"):
                    deploy.deploy(bundle, home)
                active_editor = True
                with self.assertRaisesRegex(RuntimeError, "End existing editor sessions"):
                    deploy.deploy(bundle, home, upgrade=True)
                self.assertFalse(paused)
                self.assertFalse((root / "upgrade-in-progress").exists())
                self.assertEqual(sum(call[:2] == ("compose", "-p") for call in records), 1)
                active_editor = False
                updated = deploy.deploy(bundle, home, upgrade=True)
                self.assertFalse(updated["already_installed"])
                self.assertEqual(updated["port"], first["port"])
                self.assertEqual((root / "credential").read_text(), token)
                self.assertTrue(deploy.deploy(bundle, home)["already_installed"])
                (root / "upgrade-in-progress").touch()
                paused = True
                self.assertTrue(deploy.deploy(bundle, home, upgrade=True)["already_installed"])
                self.assertFalse(paused)
                self.assertFalse((root / "upgrade-in-progress").exists())
                retained_labels = dict(labels)
                (bundle / "Dockerfile").write_text("Synthetic failed upgrade")
                fail_verification = True
                with self.assertRaisesRegex(RuntimeError, "Synthetic namespace failure"):
                    deploy.deploy(bundle, home, upgrade=True)
                self.assertEqual(labels, retained_labels)
                self.assertFalse(paused)
                self.assertFalse((root / "upgrade-in-progress").exists())
                self.assertEqual(json.loads((bundle / "compose.json").read_text())["services"]["runtime"]["image"], "sha256:synthetic-retained-image")
                self.assertEqual((root / "credential").read_text(), token)

    def test_credential_symlinks_are_refused_without_reading_the_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            outside = root / "synthetic-other-file"
            outside.write_text("Synthetic unrelated content")
            (root / "credential").symlink_to(outside)
            with self.assertRaises(OSError):
                deploy.credential(root)
            self.assertEqual(outside.read_text(), "Synthetic unrelated content")

    def test_automatic_maintenance_never_installs_an_unmanaged_editor(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary) / "developer"
            bundle = home / ".galaris/code-editor/bundle-synthetic"
            bundle.mkdir(parents=True)
            os.chown(home, 20000, 20000)
            with patch.object(deploy.os, "getuid", return_value=20000), patch.object(deploy.os, "getgid", return_value=20000), \
                 patch.object(deploy, "docker", return_value="") as docker:
                with self.assertRaisesRegex(RuntimeError, "existing managed editor credential"):
                    deploy.deploy(bundle, home, upgrade=True, require_existing=True)
                self.assertFalse(deploy.deploy(bundle, home, check_only=True)["managed"])
                self.assertFalse((bundle.parent / "credential").exists())
                deploy.credential(bundle.parent)
                with self.assertRaisesRegex(RuntimeError, "existing managed editor$"):
                    deploy.deploy(bundle, home, upgrade=True, require_existing=True)
                self.assertFalse(any(call.args[:1] == ("compose",) and len(call.args) > 1 and call.args[1] == "-p"
                                     for call in docker.call_args_list))
