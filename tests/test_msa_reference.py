"""Cross-check the container codec against an independent implementation.

The tests beside this one prove the codec is self-consistent: what it packs it
unpacks. That is necessary and not sufficient, because a codec can be
self-consistent and still disagree with every other tool that reads the format.

The fixtures here were produced by the Greaseweazle host tools, which carry
their own reader and writer for this container and share no code with this
project. `reference-720k.st` is a synthetic volume built to exercise the
packer: whole tracks of zero, whole tracks of the escape byte itself,
incompressible noise, and a mixture of runs and literals.
`reference-720k.msa` is what the other tool made of it.

Committing both means the guarantee survives without the tool being installed,
which matters because continuous integration does not have it.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from app.floppy_geometry import geometry_for_boot_sector
from app.msa import is_msa, msa_project, msa_to_st, parse_msa, st_to_msa

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SECTORS = FIXTURES / "reference-720k.st"
CONTAINER = FIXTURES / "reference-720k.msa"


class ReferenceContainerTests(unittest.TestCase):
    """The codec must agree with a reader and writer written by someone else."""

    @classmethod
    def setUpClass(cls) -> None:
        if not SECTORS.is_file() or not CONTAINER.is_file():
            raise unittest.SkipTest("the reference fixtures are not present")
        cls.sectors = SECTORS.read_bytes()
        cls.container = CONTAINER.read_bytes()

    def test_the_reference_container_is_recognised(self) -> None:
        self.assertTrue(is_msa(self.container))
        self.assertFalse(is_msa(self.sectors))

    def test_the_reference_geometry_is_read_from_the_container(self) -> None:
        image = parse_msa(self.container)
        self.assertEqual(image.sectors_per_track, 9)
        self.assertEqual(image.sides, 2)
        self.assertEqual(image.start_track, 0)
        self.assertEqual(image.end_track, 79)

    def test_decoding_the_reference_reproduces_the_original_sectors(self) -> None:
        """The other tool's output must decode to the bytes it was given."""
        self.assertEqual(msa_to_st(self.container), self.sectors)

    def test_encoding_reproduces_the_reference_container_byte_for_byte(self) -> None:
        """Packing decisions must match, not merely the sectors they carry.

        This is the strict half. Two containers can decode to identical
        sectors while disagreeing about which tracks were worth packing, and a
        reader that only checked the sectors would not notice.
        """
        self.assertEqual(st_to_msa(self.sectors), self.container)

    def test_the_boot_sector_resolves_the_geometry(self) -> None:
        """Size alone is ambiguous here, so the boot sector has to decide."""
        geometry = geometry_for_boot_sector(self.sectors[:512])
        self.assertIsNotNone(geometry)
        self.assertEqual(geometry.sectors, 9)
        self.assertEqual(geometry.sides, 2)
        self.assertEqual(geometry.tracks, 80)
        self.assertEqual(geometry.size, len(self.sectors))

    def test_the_project_report_covers_every_track_and_side(self) -> None:
        report = msa_project(self.container)
        rows = report["tracks"] if isinstance(report, dict) else report
        self.assertEqual(len(rows), 160)
        packed = [row for row in rows if row.get("compressed")]
        raw = [row for row in rows if not row.get("compressed")]
        # The fixture was built so that both decisions are exercised: the noise
        # tracks cannot be packed and the run tracks must be.
        self.assertTrue(packed, "no track was packed")
        self.assertTrue(raw, "no track was left raw")
        for row in rows:
            self.assertEqual(row["unpackedLength"], 9 * 512)


if __name__ == "__main__":  # pragma: no cover - convenience
    unittest.main()
