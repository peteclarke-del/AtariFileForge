"""The IPF path: how it behaves with and without the decoder library.

The library itself is not ours to ship, so these tests cover the two halves
the workbench owns: finding the library (or saying plainly that it is not
here), and turning the MFM bit cells it returns into sectors. The second
half is checked by encoding a track the way an ST's controller writes one,
clock bits and all, and requiring the decoder to hand back exactly what went
in, at whatever bit alignment the track happens to start.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import ipf
from app.ipf import assemble_image, crc16_ccitt

SYNC = format(0x4489, "016b")


def mfm_bits(data: bytes, last: int = 0) -> tuple[str, int]:
    """Encode bytes as MFM bit cells: a clock bit before every data bit.

    The clock bit is set only between two zero data bits, which is the rule
    the WD1772 applies and the reason ``A1`` with a suppressed clock cannot
    occur in ordinary data.
    """
    out = []
    for value in data:
        for shift in range(7, -1, -1):
            bit = (value >> shift) & 1
            out.append("1" if last == 0 and bit == 0 else "0")
            out.append(str(bit))
            last = bit
    return "".join(out), last


class TrackBuilder:
    def __init__(self) -> None:
        self.bits = ""
        self.last = 0

    def emit(self, data: bytes) -> None:
        encoded, self.last = mfm_bits(data, self.last)
        self.bits += encoded

    def sync(self) -> None:
        self.bits += SYNC * 3
        self.last = 1

    def raw(self) -> bytes:
        bits = self.bits + "0" * (-len(self.bits) % 8)
        return int(bits, 2).to_bytes(len(bits) // 8, "big")


def build_sector(builder: TrackBuilder, cylinder: int, head: int, number: int, payload: bytes, *, deleted: bool = False, size_code: int = 2) -> None:
    builder.emit(b"\x00" * 12)
    builder.sync()
    header = bytes([0xFE, cylinder, head, number, size_code])
    builder.emit(header + crc16_ccitt(b"\xa1\xa1\xa1" + header).to_bytes(2, "big"))
    builder.emit(b"\x4e" * 22 + b"\x00" * 12)
    builder.sync()
    mark = bytes([0xF8 if deleted else 0xFB])
    builder.emit(mark + payload + crc16_ccitt(b"\xa1\xa1\xa1" + mark + payload).to_bytes(2, "big"))
    builder.emit(b"\x4e" * 40)


def payload_for(number: int) -> bytes:
    return bytes(((number * 7 + offset) & 0xFF) for offset in range(512))


def build_track(cylinder: int, head: int = 0, sectors: int = 9) -> tuple[bytes, list[bytes]]:
    """A whole track as TOS formats one: gaps, syncs, marks and CRCs."""
    payloads = [payload_for(number) for number in range(1, sectors + 1)]
    builder = TrackBuilder()
    builder.emit(b"\x4e" * 60)
    for number, payload in enumerate(payloads, 1):
        build_sector(builder, cylinder, head, number, payload)
    raw = builder.raw()
    return raw + b"\x92" * max(0, 6250 - len(raw)), payloads


def rotate_bits(raw: bytes, count: int) -> bytes:
    bits = format(int.from_bytes(raw, "big"), f"0{len(raw) * 8}b")
    rotated = bits[count:] + bits[:count]
    return int(rotated, 2).to_bytes(len(raw), "big")


class IPFAvailabilityTests(unittest.TestCase):
    def test_a_missing_library_is_explained_rather_than_guessed_at(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.object(
            ipf, "_search_directories", return_value=[Path(folder)]
        ), patch.dict("os.environ", {ipf.ENVIRONMENT_VARIABLE: ""}, clear=False):
            self.assertIsNone(ipf.library_path())
            self.assertFalse(ipf.available())
            message = ipf.unavailable_message()
            self.assertIn("SPS decoder library", message)
            self.assertIn(ipf.ENVIRONMENT_VARIABLE, message)

    def test_the_environment_variable_names_one_exact_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            library = Path(folder) / "libcapsimage.so.5.1"
            library.write_bytes(b"not really a library")
            with patch.dict("os.environ", {ipf.ENVIRONMENT_VARIABLE: str(library)}):
                self.assertEqual(ipf.library_path(), library)
            with patch.dict("os.environ", {ipf.ENVIRONMENT_VARIABLE: str(library) + "-gone"}):
                self.assertIsNone(ipf.library_path())

    def test_reading_without_the_library_raises_the_explanation(self) -> None:
        with tempfile.TemporaryDirectory() as folder, patch.object(
            ipf, "_search_directories", return_value=[Path(folder)]
        ), patch.dict("os.environ", {ipf.ENVIRONMENT_VARIABLE: ""}, clear=False):
            with self.assertRaisesRegex(ipf.IPFError, "SPS decoder library"):
                ipf.read_ipf(Path(folder) / "capture.ipf")


class CrcTests(unittest.TestCase):
    def test_the_crc_is_ccitt_over_the_sync_bytes_and_the_mark(self) -> None:
        # The CRC of an ID field for cylinder 0 head 0 sector 1 size 2 as
        # written by every formatter that follows the IBM layout.
        self.assertEqual(crc16_ccitt(b"\xa1\xa1\xa1\xfe\x00\x00\x01\x02"), 0xCA6F)
        self.assertEqual(crc16_ccitt(b""), 0xFFFF)


class MfmDecodeTests(unittest.TestCase):
    def test_a_written_track_decodes_back_to_its_sectors(self) -> None:
        for sectors in (9, 10, 11):
            with self.subTest(sectors=sectors):
                raw, payloads = build_track(3, sectors=sectors)
                found, warnings = ipf._decode_track(raw, sectors)
                self.assertEqual(warnings, [])
                self.assertEqual(sorted(found), list(range(sectors)))
                for number, payload in enumerate(payloads):
                    self.assertEqual(found[number], payload, f"sector {number + 1}")

    def test_the_layout_is_derived_when_no_count_is_given(self) -> None:
        raw, _payloads = build_track(0, sectors=10)
        found, warnings = ipf._decode_track(raw)
        self.assertEqual(warnings, [])
        self.assertEqual(sorted(found), list(range(10)))

    def test_a_sector_with_a_damaged_header_is_reported_not_used(self) -> None:
        raw, _payloads = build_track(0)
        bits = format(int.from_bytes(raw, "big"), f"0{len(raw) * 8}b")
        # The first ID field starts after 60 bytes of gap, 12 of zeroes and
        # the three syncs; its cylinder byte is the second byte after them.
        header = 16 * (60 + 12) + 48 + 16
        damaged = bits[: header + 1] + ("1" if bits[header + 1] == "0" else "0") + bits[header + 2 :]
        found, warnings = ipf._decode_track(int(damaged, 2).to_bytes(len(raw), "big"), 9)
        self.assertNotIn(0, found)
        self.assertTrue(any("header failed its CRC" in item for item in warnings), warnings)
        self.assertEqual(sorted(found), list(range(1, 9)))

    def test_a_sector_with_damaged_data_is_reported_not_used(self) -> None:
        raw, _payloads = build_track(0)
        bits = format(int.from_bytes(raw, "big"), f"0{len(raw) * 8}b")
        data = 16 * (60 + 12) + 48 + 16 * 7 + 16 * (22 + 12) + 48 + 16 + 16 * 100
        damaged = bits[: data + 1] + ("1" if bits[data + 1] == "0" else "0") + bits[data + 2 :]
        found, warnings = ipf._decode_track(int(damaged, 2).to_bytes(len(raw), "big"), 9)
        self.assertNotIn(0, found)
        self.assertTrue(any("data failed its CRC" in item for item in warnings), warnings)

    def test_a_sector_that_straddles_the_index_is_still_found(self) -> None:
        """A track is a ring, so the last sector may wrap past its start."""
        raw, payloads = build_track(1)
        for shift in (600, 4_003, len(raw) * 8 - 700):
            with self.subTest(shift=shift):
                found, warnings = ipf._decode_track(rotate_bits(raw, shift), 9)
                self.assertEqual(warnings, [])
                self.assertEqual(sorted(found), list(range(9)))
                self.assertEqual(found[0], payloads[0])

    def test_a_deleted_data_mark_is_still_a_sector(self) -> None:
        builder = TrackBuilder()
        builder.emit(b"\x4e" * 60)
        build_sector(builder, 0, 0, 1, payload_for(1), deleted=True)
        found, warnings = ipf._decode_track(builder.raw(), 9)
        self.assertEqual(warnings, [])
        self.assertEqual(found, {0: payload_for(1)})

    def test_a_non_standard_sector_size_is_reported_not_placed(self) -> None:
        builder = TrackBuilder()
        builder.emit(b"\x4e" * 60)
        build_sector(builder, 0, 0, 1, bytes(256), size_code=1)
        found, warnings = ipf._decode_track(builder.raw(), 9)
        self.assertEqual(found, {})
        self.assertTrue(any("256-byte sectors" in item for item in warnings), warnings)

    def test_a_sector_number_outside_the_layout_is_reported(self) -> None:
        builder = TrackBuilder()
        builder.emit(b"\x4e" * 60)
        build_sector(builder, 0, 0, 12, payload_for(12))
        found, warnings = ipf._decode_track(builder.raw(), 9)
        self.assertEqual(found, {})
        self.assertTrue(any("outside the layout" in item for item in warnings), warnings)


class ImageAssemblyTests(unittest.TestCase):
    def test_the_layout_is_the_highest_sector_number_recovered(self) -> None:
        tracks = {
            (0, 0): {number: payload_for(number + 1) for number in range(9)},
            (0, 1): {number: payload_for(number + 1) for number in range(8)},
        }
        image, recovered, sectors_per_track = assemble_image(tracks, 1, 2, None)
        self.assertEqual(sectors_per_track, 9)
        self.assertEqual(len(image), 2 * 9 * 512)
        self.assertEqual(recovered, 17)
        self.assertEqual(image[9 * 512 : 10 * 512], payload_for(1))
        self.assertEqual(image[17 * 512 :], bytes(512))

    def test_a_named_layout_is_honoured_and_extra_sectors_are_dropped(self) -> None:
        tracks = {(0, 0): {number: payload_for(number + 1) for number in range(10)}}
        image, recovered, sectors_per_track = assemble_image(tracks, 1, 1, 9)
        self.assertEqual((sectors_per_track, recovered, len(image)), (9, 9, 9 * 512))

    def test_nothing_recovered_is_an_empty_image(self) -> None:
        self.assertEqual(assemble_image({}, 80, 2, None), (b"", 0, 0))


if __name__ == "__main__":
    unittest.main()
