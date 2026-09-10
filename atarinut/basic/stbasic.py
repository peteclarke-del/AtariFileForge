"""Atari ST BASIC, and the shared scanner for every listing held as text.

The BASIC Atari shipped with the ST saves a program as plain ASCII: numbered
lines, one per record, nothing tokenised. There is no token table to reproduce
and no round trip to prove, because the bytes on the disk *are* the listing.
What the workbench needs instead is a scanner that knows which words are
keywords, so the editor can colour a listing and tell a variable named
``COLORS`` from the ``COLOR`` command.

That scanner is shared. GFA BASIC's ``.LST`` export and STOS's ``.ASC`` export
are both plain listings too, so ``scan_source`` takes the keyword set as an
argument and serves all three. The one rule it enforces is the one every ST
BASIC follows: a keyword is only a keyword when it is not glued to a name
character on either side, and a typed name such as ``PRINT$`` is a variable,
not the command with a suffix.
"""

from __future__ import annotations

import re

#: The commands Atari ST BASIC understands. The window, drawing and sound
#: words are the ones that make it recognisable: no other ST BASIC has
#: ``FULLW``, ``GOTOXY``, ``PCIRCLE`` or ``VDISYS``.
STATEMENTS: tuple[str, ...] = tuple(
    """
    AUTO BLOAD BREAK BSAVE CHAIN CIRCLE CLEAR CLEARW CLOSE CLOSEW CLS COLOR COMMON CONT
    DATA DEF DEFDBL DEFINT DEFSNG DEFSTR DELETE DIM DIR ELLIPSE ELSE END ERASE ERROR FIELD
    FILL FOLLOW FOR FULLW GEMSYS GET GOSUB GOTO GOTOXY IF INPUT KILL LET LINEF LIST LLIST
    LOAD LOCATE LPRINT LSET MERGE NAME NEW NEXT ON OPEN OPENW OPTION OUT PCIRCLE PELLIPSE
    POKE PRINT PUT QUIT RANDOMIZE READ REM RENUM RESTORE RESUME RETURN RSET RUN SAVE SOUND
    STEP STOP SWAP SYSTEM THEN TITLEW TO TROFF TRON VDISYS WAVE WEND WHILE WIDTH WRITE
    """.split()
)

#: The functions and system variables.
FUNCTIONS: tuple[str, ...] = tuple(
    """
    ABS ASC ATN CDBL CHR$ CINT COS CSNG CVD CVI CVS DATE$ EOF ERL ERR EXP FIX FN FRE HEX$
    INKEY$ INP INSTR INT LEFT$ LEN LOC LOF LOG MID$ MKD$ MKI$ MKS$ OCT$ PEEK POS RIGHT$ RND
    SGN SIN SPACE$ SPC SQR STR$ STRING$ SYSTAB TAB TAN TIME$ TIMER USING VAL VARPTR
    """.split()
)

#: Words that behave as operators inside an expression.
OPERATORS: tuple[str, ...] = ("AND", "EQV", "IMP", "MOD", "NOT", "OR", "XOR")

#: Words ST BASIC spells as two, which the scanner reads as one keyword.
COMPOUND_KEYWORDS: tuple[str, ...] = (
    "ON ERROR", "LINE INPUT", "OPTION BASE", "DEF FN", "DEF SEG", "GO TO", "GO SUB",
    "ERROR GOTO", "RESUME NEXT", "PRINT USING",
)

KEYWORDS: frozenset[str] = frozenset(STATEMENTS + FUNCTIONS + OPERATORS)

#: A typed name ends with one of these. ``A$`` is a string, ``A%`` an integer
#: and ``A!`` a single-precision number.
TYPE_SUFFIXES = "$%!"

#: Words that introduce a line-number destination, so the scanner can colour
#: the number that follows as a destination rather than as arithmetic.
DESTINATION_KEYWORDS = frozenset({"GOTO", "GOSUB", "THEN", "ELSE", "RESTORE", "RUN", "RESUME", "LIST", "DELETE"})

#: A line number at the start of a line. ``match`` anchors it, so no ``^``
#: is needed and none is wanted: the scanner applies it line by line.
_LINE_START = re.compile(r"(\s*)(\d+)")
_NUMBER = re.compile(r"&[HO][0-9A-Fa-f]+|&[0-9A-Fa-f]+|\d+(?:\.\d+)?(?:[ED][-+]?\d+)?|\.\d+(?:[ED][-+]?\d+)?", re.IGNORECASE)
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.]*")


def is_name_character(character: str) -> bool:
    return bool(character) and (character.isalnum() or character in "_.")


def _keyword_at(source: str, position: int, keywords: frozenset[str], compound: tuple[str, ...], suffixes: str) -> str:
    """The keyword spelled at ``position``, or an empty string."""
    name = _NAME.match(source, position)
    if name is None:
        return ""
    word = name.group(0)
    end = name.end()
    # A trailing type suffix makes the word a variable, never a command.
    if end < len(source) and source[end] in suffixes:
        candidate = source[position : end + 1].upper()
        return candidate if candidate in keywords else ""
    upper = word.upper()
    # A compound keyword is matched first, so ON ERROR is one word, not two.
    for phrase in compound:
        length = len(phrase)
        if source[position : position + length].upper() == phrase and not is_name_character(source[position + length : position + length + 1]):
            return source[position : position + length]
    return word if upper in keywords else ""


def scan_source(
    source: str,
    keywords: frozenset[str],
    compound: tuple[str, ...] = (),
    suffixes: str = TYPE_SUFFIXES,
    comment_words: tuple[str, ...] = ("REM",),
    comment_marks: str = "'",
):
    """Yield ``(kind, text, start, end)`` for every element of a listing.

    ``kind`` is one of the ``TokenKind`` values: ``keyword``, ``identifier``,
    ``number``, ``string``, ``comment``, ``operator`` or ``line-number``.
    Offsets are into ``source``.
    """
    position = 0
    length = len(source)
    at_line_start = True
    while position < length:
        character = source[position]
        if character == "\n":
            at_line_start = True
            position += 1
            continue
        if character in " \t":
            position += 1
            continue
        if at_line_start:
            at_line_start = False
            number = _LINE_START.match(source, position)
            if number is not None:
                yield "line-number", number.group(2), number.start(2), number.end()
                position = number.end()
                continue
        if character == '"':
            end = source.find('"', position + 1)
            end = source.find("\n", position + 1) if end < 0 else end + 1
            end = length if end < 0 else end
            yield "string", source[position:end], position, end
            position = end
            continue
        if character in comment_marks:
            end = source.find("\n", position)
            end = length if end < 0 else end
            yield "comment", source[position:end], position, end
            position = end
            continue
        keyword = _keyword_at(source, position, keywords, compound, suffixes)
        if keyword:
            end = position + len(keyword)
            yield "keyword", keyword, position, end
            if keyword.upper() in comment_words:
                stop = source.find("\n", end)
                stop = length if stop < 0 else stop
                if stop > end:
                    yield "comment", source[end:stop], end, stop
                position = stop
                continue
            position = end
            continue
        name = _NAME.match(source, position)
        if name is not None:
            end = name.end()
            if end < len(source) and source[end] in suffixes:
                end += 1
            yield "identifier", source[position:end], position, end
            position = end
            continue
        number = _NUMBER.match(source, position)
        if number is not None:
            yield "number", number.group(0), position, number.end()
            position = number.end()
            continue
        yield "operator", character, position, position + 1
        position += 1


def format_listing(source: str) -> str:
    """Give every numbered line one space after its number."""
    out = []
    for row in str(source).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = _LINE_START.match(row)
        out.append(f"{match.group(2)} {row[match.end():].lstrip()}".rstrip() if match else row.rstrip())
    return "\n".join(out)


def score(source: str) -> int:
    """How strongly a listing reads as Atari ST BASIC.

    Numbered lines are worth little on their own, because STOS numbers its
    lines too. The words below are what separate them: no other ST BASIC has
    ``FULLW``, ``GOTOXY``, ``PCIRCLE``, ``VDISYS`` or ``SYSTAB``.
    """
    upper = source.upper()
    distinctive = ("FULLW", "CLEARW", "OPENW", "CLOSEW", "TITLEW", "GOTOXY", "LINEF",
                   "PCIRCLE", "PELLIPSE", "VDISYS", "GEMSYS", "SYSTAB", "DEFDBL", "DEFSNG")
    return sum(3 for word in distinctive if re.search(rf"\b{word}\b", upper)) + sum(
        1 for word in ("PRINT", "GOTO", "GOSUB", "THEN", "NEXT", "INPUT", "DIM", "RETURN")
        if re.search(rf"\b{word}\b", upper)
    )


__all__ = [
    "COMPOUND_KEYWORDS",
    "DESTINATION_KEYWORDS",
    "FUNCTIONS",
    "KEYWORDS",
    "OPERATORS",
    "STATEMENTS",
    "TYPE_SUFFIXES",
    "format_listing",
    "is_name_character",
    "scan_source",
    "score",
]
