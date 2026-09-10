"""Turning a saved Atari ST BASIC program back into readable lines.

The ST had three BASICs and only one of them saved plain text. A GFA BASIC
``.GFA`` holds the interpreter's own token stream, a STOS ``.BAS`` holds
another, and only Atari's ST BASIC wrote the listing out as characters.
Reading any of them therefore means running a token table backwards, which is
work the ``atarinut.basic`` package owns. This module is the single place the
workbench asks it to do that, so a listing shown in the file inspector, the
editor and a report all come from the same decode.

Which BASIC a file is comes from its bytes, never from its name, because a
program recovered from a floppy may have any extension or none. Anything that
is not one of the three returns ``None``, rather than a list of lines
assembled out of coincidence.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BasicLine:
    """One line of a saved BASIC program.

    ``number`` is the printed line number for a numbered dialect. GFA BASIC
    has no line numbers, so there it is the line's position in the program,
    counting from zero, and ``depth`` carries the block indentation instead.
    """

    number: int
    body: bytes
    text: str
    depth: int = 0


@dataclass(frozen=True)
class BasicProgram:
    """A decoded program: its dialect, its lines and whether it can be saved."""

    dialect: str
    dialect_id: str
    writable: bool
    line_numbers: bool
    lines: list
    program_length: int
    reason: str = ""


def decode_program(program: bytes) -> BasicProgram | None:
    """Decode a saved BASIC program, whichever of the three dialects it is."""
    try:
        from atarinut.basic import Verdict, detect, scan_program
    except ImportError:  # pragma: no cover - the tokeniser ships with the app
        return None
    detection = detect(program)
    if detection.verdict not in {Verdict.BASIC, Verdict.BASIC_TRAILING} or detection.dialect is None:
        return None
    dialect = detection.dialect
    length = int(detection.program_length or len(program))
    try:
        scanned = list(scan_program(program[:length], dialect=dialect))
    except Exception:
        return None
    if not scanned:
        return None
    # A tokenised dialect's spans are byte offsets into the file. A text
    # dialect's are offsets into the decoded listing, whose line endings the
    # decode has already normalised, so the line's own text is the body.
    lines = [
        BasicLine(
            number=int(line.line_number),
            body=program[line.start : line.end] if dialect.tokenised else line.text.encode("latin-1", "replace"),
            text=line.text,
            depth=int(line.depth),
        )
        for line in scanned
    ]
    return BasicProgram(
        dialect=dialect.name,
        dialect_id=dialect.identifier,
        writable=bool(dialect.writable),
        line_numbers=bool(dialect.line_numbers),
        lines=lines,
        program_length=length,
        reason=detection.reason,
    )


def decode_basic(program: bytes) -> list[BasicLine] | None:
    """The lines of a saved BASIC program, or ``None`` if it is not one."""
    decoded = decode_program(program)
    return decoded.lines if decoded else None


__all__ = ["BasicLine", "BasicProgram", "decode_basic", "decode_program"]
