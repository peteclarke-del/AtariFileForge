"""Replacement GEM desktops, and which one suits a given machine.

The built-in TOS desktop is spartan: no program groups, no icons of your own,
no way to find a file. Every serious Atari acquired a replacement, and getting
one onto a drive is the same tedium every time. Copy the distribution into a
folder, put its resource file beside the program, put whatever belongs in
``AUTO`` in ``AUTO``, then teach the desktop configuration that the program
exists so it can be started without going looking for it.

This does that from the operator's own copy. Nothing here is bundled or
fetched, for the same reason no hard-disk driver is: NeoDesk is Gribnif's,
Gemini and Thing are their authors', and only TeraDesk is under a licence that
would allow redistribution at all. A desktop the operator has not supplied is
offered, marked as not supplied, and not selectable, so the choice that cannot
be made is visible rather than absent.

What this deliberately does not do is make the replacement start instead of
the built-in desktop. That is arranged differently on every TOS release and by
every one of these programs, and writing a record into somebody's working
desktop configuration on the strength of a guess is not a trade worth making.
The desktop is installed, listed among the applications and put on the desktop
itself, so it is one double-click away, and the result says so plainly.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

from . import atari_paths, volume_copy
from .drive_preparation import (
    DESKTOP_FILES,
    NEWDESK,
    REPOSITORY_ROOT,
    _find,
    _version_from,
    application_record,
    default_desktop,
    desktop_icon_record,
    installed_applications,
    merge_desktop,
)
from .image_session import ImageSession
from .errors import DiskError

#: Where the operator keeps the desktops they own, on the same convention the
#: hard-disk drivers already use.
DESKTOP_DIR = Path(
    os.environ.get(
        "ATARI_FILE_FORGE_DESKTOP_DIR",
        Path.home() / ".config" / "atari-file-forge" / "desktops",
    )
)

#: The git-ignored directory beside the source where they may also be kept.
REPOSITORY_DESKTOP_DIR = REPOSITORY_ROOT / "firmware" / "desktops"

#: Every machine in the range, for a desktop that suits all of them.
EVERY_MACHINE = frozenset({"st", "megast", "ste", "megaste", "tt030", "falcon030"})

KIB = 1024
MIB = 1024 * KIB


@dataclasses.dataclass(frozen=True)
class Desktop:
    """One replacement desktop, and what installing it involves."""

    key: str
    label: str
    #: The program the desktop starts from, in the order to look for it. The
    #: first name found in the operator's directory is the one installed.
    files: tuple[str, ...]
    #: Everything that has to sit beside the program for it to run: resource
    #: files, its own configuration, its help.
    companions: tuple[str, ...] = ()
    #: Programs that belong in ``AUTO`` rather than the desktop's own folder.
    auto_files: tuple[str, ...] = ()
    #: The folder on the drive it is installed into.
    folder: str = ""
    #: What its distribution folder is normally called, for reading the
    #: release out of the folder the operator unpacked it as.
    folder_names: tuple[str, ...] = ()
    #: The machines it is a sensible choice on.
    machines: frozenset[str] = EVERY_MACHINE
    #: What it keeps resident once it is running. On a 1 MiB machine this is
    #: the difference between running a large application and not.
    resident_bytes: int = 0
    #: The smallest machine it is worth putting on.
    memory_bytes: int = MIB
    licence: str = ""
    note: str = ""


DESKTOPS: tuple[Desktop, ...] = (
    Desktop(
        "desktop-teradesk",
        "TeraDesk",
        ("TERADESK.PRG", "DESKTOP.PRG"),
        companions=("TERADESK.RSC", "DESKTOP.RSC", "TERADESK.INF"),
        folder="TERADESK",
        folder_names=("TERADESK", "TERA"),
        machines=EVERY_MACHINE,
        resident_bytes=64 * KIB,
        memory_bytes=512 * KIB,
        licence="Free software, GPL. The source is published by the FreeMiNT project.",
        note="The smallest of these by some way, and the least fussy about "
             "which TOS it finds. It is the one to choose on a 1 MB machine, "
             "or wherever the memory is wanted for the application rather "
             "than the desktop.",
    ),
    Desktop(
        "desktop-neodesk",
        "NeoDesk 4",
        ("NEODESK.PRG", "NEODESK4.PRG"),
        companions=("NEODESK.RSC", "NEODESK.INF", "NEODESK4.RSC"),
        folder="NEODESK",
        folder_names=("NEODESK", "NEODESK4"),
        machines=frozenset({"st", "megast", "ste", "megaste", "tt030"}),
        resident_bytes=154 * KIB,
        memory_bytes=2 * MIB,
        licence="Commercial, Gribnif Software. Supply your own copy.",
        note="The most complete of them: icons of your own, program groups, "
             "a file search, background patterns. It keeps about 154 KB "
             "resident and drops to roughly 24 KB while another program "
             "runs, which is why it is comfortable on a 2 MB machine and "
             "generous on a 4 MB one. It pairs with Geneva if multitasking "
             "is wanted.",
    ),
    Desktop(
        "desktop-gemini",
        "Gemini with Mupfel",
        ("GEMINI.APP", "GEMINI.PRG"),
        companions=("GEMINI.RSC", "GEMINI.INF", "MUPFEL.TTP", "MUPFEL.APP"),
        folder="GEMINI",
        folder_names=("GEMINI",),
        machines=EVERY_MACHINE,
        resident_bytes=120 * KIB,
        memory_bytes=2 * MIB,
        licence="Free to use. Supply your own copy.",
        note="Carries Mupfel, a Unix-like shell built into the desktop, so a "
             "command line and a GEM window are the same environment. The "
             "one to choose if you spend time at a prompt.",
    ),
    Desktop(
        "desktop-thing",
        "Thing",
        ("THING.APP", "THING.PRG"),
        companions=("THING.RSC", "THING.INF"),
        folder="THING",
        folder_names=("THING",),
        machines=frozenset({"ste", "megaste", "tt030", "falcon030"}),
        resident_bytes=110 * KIB,
        memory_bytes=2 * MIB,
        licence="Free to use. Supply your own copy.",
        note="Written to replace Gemini and built for high-resolution mono. "
             "It understands long filenames, so it is the one that still "
             "makes sense if the machine later runs MagiC or MiNT.",
    ),
)

DESKTOPS_BY_KEY = {desktop.key: desktop for desktop in DESKTOPS}

#: The choice that installs nothing, which is what a drive gets by default.
NO_DESKTOP = "desktop-none"


def describe_desktops() -> list[dict]:
    """The desktop choices, for an interface that has to explain them."""
    return [
        {
            "id": desktop.key,
            "label": desktop.label,
            "files": list(desktop.files),
            "companions": list(desktop.companions),
            "autoFiles": list(desktop.auto_files),
            "folder": desktop.folder,
            "machines": sorted(desktop.machines),
            "residentBytes": desktop.resident_bytes,
            "memoryBytes": desktop.memory_bytes,
            "licence": desktop.licence,
            "note": desktop.note,
        }
        for desktop in DESKTOPS
    ]


def desktop_for(key: str) -> Desktop:
    """The desktop a request named, or a refusal that lists the choices."""
    chosen = DESKTOPS_BY_KEY.get(str(key or "").strip())
    if chosen is None:
        raise DiskError(
            f"{key} is not a replacement desktop this recognises. Choose one of: "
            + ", ".join(desktop.key for desktop in DESKTOPS)
            + "."
        )
    return chosen


def desktop_directories() -> list[Path]:
    """Where an operator's own desktops are looked for, in order."""
    return [DESKTOP_DIR, REPOSITORY_DESKTOP_DIR]


@dataclasses.dataclass(frozen=True)
class DesktopDistribution:
    """One desktop as the operator supplied it, ready to be copied in."""

    desktop: Desktop
    #: The program itself: its GEMDOS name and its bytes.
    name: str
    payload: bytes
    #: Where it was found, so a report can say which copy was used.
    source: Path
    #: Everything that goes into the desktop's folder beside the program.
    companions: tuple[tuple[str, bytes], ...] = ()
    #: Files that belong in ``AUTO``, by GEMDOS name.
    auto: tuple[tuple[str, bytes], ...] = ()
    #: The release, read from the folder the distribution was found in.
    version: str = ""


def find_desktop(desktop: Desktop, directories=None) -> DesktopDistribution | None:
    """Locate the operator's copy of one desktop, or report that it is absent.

    Nothing is fetched. A desktop that is not in one of the directories is
    simply not available, and saying so is the whole answer: three of these
    four are somebody's property and this application has no lawful way of
    producing them.
    """
    for directory in (directories if directories is not None else desktop_directories()):
        for name in desktop.files:
            found = _find(Path(directory), name)
            if found is None:
                continue
            companions = []
            for extra in desktop.companions:
                beside = _find(Path(directory), extra)
                if beside is not None:
                    companions.append((extra, beside.read_bytes()))
            auto = []
            for extra in desktop.auto_files:
                beside = _find(Path(directory), extra)
                if beside is not None:
                    auto.append((extra, beside.read_bytes()))
            return DesktopDistribution(
                desktop=desktop,
                name=name,
                payload=found.read_bytes(),
                source=found,
                companions=tuple(companions),
                auto=tuple(auto),
                version=_version_from(found),
            )
    return None


def recommended_desktop(machine: str, memory_bytes: int = 0) -> dict:
    """Which desktop suits this machine, and why.

    The answer turns on two things: whether the machine has the memory to
    keep one resident, and whether it is one of the later machines where long
    filenames and high-resolution mono are worth having. Where the memory is
    not known it is not guessed at, and the recommendation falls to the one
    that fits everywhere.
    """
    name = str(machine or "st").strip().lower()
    memory = int(memory_bytes or 0)
    suitable = [desktop for desktop in DESKTOPS if name in desktop.machines]
    if not suitable:
        suitable = list(DESKTOPS)

    def choose(key: str, reason: str) -> dict:
        return {"id": key, "reason": reason, "machine": name}

    if memory and memory < 2 * MIB:
        return choose(
            "desktop-teradesk",
            f"{_memory_text(memory)} leaves little to spare, and TeraDesk keeps "
            "the least of it. The others are worth having once there is 2 MB.",
        )
    if name in {"tt030", "falcon030"}:
        return choose(
            "desktop-thing",
            "Thing was built for high-resolution mono and understands long "
            "filenames, so it still makes sense if this machine later runs "
            "MagiC or MiNT.",
        )
    if memory >= 2 * MIB:
        return choose(
            "desktop-neodesk",
            f"{_memory_text(memory)} is comfortably enough for the most "
            "complete of them. NeoDesk 4 keeps about 154 KB resident and "
            "drops to roughly 24 KB while another program runs.",
        )
    if name in {"ste", "megaste"}:
        return choose(
            "desktop-neodesk",
            "An STE is rarely the machine that is short of memory, and "
            "NeoDesk 4 is the most complete of them.",
        )
    return choose(
        "desktop-teradesk",
        "With the memory unknown, the least demanding answer is the right "
        "one: TeraDesk asks little of the machine and little of its TOS.",
    )


def _memory_text(memory_bytes: int) -> str:
    if memory_bytes >= MIB:
        whole = memory_bytes / MIB
        return f"{whole:.0f} MB" if whole == int(whole) else f"{whole:.1f} MB"
    return f"{memory_bytes // KIB} KB"


class DesktopReplacementMixin:
    """Installing a replacement desktop from the operator's own copy."""

    def available_desktops(self) -> list[dict]:
        """Which replacement desktops the operator has supplied a copy of.

        A choice that cannot be carried out should not be offered as though it
        could. Three of these four are somebody's property, so the reason one
        is missing is always the same: the operator has to put their own copy
        in one of these directories.
        """
        found = [{"id": NO_DESKTOP, "available": True, "version": "", "source": ""}]
        for desktop in DESKTOPS:
            distribution = find_desktop(desktop)
            found.append({
                "id": desktop.key,
                "available": distribution is not None,
                "version": distribution.version if distribution else "",
                "source": str(distribution.source) if distribution else "",
            })
        return found

    def install_desktop_replacement(
        self, session: ImageSession, key: str, *, on_desktop: bool = True
    ) -> dict:
        """Copy a replacement desktop onto this volume and install it.

        The program and everything that has to sit beside it go into a folder
        of their own, anything the distribution puts in ``AUTO`` goes into
        ``AUTO``, and the desktop configuration learns that the program exists
        so it can be started without going looking for it.

        Making it start *instead of* the built-in desktop is left alone. Every
        TOS release and every one of these programs arranges that differently,
        and writing a guess into a working desktop configuration is not a
        trade worth making. The result says so.
        """
        if str(key or "").strip() in {"", NO_DESKTOP}:
            return {"id": NO_DESKTOP, "installed": False, "files": [], "warnings": []}
        desktop = desktop_for(key)
        self.require_mounted_volume(session)
        self.require_writable_geometry(session)
        distribution = find_desktop(desktop)
        if distribution is None:
            raise DiskError(
                f"No copy of {desktop.label} was found. {desktop.licence} "
                f"Put the files you own in {DESKTOP_DIR} or "
                f"{REPOSITORY_DESKTOP_DIR}, unpacked as they were published."
            )

        folder = desktop.folder or atari_paths.leaf(distribution.name).split(".")[0]
        if not volume_copy.directory_exists(self, session, folder):
            self.make_directory(session, folder)
        written: list[str] = []
        program = atari_paths.join(folder, distribution.name)
        volume_copy.write_file(self, session, program, distribution.payload)
        written.append(program)
        for name, payload in distribution.companions:
            path = atari_paths.join(folder, name)
            volume_copy.write_file(self, session, path, payload)
            written.append(path)
        for name, payload in distribution.auto:
            if not volume_copy.directory_exists(self, session, "AUTO"):
                self.make_directory(session, "AUTO")
            path = atari_paths.join("AUTO", name)
            volume_copy.write_file(self, session, path, payload)
            written.append(path)

        drive = self.partition_label(session) or "C"
        name = next(
            (item for item in DESKTOP_FILES if volume_copy.entry_exists(self, session, item)),
            "",
        )
        # A volume with no desktop configuration at all is given the default
        # one to add to. Reading a file that is known not to be there raises
        # out of the engine rather than returning nothing, so the existence
        # check decides, not the exception.
        existing = (
            self.read_file(session, name).decode("latin-1")
            if name else default_desktop(drive)
        )
        name = name or NEWDESK
        records = [application_record(program, drive=drive)]
        if on_desktop:
            records.append(desktop_icon_record(program, desktop.label, drive=drive))
        merged, added = merge_desktop(existing, records)
        volume_copy.write_file(self, session, name, merged.encode("latin-1"))
        self._mark_mutated(session)
        self._persist_session(session)
        return {
            "id": desktop.key,
            "label": desktop.label,
            "installed": True,
            "version": distribution.version,
            "source": str(distribution.source),
            "folder": folder,
            "program": program,
            "files": written,
            "desktopFile": name,
            "records": added,
            "applications": installed_applications(merged),
            "warnings": [
                f"{desktop.label} is installed and on the desktop, but the "
                "built-in TOS desktop still starts first. Making a "
                "replacement start in its place is arranged differently by "
                "every TOS release and by every one of these programs, so it "
                "is left to its own documented method rather than guessed at.",
            ],
        }


__all__ = [
    "DESKTOPS",
    "DESKTOPS_BY_KEY",
    "DESKTOP_DIR",
    "Desktop",
    "DesktopDistribution",
    "EVERY_MACHINE",
    "NO_DESKTOP",
    "REPOSITORY_DESKTOP_DIR",
    "DesktopReplacementMixin",
    "describe_desktops",
    "desktop_directories",
    "desktop_for",
    "find_desktop",
    "recommended_desktop",
]
