"""GFA BASIC 3.x ``.GFA`` files: reading, listing and writing.

A ``.GFA`` file is the interpreter's in-memory program written out as is:

* two header bytes (``0x00`` for SAVE, ``0xFF`` for PSAVE, then the format
  version: 3 for GFA BASIC 3.0x, 4 for 3.5x),
* the ten-byte magic ``GFA-BASIC3``,
* 38 big-endian 32-bit "memory separators" (cumulative offsets): the sizes
  of the sixteen identifier tables, the size of the program, and the sizes of
  the sixteen pointer fields the interpreter builds for those tables,
* the identifier pool: sixteen runs of Pascal strings (one per name class:
  float, string, integer, boolean, the four array forms of those, word, byte,
  labels, procedures, word array, byte array, numeric functions and string
  functions), each run padded to an even length,
* the program: lines of ``size, command, tokens...`` where the command word
  selects the statement (``LINE_COMMANDS``) and the tokens are single bytes
  (``PRIMARY_TOKENS``), a 208 escape plus a byte (``SECONDARY_TOKENS``),
  typed variable references (224 + class with a byte index, or 240 + class
  with a word index), literals, and the 70 end marker that may introduce a
  trailing ``!`` comment. The final line is ``size 4, command 180``.

Indentation is not stored; the lister re-derives it from the block structure
exactly as GFA BASIC does, two spaces per level.

What is proven and what is best effort
--------------------------------------
What the tests prove is that this module is self-consistent and stable:
``detokenise(tokenise(s)) == s`` for every listing in
``tests/fixtures/basic``, and tokenising a listing twice gives the same
bytes. No ``.GFA`` file written by a real GFA BASIC 3 was available to compare
against, so *that* claim is not made: the layout and the token tables come
from the GPL gfalist utility, and the spacing and indentation rules were
inferred from real ``.LST`` source. A listing this module produces may
therefore differ from GFA's own in a detail no test here can catch.

A saved file also carries things no listing can: block-structure words that
are absolute RAM addresses, alignment bytes that are whatever was in memory,
four header words of interpreter state, and an identifier pool kept in editing
order with stale names in it. GFA BASIC rebuilds all of that on LOAD. So the
byte-level round-trip claim is ``tokenise(detokenise(x)) == canonicalise(x)``,
where ``canonicalise`` re-serialises the decoded token stream through the same
writer ``tokenise`` uses (zero alignment bytes and block words, names in first
use order, no stale names). The tests prove that on every corpus file.

Where the same text has more than one possible encoding (an integer or a
float constant, a numeric or a string comparison, the argument-count variants
of a function) the choice made here is the one that survives a round trip, not
necessarily the one GFA itself would make. ``_ExpressionScanner`` and
``_Encoder.choose_command`` say where a choice is inferred. A fractional float
literal is printed with the fewest digits that read back to the same stored
value.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import dataclass, field
from decimal import Decimal

from ..errors import DataError
from .gfa_tables import LINE_COMMANDS, PRIMARY_TOKENS, SECONDARY_TOKENS

MAGIC_3 = b"GFA-BASIC3"
MAGIC_2 = b"GfABASIC"
HEADER_LENGTH = 2 + 10 + 38 * 4
TABLE_COUNT = 16

#: Variable suffix per name class, in the order the interpreter keeps them.
VARIABLE_SUFFIXES = ("#", "$", "%", "!", "#(", "$(", "%(", "!(", "&", "|", "", "", "&(", "|(", "", "$")
CLASS_LABEL, CLASS_PROCEDURE, CLASS_FUNCTION, CLASS_STRING_FUNCTION = 10, 11, 14, 15
SIMPLE_CLASS_BY_SUFFIX = {"#": 0, "$": 1, "%": 2, "!": 3, "&": 8, "|": 9}
ARRAY_CLASS_BY_SUFFIX = {"#": 4, "$": 5, "%": 6, "!": 7, "&": 12, "|": 13}
STRING_CLASSES = frozenset({1, 5, 15})

#: Line commands that open a block: the following lines indent one level.
OPENING_COMMANDS = frozenset({0, 8, 16, 24, 32, 40, 48, 176, 196, 200, 216, 1796} | set(range(76, 124, 4)))
#: Line commands that close a block: this line and the following ones outdent.
CLOSING_COMMANDS = frozenset({4, 12, 20, 28, 36, 44, 52, 204, 208} | set(range(124, 172, 4)))
#: Line commands printed one level out without changing the depth (ELSE, CASE...).
MIDDLE_COMMANDS = frozenset({56, 60, 64, 224, 252})
#: Commands that take raw text to the 0x0D terminator.
TEXT_COMMANDS = frozenset({456, 460, 464, 468, 1644, 1016})
#: Commands that take raw text and print a space before it when there is any.
SPACED_TEXT_COMMANDS = frozenset({456, 460, 464, 468})
COMMENT_COMMANDS = frozenset({456, 460, 464})
#: Commands printed with a trailing space only when operands follow.
OPTIONAL_SPACE_COMMANDS = frozenset({
    192, 236, 420, 1020, 1072, 1108, 1128, 1136, 1140, 1144, 1236, 1276, 1300,
    1364, 1416, 1420, 1592, 588, 1212, 1260,
})
#: Commands followed by four bytes of interpreter state (block pointers).
POINTER_COMMANDS = frozenset({
    4, 12, 16, 20, 32, 48, 56, 60, 64, 172, 176, 196, 200, 204, 208, 220, 224,
})
END_OF_PROGRAM = 180
INLINE_COMMAND = 1668
LABEL_COMMAND = 252
PROCEDURE_CALL_COMMAND = 248
END_MARKER = 0x46
TEXT_TERMINATOR = 0x0D
SECONDARY_ESCAPE = 208

#: Line commands whose operand is a variable reference: command -> (class, follower).
#: The follower is the text GFA prints after the name.
VARIABLE_COMMANDS: dict[int, tuple[int, str]] = {}
for _commands, _class, _follower in (
    ((304, 76, 80, 84, 256), 0, "="), ((308, 260), 1, "="), ((312, 88, 92, 96, 264), 2, "="),
    ((316, 268), 3, "="), ((320, 100, 104, 108, 272), 8, "="), ((324, 112, 116, 120, 276), 9, "="),
    ((328, 280, 656, 688, 720, 752, 784, 816), 4, ""), ((332, 284), 5, ""),
    ((336, 288, 660, 692, 724, 756, 788, 820), 6, ""), ((340, 292), 7, ""),
    ((344, 296, 664, 696, 728, 760, 792, 824), 12, ""), ((348, 300, 668, 700, 732, 764, 796, 828), 13, ""),
    ((240, 244), 11, ""),
    ((640, 672), 0, ""), ((644, 676), 2, ""), ((648, 680), 8, ""), ((652, 684), 9, ""),
    ((704, 736, 768, 800), 0, ","), ((708, 740, 772, 804), 2, ","),
    ((712, 744, 776, 808), 8, ","), ((716, 748, 780, 812), 9, ","),
):
    for _command in _commands:
        VARIABLE_COMMANDS[_command] = (_class, _follower)
#: PROCEDURE, > PROCEDURE and the @ call: the name, then "(" unless the line ends.
PROCEDURE_COMMANDS = frozenset({24, 216, 248})
#: NEXT: four pointer bytes, then the loop variable.
NEXT_COMMANDS: dict[int, int] = {}
for _commands, _class in (((124, 128, 132), 0), ((136, 140, 144), 2), ((148, 152, 156), 8), ((160, 164, 168), 9)):
    for _command in _commands:
        NEXT_COMMANDS[_command] = _class
FOR_BASE = {0: 76, 2: 88, 8: 100, 9: 112}
NEXT_BASE = {0: 124, 2: 136, 8: 148, 9: 160}
ASSIGNMENT_CODES = {0: 304, 1: 308, 2: 312, 3: 316, 8: 320, 9: 324, 4: 328, 5: 332, 6: 336, 7: 340, 12: 344, 13: 348}
LET_CODES = {0: 256, 1: 260, 2: 264, 3: 268, 8: 272, 9: 276, 4: 280, 5: 284, 6: 288, 7: 292, 12: 296, 13: 300}
ARITHMETIC_FAMILIES = {"INC": 640, "DEC": 672, "ADD": 704, "SUB": 736, "MUL": 768, "DIV": 800}
MEMORY_ASSIGNMENTS = {
    "{": 920, "LONG{": 924, "INT{": 928, "CARD{": 932, "BYTE{": 936, "CHAR{": 940,
    "FLOAT{": 944, "DOUBLE{": 948, "SINGLE{": 492, "WORD{": 1672,
}

#: Primary tokens that gfalist reports as unknown single bytes.
UNKNOWN_PRIMARY = frozenset({
    46, 64, 68, 136, 137, 142, 144, 145, 146, 147, 148, 149, 150, 164, 165, 166,
    169, 177, 178, 179, 180, 181, 197, 209, 210, 211, 212, 213, 214,
})

#: Literal tokens: the unpadded code and its padded twin (used when the value
#: would otherwise start at an odd offset).
PADDED_TWIN = {200: 201, 202: 203, 204: 205, 206: 207, 216: 215, 218: 217, 220: 219, 223: 221, 198: 199}
UNPADDED = {padded: plain for plain, padded in PADDED_TWIN.items()}
INT_TOKENS = {200: 10, 202: 16, 204: 8, 206: 2}
FLOAT_TOKENS = {223: 10, 220: 16, 216: 8, 218: 2}
INT_TOKEN_BY_BASE = {10: 200, 16: 202, 8: 204, 2: 206}
FLOAT_TOKEN_BY_BASE = {10: 223, 16: 220, 8: 216, 2: 218}
BASE_PREFIX = {16: "&H", 8: "&O", 2: "&X"}
ZERO_TOKEN = 184
PRINT_NUMERIC_MARKER = 55

#: Kinds used for the editor's colouring (mirrors ``TokenKind`` values).
KEYWORD = "keyword"
IDENTIFIER = "identifier"
NUMBER = "number"
STRING = "string"
COMMENT = "comment"
OPERATOR = "operator"
SPACE = "space"

#: Primary tokens that are operators or punctuation rather than keywords.
OPERATOR_TOKENS = frozenset(
    list(range(0, 36)) + [45, 51, 57, 67, 69, 77, 80, 81, 88, 91, 124, 156, 157, 159, 189]
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
@dataclass
class Item:
    """One element of a line's token stream.

    ``kind`` is one of ``tok`` (primary token), ``sft`` (secondary token),
    ``var`` (token = class, name), ``int``/``float`` (token, value), ``str``
    (token, text), ``comment`` (token = spaces before the ``!``, text) for a
    trailing comment and ``inline`` (bytes) for INLINE data.
    """

    kind: str
    token: int = 0
    value: object = None
    name: str = ""


@dataclass
class LineModel:
    command: int
    operand: tuple[int, str] | None = None
    text: str = ""
    items: list[Item] = field(default_factory=list)


@dataclass
class GfaPiece:
    """One rendered fragment of a line, with its source byte span."""

    kind: str
    text: str
    start: int
    end: int
    value: object = None


@dataclass
class GfaLine:
    offset: int
    size: int
    command: int
    body: bytes
    model: LineModel | None = None
    depth: int = 0
    text: str = ""
    pieces: list = field(default_factory=list)


@dataclass
class GfaProgram:
    protected: bool
    version: int
    separators: list[int]
    identifiers: list[list[str]]
    lines: list[GfaLine]
    pool_length: int
    program_length: int


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------
def gfa_double_to_float(raw: bytes) -> float:
    """Convert GFA BASIC's eight-byte float to a Python float.

    The layout is a 48-bit mantissa with its leading bit stored explicitly
    (the first six bytes) followed by a 16-bit exponent word carrying the IEEE
    bias of 1023 plus one. A negative number stores the negated exponent word,
    so the sign lives in the exponent rather than in a separate bit. Zero is
    all zero bytes.
    """
    mantissa = int.from_bytes(raw[:6], "big")
    exponent = struct.unpack(">h", raw[6:8])[0]
    if mantissa == 0 or exponent == 0:
        return 0.0
    sign = -1.0 if exponent < 0 else 1.0
    return sign * math.ldexp(mantissa, abs(exponent) - 1023 - 47)


def float_to_gfa_double(number: float) -> bytes:
    """Encode a float in GFA BASIC's eight-byte layout (see ``gfa_double_to_float``)."""
    if number == 0:
        return bytes(8)
    fraction, exponent = math.frexp(abs(number))
    mantissa = int(round(fraction * (1 << 48)))
    if mantissa >= 1 << 48:
        mantissa >>= 1
        exponent += 1
    stored_exponent = exponent - 1 + 1023
    if not 0 < stored_exponent < 0x8000:
        raise DataError(f"{number!r} is outside the range GFA BASIC can store.")
    if number < 0:
        stored_exponent = -stored_exponent
    return mantissa.to_bytes(6, "big") + struct.pack(">h", stored_exponent)


def format_float(number: float) -> str:
    """Print a float with the fewest digits that read back to the same stored value.

    Whole numbers print without a decimal point, as GFA lists them.
    """
    if number == 0:
        return "0"
    if number == int(number) and abs(number) < 1e15:
        return str(int(number))
    stored = float_to_gfa_double(number)
    for digits in range(1, 18):
        text = "%.*G" % (digits, number)
        if float_to_gfa_double(float(text)) == stored:
            break
    else:
        text = repr(number)
    if "E" in text:
        mantissa, exponent = text.split("E")
        if -5 <= int(exponent) <= 15:
            text = format(Decimal(text), "f")
    return text


def format_based(value: int, base: int) -> str:
    """Print an integer in base 2, 8 or 16 as GFA does: negatives as 32-bit two's complement."""
    digits = "0123456789ABCDEF"
    value = int(value) & 0xFFFFFFFF
    if value == 0:
        return "0"
    out = []
    while value:
        out.append(digits[value % base])
        value //= base
    return "".join(reversed(out))


def literal_text(item: Item) -> str:
    """The listing text of an ``int`` or ``float`` item."""
    token = item.token
    if token == ZERO_TOKEN:
        return "0"
    if token in INT_TOKENS:
        base = INT_TOKENS[token]
        return str(item.value) if base == 10 else BASE_PREFIX[base] + format_based(item.value, base)
    base = FLOAT_TOKENS[token]
    if base == 10:
        return format_float(item.value)
    return BASE_PREFIX[base] + format_based(int(item.value), base)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------
def read_header(data: bytes) -> tuple[bool, int, list[int]]:
    if len(data) < HEADER_LENGTH:
        raise DataError("The file is too short to hold a GFA BASIC 3 header.")
    if data[2:12] != MAGIC_3:
        raise DataError("The GFA-BASIC3 signature is missing.")
    version = data[1]
    if version not in (3, 4):
        raise DataError(f"GFA BASIC file version {version} is not a 3.x format.")
    protected = data[0] == 0xFF
    separators = list(struct.unpack(">38I", data[12:HEADER_LENGTH]))
    return protected, version, separators


def read_identifiers(pool: bytes, counts: list[int]) -> list[list[str]]:
    tables: list[list[str]] = []
    position = 0
    for count in counts:
        top = position
        names = []
        for _ in range(count):
            if position >= len(pool):
                raise DataError("The identifier pool ends inside a name table.")
            length = pool[position]
            position += 1
            names.append(pool[position : position + length].decode("latin-1"))
            position += length
        position += (position - top) & 1
        tables.append(names)
    return tables


def parse_program(data: bytes) -> GfaProgram:
    """Split a ``.GFA`` file into header, identifier tables and raw lines."""
    protected, version, separators = read_header(data)
    pool_length = separators[16] - separators[0]
    program_length = separators[19] - separators[16]
    if pool_length < 0 or program_length < 0:
        raise DataError("The GFA BASIC header separators are inconsistent.")
    pool_start = HEADER_LENGTH
    program_start = pool_start + pool_length
    if program_start + program_length > len(data):
        raise DataError(
            f"The header promises {program_start + program_length:,} bytes but the file has {len(data):,}."
        )
    counts = [(separators[20 + i] - separators[19 + i]) // 4 for i in range(TABLE_COUNT)]
    if protected:
        identifiers: list[list[str]] = [[] for _ in range(TABLE_COUNT)]
    else:
        identifiers = read_identifiers(data[pool_start:program_start], counts)
    lines: list[GfaLine] = []
    position = program_start
    remaining = program_length
    while remaining > 0:
        if position + 4 > len(data):
            raise DataError(f"The line at offset {position} is truncated.")
        size = struct.unpack(">H", data[position : position + 2])[0]
        if size < 4 or position + size > len(data):
            raise DataError(f"The line at offset {position} declares an impossible size of {size}.")
        command = struct.unpack(">H", data[position + 2 : position + 4])[0]
        lines.append(GfaLine(position, size, command, data[position + 4 : position + size]))
        position += size
        remaining -= size
    return GfaProgram(protected, version, separators, identifiers, lines, pool_length, program_length)


class _Decoder:
    """Turn a raw line into a ``LineModel`` (and remember where each item came from)."""

    def __init__(self, program: GfaProgram):
        self.program = program

    def name(self, kind: int, index: int) -> str:
        if self.program.protected:
            return f"v{kind:x}_{index:x}"
        table = self.program.identifiers[kind]
        if index >= len(table):
            raise DataError(f"Variable {index} of class {kind} is missing from the name table.")
        return table[index]

    def decode(self, line: GfaLine) -> tuple[LineModel, list[tuple[int, int]]]:
        """Return the model and, per item, its (start, end) byte span in the body."""
        command = line.command
        body = line.body
        top = -2
        spans: list[tuple[int, int]] = []
        model = LineModel(command)
        if command not in LINE_COMMANDS:
            raise DataError(f"Unknown GFA BASIC line command {command} at offset {line.offset}.")
        src = 0

        def aligned(index: int) -> int:
            return index + ((index - top) & 1)

        def read_word(at: int) -> int:
            if at + 2 > len(body):
                raise DataError(f"The line at offset {line.offset} ends inside an operand.")
            return struct.unpack(">H", body[at : at + 2])[0]

        if command in TEXT_COMMANDS:
            end = body.find(bytes((TEXT_TERMINATOR,)), src)
            if end < 0:
                raise DataError(f"The text of the line at offset {line.offset} is unterminated.")
            model.text = body[src:end].decode("latin-1")
            return model, spans
        if command in NEXT_COMMANDS:
            src += 4
            model.operand = (NEXT_COMMANDS[command], self.name(NEXT_COMMANDS[command], read_word(src)))
            src += 2
        elif command in VARIABLE_COMMANDS:
            kind = VARIABLE_COMMANDS[command][0]
            model.operand = (kind, self.name(kind, read_word(src)))
            src += 2
        elif command in PROCEDURE_COMMANDS:
            model.operand = (CLASS_PROCEDURE, self.name(CLASS_PROCEDURE, read_word(src)))
            src += 2
        elif command in POINTER_COMMANDS:
            src += 4

        bot = len(body)
        while src < bot:
            token = body[src]
            start = src
            src += 1
            if token == END_MARKER:
                src = aligned(src)
                if src >= bot:
                    break
                if command == INLINE_COMMAND:
                    model.items.append(Item("inline", 0, bytes(body[src:bot])))
                    spans.append((start, bot))
                    break
                spaces = body[src]
                src += 1
                end = body.find(bytes((TEXT_TERMINATOR,)), src)
                end = bot if end < 0 else end
                model.items.append(Item("comment", spaces, body[src:end].decode("latin-1")))
                spans.append((start, end))
                break
            if token in (198, 199):
                if token == 199:
                    src += 1
                word = body[src : src + 4]
                src += 4
                model.items.append(Item("str", 198, word.lstrip(b"\x00").decode("latin-1")))
            elif token in (200, 201, 202, 203, 204, 205, 206, 207):
                if token & 1:
                    src += 1
                value = struct.unpack(">i", body[src : src + 4])[0]
                model.items.append(Item("int", UNPADDED.get(token, token), value))
                src += 4
            elif token == SECONDARY_ESCAPE:
                code = body[src]
                src += 1
                if SECONDARY_TOKENS.get(code) is None:
                    raise DataError(f"Unknown GFA BASIC function token 208,{code} at offset {line.offset}.")
                model.items.append(Item("sft", code))
            elif token in (215, 216, 217, 218, 219, 220, 221, 223):
                if token in (215, 217, 219, 221):
                    src += 1
                number = gfa_double_to_float(body[src : src + 8])
                src += 8
                model.items.append(Item("float", UNPADDED.get(token, token), number))
            elif token == 222:
                length = body[src]
                src += 1
                model.items.append(Item("str", 222, body[src : src + length].decode("latin-1")))
                src += length
            elif 224 <= token <= 239:
                model.items.append(Item("var", token - 224, None, self.name(token - 224, body[src])))
                src += 1
            elif 240 <= token <= 255:
                model.items.append(Item("var", token - 240, None, self.name(token - 240, read_word(src))))
                src += 2
            elif token in UNKNOWN_PRIMARY:
                src += 1
                continue
            elif token == ZERO_TOKEN:
                model.items.append(Item("int", ZERO_TOKEN, 0))
            else:
                if PRIMARY_TOKENS.get(token) is None:
                    raise DataError(f"Unknown GFA BASIC token {token} at offset {line.offset + 4 + start}.")
                model.items.append(Item("tok", token))
            spans.append((start, src))
        return model, spans


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------
def _item_fragments(model: LineModel) -> list[tuple[str, str, object]]:
    """Render a model's items as (kind, text, value) fragments."""
    out: list[tuple[str, str, object]] = []
    for item in model.items:
        if item.kind == "tok":
            text = PRIMARY_TOKENS[item.token]
            out.append((OPERATOR if item.token in OPERATOR_TOKENS else KEYWORD, text, item.token))
        elif item.kind == "sft":
            out.append((KEYWORD, SECONDARY_TOKENS[item.token], (SECONDARY_ESCAPE, item.token)))
        elif item.kind == "var":
            out.append((IDENTIFIER, item.name.lower() + VARIABLE_SUFFIXES[item.token], (item.token, item.name)))
        elif item.kind in ("int", "float"):
            out.append((NUMBER, literal_text(item), (item.token, item.value)))
        elif item.kind == "str":
            text = item.value if item.token == 198 else item.value.replace('"', '""')
            out.append((STRING, '"' + text + '"', (item.token, item.value)))
        elif item.kind == "comment":
            out.append((COMMENT, " " * item.token + "!" + item.value, (END_MARKER, item.value)))
        elif item.kind == "inline":
            out.append((SPACE, "", (END_MARKER, None)))
    return out


def render_model(model: LineModel, depth: int) -> tuple[list[tuple[str, str, object]], int, int]:
    """Render a line model; returns (fragments, indent level, depth for the next line)."""
    command = model.command
    if command in OPENING_COMMANDS:
        indent, next_depth = depth, depth + 1
    elif command in CLOSING_COMMANDS:
        indent, next_depth = depth - 1, depth - 1
    elif command in MIDDLE_COMMANDS:
        indent, next_depth = depth - 1, depth
    else:
        indent, next_depth = depth, depth
    indent = max(indent, 0)
    fragments: list[tuple[str, str, object]] = []
    command_text = LINE_COMMANDS[command]
    if command_text:
        fragments.append((COMMENT if command in COMMENT_COMMANDS else KEYWORD, command_text, ("command", command)))
    if command in TEXT_COMMANDS:
        if model.text and command in SPACED_TEXT_COMMANDS:
            fragments.append((SPACE, " ", None))
        if model.text:
            fragments.append((COMMENT if command in COMMENT_COMMANDS else STRING, model.text, ("text", model.text)))
        return fragments, indent, next_depth
    has_more = bool(model.items) and model.items[0].kind not in ("comment", "inline")
    body = _item_fragments(model)
    # A token that already carries its own leading space, such as " AT(",
    # supplies the separator itself, so PRINT AT(1,8) is not spaced twice.
    if command in OPTIONAL_SPACE_COMMANDS and has_more and not (
        model.operand is None and body and body[0][1].startswith(" ")
    ):
        fragments.append((SPACE, " ", None))
    if model.operand is not None:
        kind, name = model.operand
        fragments.append((IDENTIFIER, name.lower() + VARIABLE_SUFFIXES[kind], ("operand", model.operand)))
        if command in VARIABLE_COMMANDS:
            follower = VARIABLE_COMMANDS[command][1]
            if follower:
                fragments.append((OPERATOR, follower, None))
        elif command in PROCEDURE_COMMANDS and has_more and command != PROCEDURE_CALL_COMMAND:
            fragments.append((OPERATOR, "(", None))
    fragments.extend(body)
    return fragments, indent, next_depth


def inline_listing(data: bytes) -> list[str]:
    """Comment lines that carry INLINE data through a listing."""
    lines = [f"' ## INLINE {len(data)} bytes"]
    for offset in range(0, len(data), 16):
        chunk = data[offset : offset + 16]
        lines.append(f"' ## INLINE ${offset:04X}: " + " ".join(f"{byte:02x}" for byte in chunk))
    return lines


def decode_lines(program: GfaProgram) -> list[GfaLine]:
    """Decode and render every line; the end-of-program line is left out."""
    decoder = _Decoder(program)
    depth = 0
    rendered: list[GfaLine] = []
    for line in program.lines:
        if line.command == END_OF_PROGRAM:
            break
        model, spans = decoder.decode(line)
        fragments, indent, depth = render_model(model, depth)
        base = line.offset + 4
        pieces: list[GfaPiece] = []
        prefix = "  " * indent
        if prefix:
            pieces.append(GfaPiece(SPACE, prefix, line.offset, line.offset))
        text_parts = [prefix]
        span_iter = iter(spans)
        for kind, text, value in fragments:
            start = end = line.offset + 2
            if value is None:
                pass
            elif isinstance(value, tuple) and value[0] in ("command", "operand"):
                start, end = line.offset + 2, line.offset + 4
            elif isinstance(value, tuple) and value[0] == "text":
                start, end = line.offset + 4, line.offset + line.size
            else:
                span = next(span_iter, None)
                if span is not None:
                    start, end = base + span[0], base + span[1]
            if text:
                pieces.append(GfaPiece(kind, text, start, end, value))
                text_parts.append(text)
        line.model = model
        line.depth = indent
        line.pieces = pieces
        line.text = "".join(text_parts)
        rendered.append(line)
    return rendered


def detokenise_gfa(data: bytes) -> str:
    """List a ``.GFA`` file as GFA BASIC 3 would, with INLINE data as comment lines."""
    program = parse_program(data)
    out: list[str] = []
    for line in decode_lines(program):
        out.append(line.text)
        for item in line.model.items:
            if item.kind == "inline":
                indent = "  " * line.depth
                out.extend(indent + entry for entry in inline_listing(item.value))
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------
class _Pool:
    """The sixteen identifier tables, filled in first-use order."""

    def __init__(self):
        self.tables: list[list[str]] = [[] for _ in range(TABLE_COUNT)]
        self.index: dict[tuple[int, str], int] = {}

    def lookup(self, kind: int, name: str) -> int:
        key = (kind, name.upper())
        if key not in self.index:
            if len(name) > 255:
                raise DataError(f"The name {name!r} is longer than GFA BASIC allows.")
            self.index[key] = len(self.tables[kind])
            self.tables[kind].append(name.upper())
        return self.index[key]

    def encode(self) -> bytes:
        out = bytearray()
        for table in self.tables:
            top = len(out)
            for name in table:
                raw = name.encode("latin-1")
                out.append(len(raw))
                out.extend(raw)
            if (len(out) - top) & 1:
                out.append(0)
        return bytes(out)


def _serialise_line(model: LineModel, pool: _Pool) -> bytes:
    command = model.command
    line = bytearray(struct.pack(">H", command))

    def align() -> None:
        if len(line) & 1:
            line.append(0)

    if command in TEXT_COMMANDS:
        line.extend(model.text.encode("latin-1", "replace"))
        line.append(TEXT_TERMINATOR)
        align()
        return struct.pack(">H", len(line) + 2) + bytes(line)
    if model.operand is None and (command in NEXT_COMMANDS or command in VARIABLE_COMMANDS or command in PROCEDURE_COMMANDS):
        raise DataError(f"Line command {command} needs a variable operand.")
    if command in NEXT_COMMANDS:
        line.extend(bytes(4))
        line.extend(struct.pack(">H", pool.lookup(*model.operand)))
    elif command in VARIABLE_COMMANDS or command in PROCEDURE_COMMANDS:
        line.extend(struct.pack(">H", pool.lookup(*model.operand)))
    elif command in POINTER_COMMANDS:
        line.extend(bytes(4))
    closed = False
    for item in model.items:
        if item.kind == "tok":
            line.append(item.token)
        elif item.kind == "sft":
            line.extend((SECONDARY_ESCAPE, item.token))
        elif item.kind == "var":
            index = pool.lookup(item.token, item.name)
            if index < 256:
                line.extend((224 + item.token, index))
            else:
                line.append(240 + item.token)
                line.extend(struct.pack(">H", index))
        elif item.kind == "int":
            if item.token == ZERO_TOKEN:
                line.append(ZERO_TOKEN)
                continue
            if (len(line) + 1) & 1:
                line.extend((PADDED_TWIN[item.token], 0))
            else:
                line.append(item.token)
            line.extend(struct.pack(">i", item.value))
        elif item.kind == "float":
            if (len(line) + 1) & 1:
                line.extend((PADDED_TWIN[item.token], 0))
            else:
                line.append(item.token)
            line.extend(float_to_gfa_double(item.value))
        elif item.kind == "str":
            raw = item.value.encode("latin-1", "replace")
            if item.token == 198:
                if (len(line) + 1) & 1:
                    line.extend((199, 0))
                else:
                    line.append(198)
                line.extend(raw.rjust(4, b"\x00"))
            else:
                if len(raw) > 255:
                    raise DataError("A GFA BASIC string constant cannot exceed 255 characters.")
                line.append(222)
                line.append(len(raw))
                line.extend(raw)
        elif item.kind == "comment":
            line.append(END_MARKER)
            align()
            line.append(item.token)
            line.extend(item.value.encode("latin-1", "replace"))
            line.append(TEXT_TERMINATOR)
            align()
            closed = True
        elif item.kind == "inline":
            line.append(END_MARKER)
            align()
            line.extend(item.value)
            closed = True
    if not closed:
        line.append(END_MARKER)
        align()
    if len(line) + 2 > 0xFFFF:
        raise DataError("A GFA BASIC line cannot exceed 65535 bytes.")
    return struct.pack(">H", len(line) + 2) + bytes(line)


def serialise(models: list[LineModel], version: int = 4) -> bytes:
    """Write line models as a complete ``.GFA`` file."""
    pool = _Pool()
    program = bytearray()
    for model in models:
        program.extend(_serialise_line(model, pool))
    program.extend(struct.pack(">HH", 4, END_OF_PROGRAM))
    pool_bytes = pool.encode()
    separators = [0]
    for table in pool.tables:
        size = sum(1 + len(name) for name in table)
        separators.append(separators[-1] + size + (size & 1))
    separators.append(separators[16])  # 17: interpreter state, rebuilt on LOAD
    separators.append(separators[16])  # 18
    separators.append(separators[16] + len(program))  # 19
    for table in pool.tables:
        separators.append(separators[-1] + 4 * len(table))
    separators.append(separators[-1])  # 36
    separators.append(separators[-1])  # 37
    header = bytes((0, version)) + MAGIC_3 + struct.pack(">38I", *separators)
    return header + pool_bytes + bytes(program)


def canonicalise(data: bytes) -> bytes:
    """Re-serialise a file through the writer; ``tokenise(detokenise(data))`` must equal this."""
    program = parse_program(data)
    if program.protected:
        raise DataError("A PSAVE-protected program carries no names and cannot be rewritten.")
    models = [line.model for line in decode_lines(program)]
    return serialise(models, program.version)


# ---------------------------------------------------------------------------
# Tokenising
# ---------------------------------------------------------------------------
def _build_keyword_index() -> tuple[dict[str, list[int]], dict[str, list[int]], dict[str, list[int]]]:
    commands: dict[str, list[int]] = {}
    for code, text in LINE_COMMANDS.items():
        if not text or code == END_OF_PROGRAM or code in VARIABLE_COMMANDS or code in NEXT_COMMANDS:
            continue
        if code in (248, 252, 964) or code in MEMORY_ASSIGNMENTS.values():
            continue
        commands.setdefault(text.strip(), []).append(code)
    primary: dict[str, list[int]] = {}
    for code, text in PRIMARY_TOKENS.items():
        if text and text.strip() and code not in UNKNOWN_PRIMARY and code not in (184, 185):
            primary.setdefault(text.strip(), []).append(code)
    secondary: dict[str, list[int]] = {}
    for code, text in SECONDARY_TOKENS.items():
        if text and text.strip():
            secondary.setdefault(text.strip(), []).append(code)
    return commands, primary, secondary


COMMAND_CODES, PRIMARY_CODES, SECONDARY_CODES = _build_keyword_index()
ARITHMETIC_OPERATORS = frozenset({"+", "-", "*", "/", "^", "MOD", "DIV", "AND", "OR", "XOR", "IMP", "EQV", "\\"})
COMPARISON_OPERATORS = frozenset({"=", "<>", "<=", "=<", ">=", "=>", "<", ">", "=="})
NUMERIC_COMPARISON = {"<>": 12, "<=": 13, "=<": 14, ">=": 15, "=>": 16, "<": 17, ">": 18, "=": 19, "==": 45}
STRING_COMPARISON = {"<>": 20, "<=": 21, "=<": 22, ">=": 23, "=>": 24, "<": 25, ">": 26, "=": 27, "==": 45}
STRUCTURE_WORDS = frozenset({"TO", "STEP", "DOWNTO", "THEN", "GOTO", "GOSUB", "AS", "OFFSET", "WITH", "USING", "FN", "VAR", "BASE", "CONT"})
#: Functions whose argument is a float rather than an integer.
FLOAT_ARGUMENT_FUNCTIONS = frozenset({"RANDOM("})
#: Memory access brackets: their address expression is float typed.
MEMORY_BRACKETS = frozenset(MEMORY_ASSIGNMENTS)
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*")
_VARIABLE = re.compile(r"([A-Za-z_][A-Za-z0-9_.]*)([#$%!&|]?)(\(?)")
_NUMBER = re.compile(r"(?:&[Hh][0-9A-Fa-f]+|&[Oo][0-7]+|&[Xx][01]+|\d+\.?\d*(?:[Ee][-+]?\d+)?|\.\d+(?:[Ee][-+]?\d+)?)")
_KEYWORD_TEXTS = sorted(set(PRIMARY_CODES) | set(SECONDARY_CODES), key=len, reverse=True)
_COMMAND_TEXTS = sorted(COMMAND_CODES, key=len, reverse=True)


def _is_name_char(character: str) -> bool:
    return bool(character) and (character.isalnum() or character in "_.")


def _split_arguments(text: str) -> list[str]:
    parts = []
    depth = 0
    start = 0
    quoted = False
    for index, character in enumerate(text):
        if character == '"':
            quoted = not quoted
        elif quoted:
            continue
        elif character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        elif character == "," and depth == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    parts.append(text[start:].strip())
    return [part for part in parts if part] if text.strip() else []


def _matching_close(text: str, opener: str, closer: str) -> int:
    """Index just past the bracket closing an already-open ``opener`` at text[0:]."""
    depth = 1
    index = 0
    quoted = False
    while index < len(text) and depth:
        character = text[index]
        if character == '"':
            quoted = not quoted
        elif quoted:
            pass
        elif character == opener:
            depth += 1
        elif character == closer:
            depth -= 1
        index += 1
    if depth:
        raise DataError(f"A {opener!r} is never closed.")
    return index


class _Encoder:
    """Turn listing text into line models."""

    def __init__(self):
        self.for_stack: list[int] = []
        self.line_number = 0

    def encode(self, source: str) -> list[LineModel]:
        models: list[LineModel] = []
        for raw in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            self.line_number += 1
            line = raw.strip()
            if not line:
                continue
            if line.startswith("' ## INLINE") and models and models[-1].command == INLINE_COMMAND:
                self._inline_chunk(models[-1], line)
                continue
            try:
                models.append(self.statement(line))
            except DataError as exc:
                raise DataError(f"Line {self.line_number}: {exc}") from exc
        return models

    @staticmethod
    def _inline_chunk(model: LineModel, line: str) -> None:
        match = re.match(r"' ## INLINE \$[0-9A-Fa-f]{4}: ((?:[0-9A-Fa-f]{2} ?)*)$", line)
        if not match:
            return
        chunk = bytes.fromhex(match.group(1).replace(" ", ""))
        if model.items and model.items[-1].kind == "inline":
            model.items[-1].value += chunk
        else:
            model.items.append(Item("inline", 0, chunk))

    # -- statements -------------------------------------------------------
    def statement(self, line: str) -> LineModel:
        upper = line.upper()
        for prefix, code in (("'", 460), ("==>", 464), ("$", 1644)):
            if line.startswith(prefix):
                rest = line[len(prefix):]
                if code != 1644 and rest.startswith(" "):
                    rest = rest[1:]
                return LineModel(code, text=rest)
        for word, code in (("REM", 456), ("DATA", 468)):
            if upper == word or upper.startswith(word + " "):
                return LineModel(code, text=line[len(word) + 1:])
        match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.]*):", line)
        if match:
            return LineModel(LABEL_COMMAND, items=[Item("var", CLASS_LABEL, None, match.group(1)), Item("tok", 124)])
        if line.startswith("@"):
            match = _NAME.match(line, 1)
            if not match:
                raise DataError("A procedure call needs a name after @.")
            model = LineModel(PROCEDURE_CALL_COMMAND, operand=(CLASS_PROCEDURE, match.group(0)))
            rest = line[match.end():].lstrip()
            if rest.startswith("("):
                model.items.append(Item("tok", 157))
                model.items.extend(self.expression(rest[1:]))
            elif rest:
                model.items.extend(self.expression(rest))
            return model
        if line.startswith("~"):
            return LineModel(964, items=self.expression(line[1:]))
        for word in ("FOR", "NEXT", "LET", "INC", "DEC", "ADD", "SUB", "MUL", "DIV", "GOSUB"):
            if upper == word or upper.startswith(word + " "):
                return self.variable_statement(word, line[len(word):].strip())
        for text in _COMMAND_TEXTS:
            if not upper.startswith(text):
                continue
            end = len(text)
            following = line[end:end + 1]
            if text[-1].isalnum() and _is_name_char(following):
                continue
            if text[-1] == "$" and following and not following.isspace():
                continue
            if text[-1] not in " (#{" and following and not following.isspace() and text[-1].isalnum():
                continue
            rest = line[end:]
            if rest.startswith(" "):
                rest = rest[1:]
            return self.keyword_statement(text, COMMAND_CODES[text], rest)
        for text in sorted(MEMORY_BRACKETS, key=len, reverse=True):
            if upper.startswith(text):
                return self.memory_assignment(text, line[len(text):])
        # GFA BASIC 3 lets a procedure be called by name alone, without the @
        # that its own lister prints, so hand-written source has to be
        # accepted here even though a listing never comes back that way.
        call = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_.]*)\s*(\(.*\))?", line)
        if call is not None and "=" not in line:
            model = LineModel(PROCEDURE_CALL_COMMAND, operand=(CLASS_PROCEDURE, call.group(1)))
            if call.group(2):
                model.items.append(Item("tok", 157))
                model.items.extend(self.expression(call.group(2)[1:-1] + ")"))
            return model
        return self.assignment(line, LET_CODES if False else ASSIGNMENT_CODES)

    def keyword_statement(self, text: str, codes: list[int], rest: str) -> LineModel:
        if text in ("PROCEDURE", "> PROCEDURE"):
            match = _NAME.match(rest)
            if not match:
                raise DataError("PROCEDURE needs a name.")
            model = LineModel(216 if text.startswith(">") else 24, operand=(CLASS_PROCEDURE, match.group(0)))
            tail = rest[match.end():].lstrip()
            if tail.startswith("("):
                model.items.extend(self.expression(tail[1:]))
            return model
        if text in ("FUNCTION", "> FUNCTION"):
            match = re.match(r"([A-Za-z_][A-Za-z0-9_.]*)(\$?)", rest)
            if not match:
                raise DataError("FUNCTION needs a name.")
            kind = CLASS_STRING_FUNCTION if match.group(2) else CLASS_FUNCTION
            model = LineModel(1796 if text.startswith(">") else 40)
            model.items.append(Item("var", kind, None, match.group(1)))
            model.items.extend(self.expression(rest[match.end():]))
            return model
        if text == "RETURN":
            if not rest:
                return LineModel(28)
            items, string_typed = self.typed_expression(rest)
            return LineModel(72 if string_typed else 68, items=items)
        if text == "GOTO":
            match = _NAME.match(rest)
            if not match or rest[match.end():].strip():
                raise DataError("GOTO needs a label name.")
            return LineModel(232, items=[Item("var", CLASS_LABEL, None, match.group(0))])
        if text.startswith("ON ") and text.endswith("GOSUB"):
            match = _NAME.match(rest)
            if not match:
                raise DataError(f"{text} needs a procedure name.")
            model = LineModel(codes[0], items=[Item("var", CLASS_PROCEDURE, None, match.group(0))])
            model.items.extend(self.expression(rest[match.end():]))
            return model
        code = self.choose_command(text, codes, rest)
        model = LineModel(code)
        if code in (588, 592, 1212):
            model.items = self.print_items(rest)
        elif code == 1588:
            model.items = self.expression(rest, float_after_comma=True)
        else:
            model.items = self.expression(rest)
        return model

    def choose_command(self, text: str, codes: list[int], rest: str) -> int:
        """Pick among duplicate line-command codes for the same text.

        Bare versus with-operand forms (RESERVE, RUN, VDISYS and the like) and
        PRINT # / INPUT # are backed by the corpus; the argument-count variants
        (CIRCLE with angles, TEXT with a length, FILL with a border colour...)
        follow the table's order, shortest form first, and are inferred.
        """
        if len(codes) == 1:
            return codes[0]
        upper = rest.upper()
        arguments = _split_arguments(rest)
        count = len(arguments)
        if text == "RESUME":
            return 420 if not rest else 424 if upper == "NEXT" else 428
        if text == "TRON":
            return 572 if not rest else 580 if rest.startswith("#") else 576
        if text in ("PRINT", "INPUT", "OUT"):
            return codes[1] if rest.startswith("#") else codes[0]
        if text == "DRAW":
            return codes[1] if " TO " in upper else codes[0]
        if text == "DEFFILL":
            return codes[1] if count >= 2 and "(" in arguments[1] else codes[0]
        if text == "DEFMOUSE":
            return codes[1] if rest.startswith('"') or "$" in rest else codes[0]
        if text in ("EVERY", "AFTER"):
            return codes[1] if upper == "STOP" else codes[2] if upper == "CONT" else codes[0]
        if text == "SWAP":
            return codes[1] if "(" in rest else codes[0]
        if text in ("RESERVE", "RUN", "SELECT", "EXIT IF", "MENU", "ON MENU", "GEMSYS", "CLOSEW", "CLEARW", "OPENW"):
            return codes[0] if not rest else codes[1]
        if text == "VDISYS":
            return codes[min(count, len(codes) - 1)]
        thresholds = {
            "SETCOLOR": (2,), "CIRCLE": (3,), "PCIRCLE": (3,), "ELLIPSE": (4,), "PELLIPSE": (4,),
            "FILL": (2,), "TEXT": (3,), "CLIP": (2, 3, 4, 5), "GET": (5, 6), "PUT": (3, 4, 5),
            "BITBLT": (1, 2), "CHDRIVE": (1,), "MAT MUL": (2, 3, 4), "MAT ADD": (2,), "MAT SUB": (2,),
        }
        limits = thresholds.get(text, ())
        index = sum(1 for limit in limits if count > limit)
        return codes[min(index, len(codes) - 1)]

    def variable_statement(self, word: str, rest: str) -> LineModel:
        if word == "GOSUB":
            match = _NAME.match(rest)
            if not match:
                raise DataError("GOSUB needs a procedure name.")
            model = LineModel(244, operand=(CLASS_PROCEDURE, match.group(0)))
            model.items.extend(self.expression(rest[match.end():]))
            return model
        if word == "LET":
            return self.assignment(rest, LET_CODES)
        match = _VARIABLE.match(rest)
        if not match:
            raise DataError(f"{word} needs a variable.")
        name, suffix, paren = match.groups()
        suffix = suffix or "#"
        is_array = bool(paren)
        kind = (ARRAY_CLASS_BY_SUFFIX if is_array else SIMPLE_CLASS_BY_SUFFIX)[suffix]
        tail = rest[match.end():]
        if word == "NEXT":
            if not self.for_stack:
                raise DataError("NEXT without FOR.")
            if kind not in NEXT_BASE:
                raise DataError(f"NEXT cannot use a {suffix} variable.")
            return LineModel(NEXT_BASE[kind] + self.for_stack.pop(), operand=(kind, name))
        if word == "FOR":
            if kind not in FOR_BASE:
                raise DataError(f"FOR cannot use a {suffix} variable.")
            body = tail.lstrip()
            if not body.startswith("="):
                raise DataError("FOR needs an assignment.")
            upper = body.upper()
            form = 8 if " STEP " in upper else 4 if " DOWNTO " in upper else 0
            self.for_stack.append(form)
            model = LineModel(FOR_BASE[kind] + form, operand=(kind, name))
            model.items = self.expression(body[1:], float_for_limit=form == 8, float_context=kind == 0)
            return model
        family = ARITHMETIC_FAMILIES[word]
        if is_array:
            if kind not in (4, 6, 12, 13):
                raise DataError(f"{word} cannot use a {suffix}( array.")
            model = LineModel(family + 16 + {4: 0, 6: 4, 12: 8, 13: 12}[kind], operand=(kind, name))
            model.items = self.expression(tail, float_after_comma=kind == 4)
            return model
        if kind not in (0, 2, 8, 9):
            raise DataError(f"{word} cannot use a {suffix} variable.")
        model = LineModel(family + {0: 0, 2: 4, 8: 8, 9: 12}[kind], operand=(kind, name))
        if word in ("INC", "DEC"):
            if tail.strip():
                raise DataError(f"{word} takes a single variable.")
            return model
        body = tail.lstrip()
        if not body.startswith(","):
            raise DataError(f"{word} needs a comma and a value.")
        model.items = self.expression(body[1:], float_context=kind == 0)
        return model

    def memory_assignment(self, text: str, rest: str) -> LineModel:
        close = _matching_close(rest, "{", "}")
        if not rest[close:].startswith("="):
            raise DataError("A memory assignment needs }= after the address.")
        model = LineModel(MEMORY_ASSIGNMENTS[text])
        model.items = self.expression(rest[: close - 1], float_context=True)
        model.items.append(Item("tok", 67))
        model.items.extend(self.expression(rest[close + 1:], float_context=text in ("FLOAT{", "DOUBLE{", "SINGLE{")))
        return model

    def assignment(self, line: str, codes: dict[int, int]) -> LineModel:
        match = _VARIABLE.match(line)
        if not match:
            raise DataError(f"Cannot understand the statement {line!r}.")
        name, suffix, paren = match.groups()
        suffix = suffix or "#"
        rest = line[match.end():]
        if paren:
            kind = ARRAY_CLASS_BY_SUFFIX[suffix]
            close = _matching_close(rest, "(", ")")
            if not rest[close:].startswith("="):
                raise DataError(f"The array assignment {line!r} needs )= after the index.")
            model = LineModel(codes[kind], operand=(kind, name))
            model.items = self.expression(rest[: close - 1])
            model.items.append(Item("tok", 57))
            model.items.extend(self.expression(rest[close + 1:], float_context=kind == 4))
            return model
        kind = SIMPLE_CLASS_BY_SUFFIX[suffix]
        rest = rest.lstrip()
        if not rest.startswith("="):
            raise DataError(f"Cannot understand the statement {line!r}.")
        model = LineModel(codes[kind], operand=(kind, name))
        model.items = self.expression(rest[1:], float_context=kind == 0)
        return model

    # -- expressions ------------------------------------------------------
    def print_items(self, rest: str) -> list[Item]:
        """PRINT arguments: each numeric value item is preceded by the invisible token 55."""
        items: list[Item] = []
        depth = 0
        quoted = False
        start = 0
        segments: list[tuple[str, str]] = []
        index = 0
        while index < len(rest):
            character = rest[index]
            if character == '"':
                quoted = not quoted
            elif quoted:
                pass
            elif character in "([{":
                depth += 1
            elif character in ")]}":
                depth -= 1
            elif character in ";," and depth == 0:
                segments.append((rest[start:index], character))
                start = index + 1
            elif character == "!" and depth == 0 and not _is_name_char(rest[index - 1:index]):
                break
            index += 1
        segments.append((rest[start:], ""))
        for text, separator in segments:
            stripped = text.strip()
            if stripped:
                piece, string_typed = self.typed_expression(text)
                upper = stripped.upper()
                value_item = not upper.startswith(("AT(", "TAB(", "SPC(", "USING ")) and piece and piece[0].kind != "comment"
                if value_item and not string_typed:
                    items.append(Item("tok", PRINT_NUMERIC_MARKER))
                items.extend(piece)
            if separator:
                items.append(Item("tok", 34 if separator == ";" else 33))
        return items

    def typed_expression(self, text: str, **options) -> tuple[list[Item], bool]:
        scanner = _ExpressionScanner(text, **options)
        items = scanner.run()
        return items, scanner.result_is_string

    def expression(self, text: str, **options) -> list[Item]:
        return self.typed_expression(text, **options)[0]


class _ExpressionScanner:
    """Tokenise one expression or argument list.

    Literal typing (proven on the corpus): a numeric constant that is the
    operand of an arithmetic or comparison operator is stored as a float (a
    zero operand uses the dedicated zero token); a constant that stands alone
    (an argument, an index, a value after TO, CASE or an assignment to an
    integer class) is stored as a 32-bit integer when it is whole and fits;
    arguments of RANDOM(, the value of ARRAYFILL, addresses inside memory
    braces and the limit of a FOR ... STEP loop are floats. Comparison
    operators and ``+`` take their string variant when the left operand is a
    string. Which of ``+`` 28/29 and ``-`` 30 GFA uses for unary signs is
    inferred (28 concatenation, 30 unary minus).
    """

    def __init__(self, text: str, float_context: bool = False, float_after_comma: bool = False,
                 float_for_limit: bool = False):
        self.text = text
        self.items: list[Item] = []
        self.position = 0
        self.float_context = float_context
        self.float_after_comma = float_after_comma
        self.float_for_limit = float_for_limit
        self.last_type = "none"       # type of the most recent operand: none, num, str
        self.previous = "start"       # kind of the previous significant token
        self.stack: list[str | None] = []  # open brackets: function type or None for grouping
        self.result_is_string = False
        self.first_type: str | None = None
        self.comma_seen = False
        self.after_to = False

    def run(self) -> list[Item]:
        text = self.text
        while self.position < len(text):
            character = text[self.position]
            if character.isspace():
                self.position += 1
                continue
            if character == '"':
                self.string()
                continue
            if character == "!" and not _is_name_char(text[self.position - 1:self.position]):
                self.comment()
                break
            if character == "@":
                self.user_function()
                continue
            if character == "&" and text[self.position + 1:self.position + 2].upper() in ("H", "O", "X"):
                self.number()
                continue
            if character.isdigit() or (character == "." and text[self.position + 1:self.position + 2].isdigit()):
                self.number()
                continue
            if character == "-" and self.previous in ("start", "open", "comma", "prefix") and _NUMBER.match(text, self.position + 1):
                self.number()
                continue
            if self.keyword():
                continue
            if character.isalpha() or character == "_":
                self.identifier()
                continue
            self.punctuation()
        self.result_is_string = self.first_type == "str"
        return self.items

    # -- helpers ------------------------------------------------------------
    def emit(self, item: Item, previous: str) -> None:
        self.items.append(item)
        self.previous = previous

    def operand(self, kind: str) -> None:
        if self.first_type is None and not self.stack:
            self.first_type = kind
        self.last_type = kind

    def next_is_operator(self, index: int) -> bool:
        while index < len(self.text) and self.text[index].isspace():
            index += 1
        rest = self.text[index:]
        if not rest:
            return False
        if rest[0] in "+-*/^\\=<>":
            return True
        match = _NAME.match(rest)
        return bool(match) and match.group(0).upper() in ARITHMETIC_OPERATORS and not _is_name_char(rest[match.end():match.end() + 1])

    def in_float_context(self) -> bool:
        if self.stack:
            function = self.stack[-1]
            return function is not None and function.startswith("float")
        if self.float_after_comma and self.comma_seen:
            return True
        if self.float_for_limit and self.after_to:
            return True
        return self.float_context

    # -- token builders ---------------------------------------------------
    def string(self) -> None:
        text = self.text
        index = self.position + 1
        out = []
        while True:
            if index >= len(text):
                raise DataError("A string constant is not closed.")
            if text[index] == '"':
                if text[index + 1:index + 2] == '"':
                    out.append('"')
                    index += 2
                    continue
                index += 1
                break
            out.append(text[index])
            index += 1
        self.position = index
        self.emit(Item("str", 222, "".join(out)), "operand")
        self.operand("str")

    def comment(self) -> None:
        code = self.text[: self.position]
        spaces = len(code) - len(code.rstrip(" "))
        self.items.append(Item("comment", spaces, self.text[self.position + 1:]))
        self.position = len(self.text)

    def number(self) -> None:
        text = self.text
        start = self.position
        negative = text[start] == "-"
        if negative:
            start += 1
        match = _NUMBER.match(text, start)
        if not match:
            raise DataError(f"Cannot read the number at {text[self.position:]!r}.")
        literal = match.group(0)
        self.position = match.end()
        operand_of_operator = self.previous == "operator" or self.next_is_operator(self.position)
        upper = literal.upper()
        if upper.startswith("&"):
            base = {"H": 16, "O": 8, "X": 2}[upper[1]]
            value = int(upper[2:], base)
            if value > 0xFFFFFFFF:
                raise DataError(f"{literal} does not fit in 32 bits.")
            signed = value - (1 << 32) if value >= 1 << 31 else value
            if negative:
                signed = -signed
            if operand_of_operator or self.in_float_context():
                self.emit(Item("float", FLOAT_TOKEN_BY_BASE[base], float(signed)), "operand")
            else:
                self.emit(Item("int", INT_TOKEN_BY_BASE[base], signed), "operand")
            self.operand("num")
            return
        is_whole = "." not in literal and "E" not in upper
        value = -float(literal) if negative else float(literal)
        if operand_of_operator:
            if value == 0 and is_whole:
                self.emit(Item("int", ZERO_TOKEN, 0), "operand")
            else:
                self.emit(Item("float", 223, value), "operand")
        elif is_whole and -0x80000000 <= int(value) <= 0x7FFFFFFF and not self.in_float_context():
            self.emit(Item("int", 200, int(value)), "operand")
        else:
            self.emit(Item("float", 223, value), "operand")
        self.operand("num")

    def user_function(self) -> None:
        match = re.match(r"@([A-Za-z_][A-Za-z0-9_.]*)(\$?)", self.text[self.position:])
        if not match:
            raise DataError("A function call needs a name after @.")
        kind = CLASS_STRING_FUNCTION if match.group(2) else CLASS_FUNCTION
        result = "str" if kind == CLASS_STRING_FUNCTION else "num"
        self.emit(Item("tok", 159), "prefix")
        self.emit(Item("var", kind, None, match.group(1)), "operand")
        self.position += match.end()
        if self.text[self.position:self.position + 1] == "(":
            self.emit(Item("tok", 35), "open")
            self.stack.append("call:" + result)
            self.position += 1
        else:
            self.operand(result)

    def keyword(self) -> bool:
        rest = self.text[self.position:]
        upper = rest.upper()
        for candidate in _KEYWORD_TEXTS:
            if not upper.startswith(candidate):
                continue
            end = len(candidate)
            following = rest[end:end + 1]
            if candidate[-1].isalnum() and _is_name_char(following):
                continue
            if candidate[-1] == "$" and (following == "(" or _is_name_char(following)):
                continue
            if candidate[-1].isalnum() and following in "#$%!&|" and following:
                continue
            self.position += end
            self.keyword_token(candidate, rest[end:])
            return True
        return False

    def keyword_token(self, candidate: str, tail: str) -> None:
        if candidate in COMPARISON_OPERATORS:
            table = STRING_COMPARISON if self.last_type == "str" else NUMERIC_COMPARISON
            self.emit(Item("tok", table[candidate]), "operator")
            return
        if candidate == "+":
            self.emit(Item("tok", 28 if self.last_type == "str" else 6), "operator")
            return
        if candidate == "-":
            token = 30 if self.previous in ("start", "open", "comma", "operator", "prefix") else 5
            self.emit(Item("tok", token), "operator")
            return
        if candidate in ARITHMETIC_OPERATORS:
            codes = PRIMARY_CODES.get(candidate) or SECONDARY_CODES.get(candidate)
            self.emit(Item("tok", codes[0]), "operator")
            return
        if candidate == "NOT":
            self.emit(Item("tok", 31), "operator")
            return
        if candidate in STRUCTURE_WORDS:
            self.emit(Item("tok", PRIMARY_CODES[candidate][0]), "prefix")
            if candidate == "TO":
                self.after_to = True
            elif candidate in ("STEP", "DOWNTO"):
                self.after_to = False
            self.last_type = "none"
            return
        if candidate in ("L:", "W:", "V:", "C:"):
            if candidate in PRIMARY_CODES:
                self.emit(Item("tok", PRIMARY_CODES[candidate][0]), "prefix")
            else:
                self.emit(Item("sft", SECONDARY_CODES[candidate][0]), "prefix")
            self.last_type = "num"
            return
        codes = PRIMARY_CODES.get(candidate)
        item_kind = "tok"
        if codes is None:
            codes = SECONDARY_CODES[candidate]
            item_kind = "sft"
        code = self.choose_function(candidate, codes, tail)
        returns_string = "$" in candidate or candidate == "CHAR{"
        if candidate.endswith(("(", "{")):
            self.emit(Item(item_kind, code), "open")
            float_typed = candidate in FLOAT_ARGUMENT_FUNCTIONS or candidate in MEMORY_BRACKETS
            self.stack.append(("float" if float_typed else "call") + (":str" if returns_string else ":num"))
        else:
            self.emit(Item(item_kind, code), "operand")
            self.operand("str" if returns_string else "num")

    @staticmethod
    def choose_function(candidate: str, codes: list[int], tail: str) -> int:
        """Argument-count variants of a function (LEFT$(, MID$(, STR$(...): fewest arguments first."""
        if len(codes) == 1 or not candidate.endswith("("):
            return codes[0]
        close = _matching_close(tail, "(", ")")
        arguments = _split_arguments(tail[: close - 1])
        if candidate == "STRING$(":
            second = arguments[1] if len(arguments) > 1 else ""
            return codes[1] if second.startswith('"') or "$" in second else codes[0]
        return codes[min(max(len(arguments) - 1, 0), len(codes) - 1)]

    def identifier(self) -> None:
        match = _VARIABLE.match(self.text, self.position)
        name, suffix, paren = match.groups()
        suffix = suffix or "#"
        self.position = match.end()
        if paren:
            kind = ARRAY_CLASS_BY_SUFFIX[suffix]
            self.emit(Item("var", kind, None, name), "open")
            self.stack.append("array:" + ("str" if kind in STRING_CLASSES else "num"))
        else:
            kind = SIMPLE_CLASS_BY_SUFFIX[suffix]
            self.emit(Item("var", kind, None, name), "operand")
            self.operand("str" if kind in STRING_CLASSES else "num")

    def punctuation(self) -> None:
        character = self.text[self.position]
        self.position += 1
        following = self.text[self.position:self.position + 1]
        if character == "(":
            self.emit(Item("tok", 35), "open")
            self.stack.append(None)
        elif character in ")}":
            function = self.stack.pop() if self.stack else None
            if character == "}" and following == "=":
                self.position += 1
                self.emit(Item("tok", 67), "operator")
            elif character == ")" and following == "=" and function is not None and function.startswith("array"):
                self.position += 1
                self.emit(Item("tok", 57), "operator")
            else:
                self.emit(Item("tok", 32 if character == ")" else 88), "operand")
            if function is not None:
                self.operand(function.split(":")[1])
        elif character == ",":
            self.emit(Item("tok", 33), "comma")
            if not self.stack:
                self.comma_seen = True
            self.last_type = "none"
        elif character == ";":
            self.emit(Item("tok", 34), "comma")
            self.last_type = "none"
        elif character == "#":
            self.emit(Item("tok", 77), "prefix")
        elif character == "[":
            self.emit(Item("tok", 80), "open")
        elif character == "]":
            self.emit(Item("tok", 81), "operand")
        elif character == ":":
            self.emit(Item("tok", 124), "operator")
        elif character == "'":
            self.emit(Item("tok", 87), "operator")
        else:
            raise DataError(f"Unexpected character {character!r}.")


def tokenise_gfa(source: str) -> bytes:
    """Encode a listing as a GFA BASIC 3.5 ``.GFA`` file."""
    models = _Encoder().encode(source)
    if not models:
        raise DataError("The listing is empty.")
    return serialise(models)


__all__ = [
    "GfaLine",
    "GfaPiece",
    "GfaProgram",
    "HEADER_LENGTH",
    "Item",
    "LineModel",
    "MAGIC_2",
    "MAGIC_3",
    "VARIABLE_SUFFIXES",
    "canonicalise",
    "decode_lines",
    "detokenise_gfa",
    "parse_program",
    "serialise",
    "tokenise_gfa",
]
