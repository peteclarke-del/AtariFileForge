"""The three Atari ST BASICs: recognition, listing, writing and scanning.

The tests are grouped by the promise they keep rather than by module, because
the promises are what the workbench relies on:

* ``detect`` names the dialect from the bytes, with no help from the filename.
* A dialect that says it is writable round-trips exactly, in both directions.
* A dialect that says it is not writable refuses to write, rather than writing
  something plausible.
* Scanning types every element of a line, and a variable that happens to
  resemble a command stays a variable.
"""

from __future__ import annotations

import pathlib
import struct

import pytest

from app.basic_listing import decode_program
from atarinut.basic import (
    DIALECTS,
    DIALECTS_BY_ID,
    GFA_BASIC_2,
    GFA_BASIC_3,
    ST_BASIC,
    STOS_BASIC,
    TokenKind,
    Verdict,
    detect,
    detokenise,
    dialect_for,
    gfa,
    is_tokenised,
    scan_program,
    stos,
    tokenise,
)
from atarinut.errors import DataError

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "basic"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def listing(name: str) -> str:
    return fixture(name).decode("latin-1").replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "dialect", "verdict"),
    [
        ("tilemap.gfa", GFA_BASIC_3, Verdict.BASIC),
        ("tilemap.lst", GFA_BASIC_3, Verdict.BASIC),
        ("gfademo.lst", GFA_BASIC_3, Verdict.BASIC),
        ("stars.bas", STOS_BASIC, Verdict.BASIC),
        ("stars.asc", STOS_BASIC, Verdict.BASIC),
        ("clock.bas", ST_BASIC, Verdict.BASIC),
    ],
)
def test_detect_names_the_dialect_from_the_bytes(name, dialect, verdict):
    detection = detect(fixture(name))
    assert detection.dialect is dialect, f"{name} was read as {detection.dialect}: {detection.reason}"
    assert detection.verdict is verdict
    assert detection.reason


def test_detect_refuses_what_is_not_basic():
    for data in (b"", b"\x00" * 64, bytes(range(256)), b"#!/bin/sh\necho hello\n"):
        detection = detect(data)
        assert detection.verdict is Verdict.NOT_BASIC
        assert detection.dialect is None
        assert detection.reason


def test_detect_says_why_a_related_file_is_not_a_program():
    """A GFA 2 save and a STOS memory bank are recognised, then declined.

    Silently reporting "not BASIC" for a file that plainly is one would send
    the user looking for a fault in their disk image, so the reason names it.
    """
    bank = stos.BANK_MAGIC + bytes(64)
    assert detect(bank).verdict is Verdict.NOT_BASIC
    assert "memory bank" in detect(bank).reason
    gfa_2 = gfa.MAGIC_2 + bytes(64)
    assert detect(gfa_2).verdict is Verdict.NOT_BASIC
    assert "GFA BASIC 2" in detect(gfa_2).reason


def test_trailing_bytes_are_reported_rather_than_swallowed():
    program = fixture("tilemap.gfa") + b"appended payload"
    detection = detect(program)
    assert detection.verdict is Verdict.BASIC_TRAILING
    assert detection.program_length == len(fixture("tilemap.gfa"))
    assert detokenise(program) == listing("tilemap.lst")


def test_is_tokenised_is_about_storage_not_about_being_basic():
    assert is_tokenised(fixture("tilemap.gfa"))
    assert is_tokenised(fixture("stars.bas"))
    # ST BASIC saves plain text, so there is nothing tokenised to unpick.
    assert not is_tokenised(fixture("clock.bas"))
    assert not is_tokenised(fixture("tilemap.lst"))


# ---------------------------------------------------------------------------
# GFA BASIC 3
# ---------------------------------------------------------------------------
def test_gfa_listing_round_trips_through_the_tokeniser():
    source = listing("tilemap.lst")
    assert detokenise(tokenise(source, GFA_BASIC_3)) == source


def test_gfa_program_round_trips_through_the_lister():
    program = fixture("tilemap.gfa")
    assert tokenise(detokenise(program), GFA_BASIC_3) == program
    assert gfa.canonicalise(program) == program


def test_a_real_gfa_listing_reaches_a_stable_form():
    """Real source is not written the way the lister writes it.

    ``gfademo.lst`` calls its procedures without the ``@`` that GFA's own
    lister prints, so the first pass changes the text. What has to hold is
    that the second pass does not: once through the codec, the listing is
    fixed, which is what makes an edit-save cycle safe.
    """
    once = detokenise(tokenise(listing("gfademo.lst"), GFA_BASIC_3))
    assert once != listing("gfademo.lst")
    assert detokenise(tokenise(once, GFA_BASIC_3)) == once
    assert tokenise(once, GFA_BASIC_3) == tokenise(detokenise(tokenise(once, GFA_BASIC_3)), GFA_BASIC_3)


def test_gfa_indentation_comes_from_block_structure():
    lines = list(scan_program(fixture("tilemap.gfa")))
    depths = {line.text.strip(): line.depth for line in lines}
    assert depths["PROCEDURE build_map(w%,h%)"] == 0
    assert depths["FOR y%=0 TO h%-1"] == 1
    assert depths["FOR x%=0 TO w%-1"] == 2
    assert depths["IF x%=0 OR y%=0 OR x%=w%-1 OR y%=h%-1"] == 3
    assert depths["ELSE"] == 3
    assert depths["ENDIF"] == 3
    assert depths["RETURN"] == 0
    assert all(line.text.startswith("  " * line.depth) for line in lines)


def test_gfa_floats_survive_the_eight_byte_encoding():
    for value in (0.0, 1.0, -1.0, 0.5, 3.5, 1e10, -2.25e-8, 3.14159265358979):
        assert gfa.gfa_double_to_float(gfa.float_to_gfa_double(value)) == pytest.approx(value)
    assert gfa.float_to_gfa_double(0.0) == bytes(8)


def test_a_truncated_gfa_file_is_refused_with_its_reason():
    program = fixture("tilemap.gfa")
    with pytest.raises(DataError):
        gfa.parse_program(program[:40])
    assert detect(program[:40]).verdict is Verdict.NOT_BASIC


# ---------------------------------------------------------------------------
# STOS BASIC
# ---------------------------------------------------------------------------
def test_stos_program_lists_as_its_source():
    assert stos.detokenise_stos(fixture("stars.bas")) == listing("stars.asc")
    assert detokenise(fixture("stars.bas")) == listing("stars.asc")


def test_stos_program_round_trips_through_the_corpus_writer():
    program = fixture("stars.bas")
    assert stos.encode_program(stos.detokenise_stos(program)) == program
    assert stos.canonicalise(program) == program


def test_stos_refuses_to_be_written_and_says_why():
    """Read-only is a decision here, not an omission.

    The keyword table was derived from real programs rather than transcribed
    from STOS, so a file written back could hold a token STOS does not accept.
    Refusing is the honest outcome, and the editor reads ``writable`` to open
    the file without a save button.
    """
    assert STOS_BASIC.writable is False
    with pytest.raises(NotImplementedError) as raised:
        tokenise("10 print", STOS_BASIC)
    assert "read-only" in str(raised.value)


def test_stos_literals_decode_to_their_written_values():
    lines = {line.number: line.text for line in stos.parse_program(fixture("stars.bas")).lines}
    assert lines[40] == "COUNT=64 : SPEED=2.5"
    assert lines[80] == "palette $0,$777,$555,$333"
    assert lines[180] == 'curs on : print "stars drawn: ";COUNT'


def test_stos_fast_floating_point_survives_a_round_trip():
    for value in (0.0, 1.0, -1.0, 2.5, 0.125, 1000.0, -0.0625):
        assert stos.ffp_to_float(stos.float_to_ffp(value)) == pytest.approx(value)
    assert stos.float_to_ffp(0.0) == bytes(4)
    assert stos.ffp_to_float(bytes.fromhex("c8000046")) == 50.0


def test_an_unrecoverable_stos_token_lists_as_a_placeholder():
    """A keyword the derived table never saw must show as a gap, not a guess."""
    assert stos.token_text(0xA0, 0x00) == "{&A0,&00}"
    assert stos.token_text(0x97) == "{&97}"
    assert stos.token_text(0xA0, 0xC8) == "palette"


def test_a_malformed_stos_line_is_refused():
    program = bytearray(fixture("stars.bas"))
    struct.pack_into(">H", program, stos.HEADER_LENGTH, 3)
    with pytest.raises(DataError):
        stos.parse_program(bytes(program))


# ---------------------------------------------------------------------------
# Atari ST BASIC
# ---------------------------------------------------------------------------
def test_st_basic_is_stored_as_the_text_it_lists_as():
    program = fixture("clock.bas")
    source = detokenise(program, ST_BASIC)
    assert tokenise(source, ST_BASIC) == program
    assert detokenise(tokenise(source, ST_BASIC), ST_BASIC) == source
    assert b"\r\n" in program, "ST BASIC writes the ST's own line endings"


def test_st_basic_is_told_apart_from_a_stos_listing():
    """Both dialects number their lines, so the keywords have to decide."""
    assert detect(fixture("clock.bas")).dialect is ST_BASIC
    assert detect(fixture("stars.asc")).dialect is STOS_BASIC


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
def kinds(line):
    return [(token.kind, token.text) for token in line.tokens]


def test_scanning_types_every_element_of_a_line():
    line = next(item for item in scan_program(fixture("clock.bas")) if item.number == 70)
    assert kinds(line) == [
        (TokenKind.LINE_NUMBER, "70"),
        (TokenKind.KEYWORD, "GOTOXY"),
        (TokenKind.NUMBER, "2"),
        (TokenKind.OPERATOR, ","),
        (TokenKind.NUMBER, "2"),
        (TokenKind.OPERATOR, ":"),
        (TokenKind.KEYWORD, "PRINT"),
        (TokenKind.STRING, '"ATARI ST BASIC CLOCK"'),
    ]


def test_a_rem_takes_the_rest_of_its_line_as_a_comment():
    line = next(item for item in scan_program(fixture("clock.bas")) if item.number == 210)
    assert [token.kind for token in line.tokens] == [
        TokenKind.LINE_NUMBER, TokenKind.KEYWORD, TokenKind.COMMENT
    ]
    assert line.tokens[-1].text.strip() == "the tidy-up section"


def test_a_typed_name_that_resembles_a_command_stays_a_variable():
    """``PRINT$`` is a string variable, not the command with a suffix.

    Every ST BASIC follows this rule, and the editor's colouring has to agree
    with it or a listing will show a variable painted as a keyword.
    """
    source = '10 PRINT$="x":COLORS%=2:PRINT PRINT$;COLORS%'
    line = next(iter(scan_program(source, ST_BASIC)))
    named = [(token.kind, token.text) for token in line.tokens if token.kind in (TokenKind.KEYWORD, TokenKind.IDENTIFIER)]
    assert named == [
        (TokenKind.IDENTIFIER, "PRINT$"),
        (TokenKind.IDENTIFIER, "COLORS%"),
        (TokenKind.KEYWORD, "PRINT"),
        (TokenKind.IDENTIFIER, "PRINT$"),
        (TokenKind.IDENTIFIER, "COLORS%"),
    ]


def test_scanning_a_gfa_program_offers_spans_into_the_file():
    program = fixture("tilemap.gfa")
    for line in scan_program(program):
        for token in line.tokens:
            assert 0 <= token.start <= token.end <= len(program)
        joined = "".join(token.text for token in line.tokens)
        assert joined.replace(" ", "") == line.text.replace(" ", "")


def test_scanning_a_stos_program_offers_spans_into_the_file():
    program = fixture("stars.bas")
    for line in scan_program(program):
        for token in line.tokens:
            assert stos.HEADER_LENGTH <= token.start <= token.end <= len(program)


def test_scanning_never_needs_the_whole_listing_first():
    """The scanner is a generator, so a program too large to edit still lists."""
    scan = scan_program(fixture("tilemap.gfa"))
    first = next(scan)
    assert first.text.startswith("'")
    assert first.index == 0


# ---------------------------------------------------------------------------
# Dialect metadata
# ---------------------------------------------------------------------------
def test_dialect_metadata_is_coherent():
    assert set(DIALECTS) == {"GFA BASIC 3", "GFA BASIC 2", "STOS BASIC", "ST BASIC"}
    assert set(DIALECTS_BY_ID) == {"gfa-basic-3", "gfa-basic-2", "stos-basic", "st-basic"}
    for dialect in DIALECTS.values():
        assert dialect_for(dialect.name) is dialect
        assert dialect_for(dialect.identifier) is dialect
        assert dialect.extensions and all(item.startswith(".") for item in dialect.extensions)
        assert dialect.keywords
    assert GFA_BASIC_3.line_numbers is False
    assert STOS_BASIC.line_numbers is True
    assert ST_BASIC.line_numbers is True
    with pytest.raises(DataError):
        dialect_for("QBasic")


def test_gfa_2_is_a_listing_dialect_without_the_3x_words():
    """GFA BASIC 2 is offered for source, not for a saved 2.x program.

    The keyword set is what earns it a place: it is GFA BASIC 3's minus the
    words 3.0 introduced, so the editor can warn that a listing will not run
    under 2.x.
    """
    assert GFA_BASIC_2.tokenised is False
    assert "SELECT" in GFA_BASIC_3.keywords
    assert "SELECT" not in GFA_BASIC_2.keywords
    assert "PRINT" in GFA_BASIC_2.keywords
    source = "a%=1\nPRINT a%\n"
    assert detokenise(tokenise(source, GFA_BASIC_2), GFA_BASIC_2) == source


# ---------------------------------------------------------------------------
# The workbench's own entry point
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "dialect_id", "writable"),
    [("tilemap.gfa", "gfa-basic-3", True), ("stars.bas", "stos-basic", False), ("clock.bas", "st-basic", True)],
)
def test_decode_program_reports_the_dialect_and_whether_it_can_be_saved(name, dialect_id, writable):
    decoded = decode_program(fixture(name))
    assert decoded is not None
    assert decoded.dialect_id == dialect_id
    assert decoded.writable is writable
    assert decoded.lines
    assert all(line.text for line in decoded.lines)


def test_decode_program_returns_nothing_for_anything_else():
    assert decode_program(b"\x00\x01\x02\x03") is None
    assert decode_program(b"") is None
