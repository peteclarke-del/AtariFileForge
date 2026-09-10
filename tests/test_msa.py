"""Magic Shadow Archiver images round-trip exactly or not at all."""

from __future__ import annotations

import unittest

from app.msa import (
    HEADER_SIZE,
    MAGIC,
    MSAError,
    is_msa,
    msa_project,
    msa_to_st,
    pack_track,
    parse_msa,
    st_to_msa,
    unpack_track,
)
from tests.msa_fixture import (
    DS_720K,
    DS_82_10,
    DS_800K,
    PC_360K,
    SS_360K,
    blank_image,
    boot_sector,
    fat12_720k_image,
    patterned_image,
)


def header(sectors: int, sides: int, start: int, end: int) -> bytes:
    return (
        MAGIC
        + sectors.to_bytes(2, "big")
        + (sides - 1).to_bytes(2, "big")
        + start.to_bytes(2, "big")
        + end.to_bytes(2, "big")
    )


class RunLengthTests(unittest.TestCase):
    def test_a_run_record_is_marker_value_and_big_endian_count(self) -> None:
        self.assertEqual(unpack_track(bytes([0xE5, 0x41, 0x00, 0x05]), 5), b"AAAAA")
        self.assertEqual(unpack_track(bytes([0x41, 0xE5, 0x42, 0x00, 0x02, 0x43]), 4), b"ABBC")

    def test_runs_of_four_or_more_are_packed_and_shorter_ones_written_out(self) -> None:
        self.assertEqual(pack_track(b"AAAB"), b"AAAB")
        self.assertEqual(pack_track(b"AAAAB"), bytes([0xE5, 0x41, 0x00, 0x04, 0x42]))

    def test_a_bare_marker_byte_is_always_written_as_a_run_of_one(self) -> None:
        """``0xE5`` cannot appear as a literal, so even one is a record."""
        packed = pack_track(b"A\xe5B")
        self.assertEqual(packed, bytes([0x41, 0xE5, 0xE5, 0x00, 0x01, 0x42]))
        self.assertEqual(unpack_track(packed, 3), b"A\xe5B")

    def test_packing_is_exact_for_every_track_shape(self) -> None:
        for raw in (
            bytes(4608),
            b"\xe5" * 4608,
            bytes(range(256)) * 18,
            b"AB" * 2304,
            b"A" * 4607 + b"\xe5",
        ):
            with self.subTest(sample=raw[:8]):
                self.assertEqual(unpack_track(pack_track(raw), len(raw)), raw)

    def test_a_run_record_cut_off_at_the_end_is_refused(self) -> None:
        with self.assertRaisesRegex(MSAError, "cut off"):
            unpack_track(bytes([0x41, 0xE5, 0x42]), 10)

    def test_a_track_that_unpacks_to_the_wrong_length_is_refused(self) -> None:
        with self.assertRaisesRegex(MSAError, "unpacked to 3 bytes"):
            unpack_track(b"ABC", 4)
        with self.assertRaisesRegex(MSAError, "more than its"):
            unpack_track(bytes([0xE5, 0x41, 0x00, 0x09]), 4)


class HeaderTests(unittest.TestCase):
    def test_the_identifier_is_required(self) -> None:
        self.assertTrue(is_msa(header(9, 2, 0, 79)))
        self.assertFalse(is_msa(b"\x0e\x0e" + bytes(8)))
        with self.assertRaisesRegex(MSAError, "0x0E0F"):
            parse_msa(bytes(HEADER_SIZE))

    def test_the_header_is_big_endian(self) -> None:
        raw = bytes(4608)
        data = header(9, 1, 0, 0) + len(raw).to_bytes(2, "big") + raw
        parsed = parse_msa(data)
        self.assertEqual((parsed.sectors_per_track, parsed.sides), (9, 1))
        self.assertEqual((parsed.start_track, parsed.end_track), (0, 0))
        self.assertEqual(parsed.tracks[0].compressed, False)

    def test_implausible_headers_are_refused(self) -> None:
        with self.assertRaisesRegex(MSAError, "sides"):
            parse_msa(MAGIC + (9).to_bytes(2, "big") + (2).to_bytes(2, "big") + bytes(4))
        with self.assertRaisesRegex(MSAError, "sectors per track"):
            parse_msa(MAGIC + (0).to_bytes(2, "big") + bytes(6))
        with self.assertRaisesRegex(MSAError, "track range"):
            parse_msa(header(9, 2, 5, 4))

    def test_a_truncated_archive_names_the_track_it_stops_at(self) -> None:
        data = st_to_msa(blank_image(DS_720K))
        with self.assertRaisesRegex(MSAError, "ends before track|holds only"):
            parse_msa(data[:-3])

    def test_trailing_bytes_are_not_ignored(self) -> None:
        data = st_to_msa(blank_image(DS_720K)) + b"\x00"
        with self.assertRaisesRegex(MSAError, "follow the last track"):
            parse_msa(data)

    def test_a_track_longer_than_its_raw_size_is_refused(self) -> None:
        data = header(9, 1, 0, 0) + (4609).to_bytes(2, "big") + bytes(4609)
        with self.assertRaisesRegex(MSAError, "longer than"):
            parse_msa(data)


class RoundTripTests(unittest.TestCase):
    def test_a_real_fat12_volume_survives_the_round_trip_byte_for_byte(self) -> None:
        image = fat12_720k_image()
        self.assertEqual(len(image), DS_720K.size)
        archive = st_to_msa(image)
        self.assertLess(len(archive), len(image) // 10, "a blank volume packs small")
        self.assertEqual(msa_to_st(archive), image)
        self.assertEqual(st_to_msa(msa_to_st(archive)), archive)

    def test_every_shape_round_trips_with_mixed_literal_and_run_tracks(self) -> None:
        for geometry in (DS_720K, SS_360K, PC_360K, DS_800K, DS_82_10):
            with self.subTest(geometry=geometry.identifier):
                image = patterned_image(geometry)
                archive = st_to_msa(image)
                parsed = parse_msa(archive)
                self.assertEqual(parsed.geometry, geometry)
                self.assertEqual(len(parsed.tracks), geometry.tracks * geometry.sides)
                self.assertEqual(msa_to_st(archive), image)
                self.assertEqual(st_to_msa(msa_to_st(archive)), archive)

    def test_a_track_is_packed_only_when_that_is_shorter(self) -> None:
        image = bytearray(patterned_image(SS_360K, with_boot=False))
        # Track 3 is made blank, so it packs; the others are noise and do not.
        image[3 * 4608 : 4 * 4608] = bytes(4608)
        parsed = parse_msa(st_to_msa(bytes(image), SS_360K))
        self.assertTrue(parsed.tracks[3].compressed)
        self.assertEqual(parsed.tracks[3].packed_length, 4)
        self.assertFalse(parsed.tracks[4].compressed)
        self.assertEqual(parsed.tracks[4].packed_length, 4608)

    def test_the_boot_sector_decides_the_shape_of_an_ambiguous_image(self) -> None:
        single = blank_image(SS_360K)
        double = blank_image(PC_360K)
        self.assertEqual(parse_msa(st_to_msa(single)).sides, 1)
        self.assertEqual(parse_msa(st_to_msa(double)).sides, 2)

    def test_an_image_whose_shape_cannot_be_settled_is_refused(self) -> None:
        with self.assertRaisesRegex(MSAError, "does not identify one shape"):
            st_to_msa(bytes(368_640))
        with self.assertRaisesRegex(MSAError, "but .* is"):
            st_to_msa(bytes(368_640), DS_720K)

    def test_a_partial_archive_places_its_tracks_where_they_belong(self) -> None:
        raw = b"\x5a" * 4608
        data = header(9, 1, 2, 2) + len(raw).to_bytes(2, "big") + raw
        image = msa_to_st(data)
        self.assertEqual(len(image), 3 * 4608)
        self.assertEqual(image[: 2 * 4608], bytes(2 * 4608))
        self.assertEqual(image[2 * 4608 :], raw)


class ProjectViewTests(unittest.TestCase):
    def test_the_project_lists_every_track_with_its_lengths(self) -> None:
        image = bytearray(patterned_image(DS_720K))
        image[4608 * 2 : 4608 * 3] = bytes(4608)
        project = msa_project(st_to_msa(bytes(image)))
        self.assertEqual(project["format"], "msa")
        self.assertEqual(project["geometry"]["id"], "ds-80t-9s")
        self.assertEqual(project["sectorsPerTrack"], 9)
        self.assertEqual(project["sides"], 2)
        self.assertEqual(len(project["tracks"]), 160)
        row = project["tracks"][2]
        self.assertEqual((row["track"], row["side"]), (1, 0))
        self.assertTrue(row["compressed"])
        self.assertEqual(row["unpackedLength"], 4608)
        self.assertEqual(row["packedLength"], 4)
        # The odd tracks of the fixture pack, and so does the blanked one.
        self.assertEqual(project["compressedTracks"], 81)
        self.assertEqual(project["size"], DS_720K.size)

    def test_the_boot_sector_fixture_is_the_shape_it_claims(self) -> None:
        boot = boot_sector(DS_800K)
        self.assertEqual(int.from_bytes(boot[0x18:0x1A], "little"), 10)
        self.assertEqual(int.from_bytes(boot[0x13:0x15], "little"), 1600)


if __name__ == "__main__":
    unittest.main()
