import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.disk_service import DiskError, DiskService
from app.download_archive import build_download_archive
from app.rom import (
    CARTRIDGE_BASE,
    DEFAULT_BANK_SIZE,
    RomError,
    entry_point_candidates,
    entry_point_inventory,
    inspect_bank,
    inspect_image,
    make_cartridge_rom,
    parse_cartridge_header,
    parse_rom_header,
    rename_cartridge,
    rom_base,
    system_fonts,
)

EMUTOS_DIR = Path(__file__).resolve().parent.parent / "firmware" / "emutos"
TOS_192K = 192 * 1024
TOS_256K = 256 * 1024
TOS_512K = 512 * 1024


def emutos(name: str = "etos192uk.img") -> bytes:
    return (EMUTOS_DIR / name).read_bytes()


class RomHeaderTests(unittest.TestCase):
    def test_a_tos_header_is_parsed(self):
        header = parse_rom_header(emutos())
        self.assertIsNotNone(header)
        self.assertEqual(header.title, "EmuTOS 1.4 UK")
        self.assertEqual(header.version, "1.4")
        self.assertEqual(header.release, "EmuTOS 1.4")
        self.assertEqual(header.roles, "EmuTOS")
        self.assertEqual(header.version_word, 0x0104)
        self.assertEqual(header.base, rom_base(TOS_192K))
        self.assertEqual(header.reset_vector, 0xFC0030)
        self.assertEqual(header.country, "United Kingdom")
        self.assertEqual(header.video_standard, "PAL")
        self.assertEqual(header.date, "2025-06-07")
        self.assertTrue(header.dates_agree)
        self.assertTrue(header.size_valid)
        self.assertTrue(header.base_valid)
        self.assertEqual(header.processor, "68000")
        self.assertGreater(header.entry_count, 5)
        self.assertEqual(header.font_count, 3)

    def test_a_256k_image_uses_the_e00000_base(self):
        header = parse_rom_header(emutos("etos256us.img"))
        self.assertIsNotNone(header)
        self.assertEqual(header.base, 0xE00000)
        self.assertEqual(header.country_short, "us")
        self.assertFalse(header.pal)
        self.assertEqual(header.version_word, 0x0206)

    def test_bytes_without_a_header_are_not_guessed_at(self):
        self.assertIsNone(parse_rom_header(bytes(4096)))
        self.assertIsNone(parse_rom_header(b"\xff" * 4096))
        self.assertIsNone(parse_rom_header(b"\x60\x2e" + bytes(4094)))

    def test_a_cartridge_is_the_other_recognised_shape(self):
        data = make_cartridge_rom(64 * 1024, "Diag")
        self.assertIsNone(parse_rom_header(data))
        cartridge = parse_cartridge_header(data)
        self.assertIsNotNone(cartridge)
        self.assertEqual(cartridge.title, "DIAG.PRG")
        self.assertEqual(cartridge.base, CARTRIDGE_BASE)
        self.assertTrue(cartridge.size_valid)

    def test_a_wrong_base_is_reported_rather_than_ignored(self):
        rom = bytearray(emutos("etos256uk.img"))
        # Keep the branch and reset vector consistent while moving the base.
        rom[4:8] = (0xFC0030).to_bytes(4, "big")
        rom[8:12] = (0xFC0000).to_bytes(4, "big")
        header = parse_rom_header(bytes(rom))
        self.assertIsNotNone(header)
        self.assertFalse(header.base_valid)
        row = inspect_bank(bytes(rom), 0)
        self.assertTrue(any("$E00000" in warning for warning in row["warnings"]), row["warnings"])

    def test_a_date_word_mismatch_is_reported(self):
        rom = bytearray(emutos())
        rom[0x1E:0x20] = b"\x00\x21"
        row = inspect_bank(bytes(rom), 0)
        self.assertFalse(row["header"]["datesAgree"])
        self.assertTrue(any("date word" in warning for warning in row["warnings"]), row["warnings"])


class EntryPointTests(unittest.TestCase):
    def test_entry_points_are_listed_with_their_evidence(self):
        rows = entry_point_candidates(emutos())
        titles = [row["title"] for row in rows]
        self.assertIn("Reset code", titles)
        self.assertIn("BIOS dispatch table", titles)
        self.assertIn("VDI entry", titles)
        table = next(row for row in rows if row["title"] == "BIOS dispatch table")
        self.assertEqual(table["length"], 48)
        self.assertEqual(table["confidence"], "declared")
        self.assertIn("LEA", table["help"])
        self.assertEqual(rows, sorted(rows, key=lambda row: row["offset"]))

    def test_the_inventory_reports_what_a_rom_answers(self):
        rows = entry_point_candidates(emutos())
        inventory = entry_point_inventory(emutos(), rows)
        names = {row["name"] for row in inventory}
        self.assertIn("XBIOS TRAP #14 handler", names)
        self.assertIn("AES initialisation", names)
        self.assertTrue(all(row["confidence"] == "declared" for row in inventory))

    def test_nothing_is_listed_for_bytes_that_are_not_a_rom(self):
        self.assertEqual(entry_point_candidates(bytes(4096)), [])
        self.assertEqual(system_fonts(bytes(4096)), [])

    def test_system_fonts_are_reported_with_their_ranges(self):
        fonts = system_fonts(emutos())
        self.assertEqual([font["name"] for font in fonts], ["6x6 system font", "8x8 system font", "8x16 system font"])
        self.assertEqual(fonts[1]["cellHeight"], 8)
        self.assertEqual(fonts[2]["cellHeight"], 16)
        self.assertLess(fonts[0]["glyphData"][0], fonts[0]["glyphData"][1])

    def test_a_decoded_bank_exposes_structures_entry_points_and_strings(self):
        row = inspect_bank(emutos(), 0, include_contents=True, include_entry_points=True)
        kinds = [item["kind"] for item in row["structures"]]
        self.assertEqual(kinds[0], "header")
        self.assertIn("entry", kinds)
        self.assertIn("table", kinds)
        self.assertIn("font", kinds)
        self.assertEqual(row["filetype"], "EmuTOS 1.4 · UK PAL")
        self.assertEqual(row["header"]["emutosVersion"], "1.4")
        self.assertIn("EmuTOS Version", [item["text"] for item in row["strings"]])
        self.assertTrue(row["modules"])
        self.assertTrue(row["starCommands"])
        self.assertEqual(len(row["fonts"]), 3)

    def test_a_continuation_bank_is_named_after_the_whole_image(self):
        data = emutos()
        image_header = parse_rom_header(data)
        first = inspect_bank(data[:DEFAULT_BANK_SIZE], 0, image_header=image_header)
        self.assertEqual(first["warnings"], [])
        self.assertTrue(any("GEMDOS TRAP #1" in note for note in first["notes"]))
        alone = inspect_bank(data[:DEFAULT_BANK_SIZE], 0)
        self.assertTrue(any("not a TOS size" in warning for warning in alone["warnings"]))
        row = inspect_bank(data[DEFAULT_BANK_SIZE : 2 * DEFAULT_BANK_SIZE], 1, image_header=image_header)
        self.assertIsNone(row["header"])
        self.assertEqual(row["name"], "EmuTOS 1.4 UK (continued)")
        self.assertIn("continuation", row["filetype"])
        self.assertEqual(row["structures"][0]["address"], 0xFC0000 + DEFAULT_BANK_SIZE)


class RomTemplateTests(unittest.TestCase):
    def test_a_cartridge_template_is_a_valid_cartridge(self):
        rom = make_cartridge_rom(128 * 1024, "Forge")
        cartridge = parse_cartridge_header(rom)
        self.assertIsNotNone(cartridge)
        self.assertEqual(cartridge.title, "FORGE.PRG")
        self.assertEqual(len(cartridge.applications), 1)
        run = cartridge.applications[0]["run"] - CARTRIDGE_BASE
        self.assertEqual(rom[run : run + 2], b"\x4e\x75")

    def test_a_cartridge_larger_than_the_port_is_refused(self):
        with self.assertRaisesRegex(RomError, "128 KiB"):
            make_cartridge_rom(TOS_256K, "Big")

    def test_a_cartridge_name_is_rewritten_in_place(self):
        rom = make_cartridge_rom(16 * 1024, "Forge")
        renamed = rename_cartridge(rom, "tool.tos")
        self.assertEqual(parse_cartridge_header(renamed).title, "TOOL.TOS")
        self.assertEqual(len(renamed), len(rom))
        self.assertEqual(renamed[:0x18], rom[:0x18])
        with self.assertRaises(RomError):
            rename_cartridge(rom, "far too long a name.prg")
        with self.assertRaises(RomError):
            rename_cartridge(emutos(), "TOS.PRG")


class RomServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = DiskService(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_a_192k_tos_image_is_listed_as_three_64k_banks(self):
        session = self.service.create_from_stream(
            "etos192uk.rom", io.BytesIO(emutos()), rom_options={"platform": "tos"},
        )
        rows = self.service.list_rom_banks(session)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["name"], "EmuTOS 1.4 UK")
        self.assertIn("continuation", rows[1]["filetype"])
        self.assertEqual(rows[2]["imageHeader"]["release"], "EmuTOS 1.4")
        decoded = self.service.inspect_rom_bank(session, 0)
        self.assertEqual(decoded["fileOffset"], 0)
        self.assertEqual(decoded["header"]["release"], "EmuTOS 1.4")
        self.assertEqual(decoded["warnings"], [])
        self.assertTrue(decoded["modules"])
        continuation = self.service.inspect_rom_bank(session, 2)
        self.assertEqual(continuation["name"], "EmuTOS 1.4 UK (continued)")
        self.assertEqual(len(decoded["diagnostics"]["sha256"]), 64)
        rows = inspect_image(session.path, DEFAULT_BANK_SIZE)
        self.assertEqual([row["bank"] for row in rows], [0, 1, 2])

    def test_a_tos_rom_cannot_be_renamed_but_a_cartridge_can(self):
        tos = self.service.create_from_stream("etos192uk.rom", io.BytesIO(emutos()))
        with self.assertRaisesRegex(DiskError, "cannot be renamed"):
            self.service.rename_rom_bank(tos, 0, "OTHER.PRG")
        cartridge = self.service.create_from_stream(
            "cart.rom", io.BytesIO(make_cartridge_rom(64 * 1024, "Forge")),
            rom_options={"platform": "cartridge"},
        )
        self.service.rename_rom_bank(cartridge, 0, "tool.tos")
        self.assertEqual(self.service.list_rom_banks(cartridge)[0]["name"], "TOOL.TOS")

    def test_an_opened_rom_layout_survives_recovery(self):
        session = self.service.create_from_stream(
            "chips.rom",
            io.BytesIO(bytes(range(256)) * 128),
            rom_options={
                "platform": "cartridge",
                "layout": "byte-interleaved-4",
                "componentNames": ["u34.rom", "u35.rom", "u36.rom", "u37.rom"],
            },
        )
        restored = DiskService(self.temporary.name)._restore_session(session.id)
        self.assertEqual(restored.rom_layout, "byte-interleaved-4")
        self.assertEqual(restored.rom_component_names[0], "u34.rom")

    def test_an_overlapping_bank_move_reads_sources_before_writing(self):
        session = self.service.create_blank(
            "rom", "Move", options={"totalSize": 4 * 1024, "bankSize": 1024}
        )
        for bank, value in enumerate((1, 2, 3, 4)):
            self.service.put_rom_bank(session, bytes((value,)) * 1024, bank)
        self.service.move_rom_banks(session, [0, 1, 2], 1)
        self.assertEqual(self.service.rom_bank_bytes(session, "bank:1")[:1], b"\x01")
        self.assertEqual(self.service.rom_bank_bytes(session, "bank:2")[:1], b"\x02")
        self.assertEqual(self.service.rom_bank_bytes(session, "bank:3")[:1], b"\x03")
        self.assertTrue(self.service.list_rom_banks(session)[0]["empty"])

    def test_a_bank_import_rejects_implicit_truncation(self):
        session = self.service.create_blank(
            "rom", "Small", options={"totalSize": 4096, "bankSize": 4096}
        )
        with self.assertRaisesRegex(DiskError, "does not fit"):
            self.service.put_rom_bank(session, b"x" * 4097)

    def test_interleaved_component_export_restores_chip_order(self):
        """A TOS ROM on two byte-wide chips is even and odd bytes, in order."""
        logical = bytes((0, 10, 20, 30, 1, 11, 21, 31))
        session = self.service.create_from_stream(
            "set.rom",
            io.BytesIO(logical),
            rom_options={
                "layout": "byte-interleaved-4",
                "componentNames": ["a.rom", "b.rom", "c.rom", "d.rom"],
            },
        )
        exports = self.service.rom_component_exports(session)
        self.assertEqual(
            [path.read_bytes() for path, _name in exports],
            [b"\x00\x01", b"\x0a\x0b", b"\x14\x15", b"\x1e\x1f"],
        )

    def test_a_saved_interleaved_rom_contains_its_readme_and_physical_chips(self):
        session = self.service.create_from_stream(
            "set.rom",
            io.BytesIO(bytes((0, 10, 20, 30, 1, 11, 21, 31))),
            rom_options={
                "platform": "cartridge",
                "layout": "byte-interleaved-4",
                "componentNames": ["u34.rom", "u35.rom", "u36.rom", "u37.rom"],
            },
        )
        archive_path, _name = build_download_archive(self.service, session)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIn("set.rom", archive.namelist())
            self.assertIn("README.md", archive.namelist())
            self.assertEqual(archive.read("ROM-components/u34.rom"), b"\x00\x01")
            readme = archive.read("README.md").decode()
            self.assertIn("byte-interleaved-4", readme)
            self.assertIn("u34.rom", readme)


if __name__ == "__main__":
    unittest.main()
