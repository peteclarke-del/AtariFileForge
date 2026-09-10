from __future__ import annotations

import unittest

from app.formats import (
    DIM_EXTENSIONS,
    GEMDOS_EXTENSIONS,
    GEOMETRY_EXTENSIONS,
    HARD_DISK_EXTENSIONS,
    HFE_EXTENSIONS,
    IPF_EXTENSIONS,
    ISO_EXTENSIONS,
    MSA_EXTENSIONS,
    ROM_EXTENSIONS,
    SCP_EXTENSIONS,
    ST_EXTENSIONS,
    STX_EXTENSIONS,
)

try:
    from app.disk_service import DiskService
except ImportError:  # the service is ported separately
    DiskService = None


class FormatTests(unittest.TestCase):
    def test_each_floppy_container_has_exactly_its_own_suffix(self):
        self.assertEqual(ST_EXTENSIONS, {".st"})
        self.assertEqual(MSA_EXTENSIONS, {".msa"})
        self.assertEqual(DIM_EXTENSIONS, {".dim"})
        self.assertEqual(STX_EXTENSIONS, {".stx"})
        self.assertEqual(HFE_EXTENSIONS, {".hfe"})
        self.assertEqual(SCP_EXTENSIONS, {".scp"})
        self.assertEqual(IPF_EXTENSIONS, {".ipf"})
        self.assertEqual(ISO_EXTENSIONS, {".iso", ".cdr"})
        self.assertEqual(GEOMETRY_EXTENSIONS, {".geo"})

    def test_hard_disk_images_come_under_every_name_they_are_distributed_as(self):
        self.assertEqual(
            HARD_DISK_EXTENSIONS, {".img", ".hd", ".ahd", ".acsi", ".ide", ".raw", ".bin"}
        )

    def test_img_and_bin_are_ambiguous_between_rom_and_hard_disk(self):
        """The byte probe decides; the sets only say which probes to run."""
        self.assertEqual(ROM_EXTENSIONS, {".img", ".rom", ".tos", ".bin"})
        self.assertEqual(ROM_EXTENSIONS & HARD_DISK_EXTENSIONS, {".img", ".bin"})

    def test_everything_that_may_hold_a_fat_volume_is_a_gemdos_extension(self):
        for extension in (".st", ".msa", ".dim", ".stx", ".hfe", ".scp", ".ipf", ".img", ".hd", ".acsi"):
            with self.subTest(extension=extension):
                self.assertIn(extension, GEMDOS_EXTENSIONS)
        for extension in (".tos", ".rom", ".iso", ".geo", ".zip"):
            with self.subTest(extension=extension):
                self.assertNotIn(extension, GEMDOS_EXTENSIONS)

    def test_no_previous_platform_suffix_survives(self):
        everything = GEMDOS_EXTENSIONS | ROM_EXTENSIONS | ISO_EXTENSIONS | GEOMETRY_EXTENSIONS
        for extension in (".adf", ".adz", ".dms", ".hdf", ".hdz", ".rdsk", ".kick"):
            with self.subTest(extension=extension):
                self.assertNotIn(extension, everything)


@unittest.skipIf(DiskService is None, "DiskService imports once the service is ported")
class DetectKindTests(unittest.TestCase):
    """What ``detect_kind`` must answer once the service is ported."""

    def test_floppy_suffixes_name_their_container_kind(self):
        expected = {
            ".st": "gemdos",
            ".msa": "msa",
            ".dim": "dim",
            ".stx": "stx",
            ".hfe": "hfe",
            ".scp": "scp",
            ".ipf": "ipf",
            ".iso": "iso",
            ".tos": "rom",
        }
        for extension, kind in expected.items():
            with self.subTest(extension=extension):
                self.assertEqual(DiskService.detect_kind(f"Games{extension}"), kind)

    def test_extensionless_images_are_content_detected(self):
        self.assertEqual(DiskService.detect_kind("HardDisk4"), "unknown")


if __name__ == "__main__":
    unittest.main()
