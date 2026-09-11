"""Managed emulator selection and command construction.

The workbench can hand an image to an emulator so a change can be watched
running rather than only inspected. Hatari is the one supported emulator: it
covers every machine from a 520ST to a Falcon030, it takes floppies, hard
drives and host folders alike, and it is driven entirely from the command
line, which is what makes a test run repeatable and scriptable on every
platform this application runs on.

Firmware is looked for in two places. A real TOS ROM the operator supplies is
preferred, because it is what the software was written against. When none is
found the bundled EmuTOS boots the machine instead: it is GPL, it is committed
under ``firmware/emutos/``, and it means a profile is never stuck at a black
screen just because a ROM that cannot be redistributed is absent.

Every command is an argv list. Nothing that came from a profile or a filename
is ever passed through a shell.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from atarinut.tosrom import is_tos_rom

from .hardware_profiles import profile_addons


@dataclass(frozen=True)
class ManagedEmulator:
    identifier: str
    label: str
    executable: str
    debugger: str
    platforms: tuple[str, ...]

    @property
    def available(self) -> bool:
        return Path(self.executable).is_file() or shutil.which(self.executable) is not None


@dataclass(frozen=True)
class Firmware:
    """One ROM the emulator can boot, and why it was the one chosen."""

    path: Path
    kind: str  # "tos" or "emutos"
    label: str
    reason: str


HATARI_ROOT = Path(os.environ.get("ATARI_HATARI_ROOT", "/usr/bin"))

#: The names Hatari is installed under. The Debian package provides hatari; a
#: Snap exposes it as hatari.hatari, and a Flatpak through its wrapper script.
#: An installation that works from a terminal should work here, so all of them
#: are looked for rather than only the Debian spelling.
HATARI_EXECUTABLE_NAMES = ("hatari", "hatari.hatari", "org.tuxfamily.hatari")


def _hatari_executable() -> str:
    """Locate Hatari, or return the conventional path so the error names it.

    ``ATARI_HATARI_EXECUTABLE`` names one exact binary and wins outright, which
    is what a build or a test needs. Otherwise the configured root is tried
    first, then PATH, under each name a packaging format uses.
    """
    override = os.environ.get("ATARI_HATARI_EXECUTABLE", "").strip()
    if override:
        return override
    for name in HATARI_EXECUTABLE_NAMES:
        candidate = HATARI_ROOT / name
        if candidate.is_file():
            return str(candidate)
    for name in HATARI_EXECUTABLE_NAMES:
        found = shutil.which(name)
        if found:
            return found
    return str(HATARI_ROOT / "hatari")


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

#: Where an operator's own TOS ROMs are looked for first. Nothing is copied
#: out of it and nothing is ever written to it.
TOS_DIR = Path(
    os.environ.get(
        "ATARI_FILE_FORGE_TOS_DIR",
        Path.home() / ".config" / "atari-file-forge" / "tos",
    )
)

#: The git-ignored directory beside the source where ROMs may also be kept.
REPOSITORY_TOS_DIR = REPOSITORY_ROOT / "firmware" / "tos"

#: The bundled EmuTOS images. These are committed, because EmuTOS is GPL.
EMUTOS_DIR = REPOSITORY_ROOT / "firmware" / "emutos"

#: The Hatari debugger script run by ``--parse`` when a debug session starts.
DEBUGGER_SCRIPT = REPOSITORY_ROOT / "app" / "hatari-debugger.txt"

ALL_MACHINES = ("st", "megast", "ste", "megaste", "tt030", "falcon030")

EMULATORS = {
    "hatari": ManagedEmulator(
        "hatari", "Hatari",
        _hatari_executable(), "hatari --debug", ALL_MACHINES,
    ),
}

#: Hatari's ``--machine`` value for each workbench machine.
HATARI_MACHINES = {
    "st": "st", "megast": "megast", "ste": "ste", "megaste": "megaste",
    "tt030": "tt", "falcon030": "falcon",
}

#: The TOS releases each machine shipped with, newest first. A newer release
#: is the better default because it carries the fixes, and any of them is a
#: ROM the machine really booted.
TOS_NAMES = {
    "st": ("tos104", "tos102", "tos100"),
    "megast": ("tos104", "tos102"),
    "ste": ("tos162", "tos106"),
    "megaste": ("tos206", "tos205"),
    "tt030": ("tos306",),
    "falcon030": ("tos404", "tos402", "tos400"),
}

#: The TOS release each firmware add-on asks for, by file stem.
TOS_ADDONS = {
    "tos-100": ("tos100",), "tos-102": ("tos102",), "tos-104": ("tos104",),
    "tos-106": ("tos106",), "tos-162": ("tos162",), "tos-205": ("tos205",),
    "tos-206": ("tos206",), "tos-306": ("tos306",),
    "tos-4xx": ("tos404", "tos402", "tos400"),
}

#: The language variants tried first. A UK ROM is a PAL machine with an
#: English desktop, a US ROM is the NTSC one; any other language is accepted
#: after those, because a German TOS 1.04 is still TOS 1.04.
TOS_LANGUAGES = ("uk", "us")

#: The EmuTOS build each machine takes. The 192 KiB build knows only the ST
#: and Mega ST hardware, the 256 KiB build adds the STE, and the 512 KiB build
#: is the one with TT and Falcon support.
EMUTOS_SIZES = {
    "st": "192", "megast": "192", "ste": "256", "megaste": "256",
    "tt030": "512", "falcon030": "512",
}

#: Media Hatari can attach directly.
FLOPPY_SUFFIXES = {".st", ".msa", ".stx", ".dim", ".ipf", ".hfe", ".zip"}
DRIVE_SUFFIXES = {".img", ".hd", ".ahd", ".acsi", ".ide", ".raw", ".bin", ".vhd"}

#: A: and B:. The machine has one internal drive and one floppy port, and
#: Hatari exposes exactly those two.
MAXIMUM_FLOPPY_DRIVES = 2

#: The most CD drives any managed machine attaches. Only the SCSI machines can
#: take one at all; see :func:`cd_drives_for`.
MAXIMUM_CD_DRIVES = 1

#: Hatari's ``--memsize`` takes 0 for 512 KiB, 1 to 14 for whole MiB, and any
#: larger number as KiB; that last form is how 2.5 MiB is written.
MEMSIZE_VALUES = {
    "512K": "0", "1M": "1", "2M": "2", "2.5M": "2560", "4M": "4", "8M": "8", "14M": "14",
}
MEMORY_ADDONS = {
    "ram-512k": "512K", "ram-1m": "1M", "ram-2m": "2M", "ram-2.5m": "2.5M",
    "ram-4m": "4M", "ram-14m": "14M",
}
DEFAULT_MEMORY = {
    "st": "512K", "megast": "1M", "ste": "1M", "megaste": "1M", "tt030": "2M", "falcon030": "4M",
}

#: Processor and clock as Hatari's ``--cpulevel`` (0 for a 68000, 3 for a
#: 68030) and ``--cpuclock`` in MHz.
PROCESSORS = {
    "st": ("0", "8"), "megast": ("0", "8"), "ste": ("0", "8"), "megaste": ("0", "16"),
    "tt030": ("3", "32"), "falcon030": ("3", "16"),
}

DEFAULT_MONITOR = {
    "st": "rgb", "megast": "rgb", "ste": "rgb", "megaste": "rgb", "tt030": "vga", "falcon030": "vga",
}
MONITOR_ADDONS = {
    "monitor-mono": "mono", "monitor-colour": "rgb", "monitor-vga": "vga", "tv-modulator": "tv",
}

ACSI_ADDONS = {"acsi-megafile", "acsi-third-party", "acsi2stm", "ultrasatan", "cosmosex"}
IDE_ADDONS = {"ide-internal", "ide-adapter", "cf-adapter"}
SCSI_ADDONS = {"scsi-internal"}

#: Frames per second of the emulated machine, for turning a run length in
#: seconds into Hatari's ``--run-vbls`` count.
VBLS_PER_SECOND = 50

#: How long a bounded, non-interactive run lasts, in seconds.
BOUNDED_SECONDS = 8
BOUNDED_DEBUG_SECONDS = 15


def tos_directories() -> list[Path]:
    """Where TOS ROMs are looked for, in order: the operator's directory, then the repository's."""
    return [TOS_DIR, REPOSITORY_TOS_DIR]


def _is_rom(path: Path) -> bool:
    """Whether the file decodes as a ROM at all.

    A collection gathered from the preservation archives carries files that
    are not ROMs: odd lengths, partial reads, and dumps that never completed.
    Handing one to the emulator produces a machine that hangs with nothing on
    screen, so the header is read before the file is offered.
    """
    try:
        return is_tos_rom(path.read_bytes())
    except OSError:
        return False


def _tos_candidates(stems: tuple[str, ...]) -> list[Path]:
    """Every ROM file matching one of ``stems``, best first.

    Three things decide the order, and each of them was needed by a real
    collection rather than imagined.

    A file that does not decode as a ROM is left out altogether, whatever it
    is called. Falling back to the bundled firmware is a result the operator
    can be told about; a machine that hangs on a partial dump is not.

    Then the name. A ROM with no language in its name comes first, because
    the later releases were not published per country: ``tos404.img`` is the
    ROM and ``tos404-a.img`` is somebody's alternative dump of it. Then the
    UK ROM, then the US one, then anything else.

    Then the length, largest first. Every genuine dump of one release is the
    same size, so a shorter file of the same release is a truncated one. The
    header alone does not catch that: a half-length dump of a 512 KiB release
    still carries a perfectly good header and reports its version happily.
    """
    found: list[Path] = []
    for stem in stems:
        for directory in tos_directories():
            if not directory.is_dir():
                continue
            matches = sorted(
                path for path in directory.glob(f"{stem}*.img") if path.is_file()
            )
            preferred = [f"{stem}.img"] + [f"{stem}{language}.img" for language in TOS_LANGUAGES]

            def rank(path: Path, preferred=preferred) -> tuple:
                try:
                    place = preferred.index(path.name)
                except ValueError:
                    place = len(preferred)
                return (place, -path.stat().st_size, path.name)

            found.extend(sorted((path for path in matches if _is_rom(path)), key=rank))
    return found


def _requested_tos(addons: set[str]) -> tuple[str, ...] | None:
    for addon, stems in TOS_ADDONS.items():
        if addon in addons:
            return stems
    return None


def tos_for(machine: str, addons=()) -> Path | None:
    """The operator-supplied TOS ROM this machine would boot, or None."""
    addons = set(addons or ())
    if "tos-emutos" in addons:
        return None
    stems = _requested_tos(addons) or TOS_NAMES.get(machine, ())
    candidates = _tos_candidates(tuple(stems))
    return candidates[0] if candidates else None


def emutos_for(machine: str, size: str | None = None) -> Path | None:
    """The bundled EmuTOS image for this machine, or the explicitly requested size."""
    size = size or EMUTOS_SIZES.get(machine, "512")
    if size in {"1024", "1024k"}:
        candidate = EMUTOS_DIR / "etos1024k.img"
        return candidate if candidate.is_file() else None
    for language in TOS_LANGUAGES:
        candidate = EMUTOS_DIR / f"etos{size}{language}.img"
        if candidate.is_file():
            return candidate
    return None


def _emutos_size_request(profile: dict) -> str | None:
    """An explicit EmuTOS size from the profile: ``emulatorFirmware: "emutos-1024k"``."""
    requested = str(profile.get("emulatorFirmware") or "").strip().lower()
    if requested.startswith("emutos-"):
        size = requested.removeprefix("emutos-").removesuffix("k")
        if size in {"192", "256", "512", "1024"}:
            return size
    return None


def firmware_for(machine: str, addons=(), *, emutos_size: str | None = None) -> Firmware | None:
    """Choose the ROM this machine boots, and say why.

    The order is: the TOS the profile asks for, or failing that any TOS the
    machine shipped with, from the operator's ROM directory and then the
    repository's; then the bundled EmuTOS in the size that fits. Only a
    missing EmuTOS returns None, and that means the checkout is incomplete.
    """
    addons = set(addons or ())
    forced = "tos-emutos" in addons or emutos_size is not None
    if not forced:
        requested = _requested_tos(addons)
        chosen = tos_for(machine, addons)
        if chosen is not None:
            release = chosen.name[3:6]
            label = f"TOS {release[0]}.{release[1:]}"
            return Firmware(
                chosen, "tos", label,
                f"{chosen.name} was found in {chosen.parent}"
                + (" as the profile requested." if requested else
                   f", which is a ROM the {machine.upper()} shipped with."),
            )
    emutos = emutos_for(machine, emutos_size)
    if emutos is None:
        return None
    size = emutos_size or EMUTOS_SIZES.get(machine, "512")
    if forced:
        why = (
            "the profile asks for EmuTOS."
            if "tos-emutos" in addons
            else f"the profile asks for the {size} KiB EmuTOS image."
        )
    elif _requested_tos(addons):
        why = (
            f"the TOS the profile asks for was not found in {TOS_DIR} or {REPOSITORY_TOS_DIR}, "
            "so the bundled EmuTOS boots the machine instead."
        )
    else:
        why = (
            f"no TOS ROM for the {machine.upper()} was found in {TOS_DIR} or {REPOSITORY_TOS_DIR}, "
            "so the bundled EmuTOS boots the machine instead."
        )
    return Firmware(emutos, "emutos", f"EmuTOS {size} KiB", f"{emutos.name} was chosen because {why}")


def cd_drives_for(machine: str) -> int:
    """How many CD drives this machine can attach: one on a SCSI machine, none elsewhere.

    Hatari has no CD-ROM emulation of its own. What it has is SCSI disk
    emulation on the TT030 and the Falcon, so a CD image is attached there as
    a second SCSI device, which a CD filing-system driver on the drive can
    read. The ST-class machines have nowhere to put one.
    """
    return MAXIMUM_CD_DRIVES if machine in {"tt030", "falcon030"} else 0


def control_socket_path(work_dir: str | Path) -> Path:
    """Where a route creates the socket Hatari connects to for remote control.

    Hatari *connects* to ``--control-socket``; it does not create it. The
    controlling process listens on this path first, then starts the emulator
    with ``control_socket=`` and writes the ``hatari-shortcut``,
    ``hatari-option`` and ``hatari-debug`` lines Hatari's own hconsole sends.
    """
    return Path(work_dir) / "hatari-control.sock"


def profile_machine(session) -> str:
    profile = getattr(session, "hardware_profile", {}) or {}
    machine = str(profile.get("machine") or "").strip().lower().replace(" ", "")
    aliases = {
        "atarist": "st", "520st": "st", "1040st": "st", "stf": "st", "stfm": "st",
        "atarimegast": "megast", "mega": "megast", "mega-st": "megast",
        "atariste": "ste", "520ste": "ste", "1040ste": "ste",
        "atarimegaste": "megaste", "mega-ste": "megaste",
        "ataritt": "tt030", "tt": "tt030", "tt-030": "tt030",
        "atarifalcon": "falcon030", "falcon": "falcon030", "falcon-030": "falcon030",
    }
    if machine in ALL_MACHINES:
        return machine
    if machine in aliases:
        return aliases[machine]
    target = str(getattr(session, "target_hardware", "") or "").lower()
    for name in ("falcon030", "tt030", "megaste", "megast", "ste"):
        if name in target:
            return name
    return "st"


def configured_emulator(session) -> ManagedEmulator:
    profile = getattr(session, "hardware_profile", {}) or {}
    machine = profile_machine(session)
    selected = str(profile.get("emulator") or "auto").strip().lower()
    if selected == "auto" or selected not in EMULATORS:
        selected = "hatari"
    emulator = EMULATORS[selected]
    if machine not in emulator.platforms:
        return EMULATORS["hatari"]
    return emulator


def emulator_status(session) -> dict:
    emulator = configured_emulator(session)
    machine = profile_machine(session)
    profile = getattr(session, "hardware_profile", {}) or {}
    addons = profile_addons(session)
    firmware = firmware_for(machine, addons, emutos_size=_emutos_size_request(profile))
    available = emulator.available
    firmware_message = ""
    if firmware is None:
        available = False
        firmware_message = (
            f" No ROM for the {machine.upper()} was found: neither a TOS in {TOS_DIR} "
            f"or {REPOSITORY_TOS_DIR}, nor the bundled EmuTOS in {EMUTOS_DIR}. "
            "The firmware/emutos directory is part of the repository; restore it."
        )
    elif available:
        firmware_message = f" {firmware.label}: {firmware.reason}"
    return {
        "id": emulator.identifier,
        "label": emulator.label,
        "available": available,
        "machine": machine,
        "firmware": str(firmware.path) if firmware else "",
        "firmwareKind": firmware.kind if firmware else "",
        "firmwareLabel": firmware.label if firmware else "",
        "firmwareReason": firmware.reason if firmware else firmware_message.strip(),
        "debugger": emulator.debugger,
        "configuredBy": "managed workbench profile",
        "message": (
            f"{emulator.label} is installed and configured for the {machine.upper()}."
            if available else
            f"{emulator.label} is selected for the {machine.upper()}, but it cannot start yet."
            if emulator.available and firmware_message else
            f"{emulator.label} is selected for the {machine.upper()}, but its executable is missing from this build."
        ) + firmware_message,
    }


def emulator_command(
    session,
    media_path: str | Path,
    *,
    debug: bool = False,
    interactive: bool = False,
    native: bool = False,
    floppies: list[str | Path] | None = None,
    cdroms: list[str | Path] | None = None,
    control_socket: str | Path | None = None,
) -> tuple[list[str], str]:
    """Build the command line that boots one image, optionally with discs.

    ``media_path`` is what the machine boots: a floppy image goes in A:, a
    hard-drive image is attached to the interface the profile declares, and a
    directory is shared as a GEMDOS drive C:.

    ``floppies`` exists for installing a title onto a drive: the machine boots
    from the hard drive with the title's disc already in A:, which is what
    every installer expects to find. A second disc fills B:, and that is all
    the drives the hardware has.

    ``cdroms`` attaches a CD image on the SCSI machines; see
    :func:`cd_drives_for` for what that means on Hatari.

    ``control_socket`` names a socket the caller is already listening on, for
    Hatari's remote-control protocol; see :func:`control_socket_path`.
    """
    emulator = configured_emulator(session)
    if not emulator.available:
        raise ValueError(f"{emulator.label} is not installed in this build.")
    profile = getattr(session, "hardware_profile", {}) or {}
    addons = profile_addons(session)
    media = Path(media_path)
    suffix = media.suffix.lower()
    machine = profile_machine(session)
    firmware = firmware_for(machine, addons, emutos_size=_emutos_size_request(profile))
    if firmware is None:
        raise ValueError(
            f"No ROM for the {machine.upper()} was found, and the bundled EmuTOS is missing from {EMUTOS_DIR}."
        )
    is_folder = media.is_dir()
    if not is_folder and suffix not in FLOPPY_SUFFIXES | DRIVE_SUFFIXES:
        raise ValueError(
            "Hatari can start from a floppy image (ST, MSA, STX, DIM, IPF, HFE, ZIP), a "
            "hard-drive image (IMG, HD, AHD, ACSI, IDE, RAW, BIN, VHD) or a folder. Export one of those first."
        )

    arguments = _desktop_command(
        emulator.executable, debug=debug, interactive=interactive, native=native
    )
    arguments += ["--machine", HATARI_MACHINES[machine], "--tos", str(firmware.path)]
    arguments += ["--memsize", _memsize(machine, addons, profile)]
    if "tt-ram" in addons and machine in {"tt030", "falcon030"}:
        # TT RAM sits above the 24-bit address space, so it needs the full
        # 32-bit addressing the 68030 has and Hatari otherwise leaves off.
        arguments += ["--ttram", "16", "--addr24", "false"]
    level, clock = PROCESSORS[machine]
    if "acc-68030-pak" in addons and machine in {"st", "megast", "ste", "megaste"}:
        level = "3"
    arguments += ["--cpulevel", level, "--cpuclock", clock]
    if "fpu-68882" in addons:
        arguments += ["--fpu", "68882"]
    elif "fpu-68881" in addons:
        arguments += ["--fpu", "68881"]
    if machine == "megast" or (machine == "st" and "blitter" in addons):
        # The STE and later always have one; Hatari's switch is for the ST.
        arguments += ["--blitter", "true"]
    if machine == "falcon030":
        arguments += ["--dsp", "emu"]
    arguments += ["--monitor", _monitor(machine, addons)]

    attached = [Path(item) for item in (floppies or [])]
    if not is_folder and suffix in FLOPPY_SUFFIXES:
        attached.insert(0, media)
    if len(attached) > MAXIMUM_FLOPPY_DRIVES:
        raise ValueError(
            f"An Atari has {MAXIMUM_FLOPPY_DRIVES} floppy drives, A: and B:; "
            f"{len(attached)} discs were attached."
        )
    if "drive-a-ss" in addons:
        arguments += ["--drive-a-heads", "1"]
    if "drive-b-external" not in addons and len(attached) < 2:
        arguments += ["--drive-b", "false"]
    for option, disc in zip(("--disk-a", "--disk-b"), attached):
        arguments += [option, str(disc)]

    if is_folder:
        arguments += ["--harddrive", str(media), "--gemdos-drive", "c"]
    elif suffix in DRIVE_SUFFIXES:
        arguments += _hard_drive_arguments(machine, addons, media)

    compact_discs = [Path(item) for item in (cdroms or [])]
    if compact_discs:
        allowed = cd_drives_for(machine)
        if len(compact_discs) > allowed:
            raise ValueError(
                f"The {machine.upper()} attaches {allowed} CD drive"
                f"{'' if allowed == 1 else 's'} under Hatari; {len(compact_discs)} discs were attached."
                + ("" if allowed else " A CD needs the SCSI port of a TT030 or Falcon030.")
            )
        for index, disc in enumerate(compact_discs, start=1):
            arguments += ["--scsi", f"{index}={disc}"]

    # With Hatari's fast boot, EmuTOS starts from A: even with a hard-drive
    # image attached, so the drive is there but its AUTO folder and
    # accessories never run, which looks exactly like a prepared drive that
    # loads nothing. Booting the drive therefore boots at normal speed. A
    # GEMDOS folder is unaffected, because Hatari makes it the boot drive
    # itself, and "Mount only" keeps the fast boot, which is what leaves the
    # machine at its own desktop with the drive merely attached.
    boots_drive = (
        not is_folder
        and suffix in DRIVE_SUFFIXES
        and str(profile.get("emulatorBoot") or "auto").strip().lower() != "catalogue"
    )
    arguments += [
        "--fast-boot", "false" if boots_drive else "true",
        "--confirm-quit", "false", "--statusbar", "false",
    ]
    if not (native and interactive):
        # The container has no sound device, and a bounded run has no listener.
        arguments += ["--sound", "off"]
    arguments += ["--log-level", "info" if debug else "warn"]
    cwd = str(media.parent)
    arguments += ["--screenshot-dir", cwd]
    if not interactive:
        seconds = BOUNDED_DEBUG_SECONDS if debug else BOUNDED_SECONDS
        # Hatari leaves on its own a little before the timeout wrapper would
        # have to end it, so a normal bounded run exits 0 rather than 124.
        arguments += ["--run-vbls", str((seconds - 1) * VBLS_PER_SECOND)]
    if control_socket is not None:
        arguments += ["--control-socket", str(control_socket)]
    if debug:
        arguments += ["--debug", "--parse", str(DEBUGGER_SCRIPT)]
    return arguments, cwd


def _memsize(machine: str, addons: set[str], profile: dict) -> str:
    size = DEFAULT_MEMORY[machine]
    for addon, value in MEMORY_ADDONS.items():
        if addon in addons:
            size = value
    requested = str(profile.get("emulatorRam") or "auto").strip().upper()
    if requested in MEMSIZE_VALUES:
        size = requested
    return MEMSIZE_VALUES[size]


def _monitor(machine: str, addons: set[str]) -> str:
    for addon, monitor in MONITOR_ADDONS.items():
        if addon in addons:
            return monitor
    return DEFAULT_MONITOR[machine]


def _hard_drive_arguments(machine: str, addons: set[str], media: Path) -> list[str]:
    """Attach a drive image to the interface the profile declares.

    With no storage add-on the machine's own interface is used: the ACSI port
    on the ST family, SCSI on the TT030 and IDE on the Falcon.
    """
    if addons & IDE_ADDONS:
        return ["--ide-master", str(media)]
    if addons & SCSI_ADDONS and machine in {"megaste", "tt030", "falcon030"}:
        return ["--scsi", f"0={media}"]
    if addons & ACSI_ADDONS and machine != "falcon030":
        return ["--acsi", f"0={media}"]
    if machine == "falcon030":
        return ["--ide-master", str(media)]
    if machine == "tt030":
        return ["--scsi", f"0={media}"]
    return ["--acsi", f"0={media}"]


def _desktop_command(
    executable: str,
    *,
    debug: bool,
    interactive: bool,
    native: bool = False,
) -> list[str]:
    """Run in the shared browser display or a bounded private X server."""
    if native and interactive:
        return [executable]
    environment = ["env", "SDL_AUDIODRIVER=dummy"]
    if interactive:
        return [
            "timeout", "--signal=TERM", "--kill-after=2", "900",
            *environment, "DISPLAY=:99", executable,
        ]
    duration = str(BOUNDED_DEBUG_SECONDS if debug else BOUNDED_SECONDS)
    return [
        "timeout", "--signal=TERM", "--kill-after=2", duration,
        *environment,
        "xvfb-run", "-a", executable,
    ]


__all__ = [
    "ALL_MACHINES",
    "DEBUGGER_SCRIPT",
    "DRIVE_SUFFIXES",
    "EMULATORS",
    "EMUTOS_DIR",
    "EMUTOS_SIZES",
    "FLOPPY_SUFFIXES",
    "Firmware",
    "HATARI_MACHINES",
    "HATARI_ROOT",
    "MAXIMUM_CD_DRIVES",
    "MAXIMUM_FLOPPY_DRIVES",
    "ManagedEmulator",
    "REPOSITORY_TOS_DIR",
    "TOS_ADDONS",
    "TOS_DIR",
    "TOS_NAMES",
    "cd_drives_for",
    "configured_emulator",
    "control_socket_path",
    "emulator_command",
    "emulator_status",
    "emutos_for",
    "firmware_for",
    "profile_machine",
    "tos_directories",
    "tos_for",
]
