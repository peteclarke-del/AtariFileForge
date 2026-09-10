r"""What one file on a GEMDOS volume actually is.

A GEMDOS directory entry says nothing about content: there is no type field
and no icon, only a name, a length, a datestamp and an attribute byte. So the
kind has to be read from the bytes, with the name as a hint and never as the
answer.

Five kinds are recognised, and each has a definite signature rather than a
guess:

``program``
    A GEMDOS executable. Its first word is ``0x601A``, which is a branch TOS
    reads as the magic number of a program header.
``basic``
    A tokenised BASIC program, recognised by the tokeniser in
    ``atarinut.basic`` rather than by extension, so a program saved without
    one is still found.
``script``
    Text the desktop or the operating system reads as instructions: a
    ``DESKTOP.INF`` or ``NEWDESK.INF``, a MiNT ``MINT.CNF``, or a batch file.
``text``
    Readable text that is not addressed to a program.
``container``
    A disk image or archive stored as an ordinary file: an MSA, a DIM, a
    Pasti capture, a ZIP or an LZH.
"""

from __future__ import annotations

import re
from . import atari_paths


LISTING_SNIFF_LIMIT = 128 * 1024

#: The first word of every GEMDOS executable, which is a short branch past
#: the twenty-eight byte program header TOS reads.
GEMDOS_EXECUTABLE_MAGIC = b"\x60\x1a"

#: Extensions TOS itself will run. ``.PRG`` and ``.APP`` start from the
#: desktop, ``.TOS`` and ``.TTP`` run in text mode with ``.TTP`` prompting for
#: a command line, ``.ACC`` loads at boot as a desk accessory, and ``.GTP``
#: is the Falcon's parameter-taking GEM program.
PROGRAM_EXTENSIONS = {".prg", ".app", ".tos", ".ttp", ".acc", ".gtp", ".prx", ".ovl"}

#: Files the desktop and the operating system read as instructions.
SCRIPT_EXTENSIONS = {".inf", ".cnf", ".bat", ".ini"}

#: The ones named in full, because they are read at boot whatever else is on
#: the volume.
SCRIPT_NAMES = {
    "desktop.inf",
    "newdesk.inf",
    "mint.cnf",
    "gem.cnf",
    "assign.sys",
    "extendos.cnf",
    "auto.bat",
}

#: Extensions that hold a whole disk or a bundle of files rather than one.
CONTAINER_EXTENSIONS = {".msa", ".dim", ".stx", ".st", ".zip", ".lzh", ".lha", ".arc"}

#: ``DESKTOP.INF`` is a line-per-record file, and every record begins with a
#: hash and one letter. The letters are the whole vocabulary: the three
#: ``#a`` ``#b`` ``#c`` records carry the video and desktop preferences,
#: ``#d`` the double-click speed, ``#E`` the environment word, ``#W`` one
#: open window, ``#M`` a drive icon, ``#T`` a trash or printer icon, ``#F``
#: and ``#D`` the file and folder install lines, ``#G`` ``#P`` an installed
#: application by extension.
DESKTOP_INF_RECORDS = {
    "#a": "display preferences",
    "#b": "desktop preferences",
    "#c": "colour preferences",
    "#d": "double-click and key repeat",
    "#E": "environment and resolution",
    "#W": "open window",
    "#M": "drive icon",
    "#T": "trash or printer icon",
    "#F": "installed file type",
    "#D": "installed folder type",
    "#G": "installed GEM application",
    "#P": "installed TOS application",
}

#: ``MINT.CNF`` is read by MiNT before the desktop starts. These are the
#: directives it acts on; anything else on a line is a comment or a variable
#: assignment.
MINT_CNF_KEYWORDS = (
    "ALIAS|CACHE|CD|DEBUG|ECHO|EXEC|GEM|GMT|HOSTNAME|INIT|MAXMEM|PATH|PRINT|"
    "REN|ROOT|SETENV|SLN|UMASK"
)

#: A batch file is a run of ordinary TOS commands.
BATCH_KEYWORDS = (
    "CD|CLS|COPY|DEL|DIR|ECHO|ERASE|EXEC|EXIT|GOTO|IF|MD|MKDIR|MOVE|PATH|"
    "PAUSE|PRINT|REM|REN|RENAME|RD|RMDIR|RUN|SET|SETENV|TYPE|VER"
)

SCRIPT_COMMAND_RE = re.compile(
    r"^\s*(?:(#[a-zA-Z])\s*(.*)|"
    rf"(?:{MINT_CNF_KEYWORDS}|{BATCH_KEYWORDS})\b\s*(.*))$"
)
_SCRIPT_ACTION_RE = re.compile(
    rf"^\s*(#[a-zA-Z]|{MINT_CNF_KEYWORDS}|{BATCH_KEYWORDS})\b\s*(.*)$",
    re.IGNORECASE,
)


def format_basic_listing(source: str) -> str:
    """Give every numbered BASIC line one visible separator after its number."""
    formatted = []
    for line in source.splitlines():
        match = re.match(r"^(\d+)(.*)$", line)
        if not match:
            formatted.append(line)
            continue
        number, body = match.groups()
        formatted.append(f"{number} {body[1:] if body.startswith((' ', chr(9))) else body}")
    return "\n".join(formatted)


def is_gemdos_program(data: bytes) -> bool:
    """True when these bytes begin with a GEMDOS program header."""
    return len(data) >= 28 and data[:2] == GEMDOS_EXECUTABLE_MAGIC


def basic_details(data: bytes) -> dict | None:
    """Describe a tokenised BASIC program, or return None for anything else.

    The dialect is whichever one in the tokeniser's own table scans the
    program, tried richest first, so a program using keywords a later release
    added is not mis-read as a damaged earlier one. The dialect names are the
    tokeniser's to choose; nothing here depends on what they are called.
    """
    try:
        from atarinut.basic import DIALECTS, Verdict, detect, detokenise, scan_program
    except ImportError:
        return None
    detection = detect(data)
    if detection.verdict not in {Verdict.BASIC, Verdict.BASIC_TRAILING}:
        return None
    program_length = int(detection.program_length or len(data))
    program = data[:program_length]
    for dialect in reversed(list(DIALECTS.values())):
        try:
            lines = list(scan_program(program, dialect=dialect))
            if not lines:
                continue
            source = format_basic_listing(detokenise(program, dialect=dialect))
        except Exception:
            continue
        return {
            "source": source,
            "dialect": dialect.name,
            "lineCount": len(lines),
            "firstLine": lines[0].line_number,
            "lastLine": lines[-1].line_number,
            "trailingBytes": len(data) - program_length,
            "programLength": program_length,
            "compound": len(data) > program_length,
            # The tokenised prefix can be replaced independently while
            # retaining a known trailing payload byte for byte.
            "editable": program_length <= 64 * 1024,
            "editNote": (
                f"The {len(data) - program_length:,}-byte trailing payload will be "
                "preserved unchanged."
                if len(data) > program_length
                else ""
            ),
        }
    return None


def script_details(data: bytes, path: str, printable_ratio: float) -> dict | None:
    """Recognise a desktop or system configuration file from its own records.

    ``DESKTOP.INF`` is recognised by its records rather than by its name,
    because the same file is called ``NEWDESK.INF`` from TOS 2 onwards and is
    routinely copied about under other names while being edited.
    """
    if not data or b"\0" in data or printable_ratio < 0.70:
        return None
    text = data.decode("latin-1", "replace").replace("\r\n", "\n").replace("\r", "\n")
    meaningful = [line for line in text.splitlines() if line.strip()]
    commands = []
    for line_number, line in enumerate(text.splitlines(), 1):
        match = _SCRIPT_ACTION_RE.match(line)
        if not match:
            continue
        action, arguments = match.groups()
        record = action if action.startswith("#") else action.upper()
        commands.append(
            {
                "line": line_number,
                "action": record,
                "arguments": arguments.strip(),
                "osCommand": not record.startswith("#"),
                "record": DESKTOP_INF_RECORDS.get(record, ""),
            }
        )
    leaf = atari_paths.leaf(path).casefold()
    named_script = leaf in SCRIPT_NAMES or leaf.endswith((".inf", ".cnf", ".bat"))
    enough_commands = commands and len(commands) >= max(1, (len(meaningful) + 1) // 2)
    if not named_script and not enough_commands:
        return None
    return {
        "lineCount": len(text.splitlines()),
        "commandCount": len(commands),
        "commands": commands,
        "namedScript": named_script,
    }


def is_container_file(data: bytes) -> bool:
    """Recognise a disk image or archive stored as an ordinary file.

    Only signatures are used. An MSA opens ``0E 0F``, a Pasti capture ``RSY``,
    a ZIP ``PK``, and an LZH carries ``-lh`` at offset two. A DIM's own
    signature is ``42 45`` at the start of its thirty-two byte header.
    """
    if len(data) < 8:
        return False
    if data[:2] == b"\x0e\x0f":
        return True
    if data[:3] == b"RSY":
        return True
    if data[:2] == b"PK" and data[2:4] in {b"\x03\x04", b"\x05\x06", b"\x07\x08"}:
        return True
    if data[2:5] in {b"-lh", b"-lz"}:
        return True
    if data[:2] == b"\x42\x45":
        return True
    return False


def analyse_content(data: bytes, path: str) -> tuple[str, dict | None, dict | None, float]:
    """Classify complete, bounded file bytes using the editor's content rules."""
    if is_container_file(data):
        return "container", None, None, 0.0
    if is_gemdos_program(data):
        return "program", None, None, 0.0
    basic = basic_details(data)
    printable = sum(value in (9, 10, 13) or 32 <= value < 127 for value in data)
    printable_ratio = printable / len(data) if data else 0.0
    script = None if basic else script_details(data, path, printable_ratio)
    kind = (
        "basic" if basic
        else "script" if script
        else "text" if data and printable_ratio >= 0.82
        else "binary"
    )
    return kind, basic, script, printable_ratio


def metadata_kind(name: str, filetype: int | str | None = None) -> str | None:
    """Return a reliable kind that needs no content read, or None to sniff bytes.

    GEMDOS keeps no type in the directory entry, so the only metadata
    available is the name. TOS itself decides what to do with a file from its
    extension, which is what makes an extension trustworthy here in a way it
    would not be on a filing system that recorded a type: ``.PRG`` does not
    describe the file, it is what makes the desktop run it.

    ``filetype`` is whatever the engine's own classifier already said about
    the name, and is accepted so a caller that has it need not repeat the
    work.
    """
    lowered = str(name or "").casefold()
    leaf = atari_paths.leaf(lowered)
    _, _, extension = leaf.rpartition(".")
    suffix = f".{extension}" if extension and extension != leaf else ""
    hint = str(filetype or "").strip().casefold()
    if hint in {"program", "executable"}:
        return "program"
    if suffix in PROGRAM_EXTENSIONS:
        return "program"
    if suffix in {".bas", ".gfa", ".sto", ".stb", ".bak"} and suffix != ".bak":
        return "basic"
    if leaf in SCRIPT_NAMES or suffix in SCRIPT_EXTENSIONS:
        return "script"
    if suffix in CONTAINER_EXTENSIONS:
        return "container"
    if (
        suffix in {".txt", ".doc", ".me", ".1st", ".md", ".asc", ".diz"}
        or leaf in {"readme", "read.me", "read_me", "license", "copying", "install"}
    ):
        return "text"
    return None


__all__ = [
    "BATCH_KEYWORDS",
    "CONTAINER_EXTENSIONS",
    "DESKTOP_INF_RECORDS",
    "GEMDOS_EXECUTABLE_MAGIC",
    "LISTING_SNIFF_LIMIT",
    "MINT_CNF_KEYWORDS",
    "PROGRAM_EXTENSIONS",
    "SCRIPT_EXTENSIONS",
    "SCRIPT_NAMES",
    "analyse_content",
    "basic_details",
    "format_basic_listing",
    "is_container_file",
    "is_gemdos_program",
    "metadata_kind",
    "script_details",
]
