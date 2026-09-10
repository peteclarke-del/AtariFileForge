"""Replacement GEM desktops: which one suits a machine, and installing it."""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from app import desktop_replacement as desktops
from app.desktop_replacement import (
    DESKTOPS,
    DESKTOPS_BY_KEY,
    NO_DESKTOP,
    describe_desktops,
    desktop_for,
    find_desktop,
    recommended_desktop,
)
from app.disk_service import DiskError, DiskService

MIB = 1024 * 1024


def program(text: bytes) -> bytes:
    """A structurally valid GEMDOS program, so it is installed as one."""
    body = text.ljust(64, b"\0")
    return struct.pack(">HIIIIIIH", 0x601A, len(body), 0, 0, 0, 0, 0, 0) + body


class CatalogueTests(unittest.TestCase):
    def test_every_desktop_names_a_program_and_a_licence(self) -> None:
        """A choice the operator has to supply must say whose it is."""
        for desktop in DESKTOPS:
            with self.subTest(desktop=desktop.key):
                self.assertTrue(desktop.files, desktop.key)
                self.assertTrue(desktop.folder, desktop.key)
                self.assertTrue(desktop.licence, desktop.key)
                self.assertTrue(desktop.note, desktop.key)
                self.assertTrue(desktop.machines, desktop.key)

    def test_the_published_catalogue_matches_the_choices(self) -> None:
        published = {row["id"] for row in describe_desktops()}
        self.assertEqual(published, set(DESKTOPS_BY_KEY))

    def test_an_unknown_desktop_is_refused_with_the_choices(self) -> None:
        with self.assertRaises(DiskError) as caught:
            desktop_for("desktop-invented")
        self.assertIn("desktop-teradesk", str(caught.exception))


class RecommendationTests(unittest.TestCase):
    """Which desktop suits which machine.

    The whole point of the recommendation is that the operator should not have
    to read an evening of forum posts to learn that NeoDesk wants memory and
    that Thing is the one that still makes sense under MagiC.
    """

    def test_a_machine_short_of_memory_is_sent_to_the_smallest(self) -> None:
        chosen = recommended_desktop("st", 1 * MIB)
        self.assertEqual(chosen["id"], "desktop-teradesk")
        self.assertIn("2 MB", chosen["reason"])

    def test_memory_decides_before_the_machine_name_does(self) -> None:
        """A 4 MB plain ST runs the most complete of them perfectly well."""
        self.assertEqual(recommended_desktop("st", 4 * MIB)["id"], "desktop-neodesk")
        self.assertEqual(recommended_desktop("megast", 4 * MIB)["id"], "desktop-neodesk")

    def test_the_later_machines_are_sent_to_the_one_built_for_them(self) -> None:
        for machine in ("tt030", "falcon030"):
            with self.subTest(machine=machine):
                chosen = recommended_desktop(machine, 8 * MIB)
                self.assertEqual(chosen["id"], "desktop-thing")
                self.assertIn("MagiC", chosen["reason"])

    def test_an_unknown_memory_is_not_guessed_at(self) -> None:
        """With nothing to go on, the least demanding answer is the right one."""
        chosen = recommended_desktop("st", 0)
        self.assertEqual(chosen["id"], "desktop-teradesk")
        self.assertIn("unknown", chosen["reason"])

    def test_neodesk_is_never_recommended_for_a_falcon(self) -> None:
        """It predates the machine, and the catalogue says which suit which."""
        self.assertNotIn("falcon030", DESKTOPS_BY_KEY["desktop-neodesk"].machines)


class SuppliedCopyTests(unittest.TestCase):
    """Nothing is bundled, so everything turns on finding the operator's copy."""

    def setUp(self) -> None:
        self.supplied = Path(tempfile.mkdtemp(prefix="aff-desktops-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.supplied, ignore_errors=True))

    def _unpack(self, folder: str, files: dict) -> None:
        root = self.supplied / folder
        root.mkdir(parents=True, exist_ok=True)
        for name, payload in files.items():
            (root / name).write_bytes(payload)

    def test_a_distribution_is_found_inside_the_folder_it_was_published_in(self) -> None:
        """Nobody flattens a distribution before using it, so neither does this."""
        self._unpack("TERADESK_4.06", {
            "TERADESK.PRG": program(b"teradesk"),
            "TERADESK.RSC": b"resource",
        })
        found = find_desktop(DESKTOPS_BY_KEY["desktop-teradesk"], [self.supplied])
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "TERADESK.PRG")
        self.assertEqual(found.version, "4.06")
        self.assertEqual([name for name, _ in found.companions], ["TERADESK.RSC"])

    def test_a_desktop_that_was_not_supplied_is_simply_absent(self) -> None:
        self.assertIsNone(find_desktop(DESKTOPS_BY_KEY["desktop-neodesk"], [self.supplied]))

    def test_installing_one_that_was_not_supplied_says_where_to_put_it(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            service = DiskService(Path(work))
            drive = service.create_blank("hd", "SYSTEM", "40MB")
            service.select_partition(drive, 0)
            desktops.DESKTOP_DIR = self.supplied
            desktops.REPOSITORY_DESKTOP_DIR = self.supplied
            with self.assertRaises(DiskError) as caught:
                service.install_desktop_replacement(drive, "desktop-neodesk")
            message = str(caught.exception)
            self.assertIn("Gribnif", message)
            self.assertIn(str(self.supplied), message)


class InstallTests(unittest.TestCase):
    def setUp(self) -> None:
        import shutil
        self.supplied = Path(tempfile.mkdtemp(prefix="aff-desktops-"))
        self.addCleanup(lambda: shutil.rmtree(self.supplied, ignore_errors=True))
        root = self.supplied / "TERADESK_4.06"
        root.mkdir()
        (root / "TERADESK.PRG").write_bytes(program(b"teradesk"))
        (root / "TERADESK.RSC").write_bytes(b"resource")
        desktops.DESKTOP_DIR = self.supplied
        desktops.REPOSITORY_DESKTOP_DIR = self.supplied
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.service = DiskService(Path(self.work.name))
        self.drive = self.service.create_blank("hd", "SYSTEM", "40MB")
        self.service.select_partition(self.drive, 0)

    def test_the_program_lands_in_a_folder_of_its_own_with_its_resource(self) -> None:
        result = self.service.install_desktop_replacement(self.drive, "desktop-teradesk")
        self.assertEqual(result["folder"], "TERADESK")
        inside = {
            entry["name"]
            for entry in self.service.list_directory(self.drive, "TERADESK")["entries"]
        }
        self.assertEqual(inside, {"TERADESK.PRG", "TERADESK.RSC"})

    def test_the_desktop_configuration_learns_how_to_start_it(self) -> None:
        """Installed means the desktop can run it, not merely that it is there."""
        result = self.service.install_desktop_replacement(self.drive, "desktop-teradesk")
        text = self.service.read_file(self.drive, result["desktopFile"]).decode("latin-1")
        self.assertIn(r"C:\TERADESK\TERADESK.PRG", text)
        self.assertTrue(any(record.startswith("#G") for record in result["records"]))
        self.assertTrue(any(record.startswith("#X") for record in result["records"]))

    def test_it_can_be_installed_without_being_put_on_the_desktop(self) -> None:
        result = self.service.install_desktop_replacement(
            self.drive, "desktop-teradesk", on_desktop=False,
        )
        self.assertFalse(any(record.startswith("#X") for record in result["records"]))

    def test_it_says_that_the_built_in_desktop_still_starts_first(self) -> None:
        """Claiming more than was done would be the worst outcome here.

        Making a replacement start in place of the built-in desktop is
        arranged differently by every TOS release and by every one of these
        programs. This installs it and says so, rather than writing a guess
        into the operator's desktop configuration.
        """
        result = self.service.install_desktop_replacement(self.drive, "desktop-teradesk")
        self.assertTrue(result["warnings"])
        self.assertIn("still starts first", result["warnings"][0])

    def test_choosing_none_writes_nothing(self) -> None:
        before = {
            entry["name"] for entry in self.service.list_directory(self.drive, "")["entries"]
        }
        result = self.service.install_desktop_replacement(self.drive, NO_DESKTOP)
        self.assertFalse(result["installed"])
        after = {
            entry["name"] for entry in self.service.list_directory(self.drive, "")["entries"]
        }
        self.assertEqual(before, after)

    def test_installing_twice_leaves_one_of_each_record(self) -> None:
        """Preparing a drive again must not multiply what is on its desktop."""
        self.service.install_desktop_replacement(self.drive, "desktop-teradesk")
        result = self.service.install_desktop_replacement(self.drive, "desktop-teradesk")
        text = self.service.read_file(self.drive, result["desktopFile"]).decode("latin-1")
        self.assertEqual(text.count(r"C:\TERADESK\TERADESK.PRG@ @ @"), 1)


if __name__ == "__main__":
    unittest.main()
