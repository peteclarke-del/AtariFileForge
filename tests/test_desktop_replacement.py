"""Replacement GEM desktops: which one suits a machine, and installing it."""

from __future__ import annotations

import dataclasses
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
        self.assertIsNone(find_desktop(DESKTOPS_BY_KEY["desktop-gemini"], [self.supplied]))

    def test_installing_one_that_was_not_supplied_says_where_to_put_it(self) -> None:
        with tempfile.TemporaryDirectory() as work:
            service = DiskService(Path(work))
            drive = service.create_blank("hd", "SYSTEM", "40MB")
            service.select_partition(drive, 0)
            desktops.DESKTOP_DIR = self.supplied
            desktops.REPOSITORY_DESKTOP_DIR = self.supplied
            with self.assertRaises(DiskError) as caught:
                service.install_desktop_replacement(drive, "desktop-gemini")
            message = str(caught.exception)
            self.assertIn("Shareware", message)
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


class LicenceTests(unittest.TestCase):
    """Which desktops this may go and fetch, and which it may not.

    The rule is the licence, not how easy the file is to find. A desktop that
    is somebody's property is installed from the operator's own copy or not at
    all, and the catalogue is what decides, so no request can ask for one.
    """

    def test_only_a_free_desktop_carries_somewhere_to_download_it_from(self) -> None:
        for desktop in DESKTOPS:
            with self.subTest(desktop=desktop.key):
                if not desktop.free:
                    self.assertEqual(desktop.sources, (), desktop.key)

    def test_every_free_desktop_says_where_it_comes_from(self) -> None:
        free = [desktop for desktop in DESKTOPS if desktop.free]
        self.assertTrue(free, "at least one desktop should be freely licensed")
        for desktop in free:
            with self.subTest(desktop=desktop.key):
                self.assertTrue(desktop.sources, desktop.key)
                for source in desktop.sources:
                    self.assertTrue(source.url.startswith("https://"), source.url)
                    self.assertTrue(source.label)

    def test_a_proprietary_desktop_is_never_fetched(self) -> None:
        def refuse(*_args, **_kwargs):
            raise AssertionError("a proprietary desktop must not be downloaded")

        with self.assertRaises(DiskError) as caught:
            desktops.fetch_desktop(DESKTOPS_BY_KEY["desktop-gemini"], opener=refuse)
        self.assertIn("Shareware", str(caught.exception))


class DownloadTests(unittest.TestCase):
    """Fetching a free desktop, without going near the network."""

    def setUp(self) -> None:
        import shutil
        self.store = Path(tempfile.mkdtemp(prefix="aff-fetch-"))
        self.addCleanup(lambda: shutil.rmtree(self.store, ignore_errors=True))

    @staticmethod
    def _archive(entries: dict) -> bytes:
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            for name, payload in entries.items():
                bundle.writestr(name, payload)
        return buffer.getvalue()

    def _opener(self, payload: bytes):
        class Response:
            def __enter__(inner):
                return inner

            def __exit__(inner, *_args):
                return False

            def read(inner, _limit=None):
                return payload

        def opener(_url, timeout=None):
            return Response()

        return opener

    def test_a_download_lands_where_a_supplied_copy_would_have(self) -> None:
        """Afterwards a download and the operator's own copy are the same thing."""
        payload = self._archive({
            "teradesk/DESKTOP.PRG": program(b"teradesk"),
            "teradesk/DESKTOP.RSC": b"resource",
        })
        desktop = DESKTOPS_BY_KEY["desktop-teradesk"]
        archive = desktops.fetch_desktop(desktop, self.store, opener=self._opener(payload))
        self.assertTrue(archive.is_file())
        self.assertEqual(archive.parent, self.store)
        found = find_desktop(desktop, [self.store])
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "DESKTOP.PRG")

    def test_something_that_is_not_an_archive_is_refused(self) -> None:
        """A captive portal answering with a login page is not a desktop."""
        desktop = DESKTOPS_BY_KEY["desktop-teradesk"]
        with self.assertRaises(DiskError) as caught:
            desktops.fetch_desktop(desktop, self.store, opener=self._opener(b"<html>login"))
        self.assertIn("not a ZIP", str(caught.exception))
        self.assertEqual(list(self.store.iterdir()), [])

    def test_an_archive_without_the_program_is_refused_and_not_kept(self) -> None:
        payload = self._archive({"README.TXT": b"nothing useful here"})
        desktop = DESKTOPS_BY_KEY["desktop-thing"]
        with self.assertRaises(DiskError) as caught:
            desktops.fetch_desktop(desktop, self.store, opener=self._opener(payload))
        self.assertIn("holds no", str(caught.exception))
        self.assertEqual(list(self.store.iterdir()), [])

    def test_an_oversized_download_is_refused(self) -> None:
        """A desktop is a few hundred kilobytes. Anything vast is not one."""
        desktop = DESKTOPS_BY_KEY["desktop-thing"]
        huge = b"x" * (desktops.MAX_DOWNLOAD_BYTES + 1)
        with self.assertRaises(DiskError) as caught:
            desktops.fetch_desktop(desktop, self.store, opener=self._opener(huge))
        self.assertIn("larger than", str(caught.exception))


class ArchiveAndFolderTests(unittest.TestCase):
    """Reading a copy the operator points at, however they keep it."""

    def setUp(self) -> None:
        import io
        import shutil
        import zipfile
        self.folder = Path(tempfile.mkdtemp(prefix="aff-chosen-"))
        self.addCleanup(lambda: shutil.rmtree(self.folder, ignore_errors=True))
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("THING/THING.APP", program(b"thing"))
            bundle.writestr("THING/THING.RSC", b"resource")
        (self.folder / "thin109d.zip").write_bytes(buffer.getvalue())

    def test_a_distribution_is_read_straight_out_of_its_archive(self) -> None:
        """Nobody unpacks a download before they want to use it."""
        found = find_desktop(DESKTOPS_BY_KEY["desktop-thing"], [self.folder])
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "THING.APP")
        self.assertEqual([name for name, _ in found.companions], ["THING.RSC"])

    def test_the_archive_itself_can_be_named(self) -> None:
        archive = self.folder / "thin109d.zip"
        found = find_desktop(DESKTOPS_BY_KEY["desktop-thing"], [archive])
        self.assertIsNotNone(found)
        self.assertEqual(found.source, archive)

    def test_a_folder_holding_somebody_elses_archives_finds_nothing(self) -> None:
        # Gemini has no download, so nothing here can stand in for it.
        import io
        import zipfile
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as bundle:
            bundle.writestr("HOLIDAY.JPG", b"not an atari program")
        (self.folder / "photos.zip").write_bytes(buffer.getvalue())
        self.assertIsNone(find_desktop(DESKTOPS_BY_KEY["desktop-gemini"], [self.folder]))


class PlacementTests(unittest.TestCase):
    """Where each kind of file has to land for TOS to find it.

    A program can live anywhere, but an accessory is loaded from the root of
    the boot drive and nowhere else, an AUTO program runs before GEM in the
    order the directory holds it, and a control panel module is read from the
    folder XControl's CPXPATH names. Putting any of them in the wrong place
    means it silently does not happen.
    """

    def setUp(self) -> None:
        import shutil
        self.supplied = Path(tempfile.mkdtemp(prefix="aff-place-"))
        self.addCleanup(lambda: shutil.rmtree(self.supplied, ignore_errors=True))
        root = self.supplied / "SAMPLE_1.00"
        root.mkdir()
        for name, payload in {
            "TERADESK.PRG": program(b"desktop"),
            "TERADESK.RSC": b"resource",
            "PANEL.ACC": b"an accessory",
            "EARLY.PRG": program(b"auto"),
            "TUNING.CPX": b"a control panel module",
        }.items():
            (root / name).write_bytes(payload)
        desktops.DESKTOP_DIR = self.supplied
        desktops.REPOSITORY_DESKTOP_DIR = self.supplied
        self.desktop = dataclasses.replace(
            DESKTOPS_BY_KEY["desktop-teradesk"],
            accessories=("PANEL.ACC",),
            auto_files=("EARLY.PRG",),
            control_panel=("TUNING.CPX",),
        )
        DESKTOPS_BY_KEY["desktop-sample"] = self.desktop
        self.addCleanup(DESKTOPS_BY_KEY.pop, "desktop-sample", None)
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.service = DiskService(Path(self.work.name))
        self.drive = self.service.create_blank("hd", "SYSTEM", "40MB")
        self.service.select_partition(self.drive, 0)

    def _names(self, folder=""):
        return {
            entry["name"]
            for entry in self.service.list_directory(self.drive, folder)["entries"]
        }

    def test_an_accessory_goes_to_the_root_and_not_beside_the_program(self) -> None:
        self.service.install_desktop_replacement(self.drive, "desktop-sample")
        self.assertIn("PANEL.ACC", self._names())
        self.assertNotIn("PANEL.ACC", self._names("TERADESK"))

    def test_an_auto_program_goes_into_auto(self) -> None:
        self.service.install_desktop_replacement(self.drive, "desktop-sample")
        self.assertIn("EARLY.PRG", self._names("AUTO"))

    def test_a_control_panel_module_goes_into_the_cpx_folder(self) -> None:
        self.service.install_desktop_replacement(self.drive, "desktop-sample")
        self.assertIn("TUNING.CPX", self._names(desktops.CPX_FOLDER))

    def test_an_auto_program_already_there_is_never_replaced(self) -> None:
        """AUTO order is often the difference between starting and not.

        A program already in AUTO holds a place in that sequence which the
        operator may have arranged deliberately, so it is left exactly as it
        is and reported as kept rather than quietly overwritten.
        """
        theirs = Path(self.work.name) / "theirs"
        theirs.write_bytes(program(b"the operator's own"))
        self.service.make_directory(self.drive, "AUTO")
        self.service.put(self.drive, "AUTO\\EARLY.PRG", theirs)
        result = self.service.install_desktop_replacement(self.drive, "desktop-sample")
        self.assertIn("AUTO\\EARLY.PRG", result["kept"])
        self.assertNotIn("AUTO\\EARLY.PRG", result["files"])
        self.assertEqual(
            self.service.read_file(self.drive, "AUTO\\EARLY.PRG"),
            theirs.read_bytes(),
        )

    def test_an_accessory_already_there_is_never_replaced(self) -> None:
        theirs = Path(self.work.name) / "panel"
        theirs.write_bytes(b"the operator's own accessory")
        self.service.put(self.drive, "PANEL.ACC", theirs)
        result = self.service.install_desktop_replacement(self.drive, "desktop-sample")
        self.assertIn("PANEL.ACC", result["kept"])
        self.assertEqual(
            self.service.read_file(self.drive, "PANEL.ACC"), theirs.read_bytes()
        )

    def test_too_many_accessories_is_reported_rather_than_discovered(self) -> None:
        """TOS loads six and ignores the rest without saying anything."""
        spare = Path(self.work.name) / "spare"
        spare.write_bytes(b"accessory")
        for index in range(7):
            self.service.put(self.drive, f"SPARE{index}.ACC", spare)
        result = self.service.install_desktop_replacement(self.drive, "desktop-sample")
        warning = next((text for text in result["warnings"] if "only the first" in text), "")
        self.assertTrue(warning, result["warnings"])
        self.assertIn("8 desk accessories", warning)


class DistributionShapeTests(unittest.TestCase):
    """A distribution arrives on a floppy, because that is how Atari software was sold."""

    def setUp(self) -> None:
        import shutil
        self.folder = Path(tempfile.mkdtemp(prefix="aff-shape-"))
        self.addCleanup(lambda: shutil.rmtree(self.folder, ignore_errors=True))

    def _disk(self, files: dict) -> Path:
        from app.disk_service import DiskService
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        service = DiskService(Path(work.name))
        floppy = service.create_blank("ds-800k", "DIST")
        service.make_directory(floppy, "NEODESK4")
        for name, payload in files.items():
            source = Path(work.name) / "payload"
            source.write_bytes(payload)
            service.put(floppy, name, source)
        image = self.folder / "NeoDesk.st"
        image.write_bytes(floppy.path.read_bytes())
        return image

    def test_a_program_is_read_off_a_distribution_floppy(self) -> None:
        """Both desktops downloadable from their authors are ZIPs of floppies."""
        self._disk({
            "NEODESK4\\NEOLOAD.PRG": program(b"loader"),
            "NEODESK4\\NEODESK.RSC": b"resource",
        })
        found = find_desktop(DESKTOPS_BY_KEY["desktop-neodesk"], [self.folder])
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "NEOLOAD.PRG")
        self.assertIn("NEODESK.RSC", [name for name, _ in found.companions])

    def test_a_floppy_inside_a_zip_is_read_too(self) -> None:
        import zipfile
        image = self._disk({"NEODESK4\\NEOLOAD.PRG": program(b"loader")})
        archive = self.folder / "NeoDesk-4.06.zip"
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.write(image, "NeoDesk.st")
            bundle.writestr("README.TXT", b"read me")
        image.unlink()
        found = find_desktop(DESKTOPS_BY_KEY["desktop-neodesk"], [archive])
        self.assertIsNotNone(found)
        self.assertEqual(found.name, "NEOLOAD.PRG")

    def test_a_floppy_holding_something_else_yields_nothing(self) -> None:
        self._disk({"NEODESK4\\READ.ME": b"not a program"})
        self.assertIsNone(find_desktop(DESKTOPS_BY_KEY["desktop-thing"], [self.folder]))
