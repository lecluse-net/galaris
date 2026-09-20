"""Exercise the real daemon module without changing any system account."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import patch


spec = importlib.util.spec_from_file_location("executord", Path(__file__).parents[1] / "executord.py")
daemon = importlib.util.module_from_spec(spec)
spec.loader.exec_module(daemon)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        for name, value in {"STATE_ROOT": root, "REGISTRY_PATH": root / "users.json"}.items():
            self.enterContext(patch.object(daemon, name, value))
        self.enterContext(patch.object(daemon, "_account_exists", return_value=False))
        self.enterContext(patch.object(daemon, "_group_exists", return_value=False))
        self.account = self.enterContext(patch.object(daemon, "_ensure_account"))
        self.key = self.enterContext(patch.object(daemon, "_write_authorized_key"))

    def create(self, number):
        return daemon.ensure_user({"agent_id": number, "agent_code": f"agent_{number}", "public_key": "ssh-ed25519 canary"})

    def test_parallel_creations_keep_every_entry_and_unique_uids(self):
        self.account.side_effect = lambda *args: time.sleep(0.003)
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(self.create, range(24)))
        registry = daemon._load_registry()
        self.assertEqual(len(registry["users"]), 24)
        self.assertEqual(len({item["uid"] for item in results}), 24)
        self.assertEqual(registry["next_uid"], daemon.UID_START + 24)

    def test_failed_account_creation_keeps_intent_and_retry_uses_same_uid(self):
        self.account.side_effect = OSError("interrupted")
        with self.assertRaises(OSError):
            self.create(1)
        self.assertEqual(daemon._load_registry()["users"]["agent_1"]["uid"], daemon.UID_START)
        self.account.side_effect = None
        self.assertEqual(self.create(1)["uid"], daemon.UID_START)
        self.assertEqual(daemon._load_registry()["next_uid"], daemon.UID_START + 1)

    def test_registry_replace_failure_preserves_previous_contents(self):
        self.create(1)
        previous = daemon.REGISTRY_PATH.read_bytes()
        with patch.object(Path, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.create(2)
        self.assertEqual(daemon.REGISTRY_PATH.read_bytes(), previous)
        self.assertEqual(list(daemon.STATE_ROOT.glob(".users-*")), [])

    def test_key_rotation_is_recoverable_after_interrupted_effect(self):
        self.create(1)
        self.key.side_effect = OSError("interrupted")
        with self.assertRaises(OSError):
            daemon.rotate_key({"agent_id": 1, "public_key": "ssh-ed25519 replacement"})
        self.key.side_effect = None
        with patch.object(daemon, "_ensure_host_key"), patch.object(daemon, "HOME_ROOT", daemon.STATE_ROOT / "homes"), patch.object(daemon, "AUTHORIZED_KEYS", daemon.STATE_ROOT / "keys"):
            daemon.reconcile()
        self.key.assert_called_with("agent_1", "ssh-ed25519 replacement", True)

    def test_existing_system_accounts_cannot_be_adopted(self):
        with patch.object(daemon, "_account_exists", return_value=True):
            with self.assertRaisesRegex(ValueError, "cannot be adopted"):
                self.create(1)
        self.account.assert_not_called()

    def test_session_stop_uses_owner_rights_even_with_a_forged_pid(self):
        self.create(1)
        run_id = str(uuid4())
        home_root = daemon.STATE_ROOT / "homes"
        receipt = home_root / "agent_1" / ".galaris" / "sessions" / run_id / "metadata.json"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({"run_id": run_id, "pid": os.getpid(), "state": "running"}))
        with patch.object(daemon, "HOME_ROOT", home_root), patch.object(daemon.os, "killpg") as root_signal, patch.object(daemon, "_run", return_value=SimpleNamespace(stdout='{"status":"outcome_unknown"}')) as execute:
            result = daemon.stop_session({"run_id": run_id})
        root_signal.assert_not_called()
        execute.assert_called_once_with("runuser", "-u", "agent_1", "--", "/usr/local/bin/galaris-exec", "stop", "--run-id", run_id)
        self.assertFalse(result["stopped"])
        self.assertEqual(result["status"], "outcome_unknown")


@unittest.skipUnless(os.geteuid() == 0, "Real UID boundary requires the isolated root test container")
class SocketTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        root.chmod(0o755)
        self.enterContext(patch.object(daemon, "CONTROL_SOCKET", root / "run" / "control.sock"))
        daemon.prepare_control_directory()
        self.enterContext(patch.dict(daemon.OPERATIONS, {"health": lambda payload: {"canary": True}}))
        self.server = await asyncio.start_unix_server(daemon._handle, path=daemon.CONTROL_SOCKET)
        os.chown(daemon.CONTROL_SOCKET, 0, daemon.CONTROL_GID)
        daemon.CONTROL_SOCKET.chmod(0o660)

    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()

    async def request_as(self, uid, groups):
        # The child connects only after dropping privileges. No production volume is mounted.
        program = """
import json, os, socket, sys
os.setgroups(json.loads(sys.argv[3])); os.setgid(int(sys.argv[2])); os.setuid(int(sys.argv[2]))
s = socket.socket(socket.AF_UNIX); s.settimeout(3)
try:
    s.connect(sys.argv[1]); s.sendall(b'{"operation":"health","payload":{}}\\n')
    print(s.recv(4096).decode())
except OSError:
    print('{"ok":false}')
finally:
    s.close()
"""
        child = await asyncio.create_subprocess_exec(sys.executable, "-c", program, str(daemon.CONTROL_SOCKET), str(uid), json.dumps(groups), stdout=asyncio.subprocess.PIPE)
        stdout, _ = await asyncio.wait_for(child.communicate(), timeout=5)
        self.assertEqual(child.returncode, 0)
        return json.loads(stdout)

    async def test_backend_supplementary_group_retains_access(self):
        self.assertTrue((await self.request_as(1000, [daemon.CONTROL_GID]))["ok"])

    async def test_agent_and_nobody_are_denied_by_filesystem(self):
        for uid in (daemon.UID_START, 65534):
            self.assertFalse((await self.request_as(uid, []))["ok"])

    async def test_peer_check_rejects_an_agent_even_with_management_group(self):
        self.assertFalse((await self.request_as(daemon.UID_START, [daemon.CONTROL_GID]))["ok"])

    async def test_control_directory_and_socket_cannot_be_replaced_by_agents(self):
        self.assertEqual(daemon.CONTROL_SOCKET.parent.stat().st_mode & 0o777, 0o770)
        self.assertEqual(daemon.CONTROL_SOCKET.stat().st_mode & 0o777, 0o660)
        self.assertEqual(daemon.CONTROL_SOCKET.parent.stat().st_uid, 0)
        self.assertEqual(daemon.CONTROL_SOCKET.parent.stat().st_gid, daemon.CONTROL_GID)


if __name__ == "__main__":
    unittest.main()
