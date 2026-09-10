"""Pasti captures are read for their sectors and reported for everything else."""

from __future__ import annotations

import unittest

from app import stx
from app.stx import (
    STXError,
    decode_stx,
    is_stx,
    parse_stx,
    protection_report,
    stx_to_st,
)
from tests.msa_fixture import DS_720K, boot_sector
from tests.stx_fixture import (
    SectorSpec,
    TrackSpec,
    build_stx,
    one_track_with_a_crc_error,
    sector_payload,
    standard_track,
)


class FileStructureTests(unittest.TestCase):
    def test_the_signature_and_version_are_checked(self) -> None:
        data, _spec = one_track_with_a_crc_error()
        self.assertTrue(is_stx(data))
        self.assertFalse(is_stx(b"RSY\x01" + bytes(12)))
        with self.assertRaisesRegex(STXError, "RSY"):
            parse_stx(bytes(16))
        wrong_version = bytearray(data)
        wrong_version[4] = 2
        with self.assertRaisesRegex(STXError, "version 2"):
            parse_stx(bytes(wrong_version))

    def test_the_file_header_fields_are_read(self) -> None:
        data = build_stx([standard_track(0, 0)], revision=2)
        parsed = parse_stx(data)
        self.assertEqual((parsed.version, parsed.tool, parsed.revision), (3, 1, 2))
        self.assertEqual(len(parsed.tracks), 1)

    def test_a_track_record_the_file_cannot_hold_is_refused(self) -> None:
        data, _spec = one_track_with_a_crc_error()
        with self.assertRaisesRegex(STXError, "does not hold|ends after"):
            parse_stx(data[:-100])

    def test_the_track_number_byte_carries_the_side_in_bit_seven(self) -> None:
        parsed = parse_stx(build_stx([standard_track(5, 0), standard_track(5, 1)]))
        self.assertEqual([(item.track, item.side) for item in parsed.tracks], [(5, 0), (5, 1)])
        self.assertEqual(parsed.sides, 2)

    def test_never_writable(self) -> None:
        self.assertFalse(stx.WRITABLE)
        self.assertFalse(hasattr(stx, "st_to_stx"))


class SectorPlacementTests(unittest.TestCase):
    def test_the_reference_track_places_nine_sectors_and_blanks_the_bad_one(self) -> None:
        data, spec = one_track_with_a_crc_error()
        decoded = decode_stx(data)
        # Ten sector records, so the layout is ten per track.
        self.assertEqual(decoded.geometry.sectors, 10)
        self.assertEqual(decoded.geometry.sides, 1)
        self.assertEqual(decoded.geometry.tracks, 1)
        for number in range(1, 10):
            offset = (number - 1) * 512
            self.assertEqual(decoded.image[offset : offset + 512], sector_payload(0, 0, number))
        self.assertEqual(decoded.image[9 * 512 : 10 * 512], bytes(512))
        self.assertEqual(decoded.unreadable, ["track 0 side 0 sector 10: CRC error"])
        self.assertEqual(decoded.protection["sectorsRecovered"], 9)
        self.assertEqual(decoded.protection["unreadableSectors"], 1)
        self.assertTrue(decoded.protection["protected"])

    def test_sectors_are_placed_by_their_id_not_their_order(self) -> None:
        spec = TrackSpec(0, 0, [
            SectorSpec(number, sector_payload(0, 0, number)) for number in (3, 1, 2, 9, 4, 5, 6, 7, 8)
        ])
        image = stx_to_st(build_stx([spec]))
        for number in range(1, 10):
            self.assertEqual(image[(number - 1) * 512 : number * 512], sector_payload(0, 0, number))

    def test_a_double_sided_disk_interleaves_sides_within_each_track(self) -> None:
        tracks = [standard_track(track, side) for track in range(3) for side in range(2)]
        decoded = decode_stx(build_stx(tracks))
        self.assertEqual((decoded.geometry.tracks, decoded.geometry.sides), (3, 2))
        for track in range(3):
            for side in range(2):
                for number in range(1, 10):
                    slot = (track * 2 + side) * 9 + number - 1
                    self.assertEqual(
                        decoded.image[slot * 512 : (slot + 1) * 512],
                        sector_payload(track, side, number),
                    )
        self.assertFalse(decoded.protection["protected"])

    def test_the_boot_sector_settles_the_sector_count(self) -> None:
        """A protected disk with odd tracks still has a boot sector that says nine."""
        first = standard_track(0, 0)
        first.sectors[0].data = boot_sector(DS_720K)
        odd = TrackSpec(1, 0, [SectorSpec(number, sector_payload(1, 0, number)) for number in range(1, 12)])
        tracks = [first, standard_track(0, 1), odd, standard_track(1, 1)]
        decoded = decode_stx(build_stx(tracks))
        self.assertEqual(decoded.geometry.sectors, 9)
        self.assertEqual(decoded.geometry.sides, 2)
        report = decoded.protection["tracks"][2]
        self.assertIn("11 sectors where 9 are standard", report["evidence"])

    def test_record_not_found_sectors_carry_no_data_and_are_reported(self) -> None:
        spec = standard_track(0, 0)
        spec.sectors[4].fdc_status = 0x10
        decoded = decode_stx(build_stx([spec]))
        self.assertEqual(decoded.image[4 * 512 : 5 * 512], bytes(512))
        self.assertEqual(decoded.unreadable, ["track 0 side 0 sector 5: record not found"])

    def test_plain_tracks_without_descriptors_are_read_in_order(self) -> None:
        spec = standard_track(2, 1)
        spec.descriptors = False
        decoded = decode_stx(build_stx([standard_track(0, 0), standard_track(0, 1), standard_track(1, 0), standard_track(1, 1), standard_track(2, 0), spec]))
        for number in range(1, 10):
            slot = (2 * 2 + 1) * 9 + number - 1
            self.assertEqual(decoded.image[slot * 512 : (slot + 1) * 512], sector_payload(2, 1, number))

    def test_a_track_image_with_sync_offset_does_not_shift_the_sectors(self) -> None:
        spec = standard_track(0, 0)
        spec.track_image = bytes(range(256)) * 24
        spec.sync_offset = 77
        decoded = decode_stx(build_stx([spec]))
        for number in range(1, 10):
            self.assertEqual(decoded.image[(number - 1) * 512 : number * 512], sector_payload(0, 0, number))
        self.assertIn("a raw track image was kept alongside the sectors", decoded.protection["tracks"][0]["evidence"])

    def test_a_duplicate_sector_id_keeps_the_first_copy(self) -> None:
        spec = standard_track(0, 0)
        spec.sectors.append(SectorSpec(3, b"\xaa" * 512))
        decoded = decode_stx(build_stx([spec]))
        self.assertEqual(decoded.image[2 * 512 : 3 * 512], sector_payload(0, 0, 3))
        self.assertIn("duplicate sector IDs 3", decoded.protection["tracks"][0]["evidence"])

    def test_a_non_standard_sector_size_is_left_out_of_the_image(self) -> None:
        spec = standard_track(0, 0)
        spec.sectors[0].size_code = 1
        spec.sectors[0].data = b"\x55" * 256
        decoded = decode_stx(build_stx([spec]))
        self.assertEqual(decoded.image[:512], bytes(512))
        self.assertIn("sector 1 is 256 bytes", decoded.protection["tracks"][0]["evidence"])


class ProtectionReportTests(unittest.TestCase):
    def test_a_clean_disk_reports_no_protection(self) -> None:
        report = protection_report(build_stx([standard_track(0, 0), standard_track(0, 1)]))
        self.assertFalse(report["protected"])
        self.assertEqual(report["protectedTracks"], 0)
        self.assertEqual(report["fuzzyBytes"], 0)
        self.assertEqual([row["evidence"] for row in report["tracks"]], [[], []])

    def test_fuzzy_bytes_timing_and_odd_ids_are_all_named(self) -> None:
        spec = standard_track(4, 0)
        spec.fuzzy = b"\xff" * 64
        spec.sectors[1].flags = 0x80
        spec.sectors[2].read_time = 17000
        spec.sectors[3].cylinder = 40
        spec.sectors[5].fdc_status = 0x20
        spec.track_length = 6500
        spec.sectors.pop()  # sector 9 is missing
        report = protection_report(build_stx([standard_track(0, 0), standard_track(1, 0), spec]))
        evidence = report["tracks"][2]["evidence"]
        self.assertIn("64 fuzzy bytes read differently on each pass", evidence)
        self.assertIn("long track of 6,500 bytes", evidence)
        self.assertIn("8 sectors where 9 are standard", evidence)
        self.assertIn("missing sector IDs 9", evidence)
        self.assertIn("sector 3 carries timing data", evidence)
        self.assertIn("sector 4 claims to be on track 40 side 0", evidence)
        self.assertIn("sector 6 uses a deleted-data mark", evidence)
        self.assertEqual(report["fuzzyBytes"], 64)
        self.assertTrue(report["protected"])
        self.assertEqual(report["protectedTracks"], 1)

    def test_the_decode_warnings_summarise_the_report(self) -> None:
        data, _spec = one_track_with_a_crc_error()
        decoded = decode_stx(data)
        self.assertTrue(decoded.warnings[0].startswith("Read from a Pasti capture"))
        self.assertTrue(any("unreadable on the original disk" in item for item in decoded.warnings))


if __name__ == "__main__":
    unittest.main()
