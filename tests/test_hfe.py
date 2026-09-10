from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.hfe import HFEError, parse_hfe_header

try:
    from app.disk_service import DiskError, DiskService, ImageSession
except ImportError:  # the service is ported separately
    DiskService = None


def header(signature: bytes = b"HXCPICFE", revision: int = 0, sides: int = 2) -> bytes:
    data = bytearray(512)
    data[:8] = signature
    data[8] = revision
    data[9] = 80
    data[10] = sides
    data[11] = 2
    data[12:14] = (250).to_bytes(2, "little")
    return bytes(data)


class HFETests(unittest.TestCase):
    def test_v1_header_geometry_is_parsed(self) -> None:
        parsed = parse_hfe_header(header())
        self.assertEqual((parsed.version, parsed.tracks, parsed.sides), ("v1", 80, 2))
        self.assertFalse(parsed.advanced)

    def test_a_single_sided_header_is_parsed(self) -> None:
        self.assertEqual(parse_hfe_header(header(sides=1)).sides, 1)

    def test_v2_and_v3_are_advanced(self) -> None:
        self.assertTrue(parse_hfe_header(header(revision=1)).advanced)
        self.assertEqual(parse_hfe_header(header(b"HXCHFEV3")).version, "v3")

    def test_invalid_signature_is_rejected(self) -> None:
        with self.assertRaisesRegex(HFEError, "valid HFE signature"):
            parse_hfe_header(header(b"NOTANHFE"))

    def test_an_incomplete_header_is_rejected(self) -> None:
        with self.assertRaisesRegex(HFEError, "incomplete"):
            parse_hfe_header(header()[:100])
        with self.assertRaisesRegex(HFEError, "track geometry"):
            parse_hfe_header(header(sides=3))


@unittest.skipIf(DiskService is None, "DiskService imports once the service is ported")
class HFEServiceTests(unittest.TestCase):
    """What the disk service must do with an HFE once it is ported."""

    def test_hfe_extension_uses_container_decoder(self) -> None:
        self.assertEqual(DiskService.detect_kind("disk.hfe"), "hfe")

    def test_decoded_non_atari_hfe_reports_container_and_filesystem_distinction(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            original = Path(folder) / "foreign.hfe"
            original.write_bytes(header())
            service = DiskService(Path(folder) / "work")

            def convert(arguments):
                output = next(
                    (item.removeprefix("-foutput:") for item in arguments if item.startswith("-foutput:")),
                    None,
                )
                if output:
                    Path(output).write_bytes(bytes(737_280))
                return "Number of bad sectors : 0"

            with (
                patch.object(service, "_run_hxcfe", side_effect=convert),
                patch.object(
                    service,
                    "identify_kind",
                    side_effect=DiskError("No supported Atari filesystem was found."),
                ),
            ):
                with self.assertRaisesRegex(
                    DiskError,
                    "container is valid, but its contents cannot be browsed",
                ):
                    service._open_hfe(original)

    def test_advanced_hfe_working_copy_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "decoded.st"
            image.write_bytes(b"")
            session = ImageSession(
                "a" * 32,
                "protected.hfe",
                "gemdos",
                image,
                hfe_original_path=Path(folder) / "protected.hfe",
                hfe_version="v3",
                hfe_read_only=True,
            )
            with self.assertRaisesRegex(DiskError, "cannot be rewritten safely"):
                DiskService.require_writable_geometry(session)

    @unittest.skipIf(
        shutil.which("hxcfe") is None,
        "HxCFE is installed in the application container",
    )
    def test_every_creatable_hfe_geometry_opens_and_browses(self) -> None:
        expected = {
            "hfe-st-720k": ("gemdos", 737_280),
            "hfe-st-360k": ("gemdos", 368_640),
            "hfe-st-800k": ("gemdos", 819_200),
            "hfe-st-1440k": ("gemdos", 1_474_560),
        }
        with tempfile.TemporaryDirectory() as folder:
            service = DiskService(Path(folder) / "work")
            for format_name, (kind, decoded_size) in expected.items():
                with self.subTest(format=format_name):
                    created = service.create_blank(format_name, "Wrapped")
                    source_hfe = created.hfe_original_path
                    if format_name == "hfe-st-720k":
                        payload = Path(folder) / "hfe-test-file"
                        payload.write_bytes(b"Browseable HFE content\n")
                        service.put(created, "TEST", payload)
                        source_hfe = service.prepare_download(created)
                    with source_hfe.open("rb") as image:
                        reopened = service.create_from_stream(created.name, image)
                    self.assertEqual(reopened.kind, kind)
                    self.assertEqual(reopened.path.stat().st_size, decoded_size)
                    listing = service.browse_directory(reopened, "", None)
                    self.assertEqual(
                        [entry["name"] for entry in listing["entries"]],
                        ["TEST"] if format_name == "hfe-st-720k" else [],
                    )


if __name__ == "__main__":
    unittest.main()
