from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app.disk_service import DiskError, DiskService, ImageSession
from app.download_archive import build_download_archive, prepared_download


class DownloadArchiveTests(unittest.TestCase):
    @staticmethod
    def _hard_disk_session(root: Path) -> tuple[DiskService, ImageSession]:
        """A real partitioned drive, which is what a download packages."""
        service = DiskService(root / "work")
        session = service.create_blank("hd", "GAMES", capacity="4MB")
        session.name = "games.img"
        session.dirty = True
        return service, session

    def test_prepare_builds_complete_archive_before_reporting_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self._hard_disk_session(Path(directory))
            progress = []

            archive_path, archive_name = build_download_archive(
                service,
                session,
                lambda message, current=None, total=None: progress.append(
                    (message, current, total)
                ),
            )

            self.assertTrue(archive_path.is_file())
            self.assertTrue(archive_name.startswith("games-"))
            self.assertEqual(progress[-1], (
                "The complete ZIP is ready to download", 100, 100,
            ))
            self.assertTrue(any(current and current >= 40 for _message, current, _total in progress))
            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(archive.namelist(), ["README.md", "games.img"])
                self.assertEqual(archive.read("games.img"), session.path.read_bytes())

            self.assertEqual(prepared_download(session), (archive_path, archive_name))

    def test_prepared_archive_is_rejected_after_the_image_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self._hard_disk_session(Path(directory))
            build_download_archive(service, session)

            with session.path.open("r+b") as image:
                image.seek(0)
                image.write(b"changed")

            with self.assertRaisesRegex(DiskError, "changed afterward"):
                prepared_download(session)

    def test_accepted_compatibility_report_is_packaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self._hard_disk_session(Path(directory))
            session.compatibility_reports = [{
                "format": "atari-file-forge-compatibility-report",
                "version": 1,
                "operation": "copy",
                "markdown": "# Accepted report\n",
                "acceptedAt": "2026-08-17T12:00:00+00:00",
            }]
            archive_path, _archive_name = build_download_archive(service, session)
            with zipfile.ZipFile(archive_path) as archive:
                self.assertIn("Compatibility/accepted-report.json", archive.namelist())
                self.assertIn("Compatibility/accepted-report.md", archive.namelist())
                self.assertEqual(archive.read("Compatibility/accepted-report.md"), b"# Accepted report\n")
                document = archive.read("Compatibility/accepted-report.json").decode("utf-8")
                self.assertNotIn('"markdown"', document)

    def test_accepting_report_invalidates_previously_prepared_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service, session = self._hard_disk_session(Path(directory))
            build_download_archive(service, session)
            session.compatibility_reports = [{"acceptedAt": "2026-08-17T12:00:00+00:00"}]
            with self.assertRaisesRegex(DiskError, "Save it again"):
                prepared_download(session)

    def test_sparse_hard_disk_archive_stands_alone_and_is_byte_exact(self) -> None:
        """A drive image is one file, so it is packaged on its own.

        An Atari hard disk carries its own partition table in its first
        sector, so nothing has to travel beside it to say what shape it is.
        The archive therefore holds the README and the image and nothing
        else, at the root rather than in a subdirectory, and the image comes
        back byte for byte even though most of it was never written.
        """
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "games.img"
            with image.open("wb") as output:
                output.write(b"AHDI")
                output.seek(8 * 1024 * 1024 - 1)
                output.write(b"\0")
            service = DiskService(root / "work")
            service._optimise_sparse_file(image)
            service.prepare_download = lambda session, progress=None: image
            session = ImageSession("b" * 32, image.name, "hd", image)

            def write_readme(_service, _session, _path, _generated, **_checksums):
                readme = root / "download-README.md"
                readme.write_text("test", encoding="utf-8")
                return readme

            with patch("app.download_archive.write_download_readme", write_readme):
                archive_path, _archive_name = build_download_archive(service, session)

            with zipfile.ZipFile(archive_path) as archive:
                self.assertEqual(archive.namelist(), ["README.md", "games.img"])
                self.assertEqual(archive.read("games.img"), image.read_bytes())


if __name__ == "__main__":
    unittest.main()
