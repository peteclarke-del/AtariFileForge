"""Read-only reports over an open Atari image.

Everything here answers a question about an image without changing a byte of
it: what the catalogue holds, which files are identical, whether TOS will
actually boot and run what is on the disk, and what a proposed cross-format
copy would alter before anything is copied.

The Atari facts these reports are built from are all recorded rather than
guessed. A program is a program because its first word is ``0x601A`` and its
declared sections fit inside the file. A floppy is bootable because the 256
big-endian words of its boot sector sum to ``0x1234``. The AUTO folder runs in
directory order because that is the order TOS reads the entries in. Where a
fact cannot be established the report says so instead of inventing one.

Nothing in this module imports the disk service: it takes a service object and
calls a small, documented set of methods on it, so the reports can be exercised
against a stub built in a test.
"""

from __future__ import annotations

import csv
import io
import re
import struct
from collections import defaultdict, deque
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from atarinut.file.filetypes import EXECUTABLE_EXTENSIONS, split_extension
from atarinut.filesystem.gemdos import tos_limit_notes

from . import atari_paths
from . import progress as progress_module
from .basic_listing import decode_basic
from .checksum import sha256_path
from .errors import DiskError
from .filename_policy import target_name_policy

try:  # pragma: no cover - resolved as soon as app.operations imports cleanly
    from .operations import OperationCancelled
except ImportError:  # pragma: no cover - stand-in while the service is ported
    class OperationCancelled(DiskError):
        """An operation was stopped at a safe boundary."""


MAX_INSPECT_BYTES = 1024 * 1024

#: The first word of every GEMDOS program, and the size of the header holding
#: the section lengths that follow it.
GEMDOS_MAGIC = 0x601A
GEMDOS_HEADER_SIZE = 28

#: ``_p_flags`` bits, as the TOS loader reads them.
PF_FASTLOAD = 0x0001
PF_TT_RAM_LOAD = 0x0002
PF_TT_RAM_MALLOC = 0x0004
PF_PRIVATE = 0x0000
PF_MEMORY_MODE = 0x0030
PF_SHARED_TEXT = 0x1000

MEMORY_MODES = {
    0x00: "private",
    0x10: "global",
    0x20: "supervisor-only",
    0x30: "world-readable",
}

#: A boot sector runs only when its 256 big-endian words sum to this value.
BOOT_CHECKSUM_MAGIC = 0x1234

#: Offsets in the Atari boot sector, after the BIOS parameter block.
BS_EXECFLG = 0x1E
BS_LDMODE = 0x20
BS_SSECT = 0x22
BS_SECTCNT = 0x24
BS_LDADDR = 0x26
BS_FATBUF = 0x2A
BS_FNAME = 0x2E

#: FAT dates run from 1 January 1980 to the end of 2107 and no further.
FAT_FIRST_YEAR = 1980
FAT_LAST_YEAR = 2107

#: The folder TOS runs at boot, and the extension it runs from it.
AUTO_FOLDER = "AUTO"
AUTO_EXTENSION = "PRG"

#: The saved desktop files TOS and EmuTOS read from the root of the boot drive.
DESKTOP_FILES = ("DESKTOP.INF", "NEWDESK.INF", "EMUDESK.INF")

#: The ``#`` line types a saved desktop uses to install an application, and
#: what the desktop does with each one.
INSTALLED_APPLICATION_LINES = {
    "G": "GEM program",
    "F": "TOS program",
    "P": "TOS program that takes parameters",
    "Y": "GEM program that takes parameters",
    "D": "document opened by an installed application",
}

#: Finding codes. Every itemised health finding carries one, so the interface,
#: the saved package and a future repair can all refer to the same thing.
AUTO_ORDER = "auto-folder-order"
AUTO_NOT_A_PROGRAM = "auto-folder-not-a-program"
AUTO_IGNORED = "auto-folder-ignored"
DESKTOP_DRIVE = "desktop-drive-assignment"
DESKTOP_APPLICATION = "desktop-installed-application"
PROGRAM_HEADER = "program-header"
PROGRAM_TT_RAM_ON_ST = "program-tt-ram-on-st"
BOOT_EXECUTABLE = "boot-sector-executable"
BOOT_INERT = "boot-sector-inert"
BOOT_LOADS_FILE = "boot-sector-loads-file"
BOOT_LOADS_SECTORS = "boot-sector-loads-sectors"
VOLUME_LABEL_MISSING = "volume-label-missing"
TOS_MOUNT_LIMIT = "tos-mount-limit"
ROOT_DIRECTORY_FULL = "root-directory-full"
NAME_CONFLICT = "name-conflict"
NAME_LOWER_CASE = "lower-case-name"
NAME_TOO_LONG = "name-too-long"
DATESTAMP_OUT_OF_RANGE = "datestamp-out-of-range"
HIDDEN_ATTRIBUTE = "hidden-attribute"
SYSTEM_ATTRIBUTE = "system-attribute"
BYTE_SWAPPED = "byte-swapped-image"

#: Statements in GFA, STOS and ST BASIC that name another file to load. STOS
#: writes ``BLOAD "PIC.PI1",bank`` and GFA writes ``CHAIN "PART2.GFA"``; both
#: end with the name in quotes, which is what the listing text is searched for.
BASIC_COMMAND_RE = re.compile(
    r"\b(CHAIN|MERGE|BLOAD|BSAVE|INLINE|EXEC|RUN|LOAD)\b[^\"'\r\n]{0,32}[\"']([^\"'\r\n]{1,64})[\"']",
    re.IGNORECASE,
)

#: ``OPEN "I",#1,"SCORES.DAT"`` names its file last, after the mode and the
#: channel number, so it needs its own pattern.
BASIC_OPEN_RE = re.compile(
    r"\bOPEN\b[^\r\n]{0,24}?#?\s*\d+\s*,\s*[\"']([^\"'\r\n]{1,64})[\"']",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------
def _join(parent: str, name: str) -> str:
    return atari_paths.join(parent, _plain(name))


def _plain(value: object) -> str:
    """Accept a GEMDOS name or path written with either separator."""
    return str(value or "").replace("\\", atari_paths.SEPARATOR)


def _row_size(row: dict) -> int:
    try:
        return int(row.get("length", row.get("size", 0)) or 0)
    except (TypeError, ValueError):
        return 0


def _is_directory(row: dict) -> bool:
    return str(row.get("type") or "") in {"dir", "directory"}


def _attributes(row: dict) -> str:
    """The six-letter ``rhsvda`` attribute text for one catalogue row."""
    return str(row.get("attributes") or row.get("attr") or "")


def _finding(code: str, title: str, detail: str = "", **extra) -> dict:
    return {"code": code, "title": title, "detail": detail, **extra}


def _capabilities(session) -> dict:
    """The mounted volume's declared limits, whatever the service calls them."""
    for name in ("capabilities", "gemdos_capabilities", "ffs_capabilities"):
        value = getattr(session, name, None)
        if isinstance(value, dict) and value:
            return value
    return {}


def _two_volume(service, session) -> bool:
    probe = getattr(service, "is_two_volume_image", None)
    return bool(probe(session)) if callable(probe) else False


def _sides(service, session) -> list[int | None]:
    return [0, 2] if _two_volume(service, session) else [None]


def _read_bytes(service, session, path: str, side: int | None, limit: int) -> bytes:
    """Read the start of one file without leaving an export behind."""
    reader = getattr(service, "read_file", None)
    if callable(reader):
        return bytes(reader(session, path, side))[:limit]
    exported = service.export_file(session, path, side)
    try:
        with exported.open("rb") as handle:
            return handle.read(limit)
    finally:
        exported.unlink(missing_ok=True)


def _walk(
    service,
    session,
    side: int | None = None,
    progress=None,
):
    """Yield every path and row below the volume root, breadth first."""
    pending = deque([""])
    visited = set()
    count = 0
    while pending:
        parent = pending.popleft()
        if parent.casefold() in visited:
            continue
        visited.add(parent.casefold())
        if progress:
            progress(f"Reading directory {atari_paths.display(parent)}", count, None)
        listing = service.list_directory(session, parent, side)
        for row in listing["entries"]:
            path = _join(parent, str(row.get("name") or "UNTITLED"))
            yield path, row
            count += 1
            if count > 100_000:
                raise DiskError("The filesystem walk exceeded the 100,000-object safety limit.")
            if _is_directory(row):
                pending.append(path)


# ---------------------------------------------------------------------------
# GEMDOS programs
# ---------------------------------------------------------------------------
def describe_program(data: bytes, file_size: int | None = None) -> dict | None:
    """Decode a GEMDOS program header, or return ``None`` for anything else.

    The header is 28 bytes: the ``0x601A`` branch, big-endian text, data, BSS
    and symbol-table lengths, a reserved long, the ``_p_flags`` long and the
    absolute-relocation word. A file whose declared sections cannot fit inside
    it is not a program, whatever its first word says, so ``file_size`` is
    given when only the header itself was read.
    """
    if len(data) < GEMDOS_HEADER_SIZE:
        return None
    magic, text, payload, bss, symbols, _reserved, flags, absolute = struct.unpack_from(
        ">HIIIIIIH", data, 0
    )
    if magic != GEMDOS_MAGIC:
        return None
    declared = int(file_size if file_size is not None else len(data))
    if GEMDOS_HEADER_SIZE + text + payload + symbols > max(declared, GEMDOS_HEADER_SIZE):
        return None
    return {
        "magic": magic,
        "text": text,
        "data": payload,
        "bss": bss,
        "symbols": symbols,
        "flags": flags,
        "flagsHex": f"{flags:08X}",
        "absolute": bool(absolute),
        "fastLoad": bool(flags & PF_FASTLOAD),
        "ttRamLoad": bool(flags & PF_TT_RAM_LOAD),
        "ttRamMalloc": bool(flags & PF_TT_RAM_MALLOC),
        "sharedText": bool(flags & PF_SHARED_TEXT),
        "memoryMode": MEMORY_MODES.get(flags & PF_MEMORY_MODE, "private"),
    }


def _program_detail(program: dict) -> str:
    parts = [
        f"text {program['text']:,}",
        f"data {program['data']:,}",
        f"bss {program['bss']:,} bytes",
        f"_p_flags &{program['flagsHex']}",
    ]
    named = [
        name
        for name, present in (
            ("fast-load", program["fastLoad"]),
            ("loads into TT RAM", program["ttRamLoad"]),
            ("allocates TT RAM", program["ttRamMalloc"]),
            ("shared text", program["sharedText"]),
        )
        if present
    ]
    parts.append(", ".join(named) if named else "no optional loader flags")
    parts.append(f"memory {program['memoryMode']}")
    return "; ".join(parts)


def program_findings(programs: list[tuple[str, dict]], machine: str = "") -> list[dict]:
    """Describe each recognised program, and flag TT RAM on a 68000 machine."""
    findings = []
    st_class = str(machine or "").strip().lower() in {"st", "megast", "ste", "megaste"}
    for path, program in programs:
        findings.append(_finding(
            PROGRAM_HEADER,
            atari_paths.display(path),
            _program_detail(program),
            path=path,
            program=program,
        ))
        if st_class and (program["ttRamLoad"] or program["ttRamMalloc"]):
            findings.append(_finding(
                PROGRAM_TT_RAM_ON_ST,
                atari_paths.display(path),
                "The program asks the loader for TT RAM, which a 68000 machine "
                "does not have. It will run from ST RAM, and a program that "
                "depends on the extra memory will run out of it.",
                path=path,
            ))
    return findings


# ---------------------------------------------------------------------------
# The boot sector
# ---------------------------------------------------------------------------
def _word_sum(sector: bytes) -> int:
    total = 0
    for offset in range(0, min(len(sector), 512), 2):
        total += int.from_bytes(sector[offset : offset + 2], "big")
    return total & 0xFFFF


def describe_boot_sector(sector: bytes) -> dict:
    """Say whether TOS would run this boot sector, and what it would load.

    A bootable Atari floppy keeps a small loader after its BIOS parameter
    block. ``ldmode`` decides how it loads: zero means find the 8.3 name held
    at ``fname`` in the root directory, anything else means read ``sectcnt``
    sectors starting at ``ssect``. Both routes end at ``ldaddr``.
    """
    if len(sector) < 512:
        return {"executable": False, "checksum": None, "loads": "", "reason": "short sector"}
    checksum = _word_sum(sector)
    executable = checksum == BOOT_CHECKSUM_MAGIC
    # The BIOS parameter block is Intel-order because it is a DOS structure,
    # but everything after it is read by 68000 code as native words.
    execflg, ldmode, ssect, sectcnt = struct.unpack_from(">HHHH", sector, BS_EXECFLG)
    load_address, fat_buffer = struct.unpack_from(">II", sector, BS_LDADDR)
    raw_name = sector[BS_FNAME : BS_FNAME + 11]
    base = raw_name[:8].decode("latin-1").strip()
    extension = raw_name[8:].decode("latin-1").strip()
    filename = f"{base}.{extension}" if extension else base
    printable = all(32 <= value < 127 for value in raw_name)
    return {
        "executable": executable,
        "checksum": checksum,
        "checksumHex": f"{checksum:04X}",
        "execflg": execflg,
        "ldmode": ldmode,
        "startSector": ssect,
        "sectorCount": sectcnt,
        "loadAddress": load_address,
        "fatBuffer": fat_buffer,
        "filename": filename if printable else "",
        "loads": (
            f"the file {filename} from the root directory"
            if ldmode == 0 and printable and base
            else f"{sectcnt} sector(s) from sector {ssect}"
            if ldmode
            else "nothing this sector names"
        ),
    }


def boot_findings(sector: bytes | None) -> list[dict]:
    if not sector:
        return []
    boot = describe_boot_sector(sector)
    if not boot["executable"]:
        return [_finding(
            BOOT_INERT,
            "The boot sector is not executable",
            f"Its 256 words sum to &{boot.get('checksumHex', '????')} rather than &1234, "
            "so TOS reads the BIOS parameter block and stops there.",
        )]
    findings = [_finding(
        BOOT_EXECUTABLE,
        "The boot sector is executable",
        f"Its words sum to &1234, so TOS runs it and it loads {boot['loads']}.",
    )]
    if boot["ldmode"] == 0 and boot["filename"]:
        findings.append(_finding(
            BOOT_LOADS_FILE,
            boot["filename"],
            f"Loaded to &{boot['loadAddress']:06X}"
            + (" and started as a program." if boot["execflg"] else "."),
            filename=boot["filename"],
        ))
    elif boot["ldmode"]:
        findings.append(_finding(
            BOOT_LOADS_SECTORS,
            f"{boot['sectorCount']} sector(s) from sector {boot['startSector']}",
            f"Loaded to &{boot['loadAddress']:06X}. The loaded code is not a "
            "catalogued file, so it is not visible in the directory.",
        ))
    return findings


# ---------------------------------------------------------------------------
# The AUTO folder
# ---------------------------------------------------------------------------
def auto_folder_findings(rows: list[dict], programs: dict[str, dict] | None = None) -> list[dict]:
    """Report the AUTO folder in the order TOS runs it.

    ``rows`` are the catalogue rows of the AUTO folder itself, in the order
    the directory holds them, because that order is the run order: TOS reads
    the entries one after another and starts each ``.PRG`` as it finds it.
    ``programs`` maps a name to its decoded header where one was read, so a
    ``.PRG`` that is not a program can be named rather than merely counted.
    """
    headers = {str(key).upper(): value for key, value in (programs or {}).items()}
    findings = []
    position = 0
    for row in rows:
        name = str(row.get("name") or "")
        if _is_directory(row):
            findings.append(_finding(
                AUTO_IGNORED, name, "A folder inside AUTO is not run by TOS.", path=name
            ))
            continue
        _base, extension = split_extension(name)
        if extension != AUTO_EXTENSION:
            findings.append(_finding(
                AUTO_IGNORED,
                name,
                f"TOS runs only .{AUTO_EXTENSION} files from AUTO, so this one is ignored.",
                path=name,
            ))
            continue
        position += 1
        header = headers.get(name.upper())
        if name.upper() in headers and header is None:
            findings.append(_finding(
                AUTO_NOT_A_PROGRAM,
                name,
                "The file has a .PRG extension but no &601A program header. "
                "TOS will try to run it and fail.",
                path=name,
                position=position,
            ))
            continue
        findings.append(_finding(
            AUTO_ORDER,
            f"{position}. {name}",
            "Run at boot, before the desktop appears."
            + (
                f" Header: {_program_detail(header)}."
                if isinstance(header, dict)
                else ""
            ),
            path=name,
            position=position,
        ))
    return findings


# ---------------------------------------------------------------------------
# The saved desktop
# ---------------------------------------------------------------------------
def parse_desktop_inf(text: str) -> dict:
    """Read the drive assignments and installed applications a desktop declares.

    A saved desktop is a line-per-setting text file. ``#M`` places a drive
    icon and carries the drive letter and the label shown under it. ``#G``,
    ``#F``, ``#P`` and ``#Y`` install an application against a filename mask,
    and ``#D`` installs a document type. Each field ends with ``@``.
    """
    drives = []
    applications = []
    for raw in str(text or "").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line.startswith("#") or len(line) < 2:
            continue
        kind = line[1]
        body = line[2:].strip()
        fields = [item.strip() for item in body.split("@")]
        words = fields[0].split() if fields else []
        if kind == "M" and len(words) >= 5:
            drives.append({
                "letter": words[4][:1].upper(),
                "label": " ".join(words[5:]) or (fields[1].strip() if len(fields) > 1 else ""),
            })
            continue
        if kind.upper() in INSTALLED_APPLICATION_LINES and len(words) >= 3:
            applications.append({
                "line": f"#{kind.upper()}",
                "role": INSTALLED_APPLICATION_LINES[kind.upper()],
                "mask": words[-1],
                "name": fields[1].strip() if len(fields) > 1 else "",
            })
    return {"drives": drives, "applications": applications}


def desktop_findings(name: str, text: str) -> list[dict]:
    desktop = parse_desktop_inf(text)
    findings = [
        _finding(
            DESKTOP_DRIVE,
            f"{name}: drive {row['letter']}:",
            f"Shown on the desktop as {row['label'] or 'an unlabelled drive icon'}.",
            letter=row["letter"],
        )
        for row in desktop["drives"]
    ]
    findings.extend(
        _finding(
            DESKTOP_APPLICATION,
            f"{name}: {row['mask']}",
            f"Installed as a {row['role']}"
            + (f", run by {row['name']}." if row["name"] else "."),
            mask=row["mask"],
        )
        for row in desktop["applications"]
    )
    return findings


# ---------------------------------------------------------------------------
# Names, datestamps and attributes
# ---------------------------------------------------------------------------
def _short_name(name: str) -> str:
    base, extension = split_extension(name)
    return f"{base[:8]}.{extension[:3]}" if extension else base[:8]


def name_findings(entries: list[tuple[str, dict]]) -> list[dict]:
    """Report 8.3 conflicts and names TOS would upper-case or truncate."""
    findings = []
    by_directory: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for path, row in entries:
        name = str(row.get("name") or "")
        by_directory[atari_paths.parent(path)][_short_name(name).upper()].append(name)
        if name != name.upper():
            findings.append(_finding(
                NAME_LOWER_CASE,
                atari_paths.display(path),
                f"TOS upper-cases every name, so this is {name.upper()} on the machine.",
                path=path,
            ))
        base, extension = split_extension(name)
        if len(base) > 8 or len(extension) > 3:
            findings.append(_finding(
                NAME_TOO_LONG,
                atari_paths.display(path),
                f"A GEMDOS name holds eight characters and a three-character "
                f"extension, so this becomes {_short_name(name).upper()}.",
                path=path,
            ))
    for directory, groups in sorted(by_directory.items()):
        for short, names in sorted(groups.items()):
            if len(names) > 1:
                findings.append(_finding(
                    NAME_CONFLICT,
                    short,
                    f"{len(names)} entries in {atari_paths.display(directory)} share "
                    f"this 8.3 name: {', '.join(sorted(names))}.",
                    path=directory,
                ))
    return findings


def datestamp_findings(entries: list[tuple[str, dict]]) -> list[dict]:
    """Report datestamps a FAT directory entry cannot hold."""
    findings = []
    for path, row in entries:
        stamp = str(row.get("datestamp") or "")
        if not stamp:
            continue
        try:
            year = datetime.fromisoformat(stamp.replace("Z", "+00:00")).year
        except ValueError:
            findings.append(_finding(
                DATESTAMP_OUT_OF_RANGE,
                atari_paths.display(path),
                f"The datestamp {stamp} could not be read as a date.",
                path=path,
            ))
            continue
        if year < FAT_FIRST_YEAR or year > FAT_LAST_YEAR:
            findings.append(_finding(
                DATESTAMP_OUT_OF_RANGE,
                atari_paths.display(path),
                f"{stamp} is outside {FAT_FIRST_YEAR} to {FAT_LAST_YEAR}, which is "
                "everything a FAT directory entry can record.",
                path=path,
            ))
    return findings


def attribute_findings(entries: list[tuple[str, dict]]) -> list[dict]:
    """Report the hidden and system entries the desktop will not show."""
    findings = []
    for path, row in entries:
        text = _attributes(row)
        if len(text) >= 3 and text[1] == "h":
            findings.append(_finding(
                HIDDEN_ATTRIBUTE,
                atari_paths.display(path),
                f"Attributes {text}: the desktop hides this entry unless "
                "Show hidden files is selected.",
                path=path,
            ))
        if len(text) >= 3 and text[2] == "s":
            findings.append(_finding(
                SYSTEM_ATTRIBUTE,
                atari_paths.display(path),
                f"Attributes {text}: a system entry, which some file selectors omit.",
                path=path,
            ))
    return findings


def capacity_findings(capabilities: dict, root_entries: int, size_bytes: int) -> list[dict]:
    """Report the root-directory ceiling and the TOS releases that can mount it."""
    findings = []
    limit = capabilities.get("directoryEntryLimit")
    if isinstance(limit, int) and limit > 0:
        remaining = limit - root_entries
        findings.append(_finding(
            ROOT_DIRECTORY_FULL,
            f"{root_entries} of {limit} root entries used",
            "The root directory of a GEMDOS volume is a fixed size. "
            + (
                f"{remaining} entries remain."
                if remaining > 0
                else "It is full: nothing more can be created in the root, "
                "however much free space the volume has."
            ),
            used=root_entries,
            limit=limit,
        ))
    for note in tos_limit_notes(int(size_bytes or 0)):
        findings.append(_finding(TOS_MOUNT_LIMIT, "Partition size", note))
    return findings


# ---------------------------------------------------------------------------
# File inspection and BASIC dependencies
# ---------------------------------------------------------------------------
def basic_commands(text: str) -> list[dict]:
    """Every statement in a BASIC listing that names another file."""
    commands = [
        {"action": action.upper(), "target": target.strip()}
        for action, target in BASIC_COMMAND_RE.findall(text)
    ]
    commands.extend(
        {"action": "OPEN", "target": target.strip()}
        for target in BASIC_OPEN_RE.findall(text)
    )
    return [item for item in commands if item["target"]]


def inspect_file(
    service,
    session,
    path: str,
    side: int | None,
    progress=None,
) -> dict:
    report = progress_module.reporter(progress)
    report(f"Reading launcher {path}", 0, None)
    exported = service.export_file(session, path, side)
    try:
        size = exported.stat().st_size
        with exported.open("rb") as source:
            preview = source.read(MAX_INSPECT_BYTES)
        truncated = size > len(preview)
        digest = sha256_path(
            exported,
            (
                lambda current, total: report(
                    f"Checksumming launcher {path}", current, total
                )
            ) if progress else None,
        )
    finally:
        exported.unlink(missing_ok=True)
    basic = decode_basic(preview)
    program = describe_program(preview, size)
    printable = sum(value in (9, 10, 13) or 32 <= value < 127 for value in preview)
    looks_text = bool(preview) and printable / len(preview) >= 0.82
    if basic:
        text = "\n".join(f"{line.number} {line.text}" for line in basic)
        view = "basic"
    elif looks_text and not program:
        text = preview.decode("latin-1", "replace").replace("\r", "\n")
        view = "text"
    else:
        text = ""
        view = "hex"
    hex_lines = []
    for offset in range(0, min(len(preview), 4096), 16):
        chunk = preview[offset : offset + 16]
        hex_lines.append(
            f"{offset:06X}  {' '.join(f'{value:02X}' for value in chunk):<47}  "
            + "".join(chr(value) if 32 <= value < 127 else "." for value in chunk)
        )
    return {
        "path": path,
        "size": size,
        "sha256": digest,
        "view": view,
        "text": text,
        "hex": "\n".join(hex_lines),
        "truncated": truncated,
        "editable": looks_text and not program and not truncated and size <= 64 * 1024,
        "tokenisedBasic": basic is not None,
        "program": program,
        "commands": basic_commands(text),
    }


def dependency_report(
    service,
    session,
    path: str,
    side: int | None,
    progress=None,
) -> dict:
    inspected = inspect_file(service, session, path, side, progress)
    parent = atari_paths.parent(path)
    catalogue = [
        (candidate_path, row)
        for candidate_path, row in _walk(service, session, side, progress)
        if not _is_directory(row)
    ]
    by_path = {candidate_path.casefold(): (candidate_path, row) for candidate_path, row in catalogue}
    by_leaf: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for candidate_path, row in catalogue:
        by_leaf[str(row.get("name") or atari_paths.leaf(candidate_path)).casefold()].append(
            (candidate_path, row)
        )
    dependencies = []
    for command in inspected["commands"]:
        original_target = command["target"].strip()
        cleaned = _plain(original_target)
        target = atari_paths.leaf(cleaned)
        # A name that names its drive, or starts at the root, is not relative
        # to the launcher, so moving the launcher into a folder breaks it.
        rooted = bool(re.match(r"^[A-Za-z]:", original_target)) or cleaned.startswith(
            atari_paths.SEPARATOR
        )
        relative_path = cleaned if rooted else _join(parent, cleaned)
        exact = by_path.get(atari_paths.normalise(relative_path).casefold())
        leaf_candidates = by_leaf.get(target.casefold(), [])
        found = exact or (leaf_candidates[0] if len(leaf_candidates) == 1 else None)
        dependencies.append({
            **command,
            "resolved": bool(found),
            "path": found[0] if found else None,
            "rootRelative": rooted,
            "ambiguous": not exact and len(leaf_candidates) > 1,
            "candidates": [candidate[0] for candidate in leaf_candidates[:20]],
        })
    unsafe = [item for item in dependencies if not item["resolved"] or item["rootRelative"] or item["ambiguous"]]
    return {
        "launcher": path,
        "dependencies": dependencies,
        "safeForSubdirectory": not unsafe,
        "warnings": [
            f"{item['action']} {item['target']} is "
            + (
                "named from the drive root"
                if item["rootRelative"]
                else "ambiguous"
                if item["ambiguous"]
                else "not present in the image"
            )
            for item in unsafe
        ],
        "filesIndexed": len(catalogue),
    }


# ---------------------------------------------------------------------------
# Manifests
# ---------------------------------------------------------------------------
def build_manifest(service, session, progress=None) -> dict:
    if session.kind in {"rom", "tosrom"}:
        records = []
        banks = service.list_rom_banks(session)
        for index, row in enumerate(banks):
            path = f"bank:{row['bank']}"
            if progress:
                progress(f"Checksumming ROM {path}", index, len(banks))
            exported = service.export_file(session, path)
            try:
                digest = sha256_path(
                    exported,
                    (lambda current, total: progress(
                        f"Checksumming ROM {path}", current, total
                    )) if progress else None,
                )
            finally:
                exported.unlink(missing_ok=True)
            records.append({
                "recordType": "rom-bank",
                "path": path,
                "bank": row["bank"],
                "title": row["name"],
                "size": row["length"],
                "romType": row["filetype"],
                "empty": row["empty"],
                "sha256": digest,
            })
        return {"image": service.summary(session), "records": records, "menus": []}

    records = []
    # A partitioned drive is described partition by partition, because a path
    # is only unique inside the volume that holds it: C: and D: may each hold
    # an AUTO\START.PRG and they are different files.
    partitions = _manifest_partitions(service, session)
    for partition, device in partitions:
        if partition is not None:
            service.select_partition(session, partition)
            records.append({
                "recordType": "partition",
                "path": f"{device}:",
                "partition": partition,
                "device": device,
                "title": str(service.summary(session).get("title") or device),
            })
        for side in _sides(service, session):
            for path, row in _walk(service, session, side, progress):
                record = {
                    "recordType": "directory" if _is_directory(row) else "file",
                    "path": path,
                    "side": side,
                    "partition": partition,
                    "size": _row_size(row),
                    "attributes": _attributes(row),
                    "datestamp": row.get("datestamp") or "",
                    "contentKind": row.get("contentKind") or "",
                    "filetype": row.get("filetype") or "",
                }
                if record["recordType"] == "file":
                    try:
                        exported = service.export_file(session, path, side)
                        try:
                            record["sha256"] = sha256_path(
                                exported,
                                (lambda current, total: progress(
                                    f"Checksumming {path}", current, total
                                )) if progress else None,
                            )
                        finally:
                            exported.unlink(missing_ok=True)
                    except OperationCancelled:
                        raise
                    except DiskError as exc:
                        record["error"] = str(exc)
                records.append(record)
    return {"image": service.summary(session), "records": records, "menus": []}


def _manifest_partitions(service, session) -> list[tuple[int | None, str]]:
    """Every partition a manifest should walk, or one unpartitioned volume.

    The session's own partition selection is restored by the caller's normal
    refresh; nothing here leaves it pointing somewhere the user did not choose,
    because a manifest is a read-only report.
    """
    if session.kind != "hd":
        return [(None, "")]
    try:
        partitions = service.list_partitions(session)
    except DiskError:
        return [(None, "")]
    if not partitions:
        return [(None, "")]
    return [
        (
            index,
            str(partition.get("device") or partition.get("name") or chr(ord("C") + index)),
        )
        for index, partition in enumerate(partitions)
    ]


def manifest_csv(manifest: dict) -> str:
    keys = sorted({key for row in manifest["records"] for key in row})
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(manifest["records"])
    return output.getvalue()


def _project_offset(value) -> int | None:
    try:
        text = str(value).strip()
        return int(text[1:], 16) if text.startswith("&") else int(text, 0)
    except (TypeError, ValueError):
        return None


def workspace_metadata_records(service, session) -> list[dict]:
    """Return bounded partition and saved-project records for workspace search."""
    records: list[dict] = []
    if session.kind == "hd":
        try:
            partitions = service.list_partitions(session)
        except DiskError:
            partitions = []
        for index, partition in enumerate(partitions):
            device = str(partition.get("device") or partition.get("name") or "")
            records.append({
                "virtual": True,
                "resultType": "partition",
                "kind": "partition",
                "name": device,
                "path": device,
                "openable": True,
                "partition": index,
                "searchFields": {
                    "device": device,
                    "filing system": partition.get("format"),
                    "partition id": partition.get("id"),
                    "size": partition.get("sizeBytes"),
                    "bootable": partition.get("bootable"),
                },
            })
    if session.kind in {"rom", "tosrom"}:
        project = session.rom_project or {}
        identity = project.get("identity") or {}
        records.append({
            "virtual": True, "resultType": "rom-project", "kind": "rom-project",
            "name": str(identity.get("title") or session.name), "path": "ROM project",
            "openable": False, "romProject": True,
            "searchFields": {
                "title": identity.get("title"), "version": identity.get("version"),
                "publisher": identity.get("publisher"), "platform": identity.get("platform"),
                "identity notes": identity.get("notes"), "project notes": project.get("notes"),
                "hardware": project.get("hardware"),
            },
        })
        for address, label in dict(project.get("symbols") or {}).items():
            records.append({
                "virtual": True, "resultType": "rom-symbol", "kind": "rom-project",
                "name": str(label), "path": "ROM project symbols", "openable": False,
                "romProject": True, "romTab": "code", "address": address,
                "searchFields": {"symbol": label, "address": address},
            })
        for region in project.get("regions") or []:
            records.append({
                "virtual": True, "resultType": "rom-region", "kind": "rom-project",
                "name": str(region.get("name") or "ROM region"), "path": "ROM project regions",
                "openable": False, "romProject": True, "romTab": "code",
                "address": region.get("start"),
                "searchFields": {
                    "region": region.get("name"), "start": region.get("start"),
                    "end": region.get("end"),
                },
            })
    for key, project in list((session.editor_projects or {}).items())[:4096]:
        parts = str(key).split("|", 1)
        if len(parts) != 2:
            continue
        side_text, path = parts
        context = {
            "path": path,
            **({"side": int(side_text)} if side_text != "-" else {}),
        }
        common = {
            "virtual": True, "kind": "project", "path": path,
            "fileName": atari_paths.leaf(path) or path, "openable": True, **context,
        }
        if project.get("notes"):
            records.append({
                **common, "resultType": "project-notes",
                "name": atari_paths.leaf(path) or path,
                "searchFields": {"project notes": project.get("notes")},
            })
        for offset, label in dict(project.get("symbols") or {}).items():
            parsed_offset = _project_offset(offset)
            if parsed_offset is None:
                continue
            records.append({
                **common, "resultType": "project-symbol", "name": str(label),
                "offset": parsed_offset, "searchFields": {"symbol": label, "offset": offset},
            })
        for offset, annotation in dict(project.get("comments") or {}).items():
            parsed_offset = _project_offset(offset)
            if parsed_offset is None:
                continue
            records.append({
                **common, "resultType": "project-comment",
                "name": atari_paths.leaf(path) or path,
                "offset": parsed_offset,
                "searchFields": {"annotation": annotation, "offset": offset},
            })
    return records[:20_000]


def duplicate_report(service, session, progress=None) -> dict:
    manifest = build_manifest(service, session, progress)
    exact: dict[str, list[dict]] = defaultdict(list)
    variants: dict[str, list[dict]] = defaultdict(list)
    for row in manifest["records"]:
        if row.get("sha256"):
            exact[str(row["sha256"])].append(row)
        # A GEMDOS 8.3 name has no room for a version, so releases distinguish
        # themselves in the base name: GAME1.PRG beside GAME2.PRG. Stripping a
        # trailing disk, side or revision marker groups those together.
        leaf = atari_paths.leaf(str(row.get("path") or ""))
        base, _extension = split_extension(leaf)
        key = re.sub(r"[^A-Z0-9]", "", re.sub(r"(?:DISK|DISC|SIDE|REV|V)?[0-9]+$", "", base.upper()))
        if key:
            variants[key].append(row)
    return {
        "exact": [items for items in exact.values() if len(items) > 1],
        "variants": [items for items in variants.values() if len(items) > 1],
    }


# ---------------------------------------------------------------------------
# The health report
# ---------------------------------------------------------------------------
def _boot_sector(service, session) -> bytes | None:
    """The volume's first sector, however the service exposes it."""
    for name in ("boot_sector", "read_boot_sector"):
        reader = getattr(service, name, None)
        if callable(reader):
            try:
                data = reader(session)
            except DiskError:
                return None
            return bytes(data) if data else None
    path = getattr(session, "path", None)
    if session.kind == "gemdos" and isinstance(path, Path) and path.is_file():
        with path.open("rb") as image:
            return image.read(512)
    return None


def _volume_size(summary: dict, session) -> int:
    """The byte count the TOS partition limits are measured against."""
    for value in (summary.get("sizeBytes"), summary.get("size")):
        if isinstance(value, int) and value > 0:
            return value
    path = getattr(session, "path", None)
    if isinstance(path, Path) and path.is_file():
        return path.stat().st_size
    return 0


def _collect_catalogue(service, session, progress=None) -> list[tuple[str, dict]]:
    return [
        (path, row)
        for side in _sides(service, session)
        for path, row in _walk(service, session, side, progress)
    ]


def _gather_programs(service, session, entries, limit=64) -> tuple[list, dict]:
    """Read the header of every executable, and of every .PRG inside AUTO."""
    programs: list[tuple[str, dict]] = []
    auto_headers: dict[str, dict | None] = {}
    inspected = 0
    for path, row in entries:
        if _is_directory(row):
            continue
        name = str(row.get("name") or "")
        _base, extension = split_extension(name)
        in_auto = atari_paths.split(path)[:1] == [AUTO_FOLDER]
        if extension not in EXECUTABLE_EXTENSIONS and not (in_auto and extension == AUTO_EXTENSION):
            continue
        if inspected >= limit and not in_auto:
            continue
        inspected += 1
        try:
            header = describe_program(
                _read_bytes(service, session, path, None, GEMDOS_HEADER_SIZE),
                _row_size(row),
            )
        except OperationCancelled:
            raise
        except (DiskError, OSError):
            continue
        if in_auto:
            auto_headers[name.upper()] = header
        if header:
            programs.append((path, header))
    return programs, auto_headers


def _score(checks: list[dict], repairable: list[dict], progress=None) -> dict:
    """Finish a health report: one status word over every check gathered."""
    score = "healthy" if all(item["status"] == "pass" for item in checks) else (
        "attention" if not any(item["status"] == "fail" for item in checks) else "failed"
    )
    if progress:
        progress("Health check complete", 1, 1)
    return {"status": score, "checks": checks, "repairable": repairable}


def health_report(service, session, progress=None) -> dict:
    checks: list[dict] = []
    repairable: list[dict] = []

    def check(category, name, function):
        try:
            detail = function()
            checks.append({"category": category, "name": name, "status": "pass", "detail": str(detail)})
        except OperationCancelled:
            raise
        except Exception as exc:
            checks.append({"category": category, "name": name, "status": "fail", "detail": str(exc)})

    def record(category, name, status, detail, findings=None):
        checks.append({
            "category": category, "name": name, "status": status,
            "detail": detail, "findings": findings or [],
        })

    capabilities = _capabilities(session)
    summary = {}
    try:
        summary = service.summary(session) or {}
    except (AttributeError, DiskError):
        summary = {}

    profile = session.hardware_profile or {}
    if profile:
        additions = ", ".join(profile.get("addons") or []) or "stock machine"
        record(
            "structural",
            "Hardware profile",
            "pass",
            f"{profile.get('name', 'Custom')} · {profile.get('machine', 'Atari ST')} · {additions}",
        )
    checks.extend(
        {"category": "structural", "name": "Compatibility warning", "status": "warn", "detail": warning}
        for warning in getattr(session, "warnings", []) or []
    )

    if session.kind in {"rom", "tosrom"}:
        if progress:
            progress("Inspecting ROM banks and headers", 0, None)
        rows = service.list_rom_banks(session)
        check("structural", "ROM byte structure", lambda: service.validate(session))
        record(
            "structural",
            "Recognised TOS ROM headers",
            "pass" if any(row.get("header") for row in rows) else "warn",
            f"{sum(bool(row.get('header')) for row in rows)} of {len(rows)} bank(s) "
            "carry a recognised TOS or EmuTOS header.",
        )
        duplicate_groups = [
            [row["bank"], *row.get("matchingBanks", [])]
            for row in rows
            if row.get("matchingBanks") and row["bank"] < min(row["matchingBanks"])
        ]
        record(
            "structural",
            "Bank fingerprints",
            "warn" if duplicate_groups else "pass",
            "; ".join("Identical banks " + ", ".join(map(str, group)) for group in duplicate_groups)
            if duplicate_groups else "Every bank has a distinct SHA-256 fingerprint.",
        )
        header_warnings = [
            f"Bank {row['bank']}: {warning}"
            for row in rows for warning in row.get("warnings", [])
        ]
        record(
            "structural",
            "Header flag consistency",
            "warn" if header_warnings else "pass",
            f"{len(header_warnings)} header or vector disagreement(s)"
            if header_warnings else "Recognised header flags agree with their entry vectors.",
            header_warnings,
        )
        partial = session.path.stat().st_size % session.rom_bank_size
        record(
            "capacity",
            "Bank boundaries",
            "warn" if partial else "pass",
            f"The final bank contains {partial:,} bytes."
            if partial else f"Every bank is {session.rom_bank_size:,} bytes.",
        )
    else:
        if progress:
            progress("Validating the filesystem structure", 0, None)
        check("structural", "Filesystem structure", lambda: service.validate(session))
        if session.kind == "hd":
            if progress:
                progress("Reading the partition table", 0, None)
            partitions = service.list_partitions(session)
            scheme = str(summary.get("scheme") or summary.get("partitionScheme") or "AHDI")
            record(
                "structural",
                "Partition table",
                "pass" if partitions else "warn",
                f"{len(partitions)} partition(s) declared under the {scheme.upper()} scheme."
                if partitions else "No partition could be read from the drive.",
            )
            limit_findings = []
            for index, partition in enumerate(partitions):
                device = str(partition.get("device") or chr(ord("C") + index))
                for note in tos_limit_notes(int(partition.get("sizeBytes") or 0)):
                    limit_findings.append(_finding(TOS_MOUNT_LIMIT, f"{device}:", note))
            record(
                "capacity",
                "TOS partition limits",
                "warn" if limit_findings else "pass",
                f"{len(limit_findings)} partition size(s) exceed a TOS release limit."
                if limit_findings else "Every partition is within the limits of the TOS release that mounts it.",
                limit_findings,
            )
            if summary.get("byteSwapped"):
                record(
                    "structural",
                    "Byte order",
                    "warn",
                    "The drive image is byte-swapped. It is read transparently here, "
                    "but an ACSI device needs the un-swapped bytes.",
                    [_finding(BYTE_SWAPPED, session.name, "Written in IDE word order.")],
                )
        # A partitioned drive that has no partition selected is several
        # volumes, not one, so the volume checks below wait until the operator
        # opens one of them rather than reporting a failure against the drive.
        if session.kind == "hd" and getattr(session, "partition", None) is None:
            record(
                "structural",
                "Volume checks",
                "pass",
                "Open a partition to check its catalogue, names, boot sector and AUTO folder.",
            )
            return _score(checks, repairable, progress)
        if progress:
            progress("Cataloguing the volume", 0, None)
        entries: list[tuple[str, dict]] = []
        try:
            entries = _collect_catalogue(service, session, progress)
        except OperationCancelled:
            raise
        except DiskError as exc:
            record("structural", "Filesystem catalogue", "fail", str(exc))
        else:
            record(
                "structural",
                "Filesystem catalogue",
                "pass",
                f"{len(entries)} object(s) read from the volume.",
            )

        label = str(summary.get("label") or capabilities.get("label") or "")
        record(
            "structural",
            "Volume label",
            "pass" if label else "warn",
            f"The volume is labelled {label}."
            if label
            else "The volume has no label, so the desktop shows only its drive letter.",
            [] if label else [_finding(VOLUME_LABEL_MISSING, session.name, "No volume label entry was found.")],
        )

        fat = str(capabilities.get("format") or summary.get("format") or "")
        clusters = capabilities.get("clusters", summary.get("clusters"))
        record(
            "structural",
            "GEMDOS format",
            "pass" if fat else "warn",
            (
                f"{fat}"
                + (f" with {int(clusters):,} data clusters" if isinstance(clusters, int) else "")
                + "."
            ) if fat else "The filing system could not be identified from the boot sector.",
        )

        boot = boot_findings(_boot_sector(service, session))
        if boot:
            record(
                "launch",
                "Boot sector",
                "pass",
                boot[0]["detail"],
                boot[1:],
            )

        root_entries = sum(1 for path, _row in entries if not atari_paths.parent(path))
        capacity = capacity_findings(capabilities, root_entries, _volume_size(summary, session))
        if capacity:
            record(
                "capacity",
                "Directory and partition capacity",
                "warn" if any(item["code"] == TOS_MOUNT_LIMIT for item in capacity) else "pass",
                f"{len(capacity)} capacity note(s).",
                capacity,
            )

        naming = [
            *name_findings(entries),
            *datestamp_findings(entries),
            *attribute_findings(entries),
        ]
        record(
            "naming",
            "Names, datestamps and attributes",
            "warn" if naming else "pass",
            f"{len(naming)} entr(y/ies) would be changed or hidden by TOS."
            if naming else "Every name is a clean 8.3 name with a datestamp TOS can hold.",
            naming,
        )

        if progress:
            progress("Reading program headers", 0, None)
        try:
            programs, auto_headers = _gather_programs(service, session, entries)
        except OperationCancelled:
            raise
        except DiskError:
            programs, auto_headers = [], {}
        machine = str((session.hardware_profile or {}).get("machine") or "")
        launch = program_findings(programs, machine)
        auto_rows = [
            row for path, row in entries
            if atari_paths.split(path)[:1] == [AUTO_FOLDER] and len(atari_paths.split(path)) == 2
        ]
        auto = auto_folder_findings(auto_rows, auto_headers)
        record(
            "launch",
            "AUTO folder",
            "warn" if any(item["code"] != AUTO_ORDER for item in auto) else "pass",
            f"{sum(1 for item in auto if item['code'] == AUTO_ORDER)} program(s) run at boot, "
            "in the order the directory holds them."
            if auto else "The volume has no AUTO folder, so TOS runs nothing before the desktop.",
            auto,
        )
        desktop = []
        for path, row in entries:
            name = str(row.get("name") or "").upper()
            if name in DESKTOP_FILES and not atari_paths.parent(path):
                try:
                    text = _read_bytes(service, session, path, None, 64 * 1024).decode(
                        "latin-1", "replace"
                    )
                except OperationCancelled:
                    raise
                except (DiskError, OSError):
                    continue
                desktop.extend(desktop_findings(name, text))
        record(
            "launch",
            "Saved desktop",
            "pass" if desktop else "warn",
            f"{len(desktop)} drive assignment(s) and installed application(s) declared."
            if desktop
            else "No DESKTOP.INF, NEWDESK.INF or EMUDESK.INF is present in the root, so the "
            "desktop opens with its built-in defaults.",
            desktop,
        )
        record(
            "launch",
            "Programs",
            "warn" if any(item["code"] == PROGRAM_TT_RAM_ON_ST for item in launch) else "pass",
            f"{len(programs)} recognised GEMDOS program(s)."
            if programs else "No GEMDOS program header was found on the volume.",
            launch,
        )

    return _score(checks, repairable, progress)


# ---------------------------------------------------------------------------
# The cross-format compatibility report
# ---------------------------------------------------------------------------
COMPATIBILITY_REPORT_FORMAT = "atari-file-forge-compatibility-report"
COMPATIBILITY_REPORT_VERSION = 1

#: Targets that keep no GEMDOS attribute byte, so hidden and system entries
#: arrive as ordinary files.
ATTRIBUTE_FREE_TARGETS = {"host", "deployment", "gemdos-folder"}


def accept_compatibility_report(service, session, document: dict) -> dict:
    """Regenerate and retain one reviewed report for the next saved package."""
    if not isinstance(document, dict):
        raise DiskError("The compatibility report is not a JSON object.")
    if (
        document.get("format") != COMPATIBILITY_REPORT_FORMAT
        or document.get("version") != COMPATIBILITY_REPORT_VERSION
    ):
        raise DiskError(
            f"Only {COMPATIBILITY_REPORT_FORMAT} version "
            f"{COMPATIBILITY_REPORT_VERSION} reports can be retained."
        )
    if not document.get("dryRun") or not isinstance(document.get("changes"), list):
        raise DiskError("Only a complete dry-run compatibility report can be retained.")
    if not isinstance(document.get("source"), dict) or not isinstance(document.get("target"), dict):
        raise DiskError("The compatibility report source or target is incomplete.")
    target = document.get("target") or {}
    if target.get("image") != session.name or target.get("kind") != session.kind:
        raise DiskError("The compatibility report belongs to a different image or filesystem.")
    report = preflight_report(
        service,
        session,
        {
            "operation": document.get("operation"),
            "changes": deepcopy(document["changes"]),
            "sourceKind": document["source"].get("kind"),
            "targetKind": target.get("kind"),
        },
    )
    if not report["canProceed"]:
        raise DiskError("Resolve the report's blocking findings before accepting it.")
    report["acceptedAt"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["acceptedImage"] = {
        "name": session.name,
        "kind": session.kind,
        "size": session.path.stat().st_size,
        "modifiedNs": session.path.stat().st_mtime_ns,
    }
    session.compatibility_reports = [*session.compatibility_reports[-9:], report]
    return report


def compatibility_report_markdown(report: dict) -> str:
    lines = [
        "# Atari File Forge compatibility report",
        "",
        f"Operation: {report['operation']}",
        f"Source: {report['source']['kind']}",
        f"Target: {report['target']['kind']}",
        f"Can proceed: {'yes' if report['canProceed'] else 'no'}",
        "",
        "## Items",
        "",
    ]
    for item in report["items"]:
        lines.append(f"### {item['sourceName'] or 'Unnamed item'}")
        lines.append("")
        lines.append(f"- Target name: `{item['targetName']}`")
        lines.append(f"- Type: {item['type']}")
        lines.append(f"- Attributes: `{item['metadata']['attributes'] or 'not supplied'}`")
        lines.append(f"- Datestamp: {item['metadata']['datestamp'] or 'not supplied'}")
        for conversion in item["conversions"]:
            lines.append(f"- Conversion: {conversion}")
        for loss in item["losses"]:
            lines.append(f"- Metadata loss: {loss}")
        lines.append("")
    lines.extend(["## Findings", ""])
    lines.extend(
        f"- {finding['severity'].upper()}: {finding['message']}"
        for finding in report["issues"]
    )
    if not report["issues"]:
        lines.append("- No compatibility findings.")
    return "\n".join(lines) + "\n"


def _datestamp_year(value: object) -> int | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).year
    except (TypeError, ValueError):
        return None


def preflight_report(service, session, payload: dict) -> dict:
    operation = str(payload.get("operation") or "review")
    changes = list(payload.get("changes") or [])
    issues = []
    items = []
    seen = set()
    target_kind = str(payload.get("targetKind") or session.kind).strip().lower()
    source_kind = str(payload.get("sourceKind") or session.kind).strip().lower()
    capabilities = _capabilities(session)
    for offset, change in enumerate(changes):
        name = str(change.get("name") or change.get("destination") or "")
        leaf = name if change.get("nameIsLeaf") else atari_paths.leaf(name)
        item_type = str(change.get("type") or "file").strip().lower()
        policy = target_name_policy(
            target_kind,
            item_type=item_type,
            name_limit=capabilities.get("nameLimit"),
        )
        validate_name = not change.get("existingDestination")
        normal = policy.normalise(leaf) if validate_name else leaf
        conversions = []
        losses = []
        if validate_name and normal != leaf:
            issues.append({"severity": "warning", "item": offset, "message": f"{leaf} becomes {normal or 'FILE'}"})
            conversions.append(f"Filename {leaf} becomes {normal or 'FILE'}")
        # What TOS does with a file is decided by its extension alone, so a
        # conversion that changes the extension changes how it is launched.
        _leaf_base, leaf_extension = split_extension(leaf)
        _normal_base, normal_extension = split_extension(normal)
        if validate_name and leaf_extension and normal_extension != leaf_extension:
            conversions.append(
                f"The .{leaf_extension} extension becomes "
                f".{normal_extension or 'none'}, so the desktop no longer treats it as "
                + (EXECUTABLE_EXTENSIONS.get(leaf_extension) or "the same kind of file")
                + "."
            )
        if change.get("nameIsLeaf"):
            parent = str(change.get("parent") or change.get("targetParent") or "")
        else:
            parent = atari_paths.parent(name)
        key = (parent.casefold(), normal.casefold())
        if validate_name and key in seen and not change.get("allowDuplicateName"):
            issues.append({"severity": "error", "item": offset, "message": f"{normal} clashes after target-name conversion"})
        seen.add(key)
        attributes = str(change.get("attributes") or change.get("attr") or change.get("access") or "")
        year = _datestamp_year(change.get("datestamp"))
        if year is not None and (year < FAT_FIRST_YEAR or year > FAT_LAST_YEAR):
            losses.append(
                f"The datestamp is {year}, which a FAT directory entry cannot hold. "
                f"It is clamped into {FAT_FIRST_YEAR} to {FAT_LAST_YEAR}."
            )
        if target_kind in ATTRIBUTE_FREE_TARGETS and any(
            letter in attributes[1:3] for letter in "hs"
        ):
            losses.append(
                "A host directory keeps no GEMDOS attribute byte, so the hidden "
                "and system bits are dropped."
            )
        items.append({
            "index": offset,
            "sourceName": str(change.get("sourceName") or leaf),
            "targetName": normal or "FILE",
            "source": str(change.get("source") or ""),
            "type": item_type,
            "metadata": {
                "attributes": attributes,
                "datestamp": str(change.get("datestamp") or ""),
                "filetype": str(change.get("filetype") or ""),
            },
            "conversions": conversions,
            "losses": losses,
        })
    report = {
        "format": COMPATIBILITY_REPORT_FORMAT,
        "version": COMPATIBILITY_REPORT_VERSION,
        "operation": operation,
        "dryRun": True,
        "source": {"kind": source_kind},
        "target": {
            "kind": target_kind,
            "image": session.name,
            "hardwareProfile": str((session.hardware_profile or {}).get("name") or ""),
        },
        "changes": changes,
        "items": items,
        "issues": issues,
        "canProceed": not any(item["severity"] == "error" for item in issues),
        "summary": f"{len(changes)} proposed changes, {len(issues)} findings",
    }
    report["markdown"] = compatibility_report_markdown(report)
    return report


__all__ = [
    "COMPATIBILITY_REPORT_FORMAT",
    "COMPATIBILITY_REPORT_VERSION",
    "MAX_INSPECT_BYTES",
    "accept_compatibility_report",
    "attribute_findings",
    "auto_folder_findings",
    "basic_commands",
    "boot_findings",
    "build_manifest",
    "capacity_findings",
    "compatibility_report_markdown",
    "datestamp_findings",
    "dependency_report",
    "describe_boot_sector",
    "describe_program",
    "desktop_findings",
    "duplicate_report",
    "health_report",
    "inspect_file",
    "manifest_csv",
    "name_findings",
    "parse_desktop_inf",
    "preflight_report",
    "program_findings",
    "workspace_metadata_records",
]
