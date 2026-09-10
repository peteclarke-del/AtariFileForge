from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.disk_service import DiskError, DiskService, ImageSession


class FailingStream(io.BytesIO):
    def __init__(self, payload: bytes, fail_after: int = 32):
        super().__init__(payload)
        self.fail_after = fail_after

    def read(self, size: int = -1) -> bytes:
        if self.tell() >= self.fail_after:
            raise OSError("injected upload failure")
        return super().read(min(size, self.fail_after - self.tell()))


class FailureInjectionTests(unittest.TestCase):
    def test_interrupted_upload_removes_the_incomplete_private_session(self):
        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder) / "work"
            service = DiskService(work)

            with self.assertRaisesRegex(OSError, "injected upload failure"):
                service.create_from_stream("broken.st", FailingStream(bytes(4096)))

            self.assertEqual(list(work.iterdir()), [])
            self.assertEqual(service.sessions, {})

    def test_rollback_restores_exact_bytes_after_a_partial_write(self):
        """An import into an existing directory is undone byte for byte.

        Expanding a disk image into a directory that already exists cannot be
        undone by deleting what was written, because there is no way to tell
        the new entries from the ones that were there before. The image is
        therefore copied first and the copy is put back when the write fails.
        """
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            source = service.create_blank("ds-720k", "SOURCE")
            target = service.create_blank("volume", "TARGET", capacity="4MB")
            payload = root / "game.prg"
            payload.write_bytes(b"\x60\x1a" + bytes(510))
            service.put(source, "GAME.PRG", payload)
            service.mark_saved(target)
            original = target.path.read_bytes()
            warnings_before = list(target.warnings)

            def fail_copy(_source, _target, _directory, _report):
                with target.path.open("r+b") as image:
                    image.seek(16)
                    image.write(b"BROKEN WRITE")
                target.warnings.append("partial warning")
                raise DiskError("copy failed")

            with patch.object(
                service, "_copy_volume_to_directory", side_effect=fail_copy
            ):
                with self.assertRaisesRegex(DiskError, "copy failed"):
                    service.extract_image_to_directory(
                        source, target, "", None, create_directory=False
                    )

            self.assertEqual(target.path.read_bytes(), original)
            self.assertFalse(target.dirty)
            self.assertEqual(target.warnings, warnings_before)
            self.assertEqual(list((root / "work").glob("*/.import-rollback-*")), [])

    def test_full_volume_refuses_the_new_file_without_losing_existing_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "FULL")
            large = root / "large.bin"
            extra = root / "extra.bin"
            # A 720 KiB volume holds 711 clusters of 1,024 bytes, so 700 KiB
            # of payload leaves too little room for a further 64 KiB file.
            large.write_bytes(b"A" * (700 * 1024))
            extra.write_bytes(b"B" * (64 * 1024))
            service.put(session, "LARGE.DAT", large)

            with self.assertRaises(DiskError):
                service.put(session, "EXTRA.DAT", extra)

            self.assertEqual(
                service.read_file(session, "LARGE.DAT"), large.read_bytes()
            )
            self.assertNotIn(
                "EXTRA.DAT",
                {
                    row["name"]
                    for row in service.list_directory(session, "", None)["entries"]
                },
            )
            self.assertEqual(service.validate(session), "No structural errors found")

    def test_corrupt_volume_fails_validation_instead_of_returning_partial_data(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "corrupt.st"
            image.write_bytes(b"not a GEMDOS volume")
            service = DiskService(Path(folder) / "work")
            session = ImageSession("f" * 32, image.name, "gemdos", image)

            with self.assertRaises(DiskError):
                service.validate(session)

            with self.assertRaises(DiskError):
                service.list_directory(session, "", None)


if __name__ == "__main__":
    unittest.main()
