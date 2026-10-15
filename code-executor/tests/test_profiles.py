"""Synthetic profile recovery and refusal of destructive or concurrent maintenance."""

import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from uuid import uuid4

from profiles import archive_profile, retained_profiles, restore_profile, state_lock


class ProfileTests(unittest.TestCase):
    def test_archive_retire_and_restore_preserve_drafts_and_leave_the_repository_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "state"
            identifier = str(uuid4())
            session = root / "sessions" / identifier
            profile = session / "profile"
            profile.mkdir(parents=True)
            (profile / "unsaved.txt").write_text("synthetic unsaved draft")
            (session / "manifest.json").write_text(json.dumps({"session": identifier, "uid": 20000, "mode": "edit"}))
            repository = base / "repository"
            repository.mkdir()
            (repository / "source.txt").write_text("synthetic committed source")
            archive = base / "backup.tar.gz"
            with state_lock(root):
                self.assertEqual(retained_profiles(root)[0]["session"], identifier)
                archive_profile(root, identifier, archive)
                self.assertTrue(profile.exists())
                # A failed backup must never remove the retained state.
                with self.assertRaises(FileExistsError):
                    archive_profile(root, identifier, archive, retire=True)
                self.assertEqual((profile / "unsaved.txt").read_text(), "synthetic unsaved draft")
                archive_profile(root, identifier, base / "retired.tar.gz", retire=True)
                self.assertFalse(session.exists())
                self.assertEqual(restore_profile(root, archive), identifier)
                self.assertEqual((profile / "unsaved.txt").read_text(), "synthetic unsaved draft")
                self.assertEqual(profile.stat().st_uid, 20000)
                with self.assertRaises(ValueError):
                    restore_profile(root, archive)
            self.assertEqual((repository / "source.txt").read_text(), "synthetic committed source")
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_live_runtime_and_unsafe_archives_cannot_be_used_for_maintenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "state"
            with state_lock(root):
                with self.assertRaisesRegex(RuntimeError, "Stop the editor runtime"):
                    with state_lock(root):
                        self.fail("Concurrent maintenance acquired the live broker lock")
            identifier = str(uuid4())
            archive = Path(temporary) / "unsafe.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo(identifier + "/../../protected")
                member.size = 4
                output.addfile(member, io.BytesIO(b"evil"))
            with self.assertRaises((ValueError, tarfile.TarError)):
                restore_profile(root, archive)
            self.assertFalse((Path(temporary) / "protected").exists())
