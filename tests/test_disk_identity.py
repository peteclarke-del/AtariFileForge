"""Proposing a title and what starts it, from the disk's own evidence.

The order the evidence is read in is the whole of what this module decides, so
each rung of it is asserted separately: a program in ``AUTO`` outranks the
desktop configuration, the desktop configuration outranks a program in the
root, and a program is judged by its header and its size rather than by its
name. A proposal the evidence does not support has to come back marked
ambiguous, because these are offered as defaults during an import where a
confident wrong answer is worse than an admitted uncertainty.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from app.disk_identity import (
    analyse_directory,
    describe_flags,
    desktop_installed_programs,
    extension_of,
    is_executable,
    program_flags,
    program_header,
)
from app.disk_service import DiskService


def program(*, text: bytes = b"code", flags: int = 0, symbols: bytes = b"") -> bytes:
    """A GEMDOS program whose header agrees with what follows it."""
    header = struct.pack(
        ">HIIIIIIH", 0x601A, len(text), 0, 256, len(symbols), 0, flags, 0
    )
    return header + text + symbols


class ProgramHeaderTests(unittest.TestCase):
    def test_a_header_is_decoded_when_its_sizes_account_for_the_file(self) -> None:
        header = program_header(program(text=b"x" * 100, flags=0x0007))
        self.assertEqual(header["text"], 100)
        self.assertEqual(header["bss"], 256)
        self.assertEqual(header["flags"], 0x0007)
        self.assertEqual(header["size"], 356)

    def test_a_file_that_only_starts_with_the_magic_is_not_a_program(self) -> None:
        """A truncated program is not a program, whatever its first word says."""
        truncated = program(text=b"x" * 100)[:60]
        self.assertIsNone(program_header(truncated))
        self.assertFalse(is_executable(truncated))

    def test_a_data_file_is_not_a_program(self) -> None:
        self.assertIsNone(program_header(b"just some data" * 8))

    def test_the_flags_a_person_would_ask_about_are_named(self) -> None:
        self.assertEqual(describe_flags(0), [])
        named = describe_flags(0x0007)
        self.assertIn("fastload", named)
        self.assertIn("load into alternate RAM", named)

    def test_an_extension_is_read_from_the_leaf_of_a_path(self) -> None:
        self.assertEqual(extension_of("GAMES\\X\\X.PRG"), "PRG")
        self.assertEqual(extension_of("READ.ME"), "ME")
        self.assertEqual(extension_of("AUTO"), "")


class DesktopRecordTests(unittest.TestCase):
    def test_a_record_that_names_a_program_is_read_and_a_mask_is_not(self) -> None:
        text = (
            "#G 03 FF 000 *.PRG@ @ @ \r\n"
            "#G 03 FF 000 C:\\GAMES\\CHUCK\\CHUCK.PRG@ @ @ \r\n"
            "#F 03 04 000 C:\\TOOLS\\FIX.TOS@ *.DAT@ @ \r\n"
        )
        self.assertEqual(desktop_installed_programs(text), ["CHUCK.PRG", "FIX.TOS"])

    def test_the_older_two_number_spelling_is_read_as_well(self) -> None:
        """TOS 1.x writes DESKTOP.INF with one fewer number before the path."""
        self.assertEqual(
            desktop_installed_programs("#G 03 FF   C:\\GAMES\\CHUCK\\CHUCK.PRG@ @ \r\n"),
            ["CHUCK.PRG"],
        )

    def test_a_configuration_with_no_installed_application_names_nothing(self) -> None:
        self.assertEqual(desktop_installed_programs("#a000000\r\n#D FF 01 000 @ *.*@ @ "), [])
        # The leading numbers of a record must never be read as a path.
        self.assertEqual(desktop_installed_programs("#G 03 FF 000 @ @ @ "), [])


class LaunchEvidenceTests(unittest.TestCase):
    """Each rung of the ladder, asserted against a real image."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)
        self.service = DiskService(self.root / "work")
        self.disk = self.service.create_blank("ds-720k", "CHUCK")

    def _put(self, path: str, data: bytes) -> None:
        host = self.root / path.replace("\\", "-")
        host.write_bytes(data)
        parent = path.rsplit("\\", 1)[0] if "\\" in path else ""
        if parent:
            from app import volume_copy

            if not volume_copy.directory_exists(self.service, self.disk, parent):
                self.service.make_directory(self.disk, parent)
        self.service.put(self.disk, path, host)

    def test_a_program_in_auto_outranks_everything_else_on_the_disk(self) -> None:
        self._put("BIG.PRG", program(text=b"x" * 4000))
        self._put("AUTO\\BOOT.PRG", program(text=b"y" * 16))

        found = analyse_directory(self.service, self.disk)

        self.assertEqual(found["filename"], "BOOT.PRG")
        self.assertEqual(found["launchFolder"], "AUTO")
        self.assertEqual(found["action"], "A")
        self.assertTrue(any("AUTO" in line for line in found["evidence"]))

    def test_a_desktop_configuration_outranks_a_program_in_the_root(self) -> None:
        self._put("BIG.PRG", program(text=b"x" * 4000))
        self._put("SMALL.PRG", program(text=b"y" * 16))
        self._put(
            "NEWDESK.INF",
            b"#a000000\r\n#G 03 FF 000 C:\\SMALL.PRG@ @ @ \r\n",
        )

        found = analyse_directory(self.service, self.disk)

        self.assertEqual(found["filename"], "SMALL.PRG")
        self.assertEqual(found["action"], "G")
        self.assertTrue(any("NEWDESK.INF" in line for line in found["evidence"]))

    def test_a_desktop_record_naming_a_missing_program_is_reported_not_used(self) -> None:
        self._put("BIG.PRG", program(text=b"x" * 4000))
        self._put("NEWDESK.INF", b"#G 03 FF 000 C:\\GONE.PRG@ @ @ \r\n")

        found = analyse_directory(self.service, self.disk)

        self.assertEqual(found["filename"], "BIG.PRG")
        self.assertTrue(any("GONE.PRG" in line for line in found["warnings"]))

    def test_a_program_is_judged_by_its_header_and_size_rather_than_its_name(self) -> None:
        """A name is not evidence; the largest real program almost always is."""
        self._put("AAAA.PRG", program(text=b"x" * 32))
        self._put("GAME.PRG", program(text=b"y" * 8000))
        self._put("MENU.PRG", b"not a program at all" * 4)

        found = analyse_directory(self.service, self.disk)

        self.assertEqual(found["filename"], "GAME.PRG")
        self.assertEqual(found["action"], "G")
        self.assertTrue(any("MENU.PRG" in line for line in found["warnings"]))

    def test_the_extension_decides_how_the_desktop_would_start_it(self) -> None:
        self._put("SETUP.TTP", program(text=b"y" * 500))
        self.assertEqual(analyse_directory(self.service, self.disk)["action"], "P")

    def test_an_accessory_is_never_proposed_as_what_starts_a_title(self) -> None:
        """TOS loads an accessory at boot; the desktop never starts one."""
        self._put("CLOCK.ACC", program(text=b"y" * 5000))
        self._put("GAME.PRG", program(text=b"y" * 100))
        self.assertEqual(analyse_directory(self.service, self.disk)["filename"], "GAME.PRG")

    def test_the_program_header_flags_are_reported_in_place_of_a_launch_stack(self) -> None:
        self._put("GAME.PRG", program(text=b"y" * 100, flags=0x0007))

        found = analyse_directory(self.service, self.disk)

        self.assertEqual(found["flags"], "7")
        self.assertEqual(found["page"], "7")
        self.assertTrue(any("_p_flags" in line for line in found["evidence"]))

    def test_flags_are_read_straight_off_one_file(self) -> None:
        self._put("GAME.PRG", program(text=b"y" * 100, flags=0x1000))
        value, evidence, applicable = program_flags(self.service, self.disk, "", "GAME.PRG")
        self.assertEqual(value, "4096")
        self.assertTrue(applicable)
        self.assertIn("shared text", evidence)

    def test_a_basic_program_has_no_header_and_therefore_no_flags(self) -> None:
        self._put("GAME.PRG", program(text=b"y" * 100))
        value, evidence, applicable = program_flags(self.service, self.disk, "", "READ.ME")
        self.assertIsNone(value)
        self.assertIn("could not be read", evidence)

    def test_an_empty_disk_is_admitted_rather_than_guessed_at(self) -> None:
        found = analyse_directory(self.service, self.disk)
        self.assertEqual(found["filename"], "")
        self.assertTrue(found["ambiguous"])
        self.assertFalse(found["launchObvious"])
        self.assertIn("The disk is empty.", found["warnings"])

    def test_two_programs_of_the_same_size_are_marked_ambiguous(self) -> None:
        self._put("ONE.PRG", program(text=b"x" * 500))
        self._put("TWO.PRG", program(text=b"y" * 500))

        found = analyse_directory(self.service, self.disk)

        self.assertTrue(found["ambiguous"])
        self.assertFalse(found["launchObvious"])
        self.assertTrue(any("same size" in line for line in found["warnings"]))

    def test_every_file_on_the_disk_is_offered_as_an_alternative(self) -> None:
        self._put("GAME.PRG", program(text=b"y" * 100))
        self._put("DATA\\LEVEL.DAT", b"level")

        candidates = analyse_directory(self.service, self.disk)["launchCandidates"]

        self.assertIn({"name": "GAME.PRG", "path": ""}, candidates)
        self.assertIn({"name": "LEVEL.DAT", "path": "DATA"}, candidates)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
