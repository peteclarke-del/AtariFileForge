"""Reading a CD image, which is how a lot of ST and Falcon material arrives.

The interesting failures here are all about names rather than about bytes. A
disc publishes the same files under as many as three different names, and
reading it through the wrong tree gives an operator eight-and-three shouting
where a perfectly good long name was sitting in the next tree along.

MetaDOS on the Atari reads the base tree, so the eight-and-three name with its
``;1`` version suffix stripped has to keep working as well: that is the name a
GEMDOS program on the real machine would see, and a disc with nothing but a
base tree is still an ordinary disc.

Each image is built in this tree by ``tests.iso_fixture`` rather than embedded,
so a failure names the field that broke.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.iso9660 import (
    ATTR_DIRECTORY,
    ATTR_HIDDEN,
    ATTR_READ_ONLY,
    Iso9660Error,
    Iso9660Image,
    format_attributes,
    is_iso_bytes,
    is_iso_name,
)
from tests.iso_fixture import build_iso, directory, file, name_entry


class _DiscTestCase(unittest.TestCase):
    """Write one disc to a scratch directory and open it."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)

    def _open(self, tree, **options) -> Iso9660Image:
        path = self.root / "disc.iso"
        path.write_bytes(build_iso(tree, **options))
        image = Iso9660Image(path)
        self.addCleanup(image.close)
        return image


class IsoReadingTests(_DiscTestCase):
    def test_a_disc_lists_its_volume_and_contents(self) -> None:
        tree = directory("")
        tree.add(file("README.TXT", b"notes"))
        tree.add(directory("EXTRAS"))

        iso = self._open(tree, volume="FALCON")

        self.assertEqual(iso.volume, "FALCON")
        self.assertEqual([e.name for e in iso.list_directory()], ["EXTRAS", "README.TXT"])

    def test_folders_are_listed_before_files(self) -> None:
        """A person browsing a disc wants its folders first, as elsewhere."""
        tree = directory("")
        tree.add(file("AAA.TXT", b"a"))
        tree.add(directory("ZZZ"))

        self.assertEqual([e.name for e in self._open(tree).list_directory()], ["ZZZ", "AAA.TXT"])

    def test_the_version_suffix_is_not_part_of_the_name(self) -> None:
        """ISO writes "README.TXT;1"; nobody wants to read that."""
        tree = directory("")
        tree.add(file("README.TXT", b"notes"))

        self.assertEqual([e.name for e in self._open(tree).list_directory()], ["README.TXT"])

    def test_a_base_tree_name_is_upper_cased(self) -> None:
        """MetaDOS shows a level 1 name, so a mixed-case one is normalised."""
        tree = directory("")
        tree.add(file("Readme.Txt", b"notes"))

        self.assertEqual([e.name for e in self._open(tree).list_directory()], ["README.TXT"])

    def test_a_file_reads_back_exactly(self) -> None:
        payload = bytes(range(256)) * 40
        tree = directory("")
        tree.add(file("AUTO.PRG", payload))

        self.assertEqual(self._open(tree).read_file("AUTO.PRG"), payload)

    def test_an_empty_file_reads_as_no_bytes(self) -> None:
        tree = directory("")
        tree.add(file("EMPTY", b""))

        self.assertEqual(self._open(tree).read_file("EMPTY"), b"")

    def test_nested_folders_are_reachable_by_path(self) -> None:
        tree = directory("")
        games = tree.add(directory("GAMES"))
        games.add(directory("EXTRAS")).add(file("TOOL.PRG", b"tool"))

        iso = self._open(tree)

        self.assertEqual(iso.read_file("GAMES/EXTRAS/TOOL.PRG"), b"tool")
        self.assertEqual(
            [e.path for e in iso.list_directory("GAMES/EXTRAS")], ["GAMES/EXTRAS/TOOL.PRG"]
        )

    def test_a_walk_reports_every_entry_once(self) -> None:
        tree = directory("")
        first = tree.add(directory("ONE"))
        first.add(file("A", b"a"))
        second = tree.add(directory("TWO"))
        second.add(directory("DEEP")).add(file("B", b"b"))

        paths = sorted(entry.path for entry in self._open(tree).walk())

        self.assertEqual(paths, ["ONE", "ONE/A", "TWO", "TWO/DEEP", "TWO/DEEP/B"])


class GemdosAttributeTests(_DiscTestCase):
    """What an Atari would say about a file on a disc it cannot write to."""

    def test_every_file_on_a_disc_is_read_only(self) -> None:
        tree = directory("")
        tree.add(file("AUTO.PRG", b"x"))

        entry = self._open(tree).list_directory()[0]

        self.assertEqual(entry.attributes, ATTR_READ_ONLY)
        self.assertEqual(entry.attribute_letters, "r-----")

    def test_a_folder_also_carries_the_directory_attribute(self) -> None:
        tree = directory("")
        tree.add(directory("EXTRAS"))

        entry = self._open(tree).list_directory()[0]

        self.assertEqual(entry.attributes, ATTR_READ_ONLY | ATTR_DIRECTORY)
        self.assertEqual(entry.attribute_letters, "r---d-")

    def test_an_entry_the_disc_hides_carries_the_hidden_attribute(self) -> None:
        tree = directory("")
        tree.add(file("SETUP.INF", b"x", hidden=True))

        entry = self._open(tree).list_directory()[0]

        self.assertEqual(entry.attributes, ATTR_READ_ONLY | ATTR_HIDDEN)
        self.assertEqual(entry.attribute_letters, "rh----")

    def test_the_recording_date_is_read_from_the_directory_record(self) -> None:
        tree = directory("")
        tree.add(file("AUTO.PRG", b"x"))

        self.assertEqual(
            self._open(tree).list_directory()[0].datestamp, "2000-11-29T13:45:00"
        )

    def test_the_letters_line_up_whatever_is_set(self) -> None:
        """Every entry prints six characters, so a column of them aligns."""
        for value in (0, ATTR_READ_ONLY, ATTR_READ_ONLY | ATTR_DIRECTORY, 0x3F):
            with self.subTest(value=value):
                self.assertEqual(len(format_attributes(value)), 6)
        self.assertEqual(format_attributes(0), "------")
        self.assertEqual(format_attributes(0x3F), "rhsvda")


class NamingSchemeTests(_DiscTestCase):
    """Which of a disc's three name schemes is read, and why it matters."""

    def test_rock_ridge_supplies_the_name_the_base_tree_shouts(self) -> None:
        tree = directory("")
        tree.add(file(
            "Emergency-Boot.inf", b"x",
            iso_name="EMERGENC.INF",
            system_use=name_entry("Emergency-Boot.inf"),
        ))

        self.assertEqual(
            [e.name for e in self._open(tree).list_directory()], ["Emergency-Boot.inf"]
        )

    def test_joliet_wins_over_rock_ridge(self) -> None:
        """Nothing is attached to the base tree that preferring Joliet loses.

        The metadata this reader reports is the GEMDOS attributes and the
        recording date, and both come from whichever tree's directory record
        is being read. So the tree with the best names is simply the better
        one to read, and this disc carries all three schemes at once.
        """
        tree = directory("")
        tree.add(file(
            "LongMixedCaseName.txt", b"x",
            iso_name="LONGMIXE.TXT",
            system_use=name_entry("rock-ridge-name.txt"),
        ))

        iso = self._open(tree, joliet=True)
        entry = iso.list_directory()[0]

        self.assertTrue(iso.joliet)
        self.assertEqual(entry.name, "LongMixedCaseName.txt")
        self.assertEqual(entry.attributes, ATTR_READ_ONLY)

    def test_rock_ridge_is_used_when_there_is_no_joliet_tree(self) -> None:
        tree = directory("")
        tree.add(file(
            "LongMixedCaseName.txt", b"x",
            iso_name="LONGMIXE.TXT",
            system_use=name_entry("LongMixedCaseName.txt"),
        ))

        iso = self._open(tree)

        self.assertFalse(iso.joliet)
        self.assertEqual([e.name for e in iso.list_directory()], ["LongMixedCaseName.txt"])

    def test_the_base_tree_is_read_when_a_disc_carries_nothing_else(self) -> None:
        """A disc mastered for MetaDOS alone is still a perfectly good disc."""
        tree = directory("")
        tree.add(file("LONGMIXE.TXT", b"x"))

        iso = self._open(tree)

        self.assertFalse(iso.joliet)
        self.assertEqual([e.name for e in iso.list_directory()], ["LONGMIXE.TXT"])

    def test_a_second_primary_descriptor_does_not_change_the_tree(self) -> None:
        """Some real discs carry two, which the standard does not describe."""
        tree = directory("")
        tree.add(file("README.TXT", b"notes"))

        iso = self._open(tree, volume="STDISC", duplicate_primary=True)

        self.assertEqual(iso.volume, "STDISC")
        self.assertEqual([e.name for e in iso.list_directory()], ["README.TXT"])


class MalformedDiscTests(_DiscTestCase):
    """A CD image is a file from somewhere else and is treated as one."""

    def _write(self, tree, **options) -> Path:
        path = self.root / "disc.iso"
        path.write_bytes(build_iso(tree, **options))
        return path

    def test_a_file_that_is_not_a_disc_is_refused_with_a_reason(self) -> None:
        path = self.root / "not.iso"
        path.write_bytes(b"\x00" * (40 * 1024))

        with self.assertRaises(Iso9660Error) as raised:
            Iso9660Image(path)

        self.assertIn("not a CD image", str(raised.exception))

    def test_a_path_cannot_step_outside_the_disc(self) -> None:
        tree = directory("")
        tree.add(file("README.TXT", b"notes"))

        with Iso9660Image(self._write(tree)) as iso:
            with self.assertRaises(Iso9660Error):
                iso.read_file("../../etc/passwd")

    def test_a_missing_path_says_so(self) -> None:
        tree = directory("")
        tree.add(file("README.TXT", b"notes"))

        with Iso9660Image(self._write(tree)) as iso:
            with self.assertRaises(Iso9660Error) as raised:
                iso.read_file("NOWHERE")
            self.assertIn("not on this disc", str(raised.exception))

    def test_listing_a_file_is_refused_rather_than_guessed_at(self) -> None:
        tree = directory("")
        tree.add(file("README.TXT", b"notes"))

        with Iso9660Image(self._write(tree)) as iso:
            with self.assertRaises(Iso9660Error):
                iso.list_directory("README.TXT")


class RecognitionTests(unittest.TestCase):
    def test_a_disc_is_recognised_by_its_descriptor_not_its_name(self) -> None:
        tree = directory("")
        tree.add(file("README.TXT", b"notes"))
        self.assertTrue(is_iso_bytes(build_iso(tree)[:40 * 1024]))

    def test_a_short_prefix_cannot_claim_to_be_a_disc(self) -> None:
        """The identifier lives at sector sixteen, so a prefix cannot answer."""
        self.assertFalse(is_iso_bytes(b"CD001" * 10))

    def test_the_usual_extensions_are_recognised(self) -> None:
        self.assertTrue(is_iso_name("FalconCD.iso"))
        self.assertTrue(is_iso_name("disc.ISO"))
        self.assertFalse(is_iso_name("Oids.st"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
