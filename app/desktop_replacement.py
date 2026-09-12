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
import fnmatch
import os
import re
from pathlib import Path

from . import atari_paths, volume_copy
from .drive_preparation import (
    REPOSITORY_ROOT,
    _find,
    _version_from,
)
from .image_session import ImageSession
from .errors import DiskError
from .software_bundles import BUNDLE_SUFFIXES, DISK_SUFFIXES, archive_files, volume_files
from .software_download import MAX_DOWNLOAD_BYTES, fetch_archive

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

#: Where XControl looks for control panel modules unless its own CPXPATH says
#: otherwise. Every drive that has a control panel at all uses this.
CPX_FOLDER = "CPX"

#: Every machine in the range, for a desktop that suits all of them.
EVERY_MACHINE = frozenset({"st", "megast", "ste", "megaste", "tt030", "falcon030"})

KIB = 1024
MIB = 1024 * KIB


@dataclasses.dataclass(frozen=True)
class Source:
    """Where a freely licensed desktop can be obtained from.

    Only a desktop whose licence allows it carries one of these. The rest are
    somebody's property, and how easy they are to find elsewhere does not
    change what this application may go and fetch on an operator's behalf.
    """

    label: str
    url: str


#: Gribnif's cookie jar manager. NeoDesk and Geneva both depend on the cookie
#: it creates and the call it adds, and Geneva stops at boot with "You must run
#: JARxxx before Geneva" without it, on every TOS, EmuTOS included. Each of
#: their master disks carries a copy, and each INSTALL.SCR copies it into AUTO
#: as JAR10.PRG, the digits being how many new cookies to make room for.
#: Geneva's copies it unless a JAR*.PRG is already there; NeoDesk's then runs
#: AUTOFRST to put it ahead of every other AUTO program except XBOOT, because a
#: program that looks for a cookie has to find the jar already made.
COOKIE_JAR = "JARXXX.PRG"
COOKIE_JAR_INSTALLED = "JAR10.PRG"
#: AUTO programs that stay ahead of the cookie jar, as NeoDesk's installer
#: arranges: a boot manager decides what else runs at all.
AUTO_BOOT_MANAGERS = ("XBOOT.PRG",)
#: A GEM.CNF line naming the program Geneva starts as its desktop, whether in
#: force or commented out as it is on the master disk.
_SHELL_LINE = re.compile(r"^\s*#?\s*shell\s+(?P<path>\S+)", re.IGNORECASE)


def _is_cookie_jar(name: str) -> bool:
    """Whether an AUTO program is a JARxxx, under whatever number it was given."""
    return fnmatch.fnmatch(name.upper(), "JAR*.PRG")


def _first_after_boot_managers(order: list[str]) -> str | None:
    """The AUTO program that runs first once any boot manager has run."""
    return next((name for name in order if name not in AUTO_BOOT_MANAGERS), None)


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
    #: They run before GEM appears, in the order the directory holds them.
    auto_files: tuple[str, ...] = ()
    #: Files that have to sit in the root of the boot drive: desk accessories,
    #: which TOS loads from there and nowhere else, and the resource files
    #: they read beside themselves. An accessory without its resource loads
    #: and then has nothing to draw, which looks exactly like not loading.
    #: On these products the control panel is an accessory rather than a CPX.
    accessories: tuple[str, ...] = ()
    #: Control panel modules for XControl, which reads them from the folder
    #: its own CPXPATH names. ``CPX`` is the conventional one.
    control_panel: tuple[str, ...] = ()
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
    #: Whether it needs Gribnif's cookie jar manager running from AUTO before
    #: it starts. See :data:`COOKIE_JAR`.
    cookie_jar: bool = False
    #: Whether the licence allows this to be fetched at all. A desktop that is
    #: somebody's property is installed from the operator's own copy or not at
    #: all.
    free: bool = False
    #: Where a free one can be downloaded from, in the order to try.
    sources: tuple[Source, ...] = ()
    note: str = ""


DESKTOPS: tuple[Desktop, ...] = (
    Desktop(
        "desktop-teradesk",
        "TeraDesk",
        ("TERADESK.PRG", "DESKTOP.PRG"),
        companions=(
            "TERADESK.RSC", "DESKTOP.RSC", "TERADESK.INF",
            # Its icons live in their own resources, and without them it
            # starts with nothing to draw.
            "ICONS.RSC", "CICONS.RSC",
        ),
        folder="TERADESK",
        folder_names=("TERADESK", "TERA"),
        machines=EVERY_MACHINE,
        resident_bytes=64 * KIB,
        memory_bytes=512 * KIB,
        licence="Free software, GPL 2, published by the FreeMiNT project.",
        free=True,
        sources=(
            Source(
                "FreeMiNT snapshots",
                "https://atari.joska.no/snapshots/teradesk/teradesk-latest.zip",
            ),
        ),
        note="The smallest of these by some way, and the least fussy about "
             "which TOS it finds. It is the one to choose on a 1 MB machine, "
             "or wherever the memory is wanted for the application rather "
             "than the desktop.",
    ),
    Desktop(
        "desktop-neodesk",
        "NeoDesk 4",
        # NEOLOAD.PRG is what starts NeoDesk. The desktop itself is
        # NEODESK.EXE, which the loader brings in, and which TOS would not
        # know how to run on its own.
        ("NEOLOAD.PRG", "NEODESK.PRG"),
        companions=(
            "NEODESK.EXE", "NEODESK.RSC", "NEODESK.HLP", "NEOICONS.NIC",
            "SETTINGS.RSC", "HELP.RSC", "ICONEDIT.RSC", "NEODESK.INF",
        ),
        # Straight from Gribnif's own INSTALL.SCR. Each accessory is copied to
        # the root together with the resource it reads, and NEOLOAD.PRG is
        # copied into AUTO as well as into the program's folder, which is what
        # starts NeoDesk when the machine comes up.
        accessories=(
            "NEOCNTRL.ACC", "NEOCNTRL.RSC",
            "NEOQUEUE.ACC", "NEOQ_C.RSC", "NEOQ_M.RSC",
            "TRASHCAN.ACC", "TRASHCAN.RSC",
            "NEO_CLI.ACC", "NEO_CLI.NIC",
        ),
        auto_files=("NEOLOAD.PRG",),
        cookie_jar=True,
        folder="NEODESK4",
        folder_names=("NEODESK", "NEODESK4"),
        machines=frozenset({"st", "megast", "ste", "megaste", "tt030"}),
        resident_bytes=154 * KIB,
        memory_bytes=2 * MIB,
        free=True,
        sources=(
            Source(
                "Gribnif Software",
                "https://gribnif.github.io/files/NeoDesk-4.06-with-CLI.zip",
            ),
        ),
        licence=(
            "Freeware. Gribnif released it under Apache 2.0 with the Commons "
            "Clause, which allows use and redistribution but not sale."
        ),
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
        licence=(
            "Shareware, and freely passed around. The source was later "
            "released under the MIT licence. No binary distribution was found "
            "to download from, so supply your own copy or point at the folder "
            "or disk image it is on."
        ),
        note="Carries Mupfel, a Unix-like shell built into the desktop, so a "
             "command line and a GEM window are the same environment. The "
             "one to choose if you spend time at a prompt.",
    ),
    Desktop(
        "desktop-thing",
        "Thing",
        ("THING.APP", "THING.PRG"),
        companions=(
            "THING.RSC", "THING.INF",
            "ICONS.RSC", "ICONS.INF", "MONOICON.RSC", "MEDICON.RSC",
        ),
        folder="THING",
        folder_names=("THING",),
        machines=frozenset({"ste", "megaste", "tt030", "falcon030"}),
        resident_bytes=110 * KIB,
        memory_bytes=2 * MIB,
        licence="Released as open source by its author, Arno Welzel.",
        free=True,
        sources=(
            Source("arnowelzel.de", "https://arnowelzel.de/download/thin109d.zip"),
        ),
        note="Written to replace Gemini and built for high-resolution mono. "
             "It understands long filenames, so it is the one that still "
             "makes sense if the machine later runs MagiC or MiNT.",
    ),
)

DESKTOPS_BY_KEY = {desktop.key: desktop for desktop in DESKTOPS}

#: Geneva is not a desktop. It is a cooperative multitasker that runs *under*
#: one, giving the machine a dropdown menu bar and several programs at once.
#: It is Gribnif's too, released on the same terms, and it is what NeoDesk was
#: designed to sit on, so it is offered alongside rather than instead.
GENEVA = Desktop(
    "companion-geneva",
    "Geneva",
    ("GENEVA.PRG",),
    companions=(
        "GENEVA.CNF", "GEM.CNF", "GNVA_TOS.PRG", "GNVA_TOS.RSC", "TERMCAP",
        "TASKMAN.RSC",
    ),
    # From Geneva's own INSTALL.SCR: the task manager and its resource go to
    # the root, and GENEVA.PRG goes into AUTO, which is what starts it.
    accessories=(
        "TASKMAN.ACC", "TASKMAN.RSC",
        "GNVADESK.ACC", "GNVADESK.RSC",
    ),
    auto_files=("GENEVA.PRG",),
    cookie_jar=True,
    folder="GENEVA",
    folder_names=("GENEVA",),
    machines=frozenset({"st", "megast", "ste", "megaste", "tt030"}),
    resident_bytes=190 * KIB,
    memory_bytes=2 * MIB,
    free=True,
    sources=(
        Source("Gribnif Software", "https://gribnif.github.io/files/Geneva-1.08.zip"),
    ),
    licence=(
        "Freeware. Gribnif released it under Apache 2.0 with the Commons "
        "Clause, which allows use and redistribution but not sale."
    ),
    note="Cooperative multitasking under the desktop: a dropdown menu bar, "
         "and several programs running at once. It was written to pair with "
         "NeoDesk and is the reason that pairing is worth having.",
)

DESKTOPS_BY_KEY[GENEVA.key] = GENEVA

#: The choice that installs nothing, which is what a drive gets by default.
NO_DESKTOP = "desktop-none"


def describe_desktops(include_companions: bool = True) -> list[dict]:
    """The desktop choices, for an interface that has to explain them."""
    listed = (*DESKTOPS, GENEVA) if include_companions else DESKTOPS
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
            "free": desktop.free,
            "sources": [{"label": s.label, "url": s.url} for s in desktop.sources],
            "note": desktop.note,
            # A companion runs under a desktop rather than being one, so an
            # interface can offer it alongside instead of instead of.
            "companion": desktop.key not in {item.key for item in DESKTOPS},
        }
        for desktop in listed
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
    #: Desk accessories, for the root of the boot drive.
    accessories: tuple[tuple[str, bytes], ...] = ()
    #: Control panel modules, for the CPX folder.
    control_panel: tuple[tuple[str, bytes], ...] = ()
    #: The release, read from the folder the distribution was found in.
    version: str = ""
    #: Gribnif's cookie jar manager, where the desktop needs it and the
    #: distribution carries it.
    cookie_jar: bytes = b""


def _wanted_names(desktop: Desktop) -> dict[str, str]:
    """Every filename this desktop needs, folded for case-blind matching."""
    wanted = {}
    for name in (
        *desktop.files,
        *desktop.companions,
        *desktop.auto_files,
        *desktop.accessories,
        *desktop.control_panel,
        *((COOKIE_JAR,) if desktop.cookie_jar else ()),
    ):
        wanted[name.casefold()] = name
    return wanted


def _from_archive(desktop: Desktop, archive: Path) -> DesktopDistribution | None:
    """Read a distribution straight out of a ZIP, without unpacking it first.

    An operator who has just downloaded one should not have to unpack it
    before it can be used, and both desktops downloadable from their own
    authors are a ZIP with the original distribution floppies inside.
    """
    held = archive_files(archive, _wanted_names(desktop))
    program = next((name for name in desktop.files if name in held), None)
    if program is None:
        return None
    return DesktopDistribution(
        desktop=desktop,
        name=program,
        payload=held[program],
        source=archive,
        companions=tuple(
            (name, held[name]) for name in desktop.companions if name in held
        ),
        auto=tuple((name, held[name]) for name in desktop.auto_files if name in held),
        accessories=tuple(
            (name, held[name]) for name in desktop.accessories if name in held
        ),
        control_panel=tuple(
            (name, held[name]) for name in desktop.control_panel if name in held
        ),
        version=_version_from(archive),
        cookie_jar=held.get(COOKIE_JAR, b"") if desktop.cookie_jar else b"",
    )


def _from_disk(desktop: Desktop, image: Path) -> DesktopDistribution | None:
    """Read a distribution off one floppy image."""
    held = volume_files(image, _wanted_names(desktop))
    program = next((name for name in desktop.files if name in held), None)
    if program is None:
        return None
    return DesktopDistribution(
        desktop=desktop,
        name=program,
        payload=held[program],
        source=image,
        companions=tuple(
            (name, held[name]) for name in desktop.companions if name in held
        ),
        auto=tuple((name, held[name]) for name in desktop.auto_files if name in held),
        accessories=tuple(
            (name, held[name]) for name in desktop.accessories if name in held
        ),
        control_panel=tuple(
            (name, held[name]) for name in desktop.control_panel if name in held
        ),
        version=_version_from(image),
        cookie_jar=held.get(COOKIE_JAR, b"") if desktop.cookie_jar else b"",
    )


def _from_file(desktop: Desktop, path: Path) -> DesktopDistribution | None:
    """Read a distribution out of whatever single file it arrived as."""
    suffix = path.suffix.casefold()
    if suffix == ".zip":
        return _from_archive(desktop, path)
    if suffix in DISK_SUFFIXES:
        return _from_disk(desktop, path)
    return None


def find_desktop(desktop: Desktop, directories=None) -> DesktopDistribution | None:
    """Locate the operator's copy of one desktop, or report that it is absent.

    Nothing is fetched here. A desktop that is in none of the directories is
    simply not available, and saying so is the whole answer for the ones that
    are somebody's property.

    Both shapes a copy arrives in are read: unpacked into a folder, which is
    how a distribution is normally kept, and still inside the ZIP it was
    downloaded as, which is how it looks ten seconds after downloading it.
    """
    for directory in (directories if directories is not None else desktop_directories()):
        root = Path(directory)
        if root.is_file():
            found = _from_file(desktop, root)
            if found is not None:
                return found
            continue
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
            accessories = []
            for extra in desktop.accessories:
                beside = _find(Path(directory), extra)
                if beside is not None:
                    accessories.append((extra, beside.read_bytes()))
            control_panel = []
            for extra in desktop.control_panel:
                beside = _find(Path(directory), extra)
                if beside is not None:
                    control_panel.append((extra, beside.read_bytes()))
            jar = _find(Path(directory), COOKIE_JAR) if desktop.cookie_jar else None
            return DesktopDistribution(
                desktop=desktop,
                name=name,
                payload=found.read_bytes(),
                source=found,
                companions=tuple(companions),
                auto=tuple(auto),
                accessories=tuple(accessories),
                control_panel=tuple(control_panel),
                version=_version_from(found),
                cookie_jar=jar.read_bytes() if jar is not None else b"",
            )
        # Nothing unpacked, so try the archives sitting in the folder. This is
        # the case an operator lands in by choosing the folder their downloads
        # went to.
        if root.is_dir():
            try:
                bundles = sorted(
                    entry for entry in root.iterdir()
                    if entry.is_file()
                    and entry.suffix.casefold() in BUNDLE_SUFFIXES
                )
            except OSError:
                bundles = []
            for bundle in bundles:
                found = _from_file(desktop, bundle)
                if found is not None:
                    return found
    return None


def fetch_desktop(desktop: Desktop, destination: Path | None = None, opener=None) -> Path:
    """Download a freely licensed desktop into the operator's own directory.

    Only a desktop whose licence allows it is fetched, and the check is on the
    catalogue rather than on the request, so no caller can ask for one that is
    somebody's property.
    """
    if not desktop.free or not desktop.sources:
        raise DiskError(f"{desktop.label} cannot be downloaded. {desktop.licence}")
    return fetch_archive(
        desktop.label,
        [(source.label, source.url) for source in desktop.sources],
        Path(destination) if destination is not None else DESKTOP_DIR,
        desktop.folder or desktop.key,
        accepts=lambda archive: _from_archive(desktop, archive) is not None,
        opener=opener,
    )


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


def _start_up_notes(desktop: Desktop, started_from_auto: bool) -> list[str]:
    """What still has to happen before this desktop comes up on its own.

    Where the distribution's own installer puts a program in ``AUTO``, that is
    the answer and it has been done. NeoDesk is the awkward case: its loader
    goes in ``AUTO``, but Gribnif's script says plainly that whether it takes
    the place of the built-in desktop depends on the machine's ROM, and offers
    Geneva as the way to arrange it. Repeating that is more use than a warning
    written from guesswork.
    """
    if not started_from_auto:
        return [
            f"{desktop.label} is installed and on the desktop, but nothing "
            "starts it automatically: its distribution puts no program in "
            "AUTO. Start it from the desktop, or follow its own documentation "
            "for starting it at boot."
        ]
    notes = [
        f"{desktop.label} starts from the AUTO folder, which is where its own "
        "installer puts it. AUTO programs run in the order the folder holds "
        "them, so check that order if the machine does not come up as expected."
    ]
    if desktop.key == "desktop-neodesk":
        notes.append(
            "Whether NeoDesk takes the place of the built-in desktop rather "
            "than running alongside it depends on the machine's ROM version. "
            "Gribnif's own installer says so and offers Geneva as the way to "
            "arrange it, so install Geneva as well if that is what you want."
        )
    return notes


class DesktopReplacementMixin:
    """Installing a replacement desktop from the operator's own copy."""

    def available_desktops(self, directories=None) -> list[dict]:
        """Which replacement desktops can actually be installed, and why.

        A choice that cannot be carried out should not be offered as though it
        could, but "not here yet" and "not ours to fetch" are different
        answers. A free desktop with a source is offered whether or not a copy
        is present, because choosing it is what downloads it. One that is
        somebody's property is offered only when the operator has supplied it.

        ``directories`` overrides where copies are looked for, which is what a
        folder the operator chose for this one install arrives as.
        """
        found = [{
            "id": NO_DESKTOP,
            "available": True,
            "obtainable": True,
            "version": "",
            "source": "",
        }]
        for desktop in (*DESKTOPS, GENEVA):
            distribution = find_desktop(desktop, directories)
            here = distribution is not None
            found.append({
                "id": desktop.key,
                "available": here,
                # A free desktop with somewhere to download it from can be
                # chosen even when there is no copy yet, because choosing it
                # is what fetches it.
                "obtainable": here or bool(desktop.free and desktop.sources),
                "version": distribution.version if distribution else "",
                "source": str(distribution.source) if distribution else "",
            })
        return found

    #: How many desk accessories TOS loads from the root of the boot drive.
    #: The seventh and anything after it are ignored, silently, which is a
    #: thing worth being told about rather than discovering on the machine.
    MAX_ACCESSORIES = 6

    def _auto_order(self, session: ImageSession) -> list[str]:
        """The AUTO folder in the order TOS will run it."""
        try:
            with self.gemdos_mount(session, writable=False) as mount:
                return [
                    entry.name
                    for entry in mount.volume.iter_entries("AUTO")
                    if entry.name not in ("..", ".") and not entry.is_dir
                ]
        except Exception:
            return []

    def _accessory_warnings(self, session: ImageSession) -> list[str]:
        """Say so when the root now holds more accessories than TOS will load."""
        try:
            entries = self.list_directory(session, "").get("entries", [])
        except DiskError:
            return []
        accessories = [
            str(entry.get("name") or "")
            for entry in entries
            if entry.get("type") != "dir"
            and str(entry.get("name") or "").upper().endswith(".ACC")
        ]
        if len(accessories) <= self.MAX_ACCESSORIES:
            return []
        ignored = sorted(accessories)[self.MAX_ACCESSORIES:]
        return [
            f"This volume now has {len(accessories)} desk accessories in its "
            f"root and TOS loads only the first {self.MAX_ACCESSORIES}. "
            f"{', '.join(ignored)} will not be loaded. Rename the ones you "
            "want to something earlier in the alphabet, or move the rest out "
            "of the root until they are wanted."
        ]

    def install_desktop_replacement(
        self,
        session: ImageSession,
        key: str,
        *,
        on_desktop: bool = True,
        directories=None,
        download: bool = True,
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
        distribution = find_desktop(desktop, directories)
        downloaded = ""
        if distribution is None and download and desktop.free and desktop.sources:
            # Free, and somewhere to get it from, so get it. It lands in the
            # same directory the operator would have put their own copy in.
            archive = fetch_desktop(desktop)
            downloaded = desktop.sources[0].url
            distribution = find_desktop(desktop, [archive])
        if distribution is None:
            raise DiskError(
                f"No copy of {desktop.label} was found. {desktop.licence} "
                f"Put the files you own in {DESKTOP_DIR} or "
                f"{REPOSITORY_DESKTOP_DIR}, or choose the folder they are in."
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
        # AUTO programs run before GEM appears, in the order the directory
        # holds them, and that order is often the difference between a machine
        # that starts and one that does not. A program already there is left
        # exactly as it is, so a new one is added after it rather than taking
        # its place in the sequence. The one exception is the cookie jar
        # below, which the vendors' own installers put first.
        kept: list[str] = []
        for name, payload in distribution.auto:
            if not volume_copy.directory_exists(self, session, "AUTO"):
                self.make_directory(session, "AUTO")
            path = atari_paths.join("AUTO", name)
            if volume_copy.entry_exists(self, session, path):
                kept.append(path)
                continue
            volume_copy.write_file(self, session, path, payload)
            written.append(path)
        cookie_jar_notes: list[str] = []
        if distribution.cookie_jar:
            jar, installed, cookie_jar_notes = self._install_cookie_jar(
                session, distribution.cookie_jar
            )
            (written if installed else kept).append(jar)
        elif desktop.cookie_jar:
            cookie_jar_notes = [
                f"The copy of {desktop.label} used has no {COOKIE_JAR}, which "
                f"{desktop.label} needs in AUTO before it will start. It is on "
                "Gribnif's master disk; supply the whole disk rather than the "
                "program alone."
            ]

        # An accessory is loaded from the root of the boot drive and nowhere
        # else, so it cannot go in the program's folder however tidy that
        # would be. TOS loads only the first six it finds, which is why one
        # already installed is never replaced by this.
        for name, payload in distribution.accessories:
            if volume_copy.entry_exists(self, session, name):
                kept.append(name)
                continue
            volume_copy.write_file(self, session, name, payload)
            written.append(name)

        # Control panel modules belong in the folder XControl's own CPXPATH
        # names. CPX is the conventional one, and is what is used when the
        # volume has no XCONTROL.INF saying otherwise.
        for name, payload in distribution.control_panel:
            if not volume_copy.directory_exists(self, session, CPX_FOLDER):
                self.make_directory(session, CPX_FOLDER)
            path = atari_paths.join(CPX_FOLDER, name)
            if volume_copy.entry_exists(self, session, path):
                kept.append(path)
                continue
            volume_copy.write_file(self, session, path, payload)
            written.append(path)

        drive = self.partition_label(session) or "C"
        placed = self._install_on_desktop(
            session, program, label=desktop.label, on_desktop=on_desktop,
        )
        name, added = placed["file"], placed["records"]
        shell_notes = self._start_neodesk_under_geneva(session, drive)
        self._mark_mutated(session)
        self._persist_session(session)
        return {
            "id": desktop.key,
            "label": desktop.label,
            "installed": True,
            "version": distribution.version,
            "source": str(distribution.source),
            "downloadedFrom": downloaded,
            "folder": folder,
            "program": program,
            "files": written,
            # What was already on the drive and therefore left alone. An
            # operator who has tuned an AUTO folder or an accessory wants to
            # know it survived, and wants to know it was not installed.
            "kept": kept,
            # The order AUTO holds its programs in is the order they run, and
            # it is the thing most likely to need a look afterwards, so it is
            # reported rather than left to be discovered.
            "autoOrder": self._auto_order(session),
            "desktopFile": name,
            "records": added,
            "applications": placed["applications"],
            "warnings": self._accessory_warnings(session) + _start_up_notes(
                desktop, bool(distribution.auto)
            ) + cookie_jar_notes + shell_notes + placed["notes"],
        }

    def _install_cookie_jar(
        self, session: ImageSession, payload: bytes
    ) -> tuple[str, bool, list[str]]:
        """Put Gribnif's cookie jar manager at the front of AUTO.

        Both INSTALL.SCR scripts copy it in as JAR10.PRG, and NeoDesk's then
        moves it ahead of everything but XBOOT. One the operator already has,
        under whatever number, is left where it is: it may be where they want
        it, and a second jar would only make a second, smaller jar.
        """
        if not volume_copy.directory_exists(self, session, "AUTO"):
            self.make_directory(session, "AUTO")
        order = self._auto_order(session)
        present = next((name for name in order if _is_cookie_jar(name)), None)
        if present is not None:
            notes = []
            if _first_after_boot_managers(order) != present:
                notes.append(
                    f"AUTO already had {present}, which was left where it is. "
                    "NeoDesk and Geneva both expect the cookie jar to run before "
                    "any other AUTO program except XBOOT, so move it to the "
                    "front if either fails to start."
                )
            return atari_paths.join("AUTO", present), False, notes
        path = atari_paths.join("AUTO", COOKIE_JAR_INSTALLED)
        volume_copy.write_file(self, session, path, payload)
        self._run_first_in_auto(session, COOKIE_JAR_INSTALLED)
        return path, True, []

    def _run_first_in_auto(self, session: ImageSession, name: str) -> None:
        """Move one AUTO program ahead of the rest, as AUTOFRST does.

        TOS runs AUTO in the order the directory holds its entries. The engine
        has no call to reorder a directory, so the folder's programs are
        written back in the new order, each with its own bytes, attributes and
        datestamp; a rewritten entry takes the first free slot, so the order
        written is the order stored. A boot manager stays in front.
        """
        from atarinut.file import FA_READONLY

        with self.gemdos_mount(session, writable=True) as mount:
            volume = mount.volume
            names = [
                entry.name for entry in volume.iter_entries("AUTO")
                if not entry.is_dir and entry.name not in (".", "..")
            ]
            leading = [item for item in names if item in AUTO_BOOT_MANAGERS]
            wanted = leading + [name] + [
                item for item in names if item != name and item not in leading
            ]
            if wanted == names:
                return
            held = {}
            for item in names:
                path = f"AUTO\\{item}"
                meta = volume.atari_meta(path)
                held[item] = (volume.read_bytes(path), meta)
                if meta.attributes & FA_READONLY:
                    volume.set_access(path, meta.attributes & ~FA_READONLY)
                volume.remove(path)
            for item in wanted:
                data, meta = held[item]
                volume.write_bytes(f"AUTO\\{item}", data, meta)

    def _start_neodesk_under_geneva(self, session: ImageSession, drive: str) -> list[str]:
        """Have Geneva start NeoDesk as its desktop when both are on the drive.

        Geneva's installer asks whether NeoDesk is there and, if it is, writes
        ``shell`` and NeoDesk's path into GEM.CNF, which is how Geneva brings
        NeoDesk up when the machine starts. The file on the master disk has
        that line commented out. Installing either of the two second has to
        make the same change, or the drive boots to Geneva's bare menu bar.
        A shell line naming another program is somebody's choice and stays.
        """
        neodesk = DESKTOPS_BY_KEY["desktop-neodesk"]
        settings = atari_paths.join(GENEVA.folder, "GEM.CNF")
        program = atari_paths.join(neodesk.folder, "NEODESK.EXE")
        if not (
            volume_copy.entry_exists(self, session, settings)
            and volume_copy.entry_exists(self, session, program)
        ):
            return []
        target = f"{drive.rstrip(':') or 'C'}:\\{program}"
        text = self.read_file(session, settings).decode("latin-1")
        newline = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()
        active = [line for line in lines if _SHELL_LINE.match(line) and not line.lstrip().startswith("#")]
        if any(_SHELL_LINE.match(line).group("path").upper() == target.upper() for line in active):
            return []
        if active:
            return [
                f"Geneva's {settings} already starts {_SHELL_LINE.match(active[0]).group('path')} "
                "as its desktop, so it was left alone. Change that line to "
                f"shell {target} to have Geneva start NeoDesk instead."
            ]
        line = f"shell {target}"
        commented = next((index for index, item in enumerate(lines) if _SHELL_LINE.match(item)), None)
        if commented is None:
            lines.append(line)
        else:
            lines[commented] = line
        volume_copy.write_file(
            self, session, settings, (newline.join(lines) + newline).encode("latin-1")
        )
        return [
            f"Geneva will start NeoDesk as its desktop: {settings} now reads "
            f"\"{line}\", as Geneva's own installer writes it when NeoDesk is present."
        ]


__all__ = [
    "DESKTOPS",
    "DESKTOPS_BY_KEY",
    "DESKTOP_DIR",
    "Desktop",
    "DesktopDistribution",
    "EVERY_MACHINE",
    "MAX_DOWNLOAD_BYTES",
    "NO_DESKTOP",
    "Source",
    "fetch_desktop",
    "REPOSITORY_DESKTOP_DIR",
    "DesktopReplacementMixin",
    "describe_desktops",
    "desktop_directories",
    "desktop_for",
    "find_desktop",
    "recommended_desktop",
]
