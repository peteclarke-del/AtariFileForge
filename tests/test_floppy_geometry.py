"""The geometry table is the one place the ST's floppy shapes are defined."""

from __future__ import annotations

import unittest

from app.floppy_geometry import (
    DEFAULT_GEOMETRY,
    GEOMETRIES,
    canonical_sizes,
    geometries_for_size,
    geometry,
    geometry_for_boot_sector,
    geometry_for_layout,
    geometry_for_size,
    resolve_geometry,
)
from tests.msa_fixture import DS_720K, PC_360K, SS_360K, boot_sector


class GeometryTableTests(unittest.TestCase):
    def test_the_table_covers_every_st_shape_plus_pc_and_hd_media(self) -> None:
        st_family = {
            (tracks, sides, sectors)
            for tracks in (80, 81, 82, 83)
            for sides in (1, 2)
            for sectors in (9, 10, 11)
        }
        shapes = {(item.tracks, item.sides, item.sectors) for item in GEOMETRIES.values()}
        self.assertTrue(st_family <= shapes)
        self.assertEqual(shapes - st_family, {(40, 1, 9), (40, 2, 9), (80, 2, 18)})
        self.assertEqual(GEOMETRIES["hd-1440k"].size, 1_474_560)
        self.assertEqual(GEOMETRIES["pc-360k"].size, 368_640)
        self.assertEqual(GEOMETRIES["pc-180k"].size, 184_320)

    def test_the_everyday_disk_is_the_default(self) -> None:
        self.assertEqual(DEFAULT_GEOMETRY.identifier, "ds-80t-9s")
        self.assertEqual(DEFAULT_GEOMETRY.size, 737_280)
        self.assertEqual(DEFAULT_GEOMETRY.track_size, 4_608)
        self.assertEqual(DEFAULT_GEOMETRY.extension, ".st")

    def test_every_geometry_is_named_by_its_own_identifier(self) -> None:
        for identifier, item in GEOMETRIES.items():
            with self.subTest(identifier=identifier):
                self.assertEqual(item.identifier, identifier)
                self.assertEqual(item.sector_size, 512)
                self.assertIn("KiB", item.label)

    def test_lookup_ignores_case_and_padding_and_names_the_choices(self) -> None:
        self.assertIs(geometry("  DS-80T-9S "), DS_720K)
        with self.assertRaisesRegex(KeyError, "Choose a floppy geometry"):
            geometry("betamax")

    def test_canonical_sizes_are_the_table_sizes(self) -> None:
        sizes = canonical_sizes()
        self.assertIn(737_280, sizes)
        self.assertIn(819_200, sizes)  # 80 x 2 x 10
        self.assertIn(901_120, sizes)  # 80 x 2 x 11
        self.assertNotIn(737_280 - 512, sizes)
        # No two shapes are one sector apart, which is what makes the
        # tail-sector repair in the flux policy safe.
        for size in sizes:
            self.assertNotIn(size + 512, sizes)


class SizeResolutionTests(unittest.TestCase):
    def test_a_size_that_names_one_shape_is_resolved(self) -> None:
        self.assertIs(geometry_for_size(737_280), DS_720K)
        self.assertEqual(geometry_for_size(1_474_560).identifier, "hd-1440k")

    def test_360k_is_ambiguous_between_st_and_pc_media(self) -> None:
        """Eighty single-sided tracks and forty double-sided ones are the same size."""
        candidates = geometries_for_size(368_640)
        self.assertEqual({item.identifier for item in candidates}, {"ss-80t-9s", "pc-360k"})
        self.assertIsNone(geometry_for_size(368_640))
        # The side count settles it when the caller knows it.
        self.assertIs(geometry_for_size(368_640, sides=1), SS_360K)
        self.assertIs(geometry_for_size(368_640, sides=2), PC_360K)

    def test_eighty_tracks_are_preferred_when_listing_candidates(self) -> None:
        self.assertEqual(geometries_for_size(737_280)[0], DS_720K)
        self.assertEqual(geometries_for_size(368_640)[0], SS_360K)

    def test_an_unknown_size_names_nothing(self) -> None:
        self.assertEqual(geometries_for_size(12_345), [])
        self.assertIsNone(geometry_for_size(800 * 1024 + 512))


class BootSectorTests(unittest.TestCase):
    def test_the_bpb_settles_the_ambiguous_size(self) -> None:
        self.assertIs(geometry_for_boot_sector(boot_sector(SS_360K)), SS_360K)
        self.assertIs(geometry_for_boot_sector(boot_sector(PC_360K)), PC_360K)

    def test_the_bpb_is_read_little_endian_at_the_documented_offsets(self) -> None:
        boot = bytearray(512)
        boot[0x0B:0x0D] = (512).to_bytes(2, "little")
        boot[0x13:0x15] = (1600).to_bytes(2, "little")
        boot[0x18:0x1A] = (10).to_bytes(2, "little")
        boot[0x1A:0x1C] = (2).to_bytes(2, "little")
        self.assertEqual(geometry_for_boot_sector(bytes(boot)).identifier, "ds-80t-10s")

    def test_a_shape_outside_the_table_is_still_believed(self) -> None:
        boot = bytearray(512)
        boot[0x0B:0x0D] = (512).to_bytes(2, "little")
        boot[0x13:0x15] = (84 * 2 * 10).to_bytes(2, "little")
        boot[0x18:0x1A] = (10).to_bytes(2, "little")
        boot[0x1A:0x1C] = (2).to_bytes(2, "little")
        found = geometry_for_boot_sector(bytes(boot))
        self.assertEqual((found.tracks, found.sides, found.sectors), (84, 2, 10))
        self.assertNotIn(found.identifier, GEOMETRIES)

    def test_a_blank_or_contradictory_boot_sector_names_nothing(self) -> None:
        self.assertIsNone(geometry_for_boot_sector(bytes(512)))
        self.assertIsNone(geometry_for_boot_sector(b"\x00" * 10))
        boot = bytearray(boot_sector(DS_720K))
        boot[0x13:0x15] = (1441).to_bytes(2, "little")  # not a whole number of tracks
        self.assertIsNone(geometry_for_boot_sector(bytes(boot)))
        boot = bytearray(boot_sector(DS_720K))
        boot[0x0B:0x0D] = (1024).to_bytes(2, "little")
        self.assertIsNone(geometry_for_boot_sector(bytes(boot)))
        boot = bytearray(boot_sector(DS_720K))
        boot[0x1A] = 3
        self.assertIsNone(geometry_for_boot_sector(bytes(boot)))


class ResolutionPolicyTests(unittest.TestCase):
    def test_the_boot_sector_wins_over_the_size(self) -> None:
        self.assertIs(resolve_geometry(368_640, boot_sector(PC_360K)), PC_360K)
        self.assertIs(resolve_geometry(368_640, boot_sector(SS_360K)), SS_360K)

    def test_a_boot_sector_that_disagrees_with_the_size_is_ignored(self) -> None:
        # A boot sector copied from a 720 KiB disk onto a 360 KiB file says
        # nothing about this file, so the size alone decides, and cannot.
        self.assertIsNone(resolve_geometry(368_640, boot_sector(DS_720K)))
        self.assertIs(resolve_geometry(737_280, boot_sector(SS_360K)), DS_720K)

    def test_without_a_boot_sector_an_unambiguous_size_decides(self) -> None:
        self.assertIs(resolve_geometry(737_280), DS_720K)
        self.assertIs(resolve_geometry(737_280, bytes(512)), DS_720K)
        self.assertIsNone(resolve_geometry(368_640, bytes(512)))

    def test_an_explicit_layout_comes_from_the_table_when_it_can(self) -> None:
        self.assertIs(geometry_for_layout(80, 2, 9), DS_720K)
        custom = geometry_for_layout(84, 2, 11)
        self.assertEqual(custom.size, 84 * 2 * 11 * 512)
        self.assertNotIn(custom.identifier, GEOMETRIES)


if __name__ == "__main__":
    unittest.main()
