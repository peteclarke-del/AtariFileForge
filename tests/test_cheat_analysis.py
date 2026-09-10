"""Cheat-candidate analysis, against ST BASIC listings and 68000 code.

The BASIC cases are deliberately written in more than one dialect. An ST
carries GFA BASIC, STOS and ST BASIC, a game is as likely to be written in any
of them, and the analysis is supposed to read the listing rather than a
dialect's tokens. If it only understood numbered lines and ``X=X-1``, every
GFA ``DEC LIVES%`` in the world would go unreported.

The machine-code cases are 68000, and several of them exist to prove a
negative: an MFP timer counting down and a palette register being written are
exactly the shapes this analysis looks for, and neither of them is a cheat.
"""

import unittest

from app.cheat_analysis import (
    analyse_basic,
    analyse_disassembly,
    cheat_report,
    disassembly_diagnostics,
    hardware_region,
)


class BasicDialectTests(unittest.TestCase):
    """One analysis, three dialects, because an ST listing may be any of them."""

    def test_st_basic_numbered_lines_and_a_poke(self):
        findings = analyse_basic(
            "10 lives%=3\n20 lives%=lives%-1\n30 IF lives%=0 THEN GOTO 100\n40 POKE $70,lives%"
        )
        self.assertTrue(any(row["category"] == "lives" and row["confidence"] == "strong" for row in findings))
        self.assertTrue(any("&70" in row["evidence"] for row in findings))

    def test_gfa_basic_dec_statement_is_a_counter_update(self):
        """GFA BASIC has no line numbers and spells the update ``DEC LIVES%``."""
        findings = analyse_basic("lives%=3\nDEC lives%\nIF lives%=0 THEN GOTO 100")
        candidate = next(row for row in findings if "lives%" in row["summary"])
        self.assertEqual(candidate["category"], "lives")
        self.assertIn("decrement", candidate["evidence"])

    def test_gfa_basic_sub_by_one_is_a_counter_update(self):
        findings = analyse_basic("energy&=9\nSUB energy&,1\nIF energy&=0 THEN GOTO 500")
        candidate = next(row for row in findings if "energy&" in row["summary"])
        self.assertEqual(candidate["category"], "energy")
        self.assertIn("decrement", candidate["evidence"])

    def test_subtracting_a_variable_is_arithmetic_not_a_counter_update(self):
        """``SUB SCORE%,BONUS%`` is a sum, and reporting it as one would be wrong."""
        findings = analyse_basic("score%=0\nSUB score%,bonus%")
        self.assertFalse(any("decrement" in row["evidence"] for row in findings))

    def test_the_stos_and_gfa_wide_pokes_are_read(self):
        for listing in ("DPOKE $3456,$4E71", "DOKE $3456,$4E71", "WORD{$3456}=$4E71"):
            with self.subTest(listing=listing):
                findings = analyse_basic(listing)
                self.assertTrue(
                    any(row["category"] == "code-patch" and "NOP" in row["summary"] for row in findings)
                )

    def test_hexadecimal_is_read_in_both_spellings(self):
        for listing in ("10 POKE &H3456,&H4E71", "POKE $3456,$4E71"):
            with self.subTest(listing=listing):
                self.assertTrue(any(row["category"] == "code-patch" for row in analyse_basic(listing)))

    def test_basic_does_not_treat_memory_reads_as_writes(self):
        findings = analyse_basic("10 A%=PEEK($70)\n20 PRINT PEEK($71)")
        self.assertFalse(any(row["category"] == "memory-write" for row in findings))

    def test_basic_rejects_unexplained_memory_write(self):
        self.assertEqual(analyse_basic("10 POKE $70,3"), [])

    def test_basic_rejects_opaque_loop_counter(self):
        findings = analyse_basic("10 L%=3\n20 L%=L%-1\n30 IF L%=0 THEN GOTO 100")
        self.assertEqual(findings, [])

    def test_basic_opaque_counter_requires_semantic_terminal_path(self):
        findings = analyse_basic('10 L%=3\n20 L%=L%-1\n30 IF L%=0 THEN GOTO 100\n100 PRINT "GAME OVER"')
        candidate = next(row for row in findings if "L%" in row["summary"])
        self.assertEqual(candidate["category"], "lives")
        self.assertIn("terminal path", candidate["evidence"])

    def test_a_write_into_the_hardware_says_which_hardware(self):
        """A poke to an MFP register is machine setup, and the risk says so."""
        candidate = next(
            row for row in analyse_basic("POKE $FFFA21,lives%") if "FFFA21" in row["summary"]
        )
        self.assertIn("MFP 68901", candidate["evidence"])
        self.assertIn("MFP 68901", candidate["risk"])

    def test_semantic_matching_does_not_confuse_sometimes_with_time(self):
        findings = analyse_basic("10 sometimes%=3\n20 sometimes%=sometimes%-1\n30 IF sometimes%=0 THEN END")
        self.assertEqual(findings, [])


class HardwareMapTests(unittest.TestCase):
    """Where the machine lives, so a changing value there is not a cheat."""

    def test_the_st_regions_are_recognised(self):
        cases = {
            "&400": "TOS system variables",
            "&FF8240": "ST and STE hardware registers",
            "&FF8800": "ST and STE hardware registers",
            "&FF8C80": "SCC serial controller",
            "&FFFA21": "MFP 68901",
            "&FFFC00": "keyboard and MIDI ACIAs",
            "&E00000": "TOS ROM",
            "&FC0000": "TOS ROM",
            "&FA0000": "cartridge port",
        }
        for address, region in cases.items():
            with self.subTest(address=address):
                self.assertEqual(hardware_region(address), region)

    def test_ordinary_program_memory_is_not_hardware(self):
        for address in ("&70", "&1234", "&20000", "&100000"):
            with self.subTest(address=address):
                self.assertEqual(hardware_region(address), "")


class DisassemblyTests(unittest.TestCase):
    """68000 code, which is the only processor an ST program is written for."""

    def test_a_constant_store_and_a_later_decrement_are_linked(self):
        """``MOVE.W #3,lives`` is the load and the store in one instruction."""
        findings = analyse_disassembly({"rows": [
            {"address": 0x2000, "mnemonic": "MOVE.W", "operand": "#3,$70"},
            {"address": 0x2004, "mnemonic": "SUBQ.W", "operand": "#1,$70"},
            {"address": 0x2008, "mnemonic": "BEQ.S", "operand": "$2010", "target": 0x2010},
            {"address": 0x2010, "mnemonic": "RTS", "operand": ""},
        ]})
        self.assertEqual(findings[0]["confidence"], "likely")
        self.assertIn("&70", findings[0]["summary"])
        self.assertEqual(findings[0]["navigation"], {"kind": "disassembly", "address": 0x2004, "offset": 0})

    def test_a_backward_decrement_loop_is_rejected(self):
        findings = analyse_disassembly({"rows": [
            {"address": 0x2000, "mnemonic": "SUBQ.W", "operand": "#1,$70"},
            {"address": 0x2004, "mnemonic": "BNE.S", "operand": "$2000", "target": 0x2000},
        ]})
        self.assertEqual(findings, [])

    def test_a_reachable_unlabelled_forward_state_change_stays_possible(self):
        findings = analyse_disassembly({"rows": [
            {"address": 0x2000, "mnemonic": "SUBQ.W", "operand": "#1,$70", "reachable": True},
            {"address": 0x2004, "mnemonic": "BEQ.S", "operand": "$2010", "target": 0x2010, "reachable": True},
            {"address": 0x2006, "mnemonic": "RTS", "operand": "", "reachable": True},
            {"address": 0x2010, "mnemonic": "RTS", "operand": "", "reachable": True},
        ]})
        self.assertEqual(findings[0]["confidence"], "possible")

    def test_unreachable_decoded_data_is_ignored(self):
        findings = analyse_disassembly({"rows": [
            {"address": 0x2000, "mnemonic": "RTS", "operand": "", "reachable": True},
            {"address": 0x2002, "mnemonic": "SUBQ.W", "operand": "#1,$70", "reachable": False},
            {"address": 0x2006, "mnemonic": "BEQ.S", "operand": "$2010", "target": 0x2010, "reachable": False},
        ]})
        self.assertEqual(findings, [])

    def test_a_runtime_payload_is_diagnosed_rather_than_reported_empty(self):
        rows = [{"address": 0x2000 + index, "mnemonic": "DC.B", "operand": "$00", "reachable": index == 0}
                for index in range(200)]
        diagnostics = disassembly_diagnostics({"rows": rows})
        self.assertTrue(any(item["kind"] == "packed" for item in diagnostics))

    def test_a_labelled_multibyte_lives_counter_is_accepted(self):
        findings = analyse_disassembly({"rows": [
            {"address": 0x2100, "mnemonic": "SUBQ.B", "operand": "#1,$80", "label": "lives_units"},
            {"address": 0x2104, "mnemonic": "BPL.S", "operand": "$2110", "target": 0x2110},
            {"address": 0x2106, "mnemonic": "MOVE.B", "operand": "#9,$80"},
            {"address": 0x210C, "mnemonic": "SUBQ.B", "operand": "#1,$81", "label": "lives_tens"},
        ]})
        self.assertTrue(any(row["category"] == "lives" for row in findings))

    def test_a_load_subtract_store_sequence_through_a_register_is_correlated(self):
        findings = analyse_disassembly({"rows": [
            {"address": 0x2FF0, "mnemonic": "MOVE.W", "operand": "#3,$71"},
            {"address": 0x3000, "mnemonic": "MOVE.W", "operand": "$71,D0"},
            {"address": 0x3004, "mnemonic": "SUBQ.W", "operand": "#1,D0"},
            {"address": 0x3006, "mnemonic": "MOVE.W", "operand": "D0,$71"},
            {"address": 0x300A, "mnemonic": "BEQ.S", "operand": "$3020", "target": 0x3020},
        ]})
        self.assertTrue(any("Load, subtract one and store" in row["summary"] for row in findings))

    def test_an_mfp_timer_countdown_is_not_a_lives_counter(self):
        """The MFP counts down four timers all day and none of them is a cheat."""
        findings = analyse_disassembly({"rows": [
            {"address": 0x4000, "mnemonic": "SUBQ.B", "operand": "#1,$FFFA21"},
            {"address": 0x4004, "mnemonic": "BNE.S", "operand": "$4000", "target": 0x4000},
        ]})
        self.assertEqual(findings, [])

    def test_a_palette_register_is_not_a_counter(self):
        findings = analyse_disassembly({"rows": [
            {"address": 0x4000, "mnemonic": "MOVE.W", "operand": "#3,$FF8240"},
            {"address": 0x4004, "mnemonic": "SUBQ.W", "operand": "#1,$FF8240"},
            {"address": 0x4008, "mnemonic": "BEQ.S", "operand": "$4020", "target": 0x4020},
        ]})
        self.assertEqual(findings, [])

    def test_decimal_and_hexadecimal_immediates_are_both_understood(self):
        decimal = analyse_disassembly({"rows": [
            {"address": 0x4100, "mnemonic": "MOVE.W", "operand": "$72,D0", "comment": "lives"},
            {"address": 0x4104, "mnemonic": "SUBQ.W", "operand": "#1,D0"},
            {"address": 0x4106, "mnemonic": "MOVE.W", "operand": "D0,$72"},
        ]})
        hexadecimal = analyse_disassembly({"rows": [
            {"address": 0x4200, "mnemonic": "MOVE.W", "operand": "$73,D0", "comment": "energy"},
            {"address": 0x4204, "mnemonic": "SUBI.W", "operand": "#$01,D0"},
            {"address": 0x4208, "mnemonic": "MOVE.W", "operand": "D0,$73"},
        ]})
        self.assertTrue(any("Load, subtract one and store" in row["summary"] for row in decimal))
        self.assertTrue(any("Load, subtract one and store" in row["summary"] for row in hexadecimal))

    def test_an_immediate_is_not_mistaken_for_the_store_address(self):
        findings = analyse_disassembly({"rows": [
            {"address": 0x4300, "mnemonic": "MOVE.W", "operand": "$74,D0", "comment": "player_lives"},
            {"address": 0x4304, "mnemonic": "SUBI.W", "operand": "#$01,D0"},
            {"address": 0x4308, "mnemonic": "MOVE.W", "operand": "D0,$74"},
        ]})
        candidate = next(row for row in findings if "Load, subtract one and store" in row["summary"])
        self.assertIn("&74", candidate["summary"])


class ReportTests(unittest.TestCase):
    def test_report_is_explicitly_read_only(self):
        report = cheat_report(path="$.GAME", kind="basic", findings=[], title="Oids", machine="st")
        self.assertTrue(report["readOnly"])
        self.assertEqual(len(report["referenceSearches"]), 4)

    def test_reference_searches_carry_the_title_and_machine(self):
        report = cheat_report(path="$.GAME", kind="basic", findings=[], title="Oids", machine="st")
        self.assertTrue(all("Oids" in row["url"] for row in report["referenceSearches"]))
        self.assertTrue(any("atarimania.com" in row["url"] for row in report["referenceSearches"]))
        self.assertTrue(any("stonish.com" in row["url"] for row in report["referenceSearches"]))


if __name__ == "__main__":
    unittest.main()
