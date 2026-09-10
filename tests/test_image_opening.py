from __future__ import annotations

import gzip
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.disk_service import DiskService
from app.errors import DiskError
from app.image_opening import open_image_path
from app.rom_components import write_combined_rom


#: A double-sided 720 KiB floppy, the shape most ST software shipped on.
FLOPPY_SIZE = 737_280


def _blank_floppy(root: Path) -> bytes:
    """Return the sectors of a freshly formatted ST floppy."""
    service = DiskService(root / "source-work")
    session = service.create_blank("ds-720k", "COMPRESS")
    try:
        return session.path.read_bytes()
    finally:
        service.discard_session(session)


class ImageOpeningTests(unittest.TestCase):
    def test_empty_native_rom_component_set_is_rejected(self):
        with TemporaryDirectory() as temporary:
            output = Path(temporary) / "combined.rom"

            with self.assertRaisesRegex(ValueError, "at least one"):
                write_combined_rom([], output)

    def test_unknown_native_rom_layout_is_rejected_before_writing(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            component = root / "component.rom"
            component.write_bytes(b"data")
            output = root / "combined.rom"

            with self.assertRaisesRegex(ValueError, "linear, two-chip or four-chip"):
                write_combined_rom([component], output, "byte-interleaved-many")

            self.assertFalse(output.exists())

    def test_native_rom_components_use_the_reviewed_interleaving_plan(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "rom0.bin"
            second = root / "rom1.bin"
            first.write_bytes(b"ac")
            second.write_bytes(b"bd")
            output = root / "combined.rom"
            write_combined_rom([first, second], output, "byte-interleaved-2")

            self.assertEqual(output.read_bytes(), b"abcd")

    def test_native_rom_layout_component_count_must_match(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            components = []
            for index in range(4):
                component = root / f"rom{index}.bin"
                component.write_bytes(bytes([index]))
                components.append(component)

            with self.assertRaisesRegex(ValueError, "requires exactly 2"):
                write_combined_rom(
                    components,
                    root / "combined.rom",
                    "byte-interleaved-2",
                )

            self.assertFalse((root / "combined.rom").exists())

    def test_a_trusted_desktop_path_opens_without_a_geometry_argument(self):
        """A desktop open takes a path and nothing beside it.

        A GEMDOS volume carries its own parameter block, so the shape of the
        disk is read out of the boot sector rather than supplied alongside the
        file. Opening one is a path and a target machine.
        """
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "Games.st"
            image.write_bytes(_blank_floppy(root))
            service = DiskService(root / "work")

            session = open_image_path(service, image, target_hardware="floppy")

            self.assertEqual(session.kind, "gemdos")
            self.assertEqual(session.target_hardware, "floppy")
            self.assertEqual(session.distribution_name, "Games.st")
            # The source is untouched: every edit lands in the session copy.
            self.assertNotEqual(session.path, image)
            self.assertEqual(session.path.read_bytes(), image.read_bytes())


class CompressedImageTests(unittest.TestCase):
    """A gzipped sector image holds a disk, so the disk is what is opened."""

    def test_a_gzipped_sector_image_opens_as_the_disk_inside_it(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sectors = _blank_floppy(root)
            service = DiskService(root / "work")

            session = service.create_from_stream(
                "Compressed.st.gz", io.BytesIO(gzip.compress(sectors, mtime=0))
            )

            self.assertEqual(session.kind, "gemdos")
            self.assertEqual(session.path.stat().st_size, FLOPPY_SIZE)
            self.assertEqual(session.path.read_bytes(), sectors)

    def test_a_truncated_gzip_image_is_refused_with_an_explanation(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sectors = _blank_floppy(root)
            compressed = gzip.compress(sectors, mtime=0)
            truncated = compressed[: len(compressed) // 2]
            service = DiskService(root / "work")

            with self.assertRaisesRegex(DiskError, "truncated or damaged"):
                service.create_from_stream("Broken.st.gz", io.BytesIO(truncated))

    def test_an_uncompressed_image_named_gz_is_left_exactly_as_it_is(self):
        """The extension is a hint; the first two bytes are the decision."""
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sectors = _blank_floppy(root)
            service = DiskService(root / "work")

            session = service.create_from_stream("Plain.st.gz", io.BytesIO(sectors))

            self.assertEqual(session.kind, "gemdos")
            self.assertEqual(session.path.read_bytes(), sectors)

    def test_a_gzipped_image_exports_back_to_the_same_sectors(self):
        """Expanding on the way in is not allowed to change a single byte.

        There is no gzip export, because a compressed wrapper is how a disk is
        distributed rather than a shape TOS reads. What has to hold is that
        the sectors written back out are the sectors that went in.
        """
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            sectors = _blank_floppy(root)
            service = DiskService(root / "work")
            session = service.create_from_stream(
                "Disk.st.gz", io.BytesIO(gzip.compress(sectors, mtime=0))
            )

            output, name = service.export_image(session, "native")

            self.assertTrue(name.endswith(".st"))
            self.assertEqual(output.read_bytes(), sectors)


if __name__ == "__main__":
    unittest.main()
