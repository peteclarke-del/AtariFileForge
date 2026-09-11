from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path

from app.disk_service import DiskError, DiskService, ImageSession


class CheckpointTests(unittest.TestCase):
    def make_session(
        self, root: Path, *, partitioned: bool = False
    ) -> tuple[DiskService, ImageSession]:
        folder = root / ("a" * 32)
        folder.mkdir()
        image = folder / ("drive.img" if partitioned else "games.st")
        image.write_bytes(b"original image")
        service = DiskService(root)
        session = ImageSession(
            "a" * 32,
            image.name,
            "hd" if partitioned else "gemdos",
            image,
            partition=0 if partitioned else None,
        )
        return service, session

    def test_named_checkpoint_restores_image_and_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory), partitioned=True)
            checkpoint = service.create_checkpoint(session, "Known good")

            session.path.write_bytes(b"changed image")
            session.name = "changed.img"
            # Which partition is open is session state, not image bytes, so a
            # restore has to put the drive back on the volume it was showing.
            session.partition = 2
            session.dirty = True
            session.warnings = ["changed"]
            restored = service.restore_checkpoint(session, checkpoint["id"])

            self.assertEqual(restored["name"], "Known good")
            self.assertEqual(session.path.read_bytes(), b"original image")
            self.assertEqual(session.name, "drive.img")
            self.assertEqual(session.partition, 0)
            self.assertFalse(session.dirty)
            self.assertEqual(session.warnings, [])

    def test_oldest_snapshot_exposes_the_validated_primary_image_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory), partitioned=True)
            oldest = service.create_checkpoint(session, "Workflow base")
            session.path.write_bytes(b"later")
            service.create_checkpoint(session, "Later point")

            image, metadata = service.oldest_checkpoint_snapshot(session)

            self.assertEqual(metadata["id"], oldest["id"])
            self.assertEqual(image.read_bytes(), b"original image")
            self.assertEqual(metadata["reason"], "Workflow base")

    def test_undo_restores_and_consumes_latest_automatic_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory))
            first = service.begin_automatic_checkpoint(session, "adding a file")
            session.path.write_bytes(b"first edit")
            session.dirty = True
            service.finish_automatic_checkpoint(session, first)
            second = service.begin_automatic_checkpoint(session, "deleting a file")
            session.path.write_bytes(b"second edit")
            service.finish_automatic_checkpoint(session, second)

            undone = service.undo_last_change(session)

            self.assertEqual(undone["reason"], "deleting a file")
            self.assertEqual(session.path.read_bytes(), b"first edit")
            self.assertTrue(service.summary(session)["checkpoints"]["canUndo"])
            service.undo_last_change(session)
            self.assertEqual(session.path.read_bytes(), b"original image")
            self.assertFalse(service.summary(session)["checkpoints"]["canUndo"])

    def test_unchanged_operation_drops_speculative_undo_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory))
            token = service.begin_automatic_checkpoint(session, "checking something")

            service.finish_automatic_checkpoint(session, token)

            self.assertEqual(service.list_checkpoints(session), [])

    def test_mutation_finaliser_persists_dirty_recovery_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory))
            token = service.begin_automatic_checkpoint(session, "editing a file")
            session.dirty = True

            service.finish_automatic_checkpoint(session, token)

            restored = service._restore_session(session.id)
            self.assertTrue(restored.dirty)

    def test_no_op_does_not_prune_existing_undo_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory))
            service.checkpoints.automatic_limit = 2
            for number in range(2):
                token = service.begin_automatic_checkpoint(session, f"edit {number}")
                session.path.write_bytes(f"edit {number}".encode())
                service.finish_automatic_checkpoint(session, token)
            no_op = service.begin_automatic_checkpoint(session, "no-op")

            service.finish_automatic_checkpoint(session, no_op)

            self.assertEqual(
                [item["reason"] for item in service.list_checkpoints(session)],
                ["edit 1", "edit 0"],
            )

    def test_named_checkpoint_is_not_consumed_by_undo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory))
            named = service.create_checkpoint(session, "Before menu work")
            session.path.write_bytes(b"changed")

            with self.assertRaisesRegex(DiskError, "no automatic checkpoint"):
                service.undo_last_change(session)

            self.assertEqual(service.list_checkpoints(session)[0]["id"], named["id"])

    def test_undo_leaves_the_applied_hardware_profile_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory))
            token = service.begin_automatic_checkpoint(session, "adding a file")
            session.path.write_bytes(b"edited")
            service.finish_automatic_checkpoint(session, token)
            # Applying a profile takes no checkpoint, so the one above still
            # records the machine from before it.
            session.hardware_profile = {"name": "Falcon030", "machine": "falcon030"}
            session.target_hardware = "hd"

            service.undo_last_change(session)

            self.assertEqual(session.path.read_bytes(), b"original image")
            self.assertEqual(session.hardware_profile["machine"], "falcon030")
            self.assertEqual(session.target_hardware, "hd")

    def test_a_rename_survives_undoing_an_earlier_edit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory))
            token = service.begin_automatic_checkpoint(session, "adding a file")
            session.path.write_bytes(b"edited")
            service.finish_automatic_checkpoint(session, token)

            service.rename_session(session, "renamed.st")

            self.assertEqual(len(service.list_checkpoints(session)), 1)
            self.assertEqual(
                service.summary(session)["checkpoints"]["undoReason"], "adding a file"
            )
            service.undo_last_change(session)
            self.assertEqual(session.path.read_bytes(), b"original image")
            self.assertEqual(session.name, "renamed.st")

    def test_undoing_an_operation_that_renamed_the_image_restores_its_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory))
            # Replacing an image from the Online Library changes its bytes and
            # its name together, so undoing it has to bring both back even
            # after a later rename.
            token = service.begin_automatic_checkpoint(session, "replacing the image")
            session.path.write_bytes(b"replacement")
            session.name = "replacement.st"
            service.finish_automatic_checkpoint(session, token)
            service.rename_session(session, "my copy.st")

            service.undo_last_change(session)

            self.assertEqual(session.path.read_bytes(), b"original image")
            self.assertEqual(session.name, "games.st")

    def test_copies_abandoned_part_way_are_cleared_when_a_session_loads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory))
            service._persist_session(session)
            checkpoints = session.path.parent / "checkpoints"
            checkpoints.mkdir()
            stale = checkpoints / f".{'b' * 32}.tmp"
            stale.mkdir()
            (stale / "image.bin").write_bytes(b"half a copy")
            in_progress = checkpoints / f".{'c' * 32}.tmp"
            in_progress.mkdir()
            (in_progress / "image.bin").write_bytes(b"still copying")
            stale_restore = session.path.parent / f".{session.path.name}.restore-{'d' * 32}"
            stale_restore.write_bytes(b"half a restore")
            unrelated = checkpoints / ".notes.tmp"
            unrelated.mkdir()
            long_ago = time.time() - 3600
            for path in (stale, stale / "image.bin", stale_restore, unrelated):
                os.utime(path, (long_ago, long_ago))

            service.sessions.clear()
            service._restore_session(session.id)

            self.assertFalse(stale.exists())
            self.assertFalse(stale_restore.exists())
            self.assertTrue(in_progress.exists())
            self.assertTrue(unrelated.exists())
            self.assertEqual(session.path.read_bytes(), b"original image")

    def test_checkpoint_names_are_validated(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self.make_session(Path(directory))
            with self.assertRaisesRegex(DiskError, "Enter a name"):
                service.create_checkpoint(session, "   ")
            with self.assertRaisesRegex(DiskError, "at most 60"):
                service.create_checkpoint(session, "x" * 61)


if __name__ == "__main__":
    unittest.main()
