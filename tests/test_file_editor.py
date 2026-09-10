from __future__ import annotations

import tempfile
import struct
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from atarinut.basic import GFA_BASIC_3, ST_BASIC, detokenise, tokenise
from atarinut.basic.stos import encode_program as encode_stos_program

from app.checksum import sha256_bytes
from app.content_kind import analyse_content, metadata_kind
from app.disk_service import DiskService
from app.errors import DiskError
from app.file_editor import (
    _format_basic_listing,
    _printable_strings,
    _renumber_listing,
    disassemble_file,
    disassemble_file_data,
    inspect_editable_file,
    normalise_basic_source,
    pack_basic_lines,
    prepare_basic_source,
    save_editor_text,
    save_editor_text_as,
    search_image_files,
    update_file_properties,
    _program_body,
    verify_basic_source,
    write_file_range,
)
from app.operations import OperationCancelled
from app.msa import st_to_msa
from tests.msa_fixture import blank_image
from app.floppy_geometry import geometry as floppy_geometry


#: The attribute byte GEMDOS gives a freshly written file, and the same byte
#: with the read-only bit set. There is no other file metadata on a GEMDOS
#: volume: the directory entry holds a name, a length, a datestamp and this.
ARCHIVE_ONLY = 0x20
READ_ONLY_BIT = 0x01


def _msa_container() -> bytes:
    """A real Magic Shadow Archiver image of an empty double-density disk."""
    shape = floppy_geometry("ds-80t-9s")
    return st_to_msa(blank_image(shape), shape)


def _gfa_program(source: str) -> bytes:
    """A saved GFA BASIC 3 program, which is the ST's tokenised, writable BASIC."""
    return tokenise(source, dialect=GFA_BASIC_3)


def _st_basic_listing(source: str) -> bytes:
    """A saved ST BASIC program, which is a numbered listing stored as characters.

    The words are chosen so that ``detect`` can name the dialect. A bare
    PRINT and END pair belongs to every BASIC the ST had, so only vocabulary
    one of them alone owns, such as FULLW and GOTOXY, proves which this is.
    """
    return tokenise(source, dialect=ST_BASIC)


class FileEditorTests(unittest.TestCase):
    def service_with_file(self, content: bytes, metadata: dict | None = None):
        folder = tempfile.TemporaryDirectory()
        source = Path(folder.name) / "exported"
        source.write_bytes(content)
        service = Mock()

        def export(*_args):
            copy = Path(folder.name) / f"copy-{service.export_file.call_count}"
            copy.write_bytes(source.read_bytes())
            return copy

        service.export_file.side_effect = export
        service.file_metadata.return_value = metadata or {
            "attributes": ARCHIVE_ONLY,
            "attributesText": "-----a",
            "access": ARCHIVE_ONLY,
            "length": len(content),
            "datestamp": "",
        }
        service.editor_project.return_value = {}
        return folder, service

    def test_detects_and_decodes_tokenised_basic(self):
        program = _gfa_program('PRINT "HELLO"\nEND')
        folder, service = self.service_with_file(program)
        try:
            report = inspect_editable_file(service, SimpleNamespace(target_hardware="floppy", hfe_read_only=False, kind="gemdos"), "GAME.GFA", None)
        finally:
            folder.cleanup()
        self.assertEqual(report["view"], "basic")
        self.assertTrue(report["editable"])
        self.assertEqual(report["basic"]["dialect"], "GFA BASIC 3")
        self.assertEqual(report["basic"]["dialectId"], "gfa-basic-3")
        # GFA BASIC indents its blocks instead of numbering its lines.
        self.assertFalse(report["basic"]["lineNumbers"])
        self.assertIn('PRINT "HELLO"', report["text"])

    def test_which_basic_a_file_is_comes_from_its_bytes(self):
        """The three saved forms the ST had, told apart without reading a name."""
        gfa = analyse_content(_gfa_program('PRINT "HELLO"\nEND'), "ANY")[1]
        self.assertEqual(gfa["dialect"], "GFA BASIC 3")
        self.assertTrue(gfa["editable"])

        st = analyse_content(_st_basic_listing('10 FULLW 2\n20 GOTOXY 0,0\n30 PRINT "HELLO"'), "ANY")[1]
        self.assertEqual(st["dialect"], "ST BASIC")
        self.assertTrue(st["lineNumbers"])
        self.assertEqual(st["firstLine"], 10)
        self.assertEqual(st["lastLine"], 30)
        self.assertEqual(st["lineCount"], 3)

        stos = analyse_content(encode_stos_program('10 CLS\n20 CURS OFF\n30 PRINT "HELLO"'), "ANY")[1]
        self.assertEqual(stos["dialect"], "STOS BASIC")
        self.assertFalse(stos["editable"])

        # Two lines every ST BASIC shares with every other BASIC are not
        # enough vocabulary to name a dialect, so nothing is guessed.
        self.assertIsNone(analyse_content(b'10 PRINT "HELLO"\n20 END\n', "ANY")[1])

    def test_listing_classifier_recognises_content_before_the_editor_opens_it(self):
        self.assertEqual(analyse_content(_gfa_program('PRINT "HELLO"\nEND'), "PROGRAM.GFA")[0], "basic")
        self.assertEqual(analyse_content(b"\x60\x1a" + bytes(30), "MENU.PRG")[0], "program")
        self.assertEqual(analyse_content(b"SETENV PATH=C:\\BIN\nEXEC C:\\MINT\\INIT.PRG\n", "MINT.CNF")[0], "script")
        self.assertEqual(analyse_content(b"A readable document about this disk.\n", "NOTES.TXT")[0], "text")
        self.assertEqual(analyse_content(bytes.fromhex("A90020F4FF60"), "CODE.DAT")[0], "binary")
        self.assertEqual(analyse_content(_msa_container(), "GAME.MSA")[0], "container")

    def test_listing_classifier_uses_the_name_where_tos_itself_trusts_it(self):
        # A GEMDOS directory entry records no type, so the extension is the
        # only metadata there is. TOS runs .PRG and .TOS from the desktop, so
        # the extension is not a description of the file, it is what makes it
        # a program.
        self.assertEqual(metadata_kind("MENU.PRG", None), "program")
        self.assertEqual(metadata_kind("FORMAT.TOS", None), "program")
        self.assertEqual(metadata_kind("GAME.BAS", None), "basic")
        self.assertEqual(metadata_kind("DESKTOP.INF", None), "script")
        self.assertEqual(metadata_kind("README.TXT", None), "text")
        self.assertEqual(metadata_kind("BACKUP.MSA", None), "container")
        # A name with no extension says nothing, so the bytes still have to
        # be read.
        self.assertIsNone(metadata_kind("NOTES", None))
        # A caller that has already classified the name is believed.
        self.assertEqual(metadata_kind("SETUP", "program"), "program")

    def test_image_search_traverses_directories_and_reports_source_lines(self):
        service = Mock()
        service.list_directory.side_effect = lambda _session, path, *_rest: {
            "entries": (
                [{"name": "GAMES", "path": "GAMES", "type": "dir", "length": 0}]
                if path == "" else
                [{"name": "AUTO.BAT", "path": "GAMES\\AUTO.BAT", "type": "file", "length": 31}]
            )
        }
        service.read_file.return_value = b"ECHO OFF\nGAMES\\ARCADIA.PRG\n"
        report = search_image_files(
            service, SimpleNamespace(kind="gemdos", partition=0), "arcadia", None, "",
        )
        self.assertEqual(report["filesConsidered"], 1)
        self.assertEqual(report["results"][0]["path"], "GAMES\\AUTO.BAT")
        self.assertEqual(report["results"][0]["matches"][0]["line"], 2)

    def test_image_search_lists_a_track_container_flat(self):
        """An MSA is converted for browsing and has no directory tree to walk."""
        service = Mock()
        service.list_directory.return_value = {"entries": [
            {"name": "READ.ME", "path": "READ.ME", "type": "file", "length": 24},
        ]}
        service.read_file.return_value = b"Written by Krisalis 1990\n"

        report = search_image_files(
            service, SimpleNamespace(kind="msa", partition=None), "krisalis", None, "",
        )

        self.assertEqual(report["filesConsidered"], 1)
        self.assertEqual(report["results"][0]["path"], "READ.ME")

    def test_image_search_matches_catalogue_attributes_and_datestamp(self):
        service = Mock()
        service.list_directory.return_value = {"entries": [{
            "name": "MENU.PRG", "path": "MENU.PRG", "type": "file", "length": 4,
            "attributes": "r----a", "attributeBits": 0x21, "attr": "r----a",
            "datestamp": "1992-05-01T09:30:00.000+00:00", "contentKind": "program",
        }]}
        service.read_file.return_value = b"\x00\x01\x02\x03"
        session = SimpleNamespace(kind="gemdos", partition=0)

        attributes = search_image_files(service, session, "r----a", None, "")
        self.assertEqual(attributes["results"][0]["metadataMatches"], ["attributes"])

        # The attribute byte is indexed under both spellings, because a
        # person may search for the letters the pane prints or for the value.
        numeric = search_image_files(service, session, "0x21", None, "")
        self.assertEqual(numeric["results"][0]["metadataMatches"], ["attributes"])

        datestamp = search_image_files(service, session, "1992-05-01", None, "")
        self.assertEqual(datestamp["results"][0]["metadataMatches"], ["datestamp"])

        filetype = search_image_files(service, session, "program", None, "")
        self.assertEqual(filetype["results"][0]["metadataMatches"], ["file type"])

    def test_image_search_accepts_a_sha256_prefix_and_returns_the_full_digest(self):
        service = Mock()
        content = b"A uniquely hashed Atari file"
        service.list_directory.return_value = {"entries": [{
            "name": "HASHED.DAT", "path": "HASHED.DAT", "type": "file", "length": len(content),
        }]}
        service.read_file.return_value = content
        digest = sha256_bytes(content)

        report = search_image_files(
            service, SimpleNamespace(kind="gemdos", partition=0), digest[:12], None, "",
        )

        self.assertTrue(report["results"][0]["hashMatch"])
        self.assertEqual(report["results"][0]["sha256"], digest)

    def test_image_search_reports_a_useful_binary_string_offset(self):
        service = Mock()
        content = bytes(range(32)) + b"LOAD GAME DATA" + bytes(range(32))
        service.list_directory.return_value = {"entries": [{
            "name": "CODE.DAT", "path": "CODE.DAT", "type": "file", "length": len(content),
        }]}
        service.read_file.return_value = content

        report = search_image_files(
            service, SimpleNamespace(kind="gemdos", partition=0), "game data", None, "",
        )

        self.assertEqual(report["results"][0]["matches"][0]["offset"], 32)

    def test_image_search_honours_cancellation_between_files(self):
        service = Mock()
        service.list_directory.return_value = {"entries": [
            {"name": "ONE.DAT", "path": "ONE.DAT", "type": "file", "length": 1},
            {"name": "TWO.DAT", "path": "TWO.DAT", "type": "file", "length": 1},
        ]}
        service.read_file.return_value = b"X"

        def cancel(message, current, _total):
            if message.startswith("Searching") and current == 1:
                raise OperationCancelled("Stopped safely")

        with self.assertRaises(OperationCancelled):
            search_image_files(
                service, SimpleNamespace(kind="gemdos", partition=0), "missing", None, "",
                progress=cancel,
            )

    def test_image_search_includes_installed_desktop_application_metadata(self):
        service = Mock()
        service.list_directory.return_value = {"entries": []}
        supplemental = [{
            "virtual": True, "resultType": "installed-application", "kind": "installed-application",
            "name": "Control Panel", "fileName": "CONTROL.ACC", "path": "CONTROL.ACC",
            "slot": 20, "openable": True,
            "searchFields": {"publisher": "Atari Corporation", "record": "#G"},
        }]

        report = search_image_files(
            service, SimpleNamespace(kind="gemdos", partition=0), "atari corporation", None, "",
            supplemental=supplemental,
        )

        self.assertEqual(report["results"][0]["metadataMatches"], ["publisher"])
        self.assertEqual(report["results"][0]["fileName"], "CONTROL.ACC")

    def test_image_search_reads_raw_rom_banks(self):
        service = Mock()
        service.list_rom_banks.return_value = [{
            "bank": 0, "name": "Cartridge ROM", "length": 64,
        }]
        service.read_file.return_value = bytes(16) + b"CARTRIDGE HEADER" + bytes(32)

        report = search_image_files(
            service, SimpleNamespace(kind="rom", partition=None), "cartridge header", None, "",
        )

        self.assertEqual(report["results"][0]["path"], "bank:0")
        self.assertEqual(report["results"][0]["matches"][0]["offset"], 16)

    def test_basic_listing_always_has_a_space_after_the_line_number(self):
        self.assertEqual(
            _format_basic_listing('10PRINT "HELLO"\n20 GOTO 10\n30\tEND'),
            '10 PRINT "HELLO"\n20 GOTO 10\n30 END',
        )

    def test_a_stos_program_opens_read_only(self):
        """STOS is decoded but never re-encoded, so it opens as a listing to read."""
        program = encode_stos_program('10 CLS\n20 CURS OFF\n30 PRINT "HELLO"\n40 GOTO 20')
        folder, service = self.service_with_file(program)
        try:
            report = inspect_editable_file(
                service,
                SimpleNamespace(target_hardware="tos", hfe_read_only=False, kind="gemdos"),
                "GAME.BAS", None,
            )
        finally:
            folder.cleanup()
        self.assertEqual(report["view"], "basic")
        self.assertEqual(report["basic"]["dialect"], "STOS BASIC")
        self.assertFalse(report["basic"]["editable"])
        self.assertFalse(report["editable"])
        self.assertIn("STOS BASIC", report["basic"]["editNote"])
        self.assertIn('print "HELLO"', report["text"])

    def test_every_basic_editing_helper_refuses_stos_by_name(self):
        for call in (
            lambda: prepare_basic_source('10 PRINT "A"', 100, 10, "stos-basic"),
            lambda: normalise_basic_source('10 PRINT "A"', "stos-basic"),
            lambda: verify_basic_source('10 PRINT "A"', "", "stos-basic"),
            lambda: pack_basic_lines([['PRINT "A"']], "stos-basic"),
        ):
            with self.assertRaises(DiskError) as refusal:
                call()
            self.assertIn("STOS BASIC is read-only", str(refusal.exception))

    def test_desktop_and_system_files_open_as_unnumbered_scripts(self):
        script = b"SETENV PATH=C:\\BIN\nCD C:\\\nEXEC C:\\MINT\\INIT.PRG\nECHO Ready\n"
        folder, service = self.service_with_file(script)
        try:
            report = inspect_editable_file(service, SimpleNamespace(hfe_read_only=False, kind="gemdos"), "MINT.CNF", None)
        finally:
            folder.cleanup()
        self.assertEqual(report["view"], "script")
        self.assertTrue(report["editable"])
        self.assertFalse(report["tokenisedBasic"])
        self.assertEqual(
            [item["action"] for item in report["script"]["commands"]],
            ["SETENV", "CD", "EXEC", "ECHO"],
        )
        self.assertEqual(report["text"].splitlines()[0], "SETENV PATH=C:\\BIN")

        folder, service = self.service_with_file(b"ECHO OFF\nCOPY A:\\*.* C:\\GAMES\n")
        try:
            other = inspect_editable_file(service, SimpleNamespace(hfe_read_only=False, kind="gemdos"), "AUTO.BAT", None)
        finally:
            folder.cleanup()
        self.assertEqual(other["view"], "script")

    def test_a_stored_disk_container_opens_as_a_browsable_container(self):
        folder, service = self.service_with_file(_msa_container())
        try:
            report = inspect_editable_file(
                service,
                SimpleNamespace(target_hardware="floppy", hfe_read_only=False, kind="gemdos"),
                "GAME.MSA", None,
            )
        finally:
            folder.cleanup()
        self.assertEqual(report["view"], "container")
        self.assertEqual(report["containerKind"], "disk-or-archive")
        self.assertTrue(report["readOnly"])
        self.assertFalse(report["editable"])

    def test_renumber_updates_destinations_not_string_contents(self):
        """A quoted 30 is text, not a line, and must survive a renumber."""
        listing = _renumber_listing('10 GOTO 30\n20 PRINT "30"\n30 FULLW 2', 100, 20)
        self.assertIn("100 GOTO 140", listing)
        self.assertIn('120 PRINT "30"', listing)
        self.assertIn("140 FULLW 2", listing)

    def test_prepare_basic_renumbers_newly_edited_listing(self):
        result = prepare_basic_source('10 PRINT "A"\n15 GOSUB 10\n20 END', 1000, 10)
        self.assertEqual(result["lineCount"], 3)
        self.assertEqual(result["dialect"], "ST BASIC")
        self.assertIn("1010 GOSUB 1000", result["text"])

    def test_renumbering_refuses_a_dialect_without_line_numbers(self):
        with self.assertRaises(DiskError) as refusal:
            prepare_basic_source('PRINT "A"\nEND', 1000, 10, "gfa-basic-3")
        self.assertIn("no line numbers", str(refusal.exception))

    def test_normalise_basic_source_validates_and_formats_pasted_lines(self):
        result = normalise_basic_source('100PRINT "PASTED"\n110GOTO 100')
        self.assertEqual(result["lineCount"], 2)
        self.assertEqual(result["text"], '100 PRINT "PASTED"\n110 GOTO 100')

    def test_basic_verification_proves_round_trip_and_maps_lines(self):
        result = verify_basic_source('10 PRINT "HELLO"\n20 GOTO 10', '10 PRINT "OLD"')
        self.assertTrue(result["roundTripExact"])
        self.assertEqual(result["lineCount"], 2)
        self.assertEqual(result["destinations"], [10])
        self.assertEqual([row["line"] for row in result["lineRanges"]], [10, 20])
        self.assertTrue(result["diff"])

    def test_project_regions_override_code_and_apply_bookmarks(self):
        # MOVEQ #65,D0 ; JSR $00FC00EE ; RTS, then a message the project marks
        # as text so it is not disassembled.
        data = bytes.fromhex("70414EB900FC00EE4E75") + b"HELLO"
        report = disassemble_file_data(
            data, {"attributes": ARCHIVE_ONLY}, SimpleNamespace(target_hardware="floppy"),
            "CODE.PRG", project={
                "symbols": {"0": "start_here"},
                "regions": [{"start": 10, "end": 15, "kind": "text", "name": "message", "width": 8}],
                "bookmarks": [{"offset": 0, "name": "entry", "note": "Reviewed entry"}],
                "comments": {"0": "User annotation"},
            },
        )
        self.assertEqual(report["rows"][0]["label"], "start_here")
        self.assertIn("Reviewed entry", report["rows"][0]["comment"])
        self.assertIn("User annotation", report["rows"][0]["comment"])
        message = next(row for row in report["rows"] if row.get("regionKind") == "text")
        self.assertEqual(message["label"], "message")
        self.assertEqual(message["mnemonic"], "DC.B")

    def test_68000_project_words_use_the_processor_byte_order(self):
        report = disassemble_file_data(
            bytes.fromhex("12344E75"), {"attributes": ARCHIVE_ONLY},
            SimpleNamespace(target_hardware="tos"), "CODE.PRG", architecture="m68k",
            project={"regions": [{"start": 0, "end": 2, "kind": "words", "width": 8}]},
        )
        word = next(row for row in report["rows"] if row.get("regionKind") == "words")
        self.assertEqual(word["operand"], "$1234")

    def test_pack_basic_lines_measures_what_the_encoder_produces(self):
        """Only a numbered dialect can be packed, and ST BASIC is the one that is.

        ST BASIC stores its listing as characters, so the encoder accepts a
        line of any length and every safe run fits on one numbered line. The
        packer still reports the shape of each run, which is what the caller
        joins statements by.
        """
        statements = ['PRINT "A"'] * 80
        result = pack_basic_lines([statements, ["A=1", "B=2", "PRINT A+B"]])
        self.assertEqual(result["groups"][0], [80])
        self.assertEqual(sum(result["groups"][0]), 80)
        self.assertEqual(result["groups"][1], [3])

        with self.assertRaises(DiskError) as refusal:
            pack_basic_lines([['PRINT "A"']], "gfa-basic-3")
        self.assertIn("no line numbers", str(refusal.exception))

    def test_a_binary_file_gets_annotated_68000_disassembly(self):
        # MOVE.W #$09,-(SP) ; TRAP #1 ; MOVE.W #$4C,-(SP) ; TRAP #1
        data = bytes.fromhex("3F3C00094E413F3C004C4E41")
        folder, service = self.service_with_file(
            data, {"attributes": ARCHIVE_ONLY, "access": ARCHIVE_ONLY, "length": len(data)}
        )
        try:
            report = disassemble_file(
                service, SimpleNamespace(target_hardware="floppy"), "CODE.PRG", None, None
            )
        finally:
            folder.cleanup()
        self.assertEqual(report["architecture"], "68000")
        self.assertIn("function number $09", report["rows"][0]["comment"])
        self.assertIn("GEMDOS Cconws", report["rows"][1]["comment"])
        self.assertIn("GEMDOS Pterm", report["rows"][3]["comment"])
        self.assertGreater(report["reachableInstructions"], 0)

    def test_printable_strings_require_human_looking_words(self):
        data = b"!!!!1234___\0Hello world!\0AB\0LOAD GAME\0hJJJJ)\0A1$%\0"
        strings = _printable_strings(data, 0x8000)
        self.assertEqual([item["text"] for item in strings], ["Hello world!", "LOAD GAME"])
        self.assertEqual(strings[0]["address"], 0x8000 + data.index(b"Hello"))

    def test_file_disassembly_reports_the_readable_text_it_finds(self):
        # MOVEQ #0,D0 ; RTS, then a NUL-terminated string.
        data = bytes.fromhex("70004e75") + b"Hello world\0"
        folder, service = self.service_with_file(
            data, {"attributes": ARCHIVE_ONLY, "access": ARCHIVE_ONLY, "length": len(data)}
        )
        try:
            report = disassemble_file(
                service, SimpleNamespace(target_hardware="floppy"), "CODE.PRG", None, None
            )
        finally:
            folder.cleanup()
        self.assertTrue(
            any("Hello world" in str(row.get("comment") or "") for row in report["rows"]),
            report["rows"][:6],
        )

    def test_disassembly_assigns_semantic_routine_and_flow_labels(self):
        """A called routine gets a purpose label; a backwards branch is a loop."""
        # BSR.B *+6 ; RTS ; NOP ; MOVEA.L $4.W,A6 ; BRA.B *-2 ; RTS
        data = bytes.fromhex("61044e754e712c78000460fe4e75")
        folder, service = self.service_with_file(
            data, {"attributes": ARCHIVE_ONLY, "access": ARCHIVE_ONLY, "length": len(data)}
        )
        try:
            report = disassemble_file(
                service, SimpleNamespace(target_hardware="floppy"), "CODE.PRG", None, None
            )
        finally:
            folder.cleanup()
        labels = [str(row.get("label") or "") for row in report["rows"]]
        self.assertTrue(any(label for label in labels), report["rows"])
        self.assertTrue(
            any(label.startswith(("loop", "sub_", "subroutine", "call_", "access_")) for label in labels),
            labels,
        )

    def test_basic_save_re_encodes_and_preserves_atari_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "EDITOR")
            source = root / "program"
            source.write_bytes(_gfa_program('PRINT "OLD"\nEND'))
            service.put(session, "PROGRAM.GFA", source)
            service.set_access(session, ["PROGRAM.GFA"], writable=False)
            before = inspect_editable_file(service, session, "PROGRAM.GFA", None)

            save_editor_text(
                service, session, "PROGRAM.GFA", None,
                'PRINT "NEW"\nEND', True, before["sha256"],
            )

            self.assertIn(
                'PRINT "NEW"',
                detokenise(service.read_file(session, "PROGRAM.GFA")),
            )
            metadata = service.file_metadata(session, "PROGRAM.GFA")
            # The attribute byte survives the re-encoded write: a read-only
            # file is one the desktop refuses to delete, and it stays that way.
            self.assertTrue(metadata["access"] & READ_ONLY_BIT, metadata)
            self.assertEqual(metadata["attributesText"], "r----a", metadata)

    def test_basic_save_preserves_a_trailing_binary_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "EDITOR")
            payload = bytes.fromhex("A90020EEFF60") + b"PAYLOAD\x00"
            source = root / "program"
            source.write_bytes(_gfa_program('PRINT "OLD"\nEND') + payload)
            service.put(session, "PROGRAM.GFA", source, "r----a")
            before = inspect_editable_file(service, session, "PROGRAM.GFA", None)

            self.assertTrue(before["editable"])
            self.assertTrue(before["basic"]["compound"])
            self.assertEqual(before["basic"]["trailingBytes"], len(payload))
            save_editor_text(
                service, session, "PROGRAM.GFA", None,
                'PRINT "NEW"\nEND', True, before["sha256"],
            )

            stored = service.read_file(session, "PROGRAM.GFA")
            self.assertTrue(stored.endswith(payload))
            self.assertIn('PRINT "NEW"', detokenise(stored[:-len(payload)]))

    def test_save_as_creates_a_sibling_with_content_and_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "EDITOR")
            source = root / "program"
            source.write_bytes(_gfa_program('PRINT "OLD"\nEND'))
            service.put(session, "PROGRAM.GFA", source)
            service.set_access(session, ["PROGRAM.GFA"], writable=False)
            before = inspect_editable_file(service, session, "PROGRAM.GFA", None)

            _image, saved_path = save_editor_text_as(
                service, session, "PROGRAM.GFA", None, "COPY.GFA",
                'PRINT "NEW"\nEND', True, before["sha256"],
            )

            self.assertEqual(saved_path, "COPY.GFA")
            self.assertIn('PRINT "NEW"', detokenise(service.read_file(session, "COPY.GFA")))
            metadata = service.file_metadata(session, "COPY.GFA")
            # One attribute byte is the whole of a GEMDOS entry's metadata,
            # so the decoded access value and the raw byte are the same thing.
            self.assertEqual(metadata["attributes"], metadata["access"], metadata)
            # The original was read-only, so the sibling is too.
            self.assertTrue(metadata["access"] & READ_ONLY_BIT, metadata)
            self.assertEqual(metadata["attributesText"], "r----a", metadata)

    def test_file_hex_write_is_fixed_size_and_stale_guarded(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "EDITOR")
            source = root / "code"
            source.write_bytes(b"ABCDEF")
            service.put(session, "CODE.DAT", source)
            before = inspect_editable_file(service, session, "CODE.DAT", None)

            result = write_file_range(
                service, session, "CODE.DAT", None, before["sha256"],
                [{"offset": 1, "data": "7879"}], True,
            )

            self.assertEqual(result["written"], 2)
            self.assertEqual(service.read_file(session, "CODE.DAT"), b"AxyDEF")

    def test_file_properties_change_the_directory_entry_not_the_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "EDITOR")
            source = root / "notes"
            source.write_bytes(b"UNCHANGED")
            service.put(session, "NOTES.TXT", source)
            before = inspect_editable_file(service, session, "NOTES.TXT", None)

            update_file_properties(
                service, session, "NOTES.TXT", None, before["sha256"],
                protection="rh---a", writable=False,
                datestamp="1992-05-01T09:30:00.000",
            )

            self.assertEqual(service.read_file(session, "NOTES.TXT"), b"UNCHANGED")
            metadata = service.file_metadata(session, "NOTES.TXT")
            self.assertTrue(metadata["access"] & READ_ONLY_BIT)
            self.assertEqual(metadata["attributesText"], "rh---a")
            self.assertTrue(metadata["datestamp"].startswith("1992-05-01T09:30"), metadata)

            # Clearing the read-only bit is the same edit in reverse, and the
            # file's bytes are still never rewritten.
            update_file_properties(
                service, session, "NOTES.TXT", None, before["sha256"],
                protection="-----a", writable=True,
            )
            metadata = service.file_metadata(session, "NOTES.TXT")
            self.assertFalse(metadata["access"] & READ_ONLY_BIT, metadata)
            self.assertEqual(service.read_file(session, "NOTES.TXT"), b"UNCHANGED")


class ProgramDisassemblyTests(unittest.TestCase):
    """Where a listing of an Atari program begins."""

    @staticmethod
    def _program(text: bytes, symbols: bytes = b"") -> bytes:
        header = struct.pack(
            ">HIIIIIIH", 0x601A, len(text), 0, 0, len(symbols), 0, 0, 0
        )
        return header + text + symbols

    def test_a_listing_starts_at_the_code_and_not_at_the_header(self) -> None:
        """The header is sizes, and decoding sizes as instructions is noise.

        A .PRG begins with 28 bytes that tell TOS how to load it. Read as
        machine code they disassemble into a branch and half a dozen ORI.B
        instructions, so every Atari program opened in the editor started with
        seven lines that meant nothing.
        """
        program = self._program(b"\x4e\x71" * 8)
        header, start, length = _program_body(program, None, None)
        self.assertEqual(start, 28)
        self.assertEqual(length, 16)
        self.assertEqual(header["text"], 16)

    def test_a_symbol_table_is_not_disassembled_as_code(self) -> None:
        program = self._program(b"\x4e\x71" * 4, symbols=b"SYMBOLDATA" * 4)
        _header, start, length = _program_body(program, None, None)
        self.assertEqual((start, length), (28, 8))

    def test_an_offset_of_zero_is_a_deliberate_request_for_the_header(self) -> None:
        """Absent and zero are different answers to "where do I start?".

        Zero means the reader wants the first byte of the file, header and
        all. Absent means they have not said, and the decoder should start
        where the code is. Collapsing the two loses the only way to look at
        a program header in the disassembler.
        """
        program = self._program(b"\x4e\x71" * 8)
        self.assertEqual(_program_body(program, 0, 28)[1:], (0, 28))
        self.assertEqual(_program_body(program, 0, None)[1:], (0, None))
        self.assertEqual(_program_body(program, 2, None)[1:], (2, None))

    def test_a_file_that_is_not_a_program_is_left_where_it_was(self) -> None:
        header, start, length = _program_body(b"not a program at all" * 8, None, None)
        self.assertIsNone(header)
        self.assertEqual((start, length), (0, None))

    def test_a_truncated_program_is_not_treated_as_one(self) -> None:
        """The sizes have to account for the bytes that are there."""
        claimed = struct.pack(">HIIIIIIH", 0x601A, 1_000_000, 0, 0, 0, 0, 0, 0)
        header, start, _length = _program_body(claimed + b"\x4e\x71", None, None)
        self.assertIsNone(header)
        self.assertEqual(start, 0)


if __name__ == "__main__":
    unittest.main()
