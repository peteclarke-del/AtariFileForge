r"""Working out what a disk is and how it starts, from the disk itself.

An imported disk arrives with a volume label, a set of files and nothing else.
This module reads that evidence and proposes a title, the file that starts the
software, and the flags that file's own header carries, along with the
reasoning behind each conclusion so a person can check it rather than being
asked to trust it.

The order the evidence is read in is the order TOS itself would take it:

1. **A program in ``AUTO``.** TOS runs everything in that folder before the
   desktop appears, so a disk that has one has already said what it wants run
   and nothing else on the disk can outrank it.
2. **A desktop configuration that installs an application.** ``NEWDESK.INF``
   and ``DESKTOP.INF`` hold the desktop's own record of which program starts
   the software, written by whoever built the disk.
3. **A program in the root**, judged by its ``0x601A`` header and its size
   rather than by its name. A disk usually carries several programs and only
   one of them is the title; the one with the most code in it almost always
   is, and a file whose header does not parse is not a program at all however
   it is named.
4. **A tokenised BASIC program**, which is not started by TOS at all but
   loaded by an interpreter.

Nothing here guesses silently. Every proposal carries its evidence, and a
proposal the evidence does not support is marked ambiguous so the caller asks
rather than writes. That distinction matters because these conclusions are
offered as defaults during an import, where a confident wrong answer is worse
than an admitted uncertainty.
"""

from __future__ import annotations

import re
import struct
from typing import TYPE_CHECKING

from . import atari_paths
from .errors import DiskError
from .filename_policy import ATARI_NAME_LIMIT
from .metadata_lookup import enrich_from_distribution_filename

if TYPE_CHECKING:  # pragma: no cover - imported for type checkers only
    from .disk_service import DiskService
    from .image_session import ImageSession


#: The first word of every GEMDOS program: a branch over the 28-byte header.
GEMDOS_MAGIC = 0x601A

#: How long that header is, and where in it the flags longword sits.
PROGRAM_HEADER_SIZE = 28
PROGRAM_FLAGS_OFFSET = 22

#: The flags word a program header carries when it asks for nothing special,
#: which is what most software written for a 520ST does.
DEFAULT_FLAGS = 0

#: Bits of ``_p_flags`` that a person would want to see named. TOS reads the
#: rest as the memory-protection field, which only MiNT and a Falcon honour.
PROGRAM_FLAG_NAMES = (
    (0x0001, "fastload"),
    (0x0002, "load into alternate RAM"),
    (0x0004, "malloc from alternate RAM"),
    (0x1000, "shared text"),
)

#: The extensions TOS will start, and the desktop record letter each one is
#: installed under. The extension is the whole of what the desktop reads, so
#: it decides how the program runs: a ``.TTP`` is asked for a command line, a
#: ``.TOS`` runs without GEM, a ``.PRG`` or ``.APP`` runs with it.
LAUNCH_ACTIONS = {
    "PRG": "G",
    "APP": "G",
    "GTP": "Y",
    "TTP": "P",
    "TOS": "F",
    "ACC": "",
}

PROGRAM_EXTENSIONS = tuple(LAUNCH_ACTIONS)

#: The folder TOS runs before the desktop appears. A program in it outranks
#: everything else on the disk, because the disk's author put it there to be
#: run first and TOS will run it whether anything else is chosen or not.
AUTO_DIRECTORY = "AUTO"

#: A program started from ``AUTO`` is not installed on the desktop at all, so
#: it has no record letter. This is what is reported instead.
AUTO_ACTION = "A"

#: The desktop's own configuration, in the order TOS looks for it.
DESKTOP_FILES = ("NEWDESK.INF", "DESKTOP.INF")

#: Record letters in a desktop configuration that install an application.
INSTALL_RECORDS = frozenset("GFPY")

#: An accessory is loaded by TOS at boot and never started by the desktop, so
#: it is recognised but never proposed as the thing that starts a title.
ACCESSORY = "ACC"


def _clean_title(value: str) -> str:
    value = re.sub(r"[_-]+", " ", value or "")
    value = re.sub(r"\b(?:SIDE|DISC|DISK)\s*[012AB]?\b", "", value, flags=re.I)
    return re.sub(r"\s+", " ", value).strip().title()


def extension_of(name: str) -> str:
    """The upper-case extension of a GEMDOS name, or an empty string."""
    leaf = atari_paths.leaf(str(name or "")) or str(name or "")
    return leaf.rsplit(".", 1)[-1].upper() if "." in leaf else ""


def program_header(data: bytes) -> dict | None:
    """Decode a GEMDOS program header, or return None when there is not one.

    A file is a program because its first word is ``0x601A`` and the sizes
    that follow account for the bytes that are actually there. Checking the
    sizes is what tells a real program from a data file that happens to begin
    with those two bytes, and from a program that was truncated in transit.
    """
    if len(data) < PROGRAM_HEADER_SIZE:
        return None
    magic, text, initialised, bss, symbols, _reserved, flags, absolute = struct.unpack_from(
        ">HIIIIIIH", data, 0
    )
    if magic != GEMDOS_MAGIC:
        return None
    body = PROGRAM_HEADER_SIZE + text + initialised + symbols
    if body > len(data):
        return None
    return {
        "text": text,
        "data": initialised,
        "bss": bss,
        "symbols": symbols,
        "flags": flags,
        "absolute": bool(absolute),
        #: What the program occupies once TOS has loaded it, which is the
        #: honest measure of how much of it there is. A file's length also
        #: counts its symbol table, which is debugging information.
        "size": text + initialised + bss,
        "complete": body == len(data) or len(data) - body < 512,
    }


def is_executable(data: bytes) -> bool:
    """Report whether the bytes are a GEMDOS program."""
    return program_header(data) is not None


def describe_flags(flags: int) -> list[str]:
    """Name the bits of a program's flags longword that a person would ask about."""
    named = [label for bit, label in PROGRAM_FLAG_NAMES if int(flags) & bit]
    protection = (int(flags) >> 4) & 0x7
    if protection:
        named.append(f"memory protection mode {protection}")
    return named


def is_stbasic(data: bytes) -> bool:
    """Report whether the bytes are a saved ST BASIC program."""
    if not data or is_executable(data):
        return False
    try:
        from atarinut.basic import Verdict, detect
    except ImportError:  # pragma: no cover - the tokeniser is always present
        return False
    return detect(data).verdict in {Verdict.BASIC, Verdict.BASIC_TRAILING}


def desktop_installed_programs(text: str) -> list[str]:
    r"""Programs a desktop configuration installs, as bare GEMDOS names.

    A record such as ``#G 03 FF 000 C:\GAMES\X\X.PRG@ @ @`` installs one named
    program; ``#G 03 FF 000 *.PRG@ @ @`` associates an extension and installs
    nothing. Only the first kind says what starts this software.
    """
    found: list[str] = []
    for line in re.split(r"\r\n|\r|\n", str(text or "")):
        if len(line) < 2 or line[0] != "#" or line[1] not in INSTALL_RECORDS:
            continue
        head = line.split("@", 1)[0].split(None, 4)
        if len(head) <= 4:
            continue
        path = head[4].strip().upper()
        if not path or "*" in path or "?" in path:
            continue
        found.append(atari_paths.leaf(path.split(":", 1)[-1]) or path)
    return found


def _read(
    service: DiskService, session: ImageSession, path: str, name: str
) -> bytes:
    """Read one entry's contents, or empty bytes when it cannot be read."""
    try:
        return service.read_file(session, atari_paths.join(path, str(name))) or b""
    except (DiskError, KeyError, OSError, UnicodeError, RuntimeError):
        return b""


def _programs(entries: list[dict]) -> list[dict]:
    return [
        row for row in entries
        if extension_of(row.get("name", "")) in LAUNCH_ACTIONS
    ]


def _auto_programs(
    service: DiskService, session: ImageSession, path: str
) -> list[dict]:
    """Programs in this directory's ``AUTO`` folder, in the order TOS runs them.

    TOS runs them in the order the directory holds them, which is the order
    they were written, so that order is kept rather than sorted.
    """
    auto = atari_paths.join(path, AUTO_DIRECTORY)
    try:
        listing = service.list_directory(session, auto)
    except (DiskError, RuntimeError):
        return []
    return [
        row for row in listing.get("entries", [])
        if row.get("type") not in {"dir", "directory"}
        and extension_of(row.get("name", "")) in {"PRG", "TOS", "TTP", "APP", "GTP"}
    ]


def _detect_launcher(
    service: DiskService,
    session: ImageSession,
    entries: list[dict],
    *,
    path: str,
) -> tuple[dict | None, str, list[str], list[str], bool]:
    """Choose the file that starts this software, and say why.

    Returns the chosen entry, the directory it lives in relative to ``path``,
    the evidence for the choice, anything worth warning about, and whether the
    disk itself disagreed about which file starts it. That last one is what
    separates a disk carrying a misnamed data file, which changes nothing, from
    a disk carrying two equally good candidates, which nobody can settle from
    the bytes alone.
    """
    evidence: list[str] = []
    warnings: list[str] = []
    contested = False

    auto = _auto_programs(service, session, path)
    if auto:
        chosen = auto[0]
        evidence.append(
            f"{chosen['name']} is in {AUTO_DIRECTORY}, so TOS runs it before the "
            "desktop appears; nothing else on the disk can start first"
        )
        if len(auto) > 1:
            warnings.append(
                f"{AUTO_DIRECTORY} holds {len(auto)} programs and TOS runs all of "
                f"them in turn. {chosen['name']} is the first."
            )
        return chosen, AUTO_DIRECTORY, evidence, warnings, contested

    by_name = {str(row.get("name", "")).upper(): row for row in entries}
    for configuration in DESKTOP_FILES:
        row = by_name.get(configuration)
        if row is None:
            continue
        installed = desktop_installed_programs(
            _read(service, session, path, row["name"]).decode("latin-1", "replace")
        )
        present = [name for name in installed if name.upper() in by_name]
        if present:
            chosen = by_name[present[0].upper()]
            evidence.append(
                f"{configuration} installs {chosen['name']} as an application, "
                "which is the disk's own record of what starts it"
            )
            if len(present) > 1:
                contested = True
                warnings.append(
                    f"{configuration} installs {len(present)} applications; "
                    f"{chosen['name']} is the first."
                )
            return chosen, "", evidence, warnings, contested
        if installed:
            warnings.append(
                f"{configuration} installs {', '.join(sorted(set(installed)))}, "
                "which is not on this disk."
            )

    candidates = []
    for row in _programs(entries):
        if extension_of(row["name"]) == ACCESSORY:
            continue
        header = program_header(_read(service, session, path, row["name"]))
        if header is None:
            warnings.append(
                f"{row['name']} is named as a program but carries no 0x601A header, "
                "so TOS would refuse to run it."
            )
            continue
        candidates.append((header["size"], str(row["name"]), row, header))
    if candidates:
        candidates.sort(key=lambda item: (-item[0], item[1]))
        _size, _name, chosen, header = candidates[0]
        evidence.append(
            f"{chosen['name']} carries a 0x601A program header and is the largest "
            f"program on the disk at {header['size']} bytes loaded"
        )
        if len(candidates) > 1:
            evidence.append(
                f"{len(candidates)} programs were examined and judged by their "
                "headers and sizes rather than by their names"
            )
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            contested = True
            warnings.append(
                "Two programs on this disk load to the same size, so which one "
                "starts the title cannot be told from the disk alone."
            )
        return chosen, "", evidence, warnings, contested

    basic = [
        row for row in entries
        if is_stbasic(_read(service, session, path, row.get("name", "")))
    ]
    if len(basic) == 1:
        evidence.append(
            f"{basic[0]['name']} is a saved ST BASIC program, and it is the only "
            "one on the disk; an interpreter loads it rather than TOS starting it"
        )
        return basic[0], "", evidence, warnings, contested
    if len(basic) > 1:
        contested = True
        warnings.append(
            f"{len(basic)} saved BASIC programs are on this disk, so which one is "
            "the title cannot be told from the disk alone."
        )
    elif not entries:
        warnings.append("The disk is empty.")
    else:
        warnings.append("No single launch program could be identified.")
    return None, "", evidence, warnings, True


def program_flags(
    service: DiskService,
    session: ImageSession,
    directory: str,
    filename: str,
) -> tuple[str | None, str, bool]:
    """Return (flags, evidence, applicable) for one launch file.

    The previous platform recorded a stack size, because the script that
    started a program set one. TOS has no such script: what a program asks of
    the machine is the ``_p_flags`` longword in its own header, which says
    whether it wants fast loading and which memory it will accept. That is a
    property of the file, so it is read out of the file.

    The third value says whether a flags figure applies at all. A tokenised
    BASIC program has no header, so it has none.
    """
    path = atari_paths.join(directory, filename)
    try:
        data = service.read_file(session, path)
    except (DiskError, KeyError, OSError, RuntimeError):
        return None, f"{atari_paths.display(path)} could not be read", True
    header = program_header(data)
    if header is None:
        if is_stbasic(data):
            return (
                None,
                f"{atari_paths.display(path)} is a BASIC program, which has no "
                "program header and therefore no flags of its own",
                False,
            )
        return None, f"{atari_paths.display(path)} carries no 0x601A program header", True
    flags = int(header["flags"])
    named = describe_flags(flags)
    detail = f" ({', '.join(named)})" if named else ""
    return (
        str(flags),
        f"{atari_paths.display(path)} declares _p_flags 0x{flags:08X}{detail}",
        True,
    )


def analyse_directory(
    service: DiskService,
    session: ImageSession,
    path: str = "",
) -> dict:
    """Describe the software in one folder, or in a volume root.

    The same reading serves a floppy and a folder on a hard drive, because on
    an Atari they are the same thing: a directory holding the files that make
    up one piece of software.
    """
    listing = service.list_directory(session, path)
    entries = [
        row for row in listing["entries"] if row.get("type") not in {"dir", "directory"}
    ]
    chosen, sub_directory, evidence, warnings, contested = _detect_launcher(
        service, session, entries, path=path
    )
    filename = str(chosen["name"]) if chosen else ""
    extension = extension_of(filename)
    action = AUTO_ACTION if sub_directory == AUTO_DIRECTORY else LAUNCH_ACTIONS.get(extension, "")
    volume_title = str(
        listing.get("directoryTitle")
        or (atari_paths.leaf(path) if atari_paths.normalise(path) else listing.get("title") or "")
    )
    title = _clean_title(volume_title)
    generic_title = not title or bool(
        re.fullmatch(r"(?:DIS[CK]|UNTITLED|EMPTY)\s*\d*", title, re.I)
    )

    flags = str(DEFAULT_FLAGS)
    if filename:
        inferred, flag_evidence, applicable = program_flags(
            service, session, atari_paths.join(path, sub_directory), filename
        )
        if inferred is not None and applicable:
            flags = inferred
            evidence.append(f"Program flags read from the launch file: {flag_evidence}")
        elif flag_evidence:
            evidence.append(flag_evidence)

    confidence = 0
    if title and not generic_title:
        confidence += 25
    if chosen:
        confidence += 45
    if not contested:
        confidence += 20
    if chosen and program_header(_read(service, session, atari_paths.join(path, sub_directory), filename)):
        confidence += 10

    candidates = [{"name": str(item["name"]), "path": path} for item in entries]
    for directory in (
        item for item in listing["entries"] if item.get("type") in {"dir", "directory"}
    ):
        child_path = atari_paths.join(path, directory["name"])
        try:
            child_entries = service.list_directory(session, child_path)["entries"]
        except (DiskError, RuntimeError):
            continue
        candidates.extend(
            {"name": str(item["name"]), "path": child_path}
            for item in child_entries
            if item.get("type") not in {"dir", "directory"}
        )

    metadata = {
        "title": title,
        "publisher": "",
        "filename": filename[:ATARI_NAME_LIMIT],
        "action": action,
        # The Atari has no launch stack. What is recorded in its place is the
        # program header's own flags longword; the field keeps its name
        # because that is what the hardware profile calls it.
        "page": flags,
        "flags": flags,
        "launchFolder": sub_directory,
        "diskTitle": volume_title[:ATARI_NAME_LIMIT],
        "path": path,
        "confidence": confidence,
        "ambiguous": confidence < 75 or not filename or generic_title or contested,
        "launchObvious": bool(filename and not contested),
        "evidence": evidence,
        "warnings": warnings,
        "sources": [],
        "matches": [],
        "launchCandidates": candidates,
    }
    source_name = getattr(session, "source_names", {}).get(path)
    if source_name:
        enrich_from_distribution_filename(metadata, source_name)
    elif getattr(session, "distribution_name", None):
        enrich_from_distribution_filename(metadata, session.distribution_name)
    return metadata


__all__ = [
    "ACCESSORY",
    "AUTO_ACTION",
    "AUTO_DIRECTORY",
    "DEFAULT_FLAGS",
    "DESKTOP_FILES",
    "GEMDOS_MAGIC",
    "LAUNCH_ACTIONS",
    "PROGRAM_EXTENSIONS",
    "PROGRAM_FLAGS_OFFSET",
    "PROGRAM_HEADER_SIZE",
    "analyse_directory",
    "describe_flags",
    "desktop_installed_programs",
    "extension_of",
    "is_executable",
    "is_stbasic",
    "program_flags",
    "program_header",
]
