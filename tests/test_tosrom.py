"""Tests for the TOS ROM engine.

EmuTOS 1.4 is committed under ``firmware/emutos`` and is always exercised.
Atari's own TOS releases are not redistributable, so those tests look for
them in ``ATARI_FILE_FORGE_TOS_DIR``, then in ``firmware/tos`` of this
checkout, then in the main checkout, and skip when none is present.
"""

import os
import struct
import tempfile
import unittest
from datetime import date
from pathlib import Path

from atarinut.errors import DataError
from atarinut.filesystem import reader_for
from atarinut.tosrom import (
    CARTRIDGE_BASE,
    ROM_BASES,
    TOS_SIZES,
    TOSROM,
    CartridgeRom,
    TOSMount,
    TOSRom,
    build_cartridge_rom,
    decode_bcd_date,
    decode_dos_date,
    is_cartridge_rom,
    is_tos_rom,
    parse_tos_header,
)

REPO = Path(__file__).resolve().parent.parent
EMUTOS_DIR = REPO / "firmware" / "emutos"
MAIN_CHECKOUT_TOS = Path(
    "/home/pclarke/ownCloud/Projects/Personal Projects/Utilities/Atari File Forge/firmware/tos"
)

#: Size, base, compatibility version word, country code and PAL flag.
EMUTOS_IMAGES = {
    "etos192uk.img": (192 * 1024, 0xFC0000, 0x0104, 3, True),
    "etos192us.img": (192 * 1024, 0xFC0000, 0x0104, 0, False),
    "etos256uk.img": (256 * 1024, 0xE00000, 0x0206, 3, True),
    "etos256us.img": (256 * 1024, 0xE00000, 0x0206, 0, False),
    "etos512uk.img": (512 * 1024, 0xE00000, 0x0206, 3, True),
    "etos512us.img": (512 * 1024, 0xE00000, 0x0206, 0, False),
    "etos1024k.img": (1024 * 1024, 0xE00000, 0x0206, 127, True),
}

#: Version word, size, base, country code, PAL flag and build date.
TOS_IMAGES = {
    "tos100uk.img": (0x0100, 192 * 1024, 0xFC0000, 3, True, "1985-11-20"),
    "tos104uk.img": (0x0104, 192 * 1024, 0xFC0000, 3, True, "1989-04-06"),
    "tos162uk.img": (0x0162, 256 * 1024, 0xE00000, 3, True, "1990-01-01"),
    "tos206uk.img": (0x0206, 256 * 1024, 0xE00000, 3, True, "1991-11-14"),
    "tos306uk.img": (0x0306, 512 * 1024, 0xE00000, 3, True, "1991-09-24"),
    "tos404.img": (0x0404, 512 * 1024, 0xE00000, 127, True, "1993-03-08"),
}


def tos_directory() -> Path | None:
    candidates = []
    configured = os.environ.get("ATARI_FILE_FORGE_TOS_DIR")
    if configured:
        candidates.append(Path(configured))
    candidates.append(REPO / "firmware" / "tos")
    candidates.append(MAIN_CHECKOUT_TOS)
    return next((path for path in candidates if path.is_dir()), None)


def emutos(name: str) -> bytes:
    return (EMUTOS_DIR / name).read_bytes()


def real_tos(test: unittest.TestCase, name: str) -> bytes:
    folder = tos_directory()
    if folder is None or not (folder / name).is_file():
        test.skipTest(f"{name} is not available; set ATARI_FILE_FORGE_TOS_DIR to test real TOS ROMs")
    return (folder / name).read_bytes()


def build_tos_image(
    size: int = 192 * 1024,
    *,
    version: int = 0x0104,
    base: int | None = None,
    country: int = 3,
    pal: bool = True,
    when: date = date(1989, 4, 6),
    dos_date: int | None = None,
    with_font: bool = True,
) -> bytearray:
    """Assemble a ROM with a valid header, vector installs, dispatch stubs and a font.

    Everything a real machine's reset path touches is present, so a test that
    passes here would decode the same way on an image taken from a board.
    """
    base = ROM_BASES[size] if base is None else base
    rom = bytearray(size)
    struct.pack_into(">HH", rom, 0, 0x602E, version)
    struct.pack_into(">II", rom, 4, base + 0x30, base)
    struct.pack_into(">II", rom, 0x0C, 0x8000, base + 0x30)
    struct.pack_into(">I", rom, 0x14, base + 0x700)
    bcd = int(f"{when.month:02d}{when.day:02d}{when.year:04d}", 16)
    struct.pack_into(">IH", rom, 0x18, bcd, (country << 1) | int(pal))
    if dos_date is None:
        dos_date = ((when.year - 1980) << 9) | (when.month << 5) | when.day
    struct.pack_into(">H", rom, 0x1E, dos_date)
    struct.pack_into(">III", rom, 0x20, 0x3000, 0xE7D, 0x5622)
    # Reset code: MOVE.W #$2700,SR / RESET, then the vector installs.
    code = bytearray(bytes.fromhex("46fc2700 4e70".replace(" ", "")))
    for vector, target in ((0xB4, 0x200), (0xB8, 0x210), (0x84, 0x400), (0x88, 0x500), (0x28, 0x900)):
        code += struct.pack(">HIH", 0x21FC, base + target, vector)
    code += bytes.fromhex("60fe")  # BRA.S *
    rom[0x30 : 0x30 + len(code)] = code
    # BIOS and XBIOS stubs: LEA table(PC),A0 then BRA.S to the common path.
    struct.pack_into(">Hh", rom, 0x200, 0x41FA, 0x300 - 0x202)
    struct.pack_into(">Hh", rom, 0x210, 0x41FA, 0x340 - 0x212)
    for index in range(12):
        struct.pack_into(">I", rom, 0x300 + index * 4, base + 0x1000 + index * 2)
    # TRAP #2 stub: CMP.W #$73,D0 / BNE.S / JSR vdi.
    rom[0x500:0x50C] = bytes.fromhex("b07c0073 6608 4eb9".replace(" ", "")) + struct.pack(">I", base + 0x600)
    # GEM memory usage parameter block: magic, end, init.
    struct.pack_into(">III", rom, 0x700, 0x87654321, 0xA000, base + 0x800)
    if with_font:
        header = 0x1000
        struct.pack_into(">HH", rom, header, 1, 9)
        rom[header + 4 : header + 4 + 15] = b"8x8 system font"
        struct.pack_into(">HH", rom, header + 36, 0, 255)
        struct.pack_into(">H", rom, header + 52, 8)
        offsets = header + 88
        glyphs = offsets + (255 - 0 + 2) * 2
        struct.pack_into(">III", rom, header + 68, 0, base + offsets, base + glyphs)
        struct.pack_into(">HH", rom, header + 80, 256, 8)
    return rom


class HeaderTests(unittest.TestCase):
    def test_every_emutos_image_decodes(self):
        for name, (size, base, word, country, pal) in EMUTOS_IMAGES.items():
            with self.subTest(image=name):
                data = emutos(name)
                self.assertTrue(is_tos_rom(data))
                rom = TOSRom(data)
                self.assertTrue(rom.emutos)
                self.assertEqual(rom.version, "1.4")
                self.assertEqual(rom.release, "EmuTOS 1.4")
                self.assertEqual(len(rom.data), size)
                self.assertEqual(rom.base, base)
                self.assertEqual(rom.header.version_word, word)
                self.assertEqual(rom.country_code, country)
                self.assertEqual(rom.pal, pal)
                self.assertEqual(rom.date, date(2025, 6, 7))
                self.assertTrue(rom.dates_agree)
                self.assertTrue(rom.size_valid)
                self.assertTrue(rom.base_valid)
                self.assertTrue(rom.header.emutos_magic)

    def test_emutos_country_names_follow_the_configuration_word(self):
        self.assertEqual(TOSRom(emutos("etos192uk.img")).country, "United Kingdom")
        self.assertEqual(TOSRom(emutos("etos256us.img")).country, "USA")
        self.assertEqual(TOSRom(emutos("etos1024k.img")).country, "multi-language")
        self.assertEqual(TOSRom(emutos("etos192uk.img")).title, "EmuTOS 1.4 UK")

    def test_real_tos_images_decode(self):
        for name, (word, size, base, country, pal, built) in TOS_IMAGES.items():
            with self.subTest(image=name):
                data = real_tos(self, name)
                rom = TOSRom(data)
                self.assertFalse(rom.emutos)
                self.assertEqual(rom.header.version_word, word)
                self.assertEqual(len(rom.data), size)
                self.assertEqual(rom.base, base)
                self.assertEqual(rom.country_code, country)
                self.assertEqual(rom.pal, pal)
                self.assertEqual(rom.date.isoformat(), built)
                self.assertTrue(rom.size_valid and rom.base_valid)
                self.assertEqual(rom.release, f"TOS {word >> 8}.{word & 0xFF:02X}")

    def test_tos_100_has_the_short_header(self):
        rom = TOSRom(real_tos(self, "tos100uk.img"))
        self.assertFalse(rom.header.extended)
        self.assertEqual(rom.header.length, 0x20)
        self.assertEqual(rom.header.reset_offset, 0x20)
        self.assertIsNone(rom.header.date_from_dos_word)
        self.assertTrue(rom.dates_agree)
        self.assertEqual(rom.segment("HEADER").end, 0x20)

    def test_a_synthetic_rom_decodes_like_a_real_one(self):
        rom = TOSRom(bytes(build_tos_image()))
        self.assertEqual(rom.release, "TOS 1.04")
        self.assertEqual(rom.title, "TOS 1.04 UK")
        self.assertEqual(rom.date, date(1989, 4, 6))
        self.assertEqual(rom.header.date_from_dos_word, date(1989, 4, 6))
        self.assertEqual(rom.base, 0xFC0000)
        self.assertFalse(rom.emutos)
        self.assertEqual(rom.header.machine, "ST and Mega ST")

    def test_bytes_that_merely_start_with_a_branch_are_not_a_rom(self):
        self.assertIsNone(parse_tos_header(b"\x60\x2e" + bytes(4094)))
        self.assertIsNone(parse_tos_header(bytes(4096)))
        self.assertIsNone(parse_tos_header(b"\xff" * 4096))
        disagreeing = build_tos_image()
        struct.pack_into(">I", disagreeing, 4, 0xFC0034)
        self.assertIsNone(parse_tos_header(bytes(disagreeing)))
        elsewhere = build_tos_image()
        struct.pack_into(">II", elsewhere, 4, 0xF00030, 0xF00000)
        self.assertIsNone(parse_tos_header(bytes(elsewhere)))
        with self.assertRaises(DataError):
            TOSRom(bytes(4096))

    def test_dates_are_decoded_from_both_header_forms(self):
        self.assertEqual(decode_bcd_date(0x11201985), date(1985, 11, 20))
        self.assertEqual(decode_bcd_date(0x06072025), date(2025, 6, 7))
        self.assertIsNone(decode_bcd_date(0x1A201985))
        self.assertIsNone(decode_bcd_date(0x13011985))
        self.assertEqual(decode_dos_date(0x1286), date(1989, 4, 6))
        self.assertEqual(decode_dos_date(0x5AC7), date(2025, 6, 7))

    def test_the_registry_vocabulary_is_fixed(self):
        self.assertEqual(TOSROM, "tosrom")
        self.assertEqual(TOS_SIZES, (192 * 1024, 256 * 1024, 512 * 1024, 1024 * 1024))
        self.assertEqual(ROM_BASES[192 * 1024], 0xFC0000)
        self.assertEqual(ROM_BASES[256 * 1024], 0xE00000)
        self.assertEqual(ROM_BASES[512 * 1024], 0xE00000)
        self.assertEqual(ROM_BASES[128 * 1024], 0xFA0000)


class StructureTests(unittest.TestCase):
    def test_emutos_segments_are_the_header_the_os_and_the_fonts(self):
        rom = TOSRom(emutos("etos192uk.img"))
        self.assertEqual([segment.name for segment in rom.segments], ["HEADER", "OS", "DATA"])
        header, os_segment, fonts = rom.segments
        self.assertEqual((header.start, header.end, header.proven), (0, 0x30, True))
        self.assertEqual((os_segment.start, os_segment.end, os_segment.proven), (0x30, len(rom.data), False))
        self.assertTrue(fonts.proven)
        self.assertEqual(len(rom.fonts), 3)
        self.assertEqual([font.name for font in rom.fonts], ["6x6 system font", "8x8 system font", "8x16 system font"])
        self.assertTrue(all(fonts.start <= font.header_offset < fonts.end for font in rom.fonts))
        self.assertEqual(rom.read_segment("HEADER"), rom.data[:0x30])
        with self.assertRaises(DataError):
            rom.read_segment("BIOS")

    def test_the_1_mib_emutos_build_carries_two_font_sets(self):
        rom = TOSRom(emutos("etos1024k.img"))
        self.assertEqual([segment.name for segment in rom.segments], ["HEADER", "OS", "DATA", "DATA2"])
        self.assertEqual(len(rom.fonts), 6)

    def test_emutos_entry_points_are_proven_from_instructions(self):
        rom = TOSRom(emutos("etos192uk.img"))
        by_name = {point.name: point for point in rom.entry_points}
        self.assertEqual(by_name["Reset code"].offset, 0x30)
        self.assertEqual(by_name["BIOS TRAP #13 handler"].offset, 0x5A2)
        self.assertEqual(by_name["XBIOS TRAP #14 handler"].offset, 0x5B0)
        self.assertEqual(by_name["BIOS dispatch table"].length, 12 * 4)
        self.assertEqual(by_name["XBIOS dispatch table"].length, 65 * 4)
        self.assertEqual(by_name["VDI entry"].offset, 0xFB7C)
        self.assertIn("AES initialisation", by_name)
        self.assertIn("GEM memory usage parameter block", by_name)
        self.assertIn("Line-A vector", by_name)
        self.assertNotIn("GEMDOS TRAP #1 handler", by_name)
        self.assertEqual([point.offset for point in rom.entry_points], sorted(point.offset for point in rom.entry_points))

    def test_real_tos_entry_points(self):
        rom = TOSRom(real_tos(self, "tos206uk.img"))
        by_name = {point.name: point.offset for point in rom.entry_points}
        self.assertEqual(by_name["GEMDOS TRAP #1 handler"], 0xFAF6)
        self.assertEqual(by_name["BIOS TRAP #13 handler"], 0xD44)
        self.assertEqual(by_name["XBIOS TRAP #14 handler"], 0xD3E)
        self.assertEqual(by_name["BIOS dispatch table"], 0xDA4)
        self.assertEqual(by_name["XBIOS dispatch table"], 0xDD6)
        self.assertEqual(by_name["VDI entry"], 0x686E)
        self.assertEqual(by_name["AES/VDI TRAP #2 handler"], 0xFA3C)
        self.assertIn("AES initialisation", by_name)

    def test_tos_1_installs_its_vectors_with_long_absolute_moves(self):
        rom = TOSRom(real_tos(self, "tos104uk.img"))
        by_name = {point.name: point.offset for point in rom.entry_points}
        self.assertEqual(by_name["GEMDOS TRAP #1 handler"], 0x92D8)
        self.assertEqual(by_name["VDI entry"], 0xAAC6)
        self.assertEqual([segment.name for segment in rom.segments], ["HEADER", "OS", "DATA"])

    def test_a_synthetic_rom_is_segmented_from_its_own_structures(self):
        rom = TOSRom(bytes(build_tos_image()))
        by_name = {point.name: point for point in rom.entry_points}
        self.assertEqual(by_name["BIOS TRAP #13 handler"].offset, 0x200)
        self.assertEqual(by_name["XBIOS TRAP #14 handler"].offset, 0x210)
        self.assertEqual(by_name["BIOS dispatch table"].offset, 0x300)
        self.assertEqual(by_name["XBIOS dispatch table"].offset, 0x340)
        self.assertEqual(by_name["GEMDOS TRAP #1 handler"].offset, 0x400)
        self.assertEqual(by_name["AES/VDI TRAP #2 handler"].offset, 0x500)
        self.assertEqual(by_name["VDI entry"].offset, 0x600)
        self.assertEqual(by_name["GEM memory usage parameter block"].offset, 0x700)
        self.assertEqual(by_name["AES initialisation"].offset, 0x800)
        self.assertEqual(by_name["Line-A vector"].offset, 0x900)
        fonts = rom.segment("DATA")
        self.assertEqual((fonts.start, fonts.end), (0x1000, 0x1000 + 88 + 514 + 2048))
        self.assertEqual(rom.fonts[0].point_size, 9)
        self.assertEqual(rom.fonts[0].cell_width, 8)

    def test_a_font_name_inside_a_message_is_not_a_font(self):
        rom = build_tos_image(with_font=False)
        rom[0x2000:0x2020] = b"8x16 system font                "
        self.assertEqual(TOSRom(bytes(rom)).fonts, [])
        self.assertEqual([segment.name for segment in TOSRom(bytes(rom)).segments], ["HEADER", "OS"])

    def test_strings_carry_rom_addresses(self):
        rom = TOSRom(emutos("etos192uk.img"))
        texts = {row["text"]: row for row in rom.strings()}
        self.assertIn("EmuTOS Version", texts)
        self.assertEqual(texts["EmuTOS Version"]["address"], 0xFC0000 + texts["EmuTOS Version"]["offset"])

    def test_to_dict_is_serialisable(self):
        report = TOSRom(emutos("etos256uk.img")).to_dict()
        self.assertEqual(report["release"], "EmuTOS 1.4")
        self.assertEqual(report["countryShort"], "uk")
        self.assertEqual(report["date"], "2025-06-07")
        self.assertEqual(report["segments"][0]["name"], "HEADER")
        self.assertTrue(report["entryPoints"])


class MountTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "etos192uk.rom"
        self.path.write_bytes(emutos("etos192uk.img"))

    def tearDown(self):
        self.temporary.cleanup()

    def mount(self, path: Path | None = None) -> TOSMount:
        return TOSMount(reader_for(path or self.path))

    def test_the_mount_lists_segments_as_a_flat_read_only_volume(self):
        mount = self.mount()
        try:
            self.assertEqual(mount.filesystem, "tosrom")
            self.assertTrue(mount.read_only)
            self.assertEqual(mount.title, "EmuTOS 1.4 UK")
            self.assertEqual([entry.name for entry in mount.iter_entries()], ["HEADER", "OS", "DATA"])
            self.assertTrue(mount.exists("DATA"))
            self.assertTrue(mount.exists(""))
            self.assertFalse(mount.exists("GEMDOS"))
            self.assertEqual(mount.stat("HEADER").length, 0x30)
            self.assertTrue(mount.stat("").is_dir)
            self.assertEqual(mount.read_bytes("HEADER"), self.path.read_bytes()[:0x30])
            self.assertEqual(mount.size_bytes(), 192 * 1024)
            self.assertEqual(mount.free_bytes(), 0)
            self.assertIsNone(mount.datestamp("OS"))
            self.assertIsNone(mount.filetype("OS"))
            with self.assertRaises(DataError):
                mount.set_title("Other")
            with self.assertRaises(DataError):
                list(mount.iter_entries("DATA"))
            with self.assertRaises(DataError):
                mount.stat("BIOS")
        finally:
            mount.close()

    def test_metadata_reports_whether_a_segment_is_proven(self):
        mount = self.mount()
        try:
            from atarinut.file import Access

            proven = mount.atari_meta("HEADER")
            fallback = mount.atari_meta("OS")
            self.assertTrue(proven.protection & int(Access.E))
            self.assertFalse(fallback.protection & int(Access.E))
            self.assertIn("not recorded", fallback.comment)
            self.assertEqual(fallback.extra["proven"], False)
            self.assertEqual(proven.extra["address"], 0xFC0000)
            with self.assertRaises(DataError):
                mount.atari_meta("BIOS")
        finally:
            mount.close()

    def test_validate_explains_the_os_fallback_and_lists_entry_points(self):
        mount = self.mount()
        try:
            problems = mount.validate()
        finally:
            mount.close()
        self.assertTrue(any("one OS segment" in problem for problem in problems))
        self.assertTrue(any("VDI entry at $FCFB7C" in problem for problem in problems))
        self.assertTrue(any("GEMDOS TRAP #1 handler" in problem for problem in problems))
        self.assertFalse(any("not a TOS size" in problem for problem in problems))

    def test_validate_reports_a_wrong_base_and_a_wrong_date_word(self):
        rom = build_tos_image(256 * 1024, base=0xFC0000, dos_date=0x0021)
        path = Path(self.temporary.name) / "odd.rom"
        path.write_bytes(bytes(rom))
        mount = self.mount(path)
        try:
            problems = mount.validate()
        finally:
            mount.close()
        self.assertTrue(any("$E00000" in problem for problem in problems))
        self.assertTrue(any("date word" in problem for problem in problems))


class CartridgeTests(unittest.TestCase):
    def test_a_built_cartridge_chains_its_application_headers(self):
        data = build_cartridge_rom(64 * 1024, ("forge.prg", "tool.tos"))
        self.assertEqual(len(data), 64 * 1024)
        self.assertTrue(is_cartridge_rom(data))
        self.assertFalse(is_tos_rom(data))
        cartridge = CartridgeRom(data)
        self.assertEqual([application.name for application in cartridge.applications], ["FORGE.PRG", "TOOL.TOS"])
        self.assertEqual(cartridge.applications[0].next, CARTRIDGE_BASE + 4 + 0x22)
        self.assertEqual(cartridge.applications[1].next, 0)
        run = cartridge.applications[0].run - CARTRIDGE_BASE
        self.assertEqual(data[run : run + 2], b"\x4e\x75")
        self.assertEqual(cartridge.applications[0].init, 0)
        self.assertEqual(cartridge.title, "FORGE.PRG")

    def test_a_cartridge_larger_than_the_port_allows_is_refused(self):
        with self.assertRaises(DataError):
            build_cartridge_rom(256 * 1024)
        with self.assertRaises(DataError):
            CartridgeRom(bytes(4096))


if __name__ == "__main__":
    unittest.main()
