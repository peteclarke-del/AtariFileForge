"""STOS BASIC ``.BAS`` files: reading and listing.

A saved STOS program is the editor's buffer written straight out behind a
78-byte header:

* the ten-byte magic ``Lionpoulos`` (a memory-bank file, ``.MBK``, uses
  ``Lionpoubnk`` instead and carries no program),
* a big-endian 32-bit length of the program area, excluding the header,
* a big-endian 32-bit offset from the end of the header to the first memory
  bank,
* fifteen four-byte bank entries: a type byte then a 24-bit length.

The program area is a run of lines. Each line is a big-endian 16-bit byte
count (covering the count itself), a big-endian 16-bit line number, then the
tokens; a zero count ends the program. Lines are an even number of bytes.

Tokens are single bytes. Anything below ``0x80`` is the ASCII character
itself, which is how ``:``, ``,``, ``;`` and the brackets are stored. From
``0x80`` up they index the tables in ``stos_tables``, with four escape bytes
widening the range and a small group carrying operands:

``0x8A``
    ``REM``: the comment text follows, terminated by ``0x00``.
``0x98``-``0x9F``
    ``GOTO GOSUB THEN ELSE RESTORE FOR WHILE REPEAT``: four bytes of
    interpreter state follow, aligned to an even offset. STOS rebuilds them
    when the program is loaded.
``0xFA``
    A variable: a flags byte whose low five bits are the name length and
    whose ``0x80`` and ``0x40`` bits mark a string or float, then three bytes
    of interpreter state, then the name.
``0xFB 0xFD 0xFE``
    A binary, hexadecimal or decimal integer: a 32-bit big-endian value.
``0xFC``
    A string: a 32-bit big-endian length, then the characters.
``0xFF``
    A float: four bytes of Motorola fast floating point, then the four-byte
    constant ``12 34 56 78`` that STOS writes after every one.

Each of those operands starts at an even offset, so a padding byte appears
after the token when it would otherwise land on an odd one.

What is proven and what is best effort
--------------------------------------
The container, the line framing, the escapes and every literal encoding above
were read off 36 real STOS programs and are exercised by the tests. The
keyword tables are a different matter: they were derived from those same
programs rather than transcribed from STOS, so they cover the 169 tokens those
programs use and no more. ``stos_tables`` says how, and a token outside them
lists as ``{&A0,&C9}`` rather than as a guess.

The listing this module produces is readable STOS source, not a byte-for-byte
reproduction of STOS's own ``.ASC`` export: STOS leaves a trailing space after
some statements and this lister does not.

``encode_program`` exists so the test corpus can be built from source, and its
output round-trips through the reader. It is **not** offered as a way to write
a file for a real STOS: the three interpreter-state bytes in a variable
reference and the four in a branch are written as zero, and no real save was
available to check that STOS accepts that. This is why ``STOS_BASIC.writable``
is ``False`` and why ``atarinut.basic.tokenise`` refuses the dialect.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from decimal import Decimal

from ..errors import DataError
from .stos_tables import (
    BASE_TOKENS,
    BINARY_TOKEN,
    BRANCH_TOKENS,
    EXTENSION_FUNCTION_ESCAPE,
    EXTENSION_FUNCTIONS,
    EXTENSION_INSTRUCTION_ESCAPE,
    EXTENSION_INSTRUCTIONS,
    FLOAT_TOKEN,
    FUNCTION_ESCAPE,
    FUNCTION_TOKENS,
    HEX_TOKEN,
    INSTRUCTION_ESCAPE,
    INSTRUCTION_TOKENS,
    INTEGER_TOKEN,
    OPERATOR_TOKENS,
    REM_TOKEN,
    STRING_TOKEN,
    VARIABLE_TOKEN,
)

PROGRAM_MAGIC = b"Lionpoulos"
BANK_MAGIC = b"Lionpoubnk"
HEADER_LENGTH = 78
BANK_COUNT = 15
MAX_LINE_NUMBER = 65535

#: STOS writes this after every float literal.
FLOAT_TRAILER = bytes.fromhex("12345678")

#: Flag bits in a variable reference's first byte.
VARIABLE_STRING = 0x80
VARIABLE_FLOAT = 0x40
VARIABLE_LENGTH = 0x1F

#: Kinds used for the editor's colouring (mirrors ``TokenKind`` values).
KEYWORD = "keyword"
IDENTIFIER = "identifier"
NUMBER = "number"
STRING = "string"
COMMENT = "comment"
OPERATOR = "operator"


@dataclass
class StosItem:
    """One decoded element of a line, with its span inside the program area."""

    kind: str
    text: str
    start: int
    end: int
    token: int = 0
    value: object = None
    #: True for a function keyword. STOS writes ``rnd(3)`` closed up but
    #: ``erase (3)``, so the lister has to know which a token is.
    function: bool = False


@dataclass
class StosBank:
    kind: int
    length: int


@dataclass
class StosLine:
    number: int
    start: int
    end: int
    items: list = field(default_factory=list)
    text: str = ""


@dataclass
class StosProgram:
    program_length: int
    bank_offset: int
    banks: list
    lines: list
    trailing: int = 0


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
def ffp_to_float(raw: bytes) -> float:
    """Convert Motorola fast floating point to a Python float.

    The first three bytes are a 24-bit mantissa read as a fraction, the top
    bit of the fourth byte is the sign and its low seven bits are the exponent
    in excess-64. All zero is zero.
    """
    if len(raw) < 4:
        raise DataError("A STOS float literal is truncated.")
    mantissa = int.from_bytes(raw[:3], "big")
    exponent = raw[3] & 0x7F
    if mantissa == 0 and exponent == 0:
        return 0.0
    sign = -1.0 if raw[3] & 0x80 else 1.0
    return sign * (mantissa / float(1 << 24)) * 2.0 ** (exponent - 64)


def float_to_ffp(number: float) -> bytes:
    """Encode a float as Motorola fast floating point (see ``ffp_to_float``)."""
    value = float(number)
    if value == 0:
        return bytes(4)
    sign = 0x80 if value < 0 else 0x00
    value = abs(value)
    exponent = 64
    while value >= 1.0:
        value /= 2.0
        exponent += 1
    while value < 0.5:
        value *= 2.0
        exponent -= 1
    mantissa = int(round(value * (1 << 24)))
    if mantissa >= 1 << 24:
        mantissa >>= 1
        exponent += 1
    if not 0 <= exponent <= 0x7F:
        raise DataError(f"{number!r} is outside the range STOS can store.")
    return mantissa.to_bytes(3, "big") + bytes((sign | exponent,))


def format_float(number: float) -> str:
    """Print a float with the fewest digits that read back to the same bytes.

    STOS lists a float in plain decimal unless the exponent is far out, and
    always with a decimal point, so ``50`` stored as a float lists as ``50.0``
    and is read back as a float rather than as an integer.
    """
    stored = float_to_ffp(number)
    for digits in range(1, 10):
        text = "%.*G" % (digits, number)
        if float_to_ffp(float(text)) == stored:
            break
    else:
        text = repr(number)
    if "E" in text and -6 <= int(text.split("E")[1]) <= 14:
        text = format(Decimal(text), "f")
    if "." not in text and "E" not in text:
        text += ".0"
    return text


def _format_based(value: int, base: int, prefix: str) -> str:
    raw = int(value) & 0xFFFFFFFF
    digits = format(raw, "X" if base == 16 else "b")
    return prefix + digits


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def read_header(data: bytes) -> tuple[int, int, list[StosBank]]:
    if len(data) < HEADER_LENGTH:
        raise DataError("The file is too short to hold a STOS BASIC header.")
    if data[:10] == BANK_MAGIC:
        raise DataError("This is a STOS memory bank file, not a saved program.")
    if data[:10] != PROGRAM_MAGIC:
        raise DataError("The Lionpoulos signature is missing.")
    length, bank_offset = struct.unpack(">II", data[10:18])
    banks = [
        StosBank(data[18 + index * 4], int.from_bytes(data[19 + index * 4 : 22 + index * 4], "big"))
        for index in range(BANK_COUNT)
    ]
    return length, bank_offset, banks


def token_text(token: int, second: int = 0, third: int = 0) -> str:
    """The listing text of a keyword token, or a ``{&..}`` placeholder."""
    if token == INSTRUCTION_ESCAPE:
        return INSTRUCTION_TOKENS.get(second) or f"{{&A0,&{second:02X}}}"
    if token == FUNCTION_ESCAPE:
        return FUNCTION_TOKENS.get(second) or f"{{&B8,&{second:02X}}}"
    if token == EXTENSION_INSTRUCTION_ESCAPE:
        return EXTENSION_INSTRUCTIONS.get((second, third)) or f"{{&A8,{second},&{third:02X}}}"
    if token == EXTENSION_FUNCTION_ESCAPE:
        return EXTENSION_FUNCTIONS.get((second, third)) or f"{{&C0,{second},&{third:02X}}}"
    return BASE_TOKENS.get(token) or f"{{&{token:02X}}}"


def decode_line(body: bytes, base: int) -> list[StosItem]:
    """Decode one line's token stream.

    ``base`` is the offset of ``body`` inside the program area, because a
    literal's operand is aligned to an even offset there.
    """
    items: list[StosItem] = []
    position = 0

    def align() -> None:
        nonlocal position
        if (base + position) & 1:
            position += 1

    def need(count: int) -> None:
        if position + count > len(body):
            raise DataError(f"The line at offset {base - 4} ends inside a token operand.")

    while position < len(body):
        token = body[position]
        start = position
        position += 1
        if token == 0:
            break
        if token < 0x80:
            character = chr(token)
            kind = STRING if character == '"' else OPERATOR
            items.append(StosItem(kind, character, start, position, token))
            continue
        if token == REM_TOKEN:
            end = body.find(b"\x00", position)
            end = len(body) if end < 0 else end
            text = body[position:end].decode("latin-1")
            items.append(StosItem(COMMENT, "rem" + text, start, end, token, text))
            position = end + 1
            break
        if token in BRANCH_TOKENS:
            align()
            need(4)
            items.append(StosItem(KEYWORD, token_text(token), start, position + 4, token, body[position : position + 4]))
            position += 4
            continue
        if token in (INSTRUCTION_ESCAPE, FUNCTION_ESCAPE):
            need(1)
            second = body[position]
            position += 1
            items.append(
                StosItem(KEYWORD, token_text(token, second), start, position, token, second, token == FUNCTION_ESCAPE)
            )
            continue
        if token in (EXTENSION_INSTRUCTION_ESCAPE, EXTENSION_FUNCTION_ESCAPE):
            need(2)
            second, third = body[position], body[position + 1]
            position += 2
            items.append(
                StosItem(
                    KEYWORD, token_text(token, second, third), start, position, token,
                    (second, third), token == EXTENSION_FUNCTION_ESCAPE,
                )
            )
            continue
        if token == VARIABLE_TOKEN:
            align()
            need(4)
            flags = body[position]
            state = body[position + 1 : position + 4]
            position += 4
            length = flags & VARIABLE_LENGTH
            need(length)
            name = body[position : position + length].decode("latin-1")
            position += length
            items.append(StosItem(IDENTIFIER, name, start, position, token, (flags, state)))
            continue
        if token in (BINARY_TOKEN, HEX_TOKEN, INTEGER_TOKEN):
            align()
            need(4)
            value = struct.unpack(">i", body[position : position + 4])[0]
            position += 4
            if token == HEX_TOKEN:
                text = _format_based(value, 16, "$")
            elif token == BINARY_TOKEN:
                text = _format_based(value, 2, "%")
            else:
                text = str(value)
            items.append(StosItem(NUMBER, text, start, position, token, value))
            continue
        if token == STRING_TOKEN:
            align()
            need(4)
            length = struct.unpack(">I", body[position : position + 4])[0]
            position += 4
            need(length)
            text = body[position : position + length].decode("latin-1")
            position += length
            items.append(StosItem(STRING, '"' + text + '"', start, position, token, text))
            continue
        if token == FLOAT_TOKEN:
            align()
            need(8)
            value = ffp_to_float(body[position : position + 4])
            position += 8
            items.append(StosItem(NUMBER, format_float(value), start, position, token, value))
            continue
        operator = token in OPERATOR_TOKENS
        kind = OPERATOR if operator else KEYWORD
        items.append(StosItem(kind, token_text(token), start, position, token, None, token > FUNCTION_ESCAPE and not operator))
    return items


def parse_program(data: bytes) -> StosProgram:
    """Split a ``.BAS`` file into its header, bank table and decoded lines."""
    length, bank_offset, banks = read_header(data)
    available = len(data) - HEADER_LENGTH
    if length > available:
        raise DataError(
            f"The header promises {length:,} program bytes but only {available:,} follow it."
        )
    program = data[HEADER_LENGTH : HEADER_LENGTH + length]
    lines: list[StosLine] = []
    position = 0
    while position + 4 <= len(program):
        size = struct.unpack(">H", program[position : position + 2])[0]
        if size == 0:
            break
        if size < 4 or size & 1 or position + size > len(program):
            raise DataError(f"The line at offset {position} declares an impossible size of {size}.")
        number = struct.unpack(">H", program[position + 2 : position + 4])[0]
        items = decode_line(program[position + 4 : position + size], position + 4)
        lines.append(StosLine(number, position, position + size, items, render_items(items)))
        position += size
    return StosProgram(length, bank_offset, banks, lines, len(program) - position)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------
def _space_before(text: str) -> bool:
    return bool(text) and (text[0].isalnum() or text[0] in '"$%_{#')


def _space_after(text: str) -> bool:
    return bool(text) and (text[-1].isalnum() or text[-1] in '"$)}`')


#: Words STOS always stands clear of what precedes them, even punctuation, so
#: ``print A;" "; else`` keeps its space after the semicolon.
SPACED_WORDS = frozenset(
    {"to", "step", "downto", "then", "else", "and", "or", "xor", "mod", "not",
     "goto", "gosub", "restore", "until", "next", "wend"}
)


def render_items(items: list) -> str:
    """Join decoded items the way STOS spaces a listing.

    Three rules cover it. A command keyword, or a word operator such as
    ``and``, always stands away from whatever follows it, which is why
    ``erase (3)`` is spaced where the function ``rnd(3)`` is not, and why
    ``print #1`` and ``palette ,,$700`` keep their gap. A structural word in ``SPACED_WORDS`` always stands away from what
    precedes it. Otherwise a space appears only between two words, never
    between a word and an operator. The statement separator ``:`` is clear on
    both sides.
    """
    out: list[str] = []
    previous_item = None
    for item in items:
        text = item.text
        if out:
            previous = out[-1]
            command = previous_item is not None and (
                (previous_item.kind == KEYWORD and not previous_item.function)
                or (previous_item.kind == OPERATOR and previous_item.text[-1:].isalpha())
            )
            if text == ":" or previous == ":":
                out.append(" ")
            elif command or text in SPACED_WORDS:
                out.append(" ")
            elif _space_after(previous) and _space_before(text):
                out.append(" ")
        out.append(text)
        previous_item = item
    return "".join(out).rstrip()


def detokenise_stos(data: bytes) -> str:
    """List a saved STOS program as numbered source lines."""
    program = parse_program(data)
    return "\n".join(f"{line.number} {line.text}".rstrip() for line in program.lines)


# ---------------------------------------------------------------------------
# Writing (test corpus only; see the module docstring)
# ---------------------------------------------------------------------------
def _reverse_tables() -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    for code, text in BASE_TOKENS.items():
        entries.append((text.upper(), bytes((code,))))
    for code, text in INSTRUCTION_TOKENS.items():
        entries.append((text.upper(), bytes((INSTRUCTION_ESCAPE, code))))
    for code, text in FUNCTION_TOKENS.items():
        entries.append((text.upper(), bytes((FUNCTION_ESCAPE, code))))
    for (extension, code), text in EXTENSION_INSTRUCTIONS.items():
        entries.append((text.upper(), bytes((EXTENSION_INSTRUCTION_ESCAPE, extension, code))))
    for (extension, code), text in EXTENSION_FUNCTIONS.items():
        entries.append((text.upper(), bytes((EXTENSION_FUNCTION_ESCAPE, extension, code))))
    entries.sort(key=lambda entry: (-len(entry[0]), entry[0]))
    return entries


REVERSE_TOKENS = _reverse_tables()
_LINE_START = re.compile(r"\s*(\d+)\s?(.*)$")
_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*[$#]?")
_NUMBER = re.compile(r"(?:\$[0-9A-Fa-f]+|%[01]+|\d+\.\d+(?:[Ee][-+]?\d+)?|\d+)")


def _encode_body(source: str, base: int) -> bytes:
    out = bytearray()

    def align() -> None:
        if (base + len(out)) & 1:
            out.append(0)

    position = 0
    while position < len(source):
        character = source[position]
        if character == " ":
            position += 1
            continue
        if character == '"':
            close = source.find('"', position + 1)
            if close < 0:
                raise DataError("A STOS string constant is unterminated.")
            text = source[position + 1 : close].encode("latin-1", "replace")
            out.append(STRING_TOKEN)
            align()
            out.extend(struct.pack(">I", len(text)))
            out.extend(text)
            position = close + 1
            continue
        upper = source[position:].upper()
        if upper.startswith("REM"):
            out.append(REM_TOKEN)
            out.extend(source[position + 3 :].encode("latin-1", "replace"))
            out.append(0)
            return bytes(out)
        keyword = next(
            (
                entry
                for entry in REVERSE_TOKENS
                if upper.startswith(entry[0])
                and not (entry[0][-1].isalnum() and _is_name_char(source[position + len(entry[0]) : position + len(entry[0]) + 1]))
            ),
            None,
        )
        if keyword is not None:
            out.extend(keyword[1])
            position += len(keyword[0])
            if keyword[1][0] in BRANCH_TOKENS:
                align()
                out.extend(bytes(4))
            continue
        number = _NUMBER.match(source, position)
        if number is not None:
            text = number.group(0)
            if text.startswith("$"):
                out.append(HEX_TOKEN)
                align()
                out.extend(struct.pack(">i", _signed(int(text[1:], 16))))
            elif text.startswith("%"):
                out.append(BINARY_TOKEN)
                align()
                out.extend(struct.pack(">i", _signed(int(text[1:], 2))))
            elif "." in text or "E" in text.upper():
                out.append(FLOAT_TOKEN)
                align()
                out.extend(float_to_ffp(float(text)))
                out.extend(FLOAT_TRAILER)
            else:
                out.append(INTEGER_TOKEN)
                align()
                out.extend(struct.pack(">i", _signed(int(text))))
            position = number.end()
            continue
        name = _NAME.match(source, position)
        if name is not None:
            text = name.group(0)
            flags = len(text)
            if flags > VARIABLE_LENGTH:
                raise DataError(f"The variable name {text!r} is longer than STOS allows.")
            if text.endswith("$"):
                flags |= VARIABLE_STRING
            elif text.endswith("#"):
                flags |= VARIABLE_FLOAT
            out.append(VARIABLE_TOKEN)
            align()
            out.append(flags)
            out.extend(bytes(3))
            out.extend(text.encode("latin-1", "replace"))
            position = name.end()
            continue
        out.append(ord(character) & 0x7F)
        position += 1
    out.append(0)
    return bytes(out)


def _is_name_char(character: str) -> bool:
    return bool(character) and (character.isalnum() or character in "_$#")


def _signed(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - (1 << 32) if value & 0x80000000 else value


def encode_program(source: str) -> bytes:
    """Encode numbered STOS source as a ``.BAS`` file.

    This builds the test corpus. It writes zeros where a real STOS save holds
    interpreter state, so the result is not offered as a file a real STOS will
    load; see the module docstring.
    """
    program = bytearray()
    previous = -1
    for raw in str(source).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw.strip():
            continue
        match = _LINE_START.match(raw)
        if not match:
            raise DataError(f"Every STOS line needs a line number: {raw.strip()!r}")
        number = int(match.group(1))
        if number > MAX_LINE_NUMBER:
            raise DataError(f"Line number {number} is above {MAX_LINE_NUMBER}.")
        if number <= previous:
            raise DataError(f"Line {number} is out of order.")
        previous = number
        body = _encode_body(match.group(2).strip(), len(program) + 4)
        size = len(body) + 4
        if size & 1:
            body += b"\x00"
            size += 1
        if size > 0xFFFF:
            raise DataError(f"Line {number} is longer than STOS allows.")
        program.extend(struct.pack(">HH", size, number))
        program.extend(body)
    if not program:
        raise DataError("The listing contains no numbered lines.")
    program.extend(bytes(4))
    header = bytearray(PROGRAM_MAGIC)
    header.extend(struct.pack(">II", len(program), len(program)))
    header.extend(bytes(BANK_COUNT * 4))
    return bytes(header) + bytes(program)


def canonicalise(data: bytes) -> bytes:
    """Re-encode a program through the writer, so a round trip can be compared."""
    return encode_program(detokenise_stos(data))


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------
def looks_like_stos(data: bytes) -> bool:
    return data[:10] == PROGRAM_MAGIC


__all__ = [
    "BANK_MAGIC",
    "HEADER_LENGTH",
    "PROGRAM_MAGIC",
    "StosBank",
    "StosItem",
    "StosLine",
    "StosProgram",
    "canonicalise",
    "decode_line",
    "detokenise_stos",
    "encode_program",
    "ffp_to_float",
    "float_to_ffp",
    "looks_like_stos",
    "parse_program",
    "read_header",
    "render_items",
    "token_text",
]
