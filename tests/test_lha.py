"""The LHA reader is checked by round trip against a real encoder.

``lha_fixture`` builds archives rather than embedding them, so every test
below runs against a stream that was encoded to the format's own rules: the
canonical Huffman assignment, the run-length escapes in the code-length
table, and back-references that overlap their own source. A decoder that
merely looked plausible would not survive that.

The header tests cover all three levels because Atari archives use all three.
Level 1 gets the most attention: its size field covers the payload and the
extended header chain together, while the first two bytes of that chain are
counted as part of the base header instead, and getting that wrong lands the
reader in the middle of compressed data with a header-shaped hole.
"""

from __future__ import annotations

import random
import unittest

from app.lha import (
    LHAArchive,
    LHAError,
    SUPPORTED_METHODS,
    is_lha_bytes,
    is_lha_name,
)
from tests.lha_fixture import (
    archive,
    compress_lh5,
    level0_member,
    level1_member,
    level2_member,
)


def _sample_payloads() -> dict[str, bytes]:
    """Payloads chosen for the decoder construct each one forces."""
    return {
        # A stored member and a compressed one both have to survive a
        # zero-length file, which is what a marker file in an AUTO folder is.
        "empty": b"",
        "short": b"HELLO",
        # A long run makes the encoder emit a match that overlaps its own
        # source, which is the copy loop's only interesting case.
        "run": b"A" * 1200,
        # A DESKTOP.INF is what this reader actually opens, and its records
        # repeat enough to fill the code-length table with short codes.
        "script": b"#a000000\r\n#b000000\r\n#E9A03\r\n" * 60,
        # Incompressible data drives the code-length table to its long codes
        # and makes the encoder emit literals almost throughout.
        "random": bytes(random.Random(7).randrange(256) for _ in range(1536)),
    }


class LHAHeaderTests(unittest.TestCase):
    def test_all_three_header_levels_yield_the_same_path_and_bytes(self) -> None:
        payload = b"GEMDOS program data"
        blob = archive(
            level0_member("GAME/LOADER.PRG", payload),
            level1_member("GAME/DATA/LEVEL1.DAT", payload),
            level2_member("GAME/DATA/DEEP/LEVEL2.DAT", payload),
        )
        opened = LHAArchive(blob)
        self.assertEqual(
            [member.path for member in opened.members],
            ["GAME/LOADER.PRG", "GAME/DATA/LEVEL1.DAT", "GAME/DATA/DEEP/LEVEL2.DAT"],
        )
        for member in opened.members:
            with self.subTest(path=member.path):
                self.assertEqual(opened.read(member), payload)

    def test_a_level_one_payload_is_not_measured_through_its_extended_headers(self) -> None:
        """The classic level 1 mistake leaves the next header unreadable.

        Two members are used because a wrong payload length is invisible on
        the first one: it only shows up when the reader tries to find where
        the second header begins.
        """
        blob = archive(
            level1_member("DEEP/NESTED/FOLDER/FIRST.DAT", b"first payload"),
            level1_member("SECOND.DAT", b"second payload"),
        )
        opened = LHAArchive(blob)
        self.assertEqual(
            [member.path for member in opened.members],
            ["DEEP/NESTED/FOLDER/FIRST.DAT", "SECOND.DAT"],
        )
        self.assertEqual(opened.read(opened.members[1]), b"second payload")

    def test_a_member_is_found_case_insensitively_as_gemdos_would(self) -> None:
        opened = LHAArchive(archive(level1_member("AUTO/GAME/LOADER.PRG", b"program")))
        self.assertIsNotNone(opened.find("auto/game/loader.prg"))
        self.assertEqual(opened.read(opened.find("AUTO/GAME/LOADER.PRG")), b"program")
        self.assertIsNone(opened.find("AUTO/GAME/MISSING.PRG"))

    def test_a_member_name_is_the_leaf_of_its_path(self) -> None:
        opened = LHAArchive(archive(level2_member("GAME/DATA/SOUND.BIN", b"x")))
        self.assertEqual(opened.members[0].name, "SOUND.BIN")


class LHADecompressionTests(unittest.TestCase):
    def test_stored_and_compressed_members_round_trip(self) -> None:
        for name, payload in _sample_payloads().items():
            for method in ("-lh0-", "-lh5-"):
                with self.subTest(payload=name, method=method):
                    opened = LHAArchive(archive(level1_member(f"GAME/{name}", payload, method)))
                    self.assertEqual(opened.members[0].method, method)
                    self.assertEqual(opened.read(opened.members[0]), payload)

    def test_every_dictionary_width_decodes(self) -> None:
        """A larger archive is packed with a wider window, so all three are covered."""
        from app.lha import _decode_lzh

        payload = b"GEMDOS PROGRAM " * 200 + bytes(random.Random(3).randrange(256) for _ in range(1024))
        for bits, method in ((13, "-lh5-"), (15, "-lh6-"), (16, "-lh7-")):
            with self.subTest(method=method):
                self.assertIn(method, SUPPORTED_METHODS)
                self.assertEqual(_decode_lzh(compress_lh5(payload, bits), len(payload), bits), payload)

    def test_a_damaged_member_is_reported_rather_than_written_out(self) -> None:
        """A silent corruption here would reach an Atari as an unbootable file."""
        blob = bytearray(archive(level1_member("GAME/DATA.BIN", b"B" * 400, "-lh5-")))
        blob[-8] ^= 0xFF
        opened = LHAArchive(bytes(blob))
        with self.assertRaises(LHAError) as raised:
            opened.read(opened.members[0])
        self.assertIn("GAME/DATA.BIN", str(raised.exception))

    def test_a_checksum_failure_can_be_looked_past_deliberately(self) -> None:
        blob = bytearray(archive(level1_member("GAME/DATA.BIN", b"B" * 400, "-lh0-")))
        blob[-4] ^= 0xFF
        opened = LHAArchive(bytes(blob))
        with self.assertRaises(LHAError):
            opened.read(opened.members[0])
        self.assertEqual(len(opened.read(opened.members[0], verify=False)), 400)


class LHASafetyTests(unittest.TestCase):
    def test_a_member_cannot_escape_the_directory_it_extracts_into(self) -> None:
        for path in ("../DESKTOP.INF", "GAME/../../AUTO/LOADER.PRG"):
            with self.subTest(path=path):
                with self.assertRaises(LHAError):
                    LHAArchive(archive(level0_member(path, b"x")))

    def test_a_member_cannot_name_an_atari_volume(self) -> None:
        """A drive letter in a member path would place the file off the target."""
        with self.assertRaises(LHAError):
            LHAArchive(archive(level0_member("C:\\AUTO\\LOADER.PRG", b"x")))

    def test_a_downloaded_error_page_is_named_as_such(self) -> None:
        """A file archive answers a missing download with HTML, not with a 404."""
        with self.assertRaises(LHAError) as raised:
            LHAArchive(b"<!DOCTYPE HTML PUBLIC \"-//W3C//DTD HTML 4.01//EN\">\n<html>...</html>\n")
        self.assertIn("not an LHA archive", str(raised.exception))

    def test_an_unsupported_method_lists_but_names_itself_when_read(self) -> None:
        blob = bytearray(archive(level1_member("GAME/DATA.BIN", b"payload")))
        blob[2:7] = b"-lh1-"
        opened = LHAArchive(bytes(blob))
        self.assertEqual(opened.members[0].path, "GAME/DATA.BIN")
        with self.assertRaises(LHAError) as raised:
            opened.read(opened.members[0])
        self.assertIn("-lh1-", str(raised.exception))

    def test_a_truncated_archive_is_refused_rather_than_half_read(self) -> None:
        blob = archive(level1_member("GAME/DATA.BIN", b"B" * 400, "-lh5-"))
        with self.assertRaises(LHAError):
            LHAArchive(blob[: len(blob) // 2])


class LHARecognitionTests(unittest.TestCase):
    def test_a_buffer_is_recognised_by_its_method_identifier(self) -> None:
        self.assertTrue(is_lha_bytes(archive(level1_member("GAME/DATA.BIN", b"x"))))
        self.assertFalse(is_lha_bytes(b"PK\x03\x04" + bytes(40)))
        self.assertFalse(is_lha_bytes(b""))

    def test_names_are_recognised_case_insensitively(self) -> None:
        self.assertTrue(is_lha_name("GAME.LHA"))
        self.assertTrue(is_lha_name("game.lzh"))
        self.assertFalse(is_lha_name("game.st"))


if __name__ == "__main__":
    unittest.main()
