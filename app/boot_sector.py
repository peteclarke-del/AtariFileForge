"""Reading a GEMDOS volume out of raw image bytes, and the shell text in it.

Two small jobs live here, and both exist because mounting a volume through
the session machinery is more work than the question deserves. A catalogue
scan wants to know what is on several hundred images; an installed-software
check wants to know what one ``.INF`` or ``.BAT`` will do. Both are answered
from a buffer of bytes that is already in hand.

Nothing here rewrites a program. TOS loads a GEMDOS executable through its
own relocation table and resolves paths at run time from the drive the
program was started from, so there is no loader to patch and no device name
to substitute: a program copied from a floppy to a partition finds its files
because ``\\`` means the current drive either way.
"""

from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: The stack sizes a batch file or desk-accessory note may ask for. Anything
#: outside this range is a transcription error rather than a deliberate
#: choice.
MIN_STACK = 1024
MAX_STACK = 262144

#: ``STACK 16384`` on a line of its own, as an installer note writes it.
STACK_SETTING = re.compile(r"(?im)^\s*STACK\s+(\d+)\s*$")

#: The program a batch file or ``DESKTOP.INF`` line actually starts.
EXECUTE_TARGET = re.compile(r"(?im)^\s*(?:EXEC|RUN|CALL)\s+(\"[^\"]+\"|\S+)")

#: Retained under their previous names so existing callers stay stable.
_STACK_SETTING = STACK_SETTING
_EXECUTE_TARGET = EXECUTE_TARGET


@dataclass(frozen=True)
class CatalogueFile:
    """One entry found by walking a volume's directories."""

    directory: str
    name: str
    length: int
    attributes: int = 0

    @property
    def path(self) -> str:
        return f"{self.directory}\\{self.name}" if self.directory else self.name


def looks_like_text_script(data: bytes) -> bool:
    """Accept a plain-text GEMDOS batch or configuration file.

    A ``DESKTOP.INF``, a ``MINT.CNF`` and a ``.BAT`` are all ordinary text,
    and none of them is required to end with a newline, so the test is the
    proportion of printable bytes rather than a terminator.
    """
    if not data or b"\0" in data[:512]:
        return False
    printable = sum(1 for byte in data[:512] if 9 <= byte <= 13 or 32 <= byte <= 126)
    return printable / max(1, len(data[:512])) > 0.9


#: Retained under its previous name so existing callers stay stable.
_looks_like_atari_script = looks_like_text_script


def gemdos_catalogue_files(data: bytes) -> list[CatalogueFile]:
    """List every file on a FAT volume held in memory, directories included.

    The bytes are staged in a temporary file because the engine addresses a
    volume through sector reads on a path. That is cheap next to the walk
    itself, and it keeps one implementation of FAT traversal in the engine
    rather than a second one here.
    """
    if not data:
        return []
    try:
        from atarinut.filesystem import create_filesystem, reader_for
    except ImportError:  # pragma: no cover - packaging failure
        return []
    with tempfile.TemporaryDirectory(prefix="atari-catalogue-") as folder:
        image = Path(folder) / "volume.st"
        image.write_bytes(data)
        try:
            reader = reader_for(image, writable=False)
        except Exception:
            return []
        try:
            mount = create_filesystem("gemdos").open(reader)
            found: list[CatalogueFile] = []
            pending = [""]
            while pending:
                directory = pending.pop()
                for entry in mount.iter_entries(directory):
                    if entry.is_dir:
                        pending.append(str(entry.path))
                        continue
                    found.append(
                        CatalogueFile(
                            directory=directory,
                            name=str(entry.name),
                            length=int(entry.length or 0),
                            attributes=int(entry.attributes or 0),
                        )
                    )
            return found
        except Exception:
            return []
        finally:
            reader.close()


def read_gemdos_file(data: bytes, entry: CatalogueFile) -> bytes:
    """Read one catalogued file's contents out of the same image bytes."""
    if not data:
        return b""
    try:
        from atarinut.filesystem import create_filesystem, reader_for
    except ImportError:  # pragma: no cover - packaging failure
        return b""
    with tempfile.TemporaryDirectory(prefix="atari-catalogue-") as folder:
        image = Path(folder) / "volume.st"
        image.write_bytes(data)
        try:
            reader = reader_for(image, writable=False)
        except Exception:
            return b""
        try:
            return create_filesystem("gemdos").open(reader).read_bytes(entry.path)
        except Exception:
            return b""
        finally:
            reader.close()


__all__ = [
    "EXECUTE_TARGET",
    "MAX_STACK",
    "MIN_STACK",
    "STACK_SETTING",
    "CatalogueFile",
    "gemdos_catalogue_files",
    "looks_like_text_script",
    "read_gemdos_file",
]
