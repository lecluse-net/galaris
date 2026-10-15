"""Actual Git/SSH on the shared mounts; no production repository or credentials."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

import runtime


def command(arguments, **kwargs):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=30, **kwargs)
    if result.returncode:
        raise AssertionError(f"Synthetic command failed ({result.returncode}): {result.stdout}\n{result.stderr}")
    return result


def owned(path: Path):
    for directory, children, files in os.walk(path):
        os.chown(directory, 20000, 20000)
        for name in children + files:
            os.chown(Path(directory) / name, 20000, 20000)


def sandbox(home, repository, profile, script, *, editable=True, git_paths=None):
    arguments, descriptors = runtime.sandbox_command(home, repository, git_paths or [], profile, 20000, 20000, editable)
    arguments = arguments[:arguments.index("/usr/bin/code-server")] + ["/bin/bash", "-euc", script]
    try:
        return command(arguments, pass_fds=descriptors)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


class GitTests(unittest.TestCase):
    def test_read_only_git_and_worktree_metadata_while_agent_can_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            home = base / "developer"
            repository = home / "project"
            repository.mkdir(parents=True)
            source = repository / "source.txt"
            source.write_text("first\n")
            command(["git", "init", "-b", "main", str(repository)])
            command(["git", "-C", str(repository), "config", "user.name", "Synthetic developer"])
            command(["git", "-C", str(repository), "config", "user.email", "developer@example.test"])
            command(["git", "-C", str(repository), "add", "."])
            command(["git", "-C", str(repository), "commit", "-m", "Synthetic initial commit"])
            worktree = home / "worktrees" / "review"
            command(["git", "-C", str(repository), "worktree", "add", "-b", "review", str(worktree)])
            owned(home)
            home.chmod(0o700)
            result = sandbox(home, worktree, base / "read" / "profile", """
                test "$(git branch --show-current)" = review
                ! git checkout -b forbidden
                ! git add source.txt
                ! printf forbidden >> source.txt
                /usr/bin/python3 -c "assert 'CapEff:\\t0000000000000000' in open('/proc/self/status').read()"
                ! test -e /run/galaris-code/token
            """, editable=False, git_paths=[repository / ".git", repository / ".git/worktrees/review"])
            self.assertEqual(result.returncode, 0)
            source = worktree / "source.txt"
            source.write_text("agent changes remain possible\n")
            result = sandbox(home, worktree, base / "edit" / "profile", """
                grep -q 'agent changes remain possible' source.txt
                printf 'human changes\n' >> source.txt
                git add source.txt
                git commit -m 'Synthetic human worktree commit'
            """, git_paths=[repository / ".git", repository / ".git/worktrees/review"])
            self.assertEqual(result.returncode, 0)
            self.assertIn("human changes", source.read_text())
            self.assertEqual(command(["git", "-c", f"safe.directory={repository}", "-C", str(repository), "log", "review", "-1", "--format=%an <%ae>"]).stdout.strip(),
                             "Synthetic developer <developer@example.test>")

    @unittest.skipUnless(shutil.which("sshd"), "Use the qualification image for the SSH forge scenario")
    def test_shared_identity_keys_and_full_git_roundtrip_over_ssh(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            base.chmod(0o755)
            home = base / "developer"
            repository = home / "project"
            repository.mkdir(parents=True)
            ssh = home / ".ssh"
            ssh.mkdir(mode=0o700)
            forge = base / "forge"
            forge.mkdir()
            command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(ssh / "id_ed25519")])
            command(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(forge / "host")])
            (forge / "authorized_keys").write_text((ssh / "id_ed25519.pub").read_text())
            (ssh / "known_hosts").write_text("[127.0.0.1]:2222 " + (forge / "host.pub").read_text())
            (ssh / "config").write_text(f"Host synthetic-forge\n HostName 127.0.0.1\n Port 2222\n User developer\n IdentityFile {ssh / 'id_ed25519'}\n UserKnownHostsFile {ssh / 'known_hosts'}\n BatchMode yes\n StrictHostKeyChecking yes\n")
            (home / ".gitconfig").write_text("[user]\n name = Synthetic shared identity\n email = shared@example.test\n")
            remote = home / "remote.git"
            command(["git", "init", "--bare", str(remote)])
            owned(home)
            home.chmod(0o700)
            Path("/run/sshd").mkdir(exist_ok=True)
            config = forge / "sshd_config"
            config.write_text(f"ListenAddress 127.0.0.1\nPort 2222\nHostKey {forge / 'host'}\nPidFile {forge / 'pid'}\nAuthorizedKeysFile {forge / 'authorized_keys'}\nPasswordAuthentication no\nKbdInteractiveAuthentication no\nUsePAM no\nStrictModes no\nAllowUsers developer\nAllowTcpForwarding no\n")
            server = subprocess.Popen(["/usr/sbin/sshd", "-D", "-e", "-f", str(config)], stderr=subprocess.PIPE)
            try:
                time.sleep(0.2)
                script = f"""
                    git init -b main
                    printf 'base\n' > source.txt
                    git add .
                    git commit -m 'Synthetic initial'
                    git remote add origin synthetic-forge:{remote}
                    git push -u origin main
                    git switch -c review
                    printf 'human\n' >> source.txt
                    git add source.txt
                    git commit -m 'Synthetic review'
                    git push -u origin review
                    git clone --branch review synthetic-forge:{remote} /tmp/peer
                    git -C /tmp/peer config user.name 'Synthetic peer'
                    git -C /tmp/peer config user.email peer@example.test
                    printf 'peer\n' > /tmp/peer/peer.txt
                    git -C /tmp/peer add .
                    git -C /tmp/peer commit -m 'Synthetic peer'
                    git -C /tmp/peer push
                    git fetch origin
                    git pull --ff-only
                    test -f peer.txt
                    printf 'local conflict\n' > source.txt
                    git add .
                    git commit -m 'Synthetic local conflict'
                    printf 'remote conflict\n' > /tmp/peer/source.txt
                    git -C /tmp/peer add .
                    git -C /tmp/peer commit -m 'Synthetic remote conflict'
                    git -C /tmp/peer push
                    git fetch origin
                    if git rebase origin/review; then exit 42; fi
                    test -d .git/rebase-merge
                    printf 'resolved by human\n' > source.txt
                    git add source.txt
                    GIT_EDITOR=true git rebase --continue
                    git push
                    test "$(git log -1 --format='%an <%ae>')" = 'Synthetic shared identity <shared@example.test>'
                    ! touch {ssh}/new-key
                """
                result = sandbox(home, repository, base / "edit" / "profile", script)
                self.assertEqual(result.returncode, 0)
                self.assertEqual((repository / "source.txt").read_text(), "resolved by human\n")
            finally:
                server.terminate()
                server.wait(timeout=5)
                server.stderr.close()


if __name__ == "__main__":
    unittest.main()
