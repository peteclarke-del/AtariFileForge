"""The three BASICs the Atari ST was programmed in.

The ST never had one BASIC. Atari shipped ST BASIC in the box and almost
nobody kept it; GFA BASIC took the machine and is what most surviving ST
source is written in; STOS was the games BASIC and saves in a format of its
own. This package reads all three from a disk image and tells the workbench
which one it is looking at.

``detect(data)`` is the way in. It takes raw bytes with no hint from the file
name and returns a ``Detection`` naming the dialect, so the caller does not
have to guess from an extension that a floppy may not carry.

The three dialects are not equally writable, and the difference is deliberate
rather than unfinished:

``GFA BASIC 3``
    Read and written. A ``.GFA`` file is decoded to a listing and a listing is
    encoded back to a ``.GFA``; the tests prove both directions on a corpus.
    Its plain-text ``.LST`` export is read as well.
``GFA BASIC 2``
    A listing dialect only. GFA BASIC 2 saved a different binary layout that
    this package does not decode, so ``GFA_BASIC_2`` exists for ``.LST``
    source and for the editor to say that a word is newer than 2.x will run.
``STOS BASIC``
    Read only. The reader is faithful and tested, but the keyword table was
    derived from real programs rather than transcribed from STOS, and a saved
    file holds interpreter state this package writes as zeros. Writing a file
    that a real STOS may refuse to load is worse than not writing one, so
    ``STOS_BASIC.writable`` is ``False`` and ``tokenise`` raises.
``Atari ST BASIC``
    Read and written, trivially: ST BASIC saves plain ASCII, so tokenising is
    the identity encoding and the round trip is exact by construction.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum

from ..errors import DataError
from . import gfa, stbasic, stos, stos_tables
from .gfa_tables import LINE_COMMANDS, PRIMARY_TOKENS, SECONDARY_TOKENS


class TokenKind(Enum):
    """What a scanned element is, for the editor's colouring."""

    KEYWORD = "keyword"
    IDENTIFIER = "identifier"
    NUMBER = "number"
    STRING = "string"
    COMMENT = "comment"
    OPERATOR = "operator"
    LINE_NUMBER = "line-number"


class Verdict(Enum):
    BASIC = "basic"
    BASIC_TRAILING = "basic-trailing"
    NOT_BASIC = "not-basic"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    text: str
    start: int
    end: int
    value: object = None


@dataclass(frozen=True)
class Line:
    """One line of a program: its text, where it came from and its tokens."""

    index: int
    number: int | None
    text: str
    start: int
    end: int
    depth: int = 0
    tokens: tuple = ()

    @property
    def line_number(self) -> int:
        """The printed line number, or the position for a dialect without them."""
        return self.index if self.number is None else self.number


@dataclass(frozen=True)
class Detection:
    """What ``detect`` made of a run of bytes.

    ``tokenised`` is about these bytes, not about the dialect: a GFA BASIC
    program is tokenised, but the same program's ``.LST`` export is not, and
    both are ``GFA_BASIC_3``.
    """

    verdict: Verdict
    dialect: object = None
    reason: str = ""
    program_length: int | None = None
    line_count: int = 0
    tokenised: bool = False


# ---------------------------------------------------------------------------
# Dialects
# ---------------------------------------------------------------------------
def _gfa_keywords() -> frozenset[str]:
    """Every word GFA BASIC 3 has a token for, taken from the token tables."""
    words: set[str] = set()
    for table in (LINE_COMMANDS, PRIMARY_TOKENS, SECONDARY_TOKENS):
        for text in table.values():
            if not text:
                continue
            stripped = text.strip().rstrip("(")
            if stripped and stripped[0].isalpha():
                words.update(stripped.split())
    return frozenset(word.upper() for word in words if word)


#: Words GFA BASIC 3 introduced. A listing that uses one of these will not run
#: under GFA BASIC 2, which is what the editor warns about when the file is
#: opened as 2.x. This list follows the "new in 3.0" section of the GFA BASIC
#: 3 manual and is best effort: it is a warning, not a refusal.
GFA_3_KEYWORDS: frozenset[str] = frozenset(
    """
    SELECT CASE DEFAULT ENDSELECT FUNCTION ENDFUNC DO LOOP EXIT INLINE RCALL
    ARRAYFILL SORT VAR LOCAL BMOVE DPEEK DPOKE LPEEK LPOKE SETTIME SUCC PRED
    TRUNC FRAC RC_INTERSECT OB_ADR DEFNUM DEFWRD DEFBYT DEFFLT DEFBIT DEFLIST
    CHAR CARD SINGLE DOUBLE DOWNTO ALERT FILESELECT MENU CLIP TEXT
    """.split()
)

#: The words that make a listing recognisably GFA rather than anything else.
GFA_MARKERS = ("PROCEDURE", "ENDFUNC", "ENDSELECT", "REPEAT", "UNTIL", "WEND",
               "DEFFILL", "DEFLINE", "PBOX", "SPOKE", "SGET", "SPUT", "INLINE")


@dataclass(frozen=True)
class Dialect:
    """One BASIC, and what this package can do with it.

    ``writable`` is the flag the editor reads: a dialect that cannot be
    re-encoded faithfully opens read-only rather than risking a save that the
    original interpreter would not load.
    """

    name: str
    identifier: str
    label: str
    writable: bool
    tokenised: bool
    line_numbers: bool
    generation: int
    extensions: tuple[str, ...]
    keywords: frozenset[str] = field(default_factory=frozenset)
    compound: tuple[str, ...] = ()
    suffixes: str = ""
    comment_marks: str = "'"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.name


GFA_BASIC_3 = Dialect(
    name="GFA BASIC 3",
    identifier="gfa-basic-3",
    label="GFA BASIC 3.x",
    writable=True,
    tokenised=True,
    line_numbers=False,
    generation=3,
    extensions=(".gfa", ".lst"),
    keywords=_gfa_keywords(),
    compound=("EXIT IF", "ELSE IF", "END SELECT", "END IF", "DO WHILE", "DO UNTIL",
              "LOOP WHILE", "LOOP UNTIL", "ON ERROR", "ON MENU", "OPEN OUT"),
    suffixes="$%&!#|",
)

GFA_BASIC_2 = Dialect(
    name="GFA BASIC 2",
    identifier="gfa-basic-2",
    label="GFA BASIC 2.x listing",
    writable=True,
    tokenised=False,
    line_numbers=False,
    generation=2,
    extensions=(".lst",),
    keywords=frozenset(GFA_BASIC_3.keywords - GFA_3_KEYWORDS),
    compound=("ELSE IF", "END IF", "ON ERROR"),
    suffixes="$%!#",
)

STOS_BASIC = Dialect(
    name="STOS BASIC",
    identifier="stos-basic",
    label="STOS BASIC",
    writable=False,
    tokenised=True,
    line_numbers=True,
    generation=2,
    extensions=(".bas", ".asc"),
    keywords=frozenset(stos_tables.STOS_KEYWORDS),
    compound=stos_tables.STOS_COMPOUND_KEYWORDS,
    suffixes="$#",
    comment_marks="",
)

ST_BASIC = Dialect(
    name="ST BASIC",
    identifier="st-basic",
    label="Atari ST BASIC",
    writable=True,
    tokenised=False,
    line_numbers=True,
    generation=1,
    extensions=(".bas",),
    keywords=stbasic.KEYWORDS,
    compound=stbasic.COMPOUND_KEYWORDS,
    suffixes=stbasic.TYPE_SUFFIXES,
)

DIALECTS: dict[str, Dialect] = {
    dialect.name: dialect for dialect in (GFA_BASIC_3, GFA_BASIC_2, STOS_BASIC, ST_BASIC)
}
DIALECTS_BY_ID: dict[str, Dialect] = {dialect.identifier: dialect for dialect in DIALECTS.values()}


def dialect_for(name: str) -> Dialect:
    """Look a dialect up by name or by identifier."""
    key = str(name or "")
    if key in DIALECTS:
        return DIALECTS[key]
    if key in DIALECTS_BY_ID:
        return DIALECTS_BY_ID[key]
    raise DataError(f"{name!r} is not a BASIC dialect this package knows.")


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------
_NUMBERED_LINE = re.compile(r"^\s*\d+[ \t]")


def _vocabulary(dialect: Dialect) -> frozenset[str]:
    return frozenset(dialect.keywords) | frozenset(word.upper() for word in dialect.compound)


#: STOS and ST BASIC both number their lines, so the line numbers say nothing
#: about which one a listing is. What separates them is the words only one of
#: them has: no ST BASIC has ``CLW`` or ``WAIT VBL``, and no STOS has ``FULLW``
#: or ``VDISYS``. Both sets are derived rather than written out, so adding a
#: keyword to a dialect sharpens the test rather than leaving it stale.
_STOS_ONLY = _vocabulary(STOS_BASIC) - _vocabulary(ST_BASIC)
_ST_ONLY = _vocabulary(ST_BASIC) - _vocabulary(STOS_BASIC)


def _vocabulary_score(upper: str, words: frozenset[str]) -> int:
    """How many of ``words`` appear in the listing, counting each word once."""
    return sum(
        1 for word in words
        if re.search(r"(?<![A-Z0-9_.])" + re.escape(word) + r"(?![A-Z0-9_$#])", upper)
    )


def _as_text(data: bytes) -> str | None:
    """Decode bytes as a listing, or return ``None`` when they are not text."""
    if not data:
        return None
    printable = sum(1 for byte in data if 32 <= byte < 127 or byte in (9, 10, 13))
    if printable / len(data) < 0.94:
        return None
    return data.decode("latin-1").replace("\r\n", "\n").replace("\r", "\n")


def _detect_text(text: str) -> Detection:
    rows = [row for row in text.split("\n") if row.strip()]
    if not rows:
        return Detection(Verdict.NOT_BASIC, None, "The file holds no lines.")
    numbered = sum(1 for row in rows if _NUMBERED_LINE.match(row))
    upper = text.upper()
    if numbered < len(rows) * 0.8:
        gfa_score = sum(2 for word in GFA_MARKERS if re.search(rf"\b{word}\b", upper))
        if gfa_score >= 4:
            return Detection(Verdict.BASIC, GFA_BASIC_3,
                             f"An unnumbered GFA BASIC listing of {len(rows)} lines.", len(text), len(rows))
        return Detection(Verdict.NOT_BASIC, None,
                         "The lines carry no line numbers and no GFA BASIC structure.")
    stos_score = _vocabulary_score(upper, _STOS_ONLY)
    st_score = _vocabulary_score(upper, _ST_ONLY)
    if stos_score > st_score:
        return Detection(Verdict.BASIC, STOS_BASIC,
                         f"A numbered STOS BASIC listing of {len(rows)} lines, "
                         f"using {stos_score} word(s) only STOS has.", len(text), len(rows))
    if st_score > stos_score and st_score >= 2:
        return Detection(Verdict.BASIC, ST_BASIC,
                         f"A numbered ST BASIC listing of {len(rows)} lines, "
                         f"using {st_score} word(s) only ST BASIC has.", len(text), len(rows))
    if stos_score or st_score:
        return Detection(Verdict.BASIC, ST_BASIC,
                         f"A numbered BASIC listing of {len(rows)} lines. Nothing in it "
                         "separates ST BASIC from STOS, so the ST's own BASIC is assumed.",
                         len(text), len(rows))
    return Detection(Verdict.NOT_BASIC, None, "Numbered lines, but no recognisable BASIC keywords.")


def detect(data: bytes) -> Detection:
    """Decide which BASIC, if any, these bytes hold.

    Nothing about the file name is consulted, because a program recovered from
    a floppy may have any extension or none.
    """
    raw = bytes(data or b"")
    if raw[2:12] == gfa.MAGIC_3:
        try:
            program = gfa.parse_program(raw)
        except DataError as error:
            return Detection(Verdict.NOT_BASIC, None, f"A GFA BASIC 3 header that does not parse: {error}")
        consumed = gfa.HEADER_LENGTH + program.pool_length + program.program_length
        reason = f"{len(program.lines)} line(s) of GFA BASIC 3."
        if program.protected:
            reason += " The program is PSAVE protected, so its names are gone."
        if consumed < len(raw):
            return Detection(Verdict.BASIC_TRAILING, GFA_BASIC_3,
                             reason + f" {len(raw) - consumed:,} trailing bytes follow.",
                             consumed, len(program.lines), True)
        return Detection(Verdict.BASIC, GFA_BASIC_3, reason, consumed, len(program.lines), True)
    if gfa.MAGIC_2 in raw[:16]:
        return Detection(Verdict.NOT_BASIC, None,
                         "A GFA BASIC 2 saved program. Only its .LST listing export is readable here.")
    if raw[:10] == stos.PROGRAM_MAGIC:
        try:
            program = stos.parse_program(raw)
        except DataError as error:
            return Detection(Verdict.NOT_BASIC, None, f"A STOS header that does not parse: {error}")
        # The declared program area holds the lines, their terminator and any
        # memory banks the program reserved, so it is all one program.
        consumed = min(stos.HEADER_LENGTH + program.program_length, len(raw))
        banks = sum(1 for bank in program.banks if bank.length)
        reason = f"{len(program.lines)} line(s) of STOS BASIC."
        if banks:
            reason += f" {banks} memory bank(s) are saved with it."
        if consumed < len(raw):
            return Detection(Verdict.BASIC_TRAILING, STOS_BASIC,
                             reason + f" {len(raw) - consumed:,} trailing bytes follow.",
                             consumed, len(program.lines), True)
        return Detection(Verdict.BASIC, STOS_BASIC, reason, consumed, len(program.lines), True)
    if raw[:10] == stos.BANK_MAGIC:
        return Detection(Verdict.NOT_BASIC, None, "A STOS memory bank file, which carries no program.")
    text = _as_text(raw)
    if text is None:
        return Detection(Verdict.NOT_BASIC, None, "The bytes are not a known BASIC and are not readable text.")
    return _detect_text(text)


def is_tokenised(data: bytes) -> bool:
    """True when *these bytes* hold a program in a tokenised form.

    A GFA BASIC ``.LST`` is GFA BASIC and is not tokenised, so the question is
    about the storage rather than about the dialect.
    """
    detection = detect(data)
    return detection.verdict in {Verdict.BASIC, Verdict.BASIC_TRAILING} and detection.tokenised


def _dialect_of(data: bytes, dialect: Dialect | None) -> Dialect:
    if dialect is not None:
        return dialect
    detection = detect(data)
    if detection.dialect is None:
        raise DataError(detection.reason or "These bytes are not a BASIC program.")
    return detection.dialect


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------
def detokenise(data: bytes, dialect: Dialect | None = None) -> str:
    """Render a saved program as its source listing.

    ``dialect`` may be left out, in which case ``detect`` chooses it.
    """
    raw = bytes(data or b"")
    chosen = _dialect_of(raw, dialect)
    if chosen is GFA_BASIC_3 and raw[2:12] == gfa.MAGIC_3:
        return gfa.detokenise_gfa(raw)
    if chosen is STOS_BASIC and raw[:10] == stos.PROGRAM_MAGIC:
        return stos.detokenise_stos(raw)
    text = _as_text(raw)
    if text is None:
        raise DataError(f"These bytes are not a {chosen.name} program.")
    return text


def tokenise(source: str, dialect: Dialect = GFA_BASIC_3) -> bytes:
    """Encode a listing as the dialect stores it.

    A dialect that saves plain text encodes to plain text with the ST's CR LF
    line endings, so the round trip is exact. ``STOS_BASIC`` refuses: see the
    package docstring for why.
    """
    text = str(source).replace("\r\n", "\n").replace("\r", "\n")
    if dialect is STOS_BASIC:
        raise NotImplementedError(
            "STOS BASIC is read-only here. The reader is derived from real saved programs "
            "rather than from STOS itself, so a file written back could hold interpreter "
            "state STOS refuses. Export the listing instead."
        )
    if dialect is GFA_BASIC_3:
        return gfa.tokenise_gfa(text)
    if dialect in (GFA_BASIC_2, ST_BASIC):
        return text.replace("\n", "\r\n").encode("latin-1", "replace")
    raise DataError(f"{dialect} cannot be written by this package.")


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------
_TEXT_KINDS = {kind.value: kind for kind in TokenKind}


def _scan_text(text: str, dialect: Dialect) -> Iterator[Line]:
    starts = [0]
    for index, character in enumerate(text):
        if character == "\n":
            starts.append(index + 1)
    rows = text.split("\n")
    by_line: list[list[Token]] = [[] for _ in rows]
    for kind, piece, start, end in stbasic.scan_source(
        text, dialect.keywords, dialect.compound, dialect.suffixes,
        comment_marks=dialect.comment_marks,
    ):
        index = max(position for position, offset in enumerate(starts) if offset <= start)
        by_line[index].append(Token(_TEXT_KINDS[kind], piece, start, end))
    for index, row in enumerate(rows):
        tokens = by_line[index]
        number = None
        if tokens and tokens[0].kind is TokenKind.LINE_NUMBER:
            number = int(tokens[0].text)
        yield Line(index, number, row.rstrip(), starts[index], starts[index] + len(row), 0, tuple(tokens))


def _scan_gfa(data: bytes) -> Iterator[Line]:
    program = gfa.parse_program(data)
    for index, line in enumerate(gfa.decode_lines(program)):
        tokens = tuple(
            Token(_TEXT_KINDS[piece.kind], piece.text, piece.start, piece.end, piece.value)
            for piece in line.pieces
            if piece.kind in _TEXT_KINDS
        )
        yield Line(index, None, line.text, line.offset, line.offset + line.size, line.depth, tokens)


def _scan_stos(data: bytes) -> Iterator[Line]:
    program = stos.parse_program(data)
    base = stos.HEADER_LENGTH
    for index, line in enumerate(program.lines):
        tokens = [Token(TokenKind.LINE_NUMBER, str(line.number), base + line.start + 2, base + line.start + 4, line.number)]
        tokens.extend(
            Token(_TEXT_KINDS[item.kind], item.text, base + line.start + 4 + item.start, base + line.start + 4 + item.end)
            for item in line.items
            if item.kind in _TEXT_KINDS
        )
        yield Line(index, line.number, f"{line.number} {line.text}".rstrip(), base + line.start, base + line.end, 0, tuple(tokens))


def scan_program(program: bytes | str, dialect: Dialect | None = None) -> Iterator[Line]:
    """Yield one ``Line`` per program line, tokens typed for colouring.

    Both a saved program and a listing are accepted, because the editor holds
    the listing and the file inspector holds the bytes, and both want the same
    view. Nothing builds the whole listing as one string first, so a program
    too large to edit can still be shown.
    """
    if isinstance(program, str):
        chosen = dialect or ST_BASIC
        yield from _scan_text(program.replace("\r\n", "\n").replace("\r", "\n"), chosen)
        return
    raw = bytes(program or b"")
    chosen = _dialect_of(raw, dialect)
    if chosen is GFA_BASIC_3 and raw[2:12] == gfa.MAGIC_3:
        yield from _scan_gfa(raw)
        return
    if chosen is STOS_BASIC and raw[:10] == stos.PROGRAM_MAGIC:
        yield from _scan_stos(raw)
        return
    text = _as_text(raw)
    if text is None:
        raise DataError(f"These bytes are not a {chosen.name} program.")
    yield from _scan_text(text, chosen)


__all__ = [
    "DIALECTS",
    "DIALECTS_BY_ID",
    "GFA_3_KEYWORDS",
    "GFA_BASIC_2",
    "GFA_BASIC_3",
    "ST_BASIC",
    "STOS_BASIC",
    "Detection",
    "Dialect",
    "Line",
    "Token",
    "TokenKind",
    "Verdict",
    "detect",
    "detokenise",
    "dialect_for",
    "is_tokenised",
    "scan_program",
    "tokenise",
]
