r"""Preparing a hard drive: a driver where one is needed, and a desktop.

There is no operating system to install onto an Atari hard drive. TOS is in
ROM, and where the machine has no ROM of its own the bundled EmuTOS supplies
one, so a drive that has been partitioned and formatted already holds
everything TOS needs in order to read it. What it does *not* hold is the two
things that turn a formatted drive into a drive somebody can use:

* a **hard-disk driver**, because the ROM of an ST, STE or Mega STE cannot
  reach an ACSI, SCSI or IDE drive by itself. The driver is loaded from the
  drive's own root sector before anything else runs, which is why that sector
  has to be executable and why the driver file has to sit in the root of the
  first partition where the loader can find it;
* a **desktop configuration**, because the desktop shows what ``NEWDESK.INF``
  or ``DESKTOP.INF`` tells it to show. Without one, an installed title is a
  program in a folder that nobody has been told about.

The three choices this offers are the three that exist, and the difference
between them is what happens on real hardware:

**Driverless** is the default. Nothing is written to the root sector, and the
sector is left inert on purpose: EmuTOS reads ACSI, SCSI and IDE drives itself
and finds the partitions without help. A machine running its original TOS ROM
will not see the drive at all, and this says so rather than leaving it to be
discovered.

**A driver the operator supplies** is copied into the boot partition's root,
and where the distribution carries the boot code that belongs in the root
sector, that code is written and the checksum word recomputed so the sector's
sum is 0x1234, which is the only thing the ROM checks before it executes it.
Nothing is downloaded and nothing is bundled: AHDI, HDDRIVER, the PP driver
and the ICD driver are each somebody's copyright and none of them may be
redistributed here. EmuTOS is the one exception, and it is not a driver.

**A desktop configuration** is written, or merged into the one already there,
so an installed title has an icon and a program the desktop will start.

What the operator's real drives look like is what this reproduces. An
ICD-prepared ACSI drive has an executable root sector, an executable boot
sector on its first partition, ``ICDBOOT.SYS`` in that partition's root and
the driver distribution in a folder beside it. An AHDI-prepared IDE drive,
stored byte-swapped, is the same with ``SHDRIVER.SYS``. A drive carrying a PC
partition table has neither sector executable, because it boots through
EmuTOS's built-in support. All three are drives that work.
"""

from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path

from . import atari_paths, volume_copy
from . import progress as progress_module
from .errors import DiskError
from .image_session import ImageSession


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

#: Where an operator's own hard-disk drivers are looked for. Nothing is ever
#: written here and nothing is ever fetched into it; it is read only in the
#: plain sense that the application only reads it.
DRIVER_DIR = Path(
    os.environ.get(
        "ATARI_FILE_FORGE_DRIVER_DIR",
        Path.home() / ".config" / "atari-file-forge" / "drivers",
    )
)

#: The git-ignored directory beside the source where drivers may also be kept,
#: which is the same arrangement ``firmware/tos`` already has for TOS ROMs.
REPOSITORY_DRIVER_DIR = REPOSITORY_ROOT / "firmware" / "drivers"

#: The folders a prepared drive is expected to have. ``AUTO`` runs what is in
#: it before the desktop appears, ``GEMSYS`` is where GEM applications are
#: conventionally kept, and ``GAMES`` is where an installed title lands.
DEFAULT_FOLDERS = ("AUTO", "GEMSYS", "GAMES")

#: The two names the desktop reads its configuration from. TOS 1.x writes
#: ``DESKTOP.INF``; TOS 2.06 and later write ``NEWDESK.INF`` and fall back to
#: the older name. Both are found on the operator's drives.
NEWDESK = "NEWDESK.INF"
DESKTOP = "DESKTOP.INF"
DESKTOP_FILES = (NEWDESK, DESKTOP)

#: The boot code that belongs in the root sector occupies everything below the
#: drive size longword, which is where the AHDI table begins. Writing past it
#: would overwrite the partition entries.
ROOT_BOOT_CODE_LIMIT = 0x1C2

#: An ICD table keeps eight more partition entries lower in the same sector,
#: so ICD boot code has less room than AHDI boot code does.
ICD_BOOT_CODE_LIMIT = 0x156

#: File names a driver distribution uses for the 512 bytes that belong in the
#: root sector. A distribution that has none of these carries its boot code
#: inside its own installer, which this application does not run.
BOOT_CODE_NAMES = ("ROOTSECT.BIN", "BOOTSECT.BIN", "HDBOOT.BIN", "ROOTSECT.BOO")

#: How large that file has to be to be believed: exactly one sector.
SECTOR_SIZE = 512


@dataclasses.dataclass(frozen=True)
class Driver:
    """One hard-disk driver, and what installing it means on this drive."""

    key: str
    label: str
    #: The driver file, in the order the loader looks for it. The first name
    #: found in the operator's driver directory is the one installed.
    files: tuple[str, ...]
    #: Programs that belong in ``AUTO`` rather than in the partition root.
    auto_files: tuple[str, ...] = ()
    #: Whether this driver needs an executable root sector at all.
    boot_sector: bool = True
    note: str = ""


#: The drivers this recognises, and the one case that needs none. The keys are
#: the values the interface sends, so they are fixed.
DRIVERLESS = "driver-emutos-builtin"

DRIVERS: tuple[Driver, ...] = (
    Driver(
        DRIVERLESS,
        "None, boot driverless under EmuTOS",
        (),
        boot_sector=False,
        note="EmuTOS reads ACSI, SCSI and IDE drives itself and finds the "
             "partitions without a driver. Nothing is written to the root "
             "sector. A machine running its original TOS ROM will not see "
             "this drive.",
    ),
    Driver(
        "driver-ahdi",
        "Atari AHDI",
        ("SHDRIVER.SYS", "AHDI.SYS"),
        auto_files=("AHDI.PRG",),
        note="Atari's own driver. AHDI 6.0 loads SHDRIVER.SYS from the root "
             "sector; AHDI 3.0 is run from AUTO instead and is limited to "
             "16 MB partitions on TOS 1.x.",
    ),
    Driver(
        "driver-hddriver",
        "HDDRIVER",
        ("HDDRIVER.SYS",),
        note="Uwe Seimet's driver, the usual choice for large partitions and "
             "for modern interfaces such as ACSI2STM and UltraSatan.",
    ),
    Driver(
        "driver-pp",
        "PP driver",
        ("PPDRIVER.SYS", "PPDRIVER.PRG"),
        note="Peter Putnik's free driver for ACSI, SCSI and IDE drives.",
    ),
    Driver(
        "driver-icd",
        "ICD Pro driver",
        ("ICDBOOT.SYS",),
        note="Supplied with ICD host adapters, and it drives most other ACSI "
             "hardware as well.",
    ),
)

DRIVERS_BY_KEY = {driver.key: driver for driver in DRIVERS}

#: Every driver file name any recognised driver uses, for reading a drive that
#: was prepared somewhere else and saying which driver is on it.
_FILE_OWNERS = {
    name.casefold(): driver
    for driver in DRIVERS
    for name in (*driver.files, *driver.auto_files)
}

#: A driver distribution normally sits in a folder named after itself and its
#: release: ``ICDPRO_6.55A`` beside ``ICDBOOT.SYS``, ``AHDI_6.061`` beside
#: ``SHDRIVER.SYS``. That folder is where the version comes from, because the
#: driver file itself carries no version anything can read.
_VERSION_IN_FOLDER = re.compile(r"[_-]v?([0-9]+(?:\.[0-9]+)*[A-Za-z]?)$")


def describe_drivers() -> list[dict]:
    """The driver choices, for an interface that has to explain them."""
    return [
        {
            "id": driver.key,
            "label": driver.label,
            "files": list(driver.files),
            "autoFiles": list(driver.auto_files),
            "bootSector": driver.boot_sector,
            "note": driver.note,
        }
        for driver in DRIVERS
    ]


def driver_for(key: str) -> Driver:
    """The driver a request named, or a refusal that lists the choices."""
    chosen = DRIVERS_BY_KEY.get(str(key or DRIVERLESS).strip())
    if chosen is None:
        raise DiskError(
            f"{key} is not a hard-disk driver this recognises. Choose one of: "
            + ", ".join(driver.key for driver in DRIVERS)
            + "."
        )
    return chosen


def driver_directories() -> list[Path]:
    """Where an operator's own drivers are looked for, in order."""
    return [DRIVER_DIR, REPOSITORY_DRIVER_DIR]


# ---------------------------------------------------------------------------
# The operator's own copy of a driver
# ---------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class Distribution:
    """One driver as the operator supplied it, ready to be copied in."""

    driver: Driver
    #: The driver file itself: its GEMDOS name and its bytes.
    name: str
    payload: bytes
    #: Where it was found, so a report can say which copy was used.
    source: Path
    #: Files that belong in ``AUTO``, by GEMDOS name.
    auto: tuple[tuple[str, bytes], ...] = ()
    #: The 512 bytes that belong in the root sector, when the distribution
    #: carries them. Most do not: the boot code lives inside the driver's own
    #: installer, which is Atari code this application does not run.
    boot_code: bytes | None = None
    #: The release, read from the folder the distribution was found in.
    version: str = ""


def _version_from(path: Path) -> str:
    for candidate in (path.parent, path):
        match = _VERSION_IN_FOLDER.search(candidate.name)
        if match:
            return match.group(1)
    return ""


def _find(directory: Path, name: str) -> Path | None:
    """Find one file by name, in this directory or one level below it.

    A driver is unpacked as it was published, which means the files usually
    arrive inside the distribution's own folder rather than loose. Looking one
    level down means the operator does not have to flatten anything.
    """
    if not directory.is_dir():
        return None
    wanted = name.casefold()
    try:
        for entry in sorted(directory.iterdir()):
            if entry.is_file() and entry.name.casefold() == wanted:
                return entry
        for entry in sorted(directory.iterdir()):
            if not entry.is_dir():
                continue
            for child in sorted(entry.iterdir()):
                if child.is_file() and child.name.casefold() == wanted:
                    return child
    except OSError:
        return None
    return None


def find_distribution(driver: Driver, directories=None) -> Distribution | None:
    """Locate the operator's copy of one driver, or report that it is absent.

    Nothing is fetched. A driver that is not in one of the directories is
    simply not available, and saying so is the whole answer: this application
    has no lawful way of producing one.
    """
    if not driver.files and not driver.auto_files:
        return None
    for directory in (directories if directories is not None else driver_directories()):
        for name in driver.files:
            found = _find(Path(directory), name)
            if found is None:
                continue
            auto = []
            for extra in driver.auto_files:
                companion = _find(Path(directory), extra)
                if companion is not None:
                    auto.append((extra, companion.read_bytes()))
            boot_code = None
            for candidate in BOOT_CODE_NAMES:
                sector = _find(Path(directory), candidate)
                if sector is not None and sector.stat().st_size == SECTOR_SIZE:
                    boot_code = sector.read_bytes()
                    break
            return Distribution(
                driver=driver,
                name=name,
                payload=found.read_bytes(),
                source=found,
                auto=tuple(auto),
                boot_code=boot_code,
                version=_version_from(found),
            )
    return None


def installed_driver(names, folders=()) -> dict:
    """Which driver a drive already carries, read off the partition root.

    The evidence is the driver file itself. The release comes from the folder
    the distribution was copied in as, because that is where both of the
    operator's own drives record it and the driver file says nothing.
    """
    for name in names:
        owner = _FILE_OWNERS.get(str(name).casefold())
        if owner is None:
            continue
        version = ""
        for folder in folders:
            match = _VERSION_IN_FOLDER.search(str(folder))
            if match:
                version = match.group(1)
                break
        return {"id": owner.key, "installed": True, "version": version, "file": str(name)}
    return {"id": DRIVERLESS, "installed": False, "version": "", "file": ""}


# ---------------------------------------------------------------------------
# The desktop configuration
# ---------------------------------------------------------------------------
#: The record letters that install an application, keyed by the extension of
#: the program each one starts. The desktop reads the extension and nothing
#: else, so a program's name has to agree with the record that installs it.
APPLICATION_RECORDS = {
    "PRG": "G",
    "APP": "G",
    "TOS": "F",
    "TTP": "P",
    "GTP": "Y",
}

#: The order records are written in. The desktop reads the file from the top
#: and the operator's own drives are in exactly this order, so a merged file
#: stays a file that TOS and a person both recognise.
RECORD_ORDER = ("a", "b", "c", "d", "K", "E", "Q", "W", "N", "D", "G", "Y", "P", "F", "M", "T", "X")

#: The header the desktop writes for itself: video and colour settings, the
#: keyboard table, the desktop preferences and the window positions. These are
#: taken verbatim from a working drive rather than invented, because a machine
#: that cannot parse them falls back to a desktop with nothing on it.
DEFAULT_HEADER = (
    "#a000000",
    "#b000000",
    "#c7770007000600070055200505552220770557075055507703111103",
    "#d" + " " * 45,
    "#K 4F 53 4C 00 46 42 43 57 45 58 00 00 00 00 00 00 00 00 00 00 00 00 00 52 00 00 4D 56 50 00 @",
    "#E 98 02 00 06 ",
    "#Q 41 40 43 40 43 40 ",
    "#W 00 00 00 01 21 16 00 @",
)

#: The document types every desktop installs, so a folder opens as a folder
#: and a program runs rather than being offered to an editor.
DEFAULT_TYPES = (
    "#N FF 04 000 @ *.*@ @ ",
    "#D FF 01 000 @ *.*@ @ ",
    "#G 03 FF 000 *.APP@ @ @ ",
    "#G 03 FF 000 *.PRG@ @ @ ",
    "#Y 03 FF 000 *.GTP@ @ @ ",
    "#P 03 FF 000 *.TTP@ @ @ ",
    "#F 03 04 000 *.TOS@ @ @ ",
)


def default_desktop(drive: str = "C") -> str:
    """A desktop configuration for a drive that has none.

    The drive letter is the one the boot partition will answer to, which is
    ``C`` on every machine that boots from a hard disk.
    """
    letter = (str(drive or "C").strip().rstrip(":") or "C")[0].upper()
    icons = (
        f"#M 00 01 00 FF {letter} HARD DISK@ @ ",
        "#M 00 00 09 FF A FLOPPY@ @ ",
        "#M 01 00 09 FF B FLOPPY@ @ ",
        "#T 00 03 02 FF   TRASH@ @ ",
    )
    return "\r\n".join([*DEFAULT_HEADER, *DEFAULT_TYPES, *icons]) + "\r\n"


def desktop_records(text: str) -> list[str]:
    """Every record in a desktop configuration, in the order it holds them."""
    return [line for line in re.split(r"\r\n|\r|\n", str(text or "")) if line.startswith("#")]


def record_letter(record: str) -> str:
    """The single letter that says what a record does."""
    return record[1:2] if len(record) > 1 else ""


def _fields(record: str) -> list[str]:
    """The ``@``-terminated fields of a record, in order."""
    return [part for part in record.split("@")]


#: A record's leading numbers differ between the two spellings of the file:
#: ``NEWDESK.INF`` writes three before the path and ``DESKTOP.INF`` two, and a
#: desktop icon writes four and a drive-letter field that may be a space. What
#: does not differ is that the path is the last thing before the first ``@``
#: and that a GEMDOS name can never contain a space, so that is what is read.
_NAMES_A_FILE = re.compile(r"^(?:[A-Za-z]:|.*[\\*?.])")


def record_path(record: str) -> str:
    r"""The path or mask an install record names, upper case and unpadded.

    ``#G 03 FF 000 C:\GAMES\X\X.PRG@ @ @`` installs that program;
    ``#G 03 FF 000 *.PRG@ @ @`` associates an extension instead. A record whose
    last field before the ``@`` is one of the leading numbers, which is what a
    ``#N`` or ``#D`` record has, names nothing and is reported as naming
    nothing.
    """
    if record_letter(record) not in set(APPLICATION_RECORDS.values()) | {"X"}:
        return ""
    head = record.split("@", 1)[0].split()
    if len(head) < 3:
        return ""
    candidate = head[-1].strip().upper()
    return candidate if _NAMES_A_FILE.match(candidate) else ""


def is_installed_application(record: str) -> bool:
    """Whether a record installs one named program rather than an extension."""
    if record_letter(record) not in APPLICATION_RECORDS.values():
        return False
    path = record_path(record)
    return bool(path) and "*" not in path and "?" not in path


def application_record(program: str, *, documents: str = "", drive: str = "C") -> str:
    r"""The record that installs one program, chosen by its own extension.

    The desktop decides how to start a program from its extension: a ``.TTP``
    is asked for a command line, a ``.TOS`` runs without GEM, a ``.PRG`` or
    ``.APP`` runs with it. Installing one under the wrong record is how a
    program ends up started in the wrong environment, so the extension picks
    the record rather than the caller.
    """
    path = str(program or "").strip()
    if not path:
        raise DiskError("Name the program the desktop should install.")
    extension = path.rsplit(".", 1)[-1].upper() if "." in atari_paths.leaf(path) else ""
    letter = APPLICATION_RECORDS.get(extension)
    if letter is None:
        raise DiskError(
            f"{atari_paths.leaf(path)} is not a program the desktop can install. "
            "A desktop application is a .PRG, .APP, .TOS, .TTP or .GTP."
        )
    full = _absolute(path, drive)
    mask = str(documents or "").strip().upper()
    return f"#{letter} 03 FF 000 {full}@ {mask}@ @ "


def desktop_icon_record(path: str, label: str, *, position=(2, 1), drive: str = "C") -> str:
    r"""The record that puts one file or folder on the desktop itself.

    ``#X`` is what the operator's own drive uses to keep ``C:\GAMES.TXT`` on
    the desktop, and the same record puts an installed title's program there.
    """
    column, row = position
    name = (str(label or atari_paths.leaf(path)).strip().upper())[:12] or "PROGRAM"
    return f"#X {column:02X} {row:02X} 04 FF   {_absolute(path, drive)}@ {name}@ "


def _absolute(path: str, drive: str) -> str:
    r"""Spell a path the way a desktop record does: ``C:\GAMES\X\X.PRG``."""
    text = str(path or "").strip()
    if re.match(r"^[A-Za-z]:", text):
        return text.upper()
    letter = (str(drive or "C").strip().rstrip(":") or "C")[0].upper()
    return f"{letter}:{atari_paths.SEPARATOR}{atari_paths.normalise(text).upper()}"


def merge_desktop(existing: str, additions) -> tuple[str, list[str]]:
    """Add records to a desktop configuration without disturbing the rest.

    A drive an operator has been using has a desktop they arranged: window
    positions, drive icons, a trash can where they put it. Rewriting that to
    install one title would be a poor trade, so each new record is inserted
    beside the records of its own kind, and a record naming the same program
    replaces the one already there rather than being added a second time.
    """
    records = desktop_records(existing) or desktop_records(default_desktop())
    added: list[str] = []
    for record in additions:
        letter = record_letter(record)
        path = record_path(record)
        replaced = False
        for position, current in enumerate(records):
            if record_letter(current) == letter and path and record_path(current) == path:
                records[position] = record
                replaced = True
                break
        if replaced:
            added.append(record)
            continue
        # An installed application goes above the extension associations of
        # its own letter, because the desktop takes the first record that
        # matches and a ``*.PRG`` association would otherwise swallow it.
        insert_at = len(records)
        for position, current in enumerate(records):
            if record_letter(current) == letter:
                insert_at = position
                break
        else:
            order = {name: index for index, name in enumerate(RECORD_ORDER)}
            rank = order.get(letter, len(RECORD_ORDER))
            insert_at = next(
                (
                    position
                    for position, current in enumerate(records)
                    if order.get(record_letter(current), len(RECORD_ORDER)) > rank
                ),
                len(records),
            )
        records.insert(insert_at, record)
        added.append(record)
    return "\r\n".join(records) + "\r\n", added


def installed_applications(text: str) -> list[dict]:
    """Every program a desktop configuration installs, with its record."""
    found = []
    for record in desktop_records(text):
        if not is_installed_application(record):
            continue
        fields = _fields(record)
        found.append({
            "record": record_letter(record),
            "path": record_path(record),
            "documents": fields[1].strip().upper() if len(fields) > 1 else "",
        })
    return found


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------
class DrivePreparationMixin:
    """Read what a drive has been prepared with, and prepare one."""

    # -- reading -------------------------------------------------------
    def _drive_sectors(self, session: ImageSession, *, writable: bool = False):
        """Open the drive's own sector 0, undoing a byte swap if there is one.

        A drive imaged through a byte-swapping IDE adapter holds every word
        with its bytes exchanged, so the root sector only makes sense once the
        swap is undone, and a sector written back has to be swapped again. One
        reader does both, which is why nothing above this has to know.
        """
        try:
            from atarinut.filesystem import reader_for
            from atarinut.filesystem.ahdi import read_partition_table
            from atarinut.filesystem.blocks import ByteSwappedReader
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise DiskError("The Atarinut partition-table API is unavailable.") from exc
        if session.kind != "hd":
            raise DiskError(
                "A hard-disk driver is written to the root sector of a drive, so "
                "this needs a partitioned hard-disk image."
            )
        probe = reader_for(session.path, writable=False)
        try:
            disk = read_partition_table(probe)
        except Exception as exc:
            raise DiskError(self._friendly_engine_error(str(exc))) from exc
        finally:
            probe.close()
        if disk.byte_swapped:
            return ByteSwappedReader(session.path, writable=writable), disk
        return reader_for(session.path, writable=writable), disk

    def drive_preparation(self, session: ImageSession) -> dict:
        """What this drive has been prepared with, read off the drive itself.

        Everything reported here is evidence rather than a record kept
        elsewhere: whether the ROM would execute the root sector, whether it
        would execute the boot partition's boot sector, which driver file is
        in that partition's root and which desktop configuration is beside it.
        A drive prepared on another machine reports as accurately as one
        prepared here.
        """
        from atarinut.filesystem.blocks import is_executable_sector

        reader, disk = self._drive_sectors(session)
        try:
            root = reader.read_block(0)
        finally:
            reader.close()

        state = {
            "scheme": disk.scheme,
            "byteSwapped": bool(disk.byte_swapped),
            "rootSectorExecutable": is_executable_sector(root),
            "partitions": len(disk.partitions),
            "bootPartition": None,
            "bootSectorExecutable": False,
            "driver": {"id": DRIVERLESS, "installed": False, "version": "", "file": ""},
            "desktop": [],
            "folders": [],
            "drivers": describe_drivers(),
            "available": self.available_drivers(),
        }
        if not disk.partitions:
            return state

        index = session.partition if session.partition is not None else 0
        state["bootPartition"] = index
        listing = self._boot_partition_listing(session, index)
        if listing is None:
            return state
        names, folders, boot_executable = listing
        state["bootSectorExecutable"] = boot_executable
        state["driver"] = installed_driver(names, folders)
        state["desktop"] = [name for name in names if name.upper() in DESKTOP_FILES]
        state["folders"] = [name for name in folders if name.upper() in DEFAULT_FOLDERS]
        return state

    def _boot_partition_listing(self, session: ImageSession, index: int):
        """The root of one partition: its files, its folders and its boot flag."""
        previous = session.partition
        try:
            if previous != index:
                self.select_partition(session, index)
            entries = self.list_directory(session, atari_paths.ROOT).get("entries", [])
            names = [str(row.get("name") or "") for row in entries if row.get("type") != "dir"]
            folders = [str(row.get("name") or "") for row in entries if row.get("type") == "dir"]
            with self.gemdos_mount(session, writable=False) as mount:
                boot = bool(mount.boot_option())
        except DiskError:
            return None
        finally:
            if previous != index:
                self.select_partition(session, previous)
        return names, folders, boot

    def available_drivers(self) -> list[dict]:
        """Which drivers the operator has actually supplied a copy of.

        A choice that cannot be carried out should not be offered as though it
        could, and the reason a driver is missing is always the same: it is
        not redistributable, so the operator has to put their own copy in one
        of these directories.
        """
        found = []
        for driver in DRIVERS:
            if driver.key == DRIVERLESS:
                found.append({"id": driver.key, "available": True, "version": "", "source": ""})
                continue
            distribution = find_distribution(driver)
            found.append({
                "id": driver.key,
                "available": distribution is not None,
                "version": distribution.version if distribution else "",
                "source": str(distribution.source) if distribution else "",
            })
        return found

    # -- writing -------------------------------------------------------
    def prepare_drive(
        self,
        session: ImageSession,
        *,
        driver: str = DRIVERLESS,
        create_folders: bool = True,
        desktop: bool = True,
        progress: progress_module.Progress | None = None,
    ) -> dict:
        """Prepare this drive to be booted, in whichever of the three ways.

        Files already on the volume are left alone. An operator who has been
        building a drive does not expect preparing it to throw work away, and
        preparing a drive twice should not undo what was done in between.
        """
        report = progress_module.reporter(progress)
        chosen = driver_for(driver)
        self.require_writable_geometry(session)
        if self.summary(session).get("readOnly"):
            raise DiskError(f"{session.name} is open read-only, so it cannot be prepared.")

        reader, disk = self._drive_sectors(session, writable=True)
        try:
            if not disk.partitions:
                raise DiskError(
                    "This drive has no partitions, so there is nowhere to put a "
                    "driver or a desktop. Partition and format it first."
                )
            index = session.partition if session.partition is not None else 0
            report("Preparing the drive", 0, 4)
            installed = self._write_root_sector(reader, disk, chosen, report)
        finally:
            reader.close()

        previous = session.partition
        if previous != index:
            self.select_partition(session, index)
        try:
            report("Installing the driver", 1, 4)
            files = self._install_driver_files(session, chosen, installed)
            report("Creating the folders a prepared drive expects", 2, 4)
            folders = self._create_folders(session) if create_folders else []
            report("Writing the desktop configuration", 3, 4)
            desktop_written = self._write_desktop(session) if desktop else []
        finally:
            if previous != index:
                self.select_partition(session, previous)

        self._mark_mutated(session)
        self._persist_session(session)
        report("Drive prepared", 4, 4)
        state = self.drive_preparation(session)
        return {
            "driver": {
                "id": chosen.key,
                "installed": bool(files),
                "version": installed.version if installed else "",
            },
            "label": chosen.label,
            "files": files,
            "folders": folders,
            "desktop": desktop_written,
            "rootSectorExecutable": state["rootSectorExecutable"],
            "state": state,
            "warnings": self._preparation_warnings(chosen, installed, state),
        }

    def _write_root_sector(self, reader, disk, chosen: Driver, report) -> Distribution | None:
        """Make the root sector executable, or leave it inert on purpose.

        The ROM executes a root sector when its 256 big-endian words sum to
        0x1234 and not otherwise, so the checksum word is the whole mechanism.
        Boot code is written only where the distribution carries it: this
        application will not fabricate a loader for a driver it does not have.
        """
        from atarinut.filesystem.blocks import apply_boot_checksum

        if disk.scheme == "mbr":
            # A PC partition table occupies the bytes an Atari loader would
            # need, and a drive that carries one boots through EmuTOS's own
            # support. Writing boot code over the table would lose the
            # partitions for the sake of a loader nothing would run.
            if chosen.key != DRIVERLESS:
                raise DiskError(
                    "This drive carries a PC partition table, which leaves no room "
                    "for an Atari boot loader. A drive prepared this way boots "
                    "through EmuTOS's built-in support, so choose the driverless "
                    "preparation for it."
                )
            return None

        sector = bytearray(reader.read_block(0))
        if chosen.key == DRIVERLESS:
            apply_boot_checksum(sector, False)
            reader.write_block(0, bytes(sector))
            reader.flush()
            return None

        distribution = find_distribution(chosen)
        if distribution is None:
            raise DiskError(
                f"No copy of {chosen.label} was found. Put the driver's own files in "
                + " or ".join(str(path) for path in driver_directories())
                + ". Atari File Forge cannot ship or fetch a hard-disk driver: only "
                "EmuTOS may be redistributed here."
            )
        if distribution.boot_code:
            report(f"Writing the {chosen.label} boot loader", 0, 4)
            limit = ICD_BOOT_CODE_LIMIT if disk.scheme == "icd" else ROOT_BOOT_CODE_LIMIT
            sector[:limit] = distribution.boot_code[:limit]
            apply_boot_checksum(sector, True)
            reader.write_block(0, bytes(sector))
            reader.flush()
        return distribution

    def _install_driver_files(
        self, session: ImageSession, chosen: Driver, distribution: Distribution | None
    ) -> list[str]:
        """Copy the driver into the boot partition's root, where it is looked for."""
        if distribution is None:
            return []
        written = [distribution.name]
        volume_copy.write_file(self, session, distribution.name, distribution.payload)
        for name, payload in distribution.auto:
            if not volume_copy.directory_exists(self, session, "AUTO"):
                self.make_directory(session, "AUTO")
            path = atari_paths.join("AUTO", name)
            volume_copy.write_file(self, session, path, payload)
            written.append(path)
        return written

    def _create_folders(self, session: ImageSession) -> list[str]:
        created = []
        for folder in DEFAULT_FOLDERS:
            if volume_copy.directory_exists(self, session, folder):
                continue
            try:
                self.make_directory(session, folder)
            except DiskError:
                continue
            created.append(folder)
        return created

    def _write_desktop(self, session: ImageSession) -> list[str]:
        """Give the volume a desktop configuration if it has none.

        A drive that already has one keeps it. The arrangement on a working
        drive is the operator's own and replacing it would be a poor trade for
        a file that only has to exist.
        """
        present = [
            name for name in DESKTOP_FILES
            if volume_copy.entry_exists(self, session, name)
        ]
        if present:
            return present
        drive = self.partition_label(session) or "C"
        volume_copy.write_file(self, session, NEWDESK, default_desktop(drive).encode("latin-1"))
        return [NEWDESK]

    def install_desktop_application(
        self,
        session: ImageSession,
        program: str,
        *,
        documents: str = "",
        label: str = "",
        on_desktop: bool = True,
    ) -> dict:
        """Install one program in the desktop configuration, and show it.

        This is what makes an installed title something a person can start.
        Copying its files onto the drive puts them there; this is what puts
        them on the desktop and tells GEM how to run them.
        """
        self.require_mounted_volume(session)
        self.require_writable_geometry(session)
        if not volume_copy.entry_exists(self, session, program):
            raise DiskError(f"{atari_paths.display(program)} is not on this volume.")
        drive = self.partition_label(session) or "C"
        name = next(
            (item for item in DESKTOP_FILES if volume_copy.entry_exists(self, session, item)),
            NEWDESK,
        )
        try:
            existing = self.read_file(session, name).decode("latin-1")
        except DiskError:
            existing = default_desktop(drive)
        records = [application_record(program, documents=documents, drive=drive)]
        if on_desktop:
            records.append(desktop_icon_record(program, label, drive=drive))
        merged, added = merge_desktop(existing, records)
        volume_copy.write_file(self, session, name, merged.encode("latin-1"))
        self._mark_mutated(session)
        self._persist_session(session)
        return {"file": name, "records": added, "applications": installed_applications(merged)}

    @staticmethod
    def _preparation_warnings(
        chosen: Driver, distribution: Distribution | None, state: dict
    ) -> list[str]:
        """Reasons this drive may still not start, said plainly."""
        warnings: list[str] = []
        if chosen.key == DRIVERLESS:
            warnings.append(
                "No driver was installed, so this drive boots only on a machine "
                "running EmuTOS, which reads ACSI, SCSI and IDE drives itself. A "
                "machine running its original TOS ROM needs a hard-disk driver "
                "and will not see this drive without one."
            )
        elif distribution is not None and not distribution.boot_code:
            warnings.append(
                f"{distribution.name} was copied into the root of the boot partition, "
                f"but the {chosen.label} distribution carries no root-sector loader "
                "this application can write, so the root sector was left as it was. "
                "Run the driver's own installation program once on the machine, or "
                "in the emulator, to write the loader."
            )
        if state.get("scheme") == "mbr":
            warnings.append(
                "This drive carries a PC partition table rather than an Atari one, "
                "so it is read by EmuTOS's built-in support and by TOS 4 and MiNT, "
                "and not by an ST or STE running its original ROM."
            )
        return warnings


__all__ = [
    "APPLICATION_RECORDS",
    "BOOT_CODE_NAMES",
    "DEFAULT_FOLDERS",
    "DESKTOP",
    "DESKTOP_FILES",
    "DRIVERLESS",
    "DRIVERS",
    "DRIVERS_BY_KEY",
    "DRIVER_DIR",
    "NEWDESK",
    "REPOSITORY_DRIVER_DIR",
    "Distribution",
    "Driver",
    "DrivePreparationMixin",
    "application_record",
    "default_desktop",
    "describe_drivers",
    "desktop_icon_record",
    "desktop_records",
    "driver_directories",
    "driver_for",
    "find_distribution",
    "installed_applications",
    "installed_driver",
    "is_installed_application",
    "merge_desktop",
    "record_letter",
    "record_path",
]
