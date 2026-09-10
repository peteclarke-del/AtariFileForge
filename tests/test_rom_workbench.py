import json
import tempfile
import unittest
from pathlib import Path

from app.rom import parse_cartridge_header, parse_rom_header
from app.rom_components import write_combined_rom
from app.rom_workbench import (
    RomWorkbenchError, apply_patch, audit_rom, bank_map, board_chip_sets,
    build_cartridge_rom, build_data_archive, compare_roms, disassemble_68000,
    hardware_export, hardware_export_zip, identify_rom, make_patch, normalise_project,
    make_selective_patch, disassemble_capstone, repair_date_word, Cs,
)

REPO = Path(__file__).resolve().parent.parent
EMUTOS = REPO / "firmware" / "emutos" / "etos192uk.img"
CATALOGUE = REPO / "app" / "rom_catalogue.json"


class RomWorkbenchTests(unittest.TestCase):
    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_disassembly_names_gemdos_calls_from_the_pushed_function_word(self):
        """``MOVE.W #$3D,-(SP) / TRAP #1`` is how every TOS program opens a file."""
        data = bytes.fromhex("3f3c003d4e414e75")
        rows = disassemble_68000(data, origin=0xE00000)["rows"]
        self.assertIn("$3D", rows[0]["comment"])
        self.assertIn("GEMDOS Fopen", rows[1]["comment"])
        self.assertEqual(rows[2]["mnemonic"], "RTS")
        self.assertEqual(rows[2]["comment"], "Return from subroutine")

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_bios_and_xbios_traps_are_named_from_their_own_tables(self):
        # MOVE.W #4,-(SP) ; TRAP #13 ; MOVE.W #37,-(SP) ; TRAP #14 ; RTS
        data = bytes.fromhex("3f3c00044e4d3f3c00254e4e4e75")
        rows = disassemble_68000(data, origin=0xE00000)["rows"]
        self.assertIn("BIOS Rwabs", rows[1]["comment"])
        self.assertIn("XBIOS Vsync", rows[3]["comment"])

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_the_gem_selector_in_d0_tells_aes_from_vdi(self):
        # MOVE.L #$73,D0 ; TRAP #2 ; MOVE.L #$C8,D0 ; TRAP #2
        data = bytes.fromhex("203c000000734e42203c000000c84e42")
        rows = disassemble_68000(data, origin=0xE00000)["rows"]
        self.assertIn("VDI", rows[0]["comment"])
        self.assertTrue(rows[1]["comment"].startswith("VDI"))
        self.assertTrue(rows[3]["comment"].startswith("AES"))

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_a_routine_that_makes_a_system_call_is_labelled_after_it(self):
        # BSR.S sub ; RTS ; sub: MOVE.W #$30,-(SP) ; TRAP #1 ; RTS
        data = bytes.fromhex("61024e753f3c00304e414e75")
        rows = disassemble_68000(data, origin=0xE00000)["rows"]
        self.assertEqual(rows[2]["label"], "call_sversion_E00004")
        self.assertIn("call_sversion", rows[0]["operand"])

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_hardware_registers_vectors_and_system_variables_are_identified(self):
        # MOVE.W #$777,$FFFF8240.L ; MOVE.L #$E0FB60,$88.W ; MOVEA.L $4F2.W,A0 ; RTS
        data = bytes.fromhex("33fc0777ffff824021fc00e0fb600088207804f24e75")
        rows = disassemble_68000(data, origin=0xE00000)["rows"]
        self.assertIn("palette colour 0", rows[0]["comment"])
        self.assertIn("TRAP #2 (AES and VDI) vector", rows[1]["comment"])
        self.assertIn("_sysbase system variable", rows[2]["comment"])

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_a_short_absolute_address_is_sign_extended_onto_the_hardware(self):
        # MOVE.B #0,$FFFA07.W (encoded as $FA07.W) ; RTS
        data = bytes.fromhex("11fc0000fa074e75")
        rows = disassemble_68000(data, origin=0xE00000)["rows"]
        self.assertIn("MFP interrupt enable A", rows[0]["comment"])

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_branches_are_labelled_and_explained(self):
        # BRA.B * ; RTS
        data = bytes.fromhex("60fe4e75")
        rows = disassemble_68000(data, origin=0xE00000)["rows"]
        self.assertEqual(rows[0]["target"], 0xE00000)
        self.assertIn("loop_E00000", rows[0]["operand"])
        self.assertIn("Branch always", rows[0]["comment"])

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_bytes_that_are_not_instructions_stay_as_data(self):
        rows = disassemble_capstone(b"\xff\xff", architecture="68000", length=2)["rows"]
        self.assertIn("DC.", rows[0]["mnemonic"], rows[0])

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_every_processor_in_the_family_decodes_big_endian(self):
        for architecture in ("68000", "68010", "68020", "68030", "68040", "68060"):
            with self.subTest(architecture=architecture):
                report = disassemble_capstone(
                    bytes.fromhex("4e714e75"), architecture=architecture, length=4,
                    symbols={"0x0": "start_here"},
                )
                self.assertEqual(
                    [row["mnemonic"] for row in report["rows"]], ["NOP", "RTS"]
                )
                self.assertEqual(report["rows"][0]["label"], "start_here")

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_an_unknown_processor_is_refused_rather_than_guessed(self):
        with self.assertRaisesRegex(RomWorkbenchError, "68000, 68010"):
            disassemble_capstone(b"\x4e\x71", architecture="z80", length=2)

    @unittest.skipIf(Cs is None, "Capstone is installed in the production image")
    def test_the_reset_code_of_a_real_rom_disassembles_with_tos_annotations(self):
        data = EMUTOS.read_bytes()
        report = disassemble_68000(data, origin=0xFC0000, start=0x30, length=0xB00)
        comments = " ".join(row["comment"] for row in report["rows"])
        self.assertIn("MMU memory configuration", comments)
        self.assertIn("TRAP #13 (BIOS) vector", comments)

    def test_comparison_and_patch_are_checksum_guarded(self):
        left, right = b"hello ROM", b"hello rom!"
        report = compare_roms(left, right)
        self.assertGreater(report["changedBytes"], 0)
        patch = make_patch(left, right)
        self.assertEqual(apply_patch(left, patch), right)
        with self.assertRaises(RomWorkbenchError):
            apply_patch(b"wrong", patch)

    def test_selective_patch_contains_only_chosen_ranges(self):
        left, right = b"ABC-DEF-GHI", b"AbC-DEF-GhI"
        report = compare_roms(left, right)
        self.assertEqual(len(report["ranges"]), 2)
        patch = make_selective_patch(left, right, [1])
        self.assertEqual(apply_patch(left, patch), b"ABC-DEF-GhI")

    def test_bank_map_finds_duplicates(self):
        data = b"A" * 256 + b"B" * 256 + b"A" * 256
        report = bank_map(data, 256)
        self.assertEqual(report["banks"][0]["duplicates"], [2])
        self.assertEqual(report["banks"][2]["duplicates"], [0])

    def test_bank_map_names_the_continuation_banks_of_a_tos_rom(self):
        report = bank_map(EMUTOS.read_bytes(), 64 * 1024)
        self.assertEqual(report["bankCount"], 3)
        self.assertEqual(report["banks"][0]["title"], "EmuTOS 1.4 UK")
        self.assertEqual(report["banks"][0]["cpuWindow"], "$FC0000-$FCFFFF")
        self.assertIn("continued", report["banks"][2]["title"])

    def test_builder_creates_a_safe_cartridge(self):
        data = build_cartridge_rom("Workshop", [{"name": "MENU.PRG"}], size=64 * 1024)
        cartridge = parse_cartridge_header(data)
        self.assertEqual([row["name"] for row in cartridge.applications], ["WORKSHOP.PRG", "MENU.PRG"])
        report = audit_rom(data, 64 * 1024)
        self.assertTrue(report["healthy"], report)
        with self.assertRaises(RomWorkbenchError):
            build_cartridge_rom("Odd", size=12345)

    def test_data_archive_refuses_overflow(self):
        with self.assertRaises(RomWorkbenchError):
            build_data_archive("Full", [("BIG", b"X" * 20_000_000)])

    def test_an_audit_of_a_real_rom_reports_emutos_and_offers_no_repair(self):
        report = audit_rom(EMUTOS.read_bytes(), 64 * 1024)
        self.assertTrue(report["healthy"], report["findings"])
        codes = [row["code"] for row in report["findings"]]
        self.assertIn("emutos", codes)
        self.assertIn("vector-install", codes)
        self.assertEqual(report["repairable"], [])

    def test_a_wrong_date_word_is_audited_and_repaired(self):
        rom = bytearray(EMUTOS.read_bytes())
        rom[0x1E:0x20] = b"\x00\x21"
        report = audit_rom(bytes(rom), 64 * 1024)
        self.assertFalse(report["healthy"])
        self.assertIn("date-word", report["repairable"])
        repaired = repair_date_word(bytes(rom))
        self.assertEqual(repaired, EMUTOS.read_bytes())
        self.assertTrue(parse_rom_header(repaired).dates_agree)
        with self.assertRaises(RomWorkbenchError):
            repair_date_word(repaired)
        with self.assertRaises(RomWorkbenchError):
            repair_date_word(bytes(4096))

    def test_hardware_export_can_mirror_swap_and_split(self):
        result = hardware_export(b"\x01\x02", device_size=8, mirror=True, lanes=2, byte_swap=True)
        self.assertEqual(result["components"], [b"\x02" * 4, b"\x01" * 4])
        self.assertEqual(result["componentNames"], ["even", "odd"])

    def test_hardware_export_can_swap_words_and_address_lines(self):
        words = hardware_export(bytes(range(8)), device_size=8, word_swap=True)
        self.assertEqual(words["components"][0], bytes((2, 3, 0, 1, 6, 7, 4, 5)))
        addresses = hardware_export(bytes(range(8)), device_size=8, address_swaps=[(0, 1)])
        self.assertEqual(addresses["components"][0], bytes((0, 2, 1, 3, 4, 6, 5, 7)))

    def test_a_192k_rom_splits_into_the_six_chips_an_st_takes(self):
        data = bytes(range(256)) * 768
        self.assertEqual(board_chip_sets(len(data))[0]["chips"], 6)
        result = hardware_export(data, device_size=len(data), lanes=2, chip_count=6)
        self.assertEqual(result["chipSize"], 32 * 1024)
        self.assertEqual(
            result["componentNames"], ["even-1", "even-2", "even-3", "odd-1", "odd-2", "odd-3"]
        )
        self.assertTrue(all(len(chip) == 32 * 1024 for chip in result["components"]))
        self.assertEqual(result["components"][0], data[0::2][: 32 * 1024])
        self.assertEqual(result["components"][3], data[1::2][: 32 * 1024])
        with tempfile.TemporaryDirectory() as folder:
            even = Path(folder) / "even.bin"
            odd = Path(folder) / "odd.bin"
            even.write_bytes(b"".join(result["components"][:3]))
            odd.write_bytes(b"".join(result["components"][3:]))
            combined = Path(folder) / "combined.rom"
            write_combined_rom([even, odd], combined, "byte-interleaved-2")
            self.assertEqual(combined.read_bytes(), data)
        archive = hardware_export_zip(result, "tos104")
        self.assertGreater(len(archive), 0)
        with self.assertRaises(RomWorkbenchError):
            hardware_export(data, device_size=len(data), lanes=2, chip_count=5)

    def test_identification_catalogue_and_mirror_hint(self):
        data = b"AB" * 16
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "catalogue.json"
            digest = __import__("hashlib").sha256(data).hexdigest()
            path.write_text(json.dumps({"roms": [{"sha256": digest, "title": "Known"}]}))
            result = identify_rom(data, path)
        self.assertTrue(result["matched"])
        self.assertTrue(any("mirrored" in row for row in result["transformations"]))
        self.assertIsNone(result["declared"])

    def test_the_shipped_catalogue_knows_emutos_and_the_header_declares_it_too(self):
        result = identify_rom(EMUTOS.read_bytes(), CATALOGUE)
        self.assertTrue(result["matched"])
        self.assertIn("EmuTOS 1.4 192 KiB", result["record"]["title"])
        self.assertEqual(result["declared"]["kind"], "emutos")
        self.assertEqual(result["declared"]["country"], "United Kingdom")
        self.assertTrue(any("192 KiB TOS ROM" in row for row in result["transformations"]))

    def test_project_metadata_is_bounded(self):
        project = normalise_project({"notes": "x" * 30000, "symbols": {"32768": "start"}})
        self.assertEqual(len(project["notes"]), 20000)
        self.assertEqual(project["symbols"]["32768"], "start")


if __name__ == "__main__":
    unittest.main()
