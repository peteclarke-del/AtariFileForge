"""FastCopy Pro images: a header, then sectors, in either of its two forms."""

from __future__ import annotations

import unittest

from app.dim import (
    HEADER_SIZE,
    DIMError,
    decode_dim,
    dim_project,
    dim_to_st,
    is_dim,
    parse_dim,
    st_to_dim,
)
from tests.msa_fixture import (
    DS_720K,
    PC_360K,
    SS_360K,
    blank_image,
    fat12_720k_image,
    patterned_image,
)


def dim_header(
    *, sides: int, sectors: int, start: int = 0, end: int = 79, used_only: bool = False, density: int = 0
) -> bytes:
    header = bytearray(HEADER_SIZE)
    header[0:2] = b"BB"
    header[3] = 1 if used_only else 0
    header[6] = sides - 1
    header[8] = sectors
    header[10] = start
    header[12] = end
    header[13] = density
    header[14:16] = (512).to_bytes(2, "big")
    return bytes(header)


class HeaderTests(unittest.TestCase):
    def test_the_documented_offsets_are_the_ones_read(self) -> None:
        parsed = parse_dim(dim_header(sides=2, sectors=10, start=0, end=81) + bytes(82 * 2 * 10 * 512))
        self.assertEqual((parsed.sides, parsed.sectors_per_track), (2, 10))
        self.assertEqual((parsed.start_track, parsed.end_track), (0, 81))
        self.assertFalse(parsed.used_sectors_only)
        self.assertEqual(parsed.geometry.identifier, "ds-82t-10s")
        self.assertTrue(parsed.complete)

    def test_a_zero_sector_size_word_means_512(self) -> None:
        header = bytearray(dim_header(sides=1, sectors=9))
        header[14:16] = bytes(2)
        parsed = parse_dim(bytes(header) + bytes(SS_360K.size))
        self.assertEqual(parsed.sector_size, 512)

    def test_the_identifier_is_required(self) -> None:
        self.assertTrue(is_dim(dim_header(sides=2, sectors=9)))
        self.assertFalse(is_dim(b"BA" + bytes(30)))
        with self.assertRaisesRegex(DIMError, "0x4242"):
            parse_dim(bytes(HEADER_SIZE))

    def test_implausible_headers_are_refused(self) -> None:
        with self.assertRaisesRegex(DIMError, "sectors per track"):
            parse_dim(dim_header(sides=2, sectors=0))
        with self.assertRaisesRegex(DIMError, "track range"):
            parse_dim(dim_header(sides=2, sectors=9, start=10, end=5))
        header = bytearray(dim_header(sides=2, sectors=9))
        header[14:16] = (256).to_bytes(2, "big")
        with self.assertRaisesRegex(DIMError, "512-byte sectors"):
            parse_dim(bytes(header))

    def test_a_short_full_form_image_is_refused_not_padded(self) -> None:
        with self.assertRaisesRegex(DIMError, "describes a 737,280-byte disk"):
            dim_to_st(dim_header(sides=2, sectors=9) + bytes(1000))


class FullFormTests(unittest.TestCase):
    def test_a_real_fat12_volume_round_trips_through_the_full_form(self) -> None:
        image = fat12_720k_image()
        wrapped = st_to_dim(image)
        self.assertEqual(len(wrapped), HEADER_SIZE + len(image))
        parsed = parse_dim(wrapped)
        self.assertEqual(parsed.geometry, DS_720K)
        self.assertEqual(dim_to_st(wrapped), image)
        self.assertEqual(st_to_dim(dim_to_st(wrapped)), wrapped)

    def test_the_header_written_names_the_shape_of_the_image(self) -> None:
        for geometry in (DS_720K, SS_360K, PC_360K):
            with self.subTest(geometry=geometry.identifier):
                wrapped = st_to_dim(blank_image(geometry))
                self.assertEqual(wrapped[6], geometry.sides - 1)
                self.assertEqual(wrapped[8], geometry.sectors)
                self.assertEqual(wrapped[12], geometry.tracks - 1)
                self.assertEqual(wrapped[3], 0, "only the full form is written")
                self.assertEqual(parse_dim(wrapped).geometry, geometry)

    def test_an_ambiguous_image_without_a_boot_sector_is_refused(self) -> None:
        with self.assertRaisesRegex(DIMError, "does not identify one shape"):
            st_to_dim(bytes(368_640))
        self.assertEqual(len(st_to_dim(bytes(368_640), SS_360K)), HEADER_SIZE + 368_640)

    def test_trailing_bytes_are_reported_and_dropped(self) -> None:
        image = patterned_image(SS_360K)
        wrapped = st_to_dim(image) + b"\xff" * 7
        sectors, warnings = decode_dim(wrapped)
        self.assertEqual(sectors, image)
        self.assertTrue(any("follow the last sector" in item for item in warnings), warnings)

    def test_an_image_starting_after_track_zero_is_placed_at_its_track(self) -> None:
        raw = b"\x77" * (2 * 2 * 9 * 512)
        wrapped = dim_header(sides=2, sectors=9, start=78, end=79) + raw
        sectors = dim_to_st(wrapped)
        self.assertEqual(len(sectors), DS_720K.size)
        self.assertEqual(sectors[: 78 * 9216], bytes(78 * 9216))
        self.assertEqual(sectors[78 * 9216 :], raw)


class UsedSectorsFormTests(unittest.TestCase):
    """The space-saving form is rebuilt from the FAT it carries."""

    def _used_sectors_image(self):
        image = fat12_720k_image()
        boot = image[:512]
        reserved = int.from_bytes(boot[0x0E:0x10], "little")
        fats = boot[0x10]
        root_entries = int.from_bytes(boot[0x11:0x13], "little")
        sectors_per_fat = int.from_bytes(boot[0x16:0x18], "little")
        sectors_per_cluster = boot[0x0D]
        system = reserved + fats * sectors_per_fat + root_entries * 32 // 512
        # Allocate clusters 2, 3 and 7 in both FATs and give them content.
        full = bytearray(image)
        for fat_index in range(fats):
            fat = (reserved + fat_index * sectors_per_fat) * 512
            for cluster, value in ((2, 3), (3, 0xFFF), (7, 0xFFF)):
                index = fat + cluster + cluster // 2
                pair = full[index] | (full[index + 1] << 8)
                pair = (pair & 0x000F) | (value << 4) if cluster & 1 else (pair & 0xF000) | value
                full[index] = pair & 0xFF
                full[index + 1] = pair >> 8
        cluster_bytes = sectors_per_cluster * 512
        for cluster in (2, 3, 7):
            offset = (system + (cluster - 2) * sectors_per_cluster) * 512
            full[offset : offset + cluster_bytes] = bytes((cluster,)) * cluster_bytes
        packed = bytes(full[: system * 512]) + b"".join(
            bytes(full[(system + (cluster - 2) * sectors_per_cluster) * 512 :][:cluster_bytes])
            for cluster in (2, 3, 7)
        )
        return bytes(full), packed

    def test_used_sectors_are_placed_by_the_fat(self) -> None:
        full, packed = self._used_sectors_image()
        wrapped = dim_header(sides=2, sectors=9, used_only=True) + packed
        sectors, warnings = decode_dim(wrapped)
        self.assertEqual(sectors, full)
        self.assertTrue(any("allocated clusters" in item for item in warnings), warnings)
        self.assertFalse(parse_dim(wrapped).complete)

    def test_a_used_sectors_header_over_a_complete_image_is_just_the_image(self) -> None:
        image = fat12_720k_image()
        sectors, warnings = decode_dim(dim_header(sides=2, sectors=9, used_only=True) + image)
        self.assertEqual(sectors, image)
        self.assertTrue(any("every sector is present" in item for item in warnings), warnings)

    def test_a_used_sectors_image_the_fat_does_not_explain_is_placed_in_order(self) -> None:
        full, packed = self._used_sectors_image()
        wrapped = dim_header(sides=2, sectors=9, used_only=True) + packed[:-512]
        sectors, warnings = decode_dim(wrapped)
        self.assertEqual(len(sectors), DS_720K.size)
        self.assertEqual(sectors[: len(packed) - 512], packed[:-512])
        self.assertTrue(any("could not be applied" in item for item in warnings), warnings)
        self.assertTrue(any("placed in order" in item for item in warnings), warnings)

    def test_a_used_sectors_image_without_a_bpb_is_placed_in_order(self) -> None:
        wrapped = dim_header(sides=2, sectors=9, used_only=True) + b"\x11" * 2048
        sectors, warnings = decode_dim(wrapped)
        self.assertEqual(sectors[:2048], b"\x11" * 2048)
        self.assertEqual(sectors[2048:], bytes(DS_720K.size - 2048))
        self.assertTrue(any("no usable BIOS parameter block" in item for item in warnings), warnings)


class ProjectViewTests(unittest.TestCase):
    def test_the_project_describes_the_header_and_completeness(self) -> None:
        project = dim_project(st_to_dim(blank_image(DS_720K)))
        self.assertEqual(project["format"], "dim")
        self.assertEqual(project["geometry"]["id"], "ds-80t-9s")
        self.assertEqual(project["density"], "double")
        self.assertTrue(project["complete"])
        self.assertFalse(project["usedSectorsOnly"])
        self.assertEqual(project["storedBytes"], DS_720K.size)


if __name__ == "__main__":
    unittest.main()
