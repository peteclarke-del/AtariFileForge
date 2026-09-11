"""The Atari hardware catalogue behind a workbench hardware profile.

A profile names one base machine and the additions fitted to it. Each add-on
says which machines can take it, what it needs and what it excludes, and
whether the managed emulator can reproduce it (``emulator="hatari"``) or it
only informs compatibility checks (``emulator="profile"``, shown as
"Validation only" in the interface).
"""

from __future__ import annotations

from copy import deepcopy


def _addon(identifier, label, group, machines, description, *, emulator="profile", requires=(), conflicts=()):
    return {
        "id": identifier, "label": label, "group": group,
        "machines": list(machines), "description": description,
        "emulator": emulator, "requires": list(requires), "conflicts": list(conflicts),
    }


ALL_MACHINES = ["st", "megast", "ste", "megaste", "tt030", "falcon030"]
#: The machines with an ACSI port on the back: everything but the Falcon.
ACSI_MACHINES = ["st", "megast", "ste", "megaste", "tt030"]
#: The 68000 machines; a 68030 in one of these is an accelerator board.
ST_CLASS = ["st", "megast", "ste", "megaste"]
#: The 68030 machines, whose processor has a coprocessor socket beside it.
THIRTY_TWO_BIT = ["tt030", "falcon030"]

ADDONS = [
    # ---- TOS firmware. Each release is offered to the machines it shipped in;
    # EmuTOS boots every one of them. ----
    _addon("tos-100", "TOS 1.00", "firmware", ["st"], "The first ROM TOS from 1985, fitted to early 520ST and 1040ST machines.", emulator="hatari"),
    _addon("tos-102", "TOS 1.02", "firmware", ["st", "megast"], "The 1987 Mega ST release, with blitter support and the ST desktop.", emulator="hatari"),
    _addon("tos-104", "TOS 1.04 (Rainbow TOS)", "firmware", ["st", "megast"], "The 1989 release most ST software was written against, with the faster GEMDOS.", emulator="hatari"),
    _addon("tos-106", "TOS 1.06", "firmware", ["ste"], "The first STE ROM, fitted to early 520STE and 1040STE machines.", emulator="hatari"),
    _addon("tos-162", "TOS 1.62", "firmware", ["ste"], "The corrected STE ROM that most 1040STE machines shipped with.", emulator="hatari"),
    _addon("tos-205", "TOS 2.05", "firmware", ["megaste"], "The first Mega STE ROM, with the NEWDESK desktop and cache support.", emulator="hatari"),
    _addon("tos-206", "TOS 2.06", "firmware", ["ste", "megaste"], "The final 256 KiB ROM, sold as an upgrade for the STE and fitted to late Mega STE machines.", emulator="hatari"),
    _addon("tos-306", "TOS 3.06", "firmware", ["tt030"], "The 512 KiB TT ROM with TT RAM, SCSI and the TT video modes.", emulator="hatari"),
    _addon("tos-4xx", "TOS 4.0x", "firmware", ["falcon030"], "The Falcon ROM (4.00, 4.02 or 4.04) with VIDEL, DSP and IDE support.", emulator="hatari"),
    _addon("tos-emutos", "EmuTOS", "firmware", ALL_MACHINES, "The free GPL operating system bundled with this application, in the ROM size that fits the machine.", emulator="hatari"),

    # ---- ST RAM ----
    _addon("ram-512k", "512 KiB ST RAM", "main-memory", ["st", "ste"], "The memory a 520ST or 520STE shipped with.", emulator="hatari"),
    _addon("ram-1m", "1 MiB ST RAM", "main-memory", ["st", "megast", "ste", "megaste", "falcon030"], "The memory a 1040ST, 1040STE, Mega 1 or basic Falcon shipped with.", emulator="hatari"),
    _addon("ram-2m", "2 MiB ST RAM", "main-memory", ["megast", "megaste", "tt030"], "A Mega 2 or the standard TT030 fitting.", emulator="hatari"),
    _addon("ram-2.5m", "2.5 MiB ST RAM", "main-memory", ["st", "ste"], "The common 1040 upgrade that pairs the original 1 MiB with a 2 MiB SIMM bank.", emulator="hatari"),
    # The ST takes it too: its memory controller drives two banks of up to
    # 2 MiB, the same support the 2.5 MiB upgrade relies on.
    _addon("ram-4m", "4 MiB ST RAM", "main-memory", ["st", "megast", "ste", "megaste", "tt030", "falcon030"], "The full complement of ST RAM the 68000 memory controller can address.", emulator="hatari"),
    _addon("ram-14m", "14 MiB ST RAM", "main-memory", ["falcon030"], "The largest Falcon memory board, needed by most Falcon multimedia software.", emulator="hatari"),
    _addon("tt-ram", "TT RAM (Fast RAM)", "expansion-memory", THIRTY_TWO_BIT, "16 MiB of 32-bit memory above the ST RAM, reached only by the 68030 and only with 32-bit addressing.", emulator="hatari"),

    # ---- Floppy drives ----
    _addon("drive-a-ss", "Single-sided internal drive (A:)", "disk", ["st"], "The 360 KiB single-sided drive fitted to early 520ST machines, which cannot read a double-sided disk.", emulator="hatari", conflicts=["drive-a-ds", "hd-floppy"]),
    _addon("drive-a-ds", "Double-sided internal drive (A:)", "disk", ALL_MACHINES, "The standard 720 KiB double-sided drive.", emulator="hatari", conflicts=["drive-a-ss"]),
    _addon("drive-b-external", "External drive (B:)", "disk", ALL_MACHINES, "A second drive on the floppy port, so a two-disk program needs no swapping.", emulator="hatari"),
    _addon("hd-floppy", "High-density drive (1.44 MiB)", "disk", ["megaste", "tt030", "falcon030"], "The Ajax controller drive fitted to later machines, reading 1.44 MiB disks as well as 720 KiB ones.", emulator="hatari", conflicts=["drive-a-ss"]),
    _addon("gotek", "Gotek with FlashFloppy", "disk", ALL_MACHINES, "A solid-state floppy replacement reading ST and HFE images from a USB stick."),

    # ---- Mass storage ----
    _addon("acsi-megafile", "Atari ACSI hard drive (SH204, SH205, Megafile)", "storage", ACSI_MACHINES, "Atari's own external hard drive on the ACSI port, from the 20 MiB SH204 to the Megafile 60.", emulator="hatari"),
    _addon("acsi-third-party", "Third-party ACSI enclosure", "storage", ACSI_MACHINES, "An ICD, Supra or Vortex enclosure bridging the ACSI port to a SCSI or MFM drive.", emulator="hatari"),
    _addon("acsi2stm", "ACSI2STM", "storage", ACSI_MACHINES, "A modern microcontroller board on the ACSI port presenting SD cards as hard drives.", emulator="hatari"),
    _addon("ultrasatan", "UltraSatan", "storage", ACSI_MACHINES, "A modern ACSI device holding two SD cards, each seen as one hard drive.", emulator="hatari"),
    _addon("cosmosex", "CosmosEx", "storage", ACSI_MACHINES, "A Raspberry Pi based ACSI device offering hard drives, floppy images and network access.", emulator="hatari"),
    _addon("ide-internal", "Internal IDE (Falcon)", "storage", ["falcon030"], "The Falcon's own 2.5 inch IDE interface.", emulator="hatari"),
    _addon("ide-adapter", "IDE adapter board", "storage", ST_CLASS, "An internal IDE board for an ST, STE or Mega, wired to the processor bus.", emulator="hatari"),
    _addon("scsi-internal", "Internal SCSI port", "storage", ["megaste", "tt030", "falcon030"], "The SCSI port built into the Mega STE, the TT030 and the Falcon.", emulator="hatari"),
    _addon("cf-adapter", "CompactFlash adapter", "storage", ST_CLASS + ["falcon030"], "A CompactFlash card on an IDE interface, seen by the machine as a hard drive.", emulator="hatari", requires=["ide-adapter|ide-internal"]),

    # ---- Hard-disk driver software ----
    _addon("driver-emutos-builtin", "EmuTOS built-in driver", "driver", ALL_MACHINES, "EmuTOS reads ACSI, SCSI and IDE drives itself, so no driver need be installed on the drive.", requires=["tos-emutos"]),
    _addon("driver-ahdi", "Atari AHDI", "driver", ALL_MACHINES, "Atari's own hard-disk driver, installed on the root sector of the drive."),
    _addon("driver-hddriver", "HDDRIVER", "driver", ALL_MACHINES, "Uwe Seimet's driver, the usual choice for large partitions and modern interfaces."),
    _addon("driver-pp", "PP driver (PPDRIVER)", "driver", ALL_MACHINES, "Peter Putnik's free driver for ACSI, SCSI and IDE drives."),
    _addon("driver-icd", "ICD Pro driver", "driver", ALL_MACHINES, "The driver supplied with ICD host adapters, which also drives most other ACSI hardware."),

    # ---- Processor ----
    _addon("acc-68030-pak", "68030 accelerator (PAK68/3 class)", "accelerator", ST_CLASS, "A 68030 board in the 68000 socket, which only TOS 2.06 and EmuTOS can run.", emulator="hatari"),
    _addon("blitter", "Blitter chip", "accelerator-option", ["st"], "The graphics coprocessor built into the Mega ST and STE, fitted to a plain ST as an upgrade.", emulator="hatari"),
    _addon("fpu-68881", "68881 FPU", "accelerator-option", ST_CLASS, "A floating-point coprocessor on the accelerator board.", emulator="hatari", requires=["acc-68030-pak"], conflicts=["fpu-68882"]),
    _addon("fpu-68882", "68882 FPU", "accelerator-option", THIRTY_TWO_BIT, "A floating-point coprocessor in the socket beside the TT030 or Falcon 68030.", emulator="hatari", conflicts=["fpu-68881"]),

    # ---- Display ----
    _addon("monitor-mono", "SM124 monochrome monitor", "graphics", ALL_MACHINES, "The 640 by 400 high-resolution monitor, needed by most productivity software.", emulator="hatari"),
    _addon("monitor-colour", "SC1224 colour monitor", "graphics", ALL_MACHINES, "The RGB monitor for low and medium resolution, which is what games expect.", emulator="hatari"),
    _addon("monitor-vga", "VGA monitor", "graphics", THIRTY_TWO_BIT, "A PC monitor on the TT030 or Falcon, giving the machine its higher video modes.", emulator="hatari"),
    _addon("tv-modulator", "Television through the RF modulator", "graphics", ["st", "ste"], "A television on the STF or STE modulator, in colour but with a soft picture.", emulator="hatari"),

    # ---- Ports and peripherals ----
    _addon("midi", "MIDI ports", "ports", ALL_MACHINES, "The built-in MIDI In and Out ports used by sequencers."),
    _addon("cartridge-port", "Cartridge port", "ports", ALL_MACHINES, "The 128 KiB ROM cartridge slot on the left-hand side."),
    _addon("printer", "Printer on the parallel port", "ports", ALL_MACHINES, "A Centronics printer, which GEM programs reach through the printer port."),
    _addon("modem-rs232", "Modem on the RS-232 port", "ports", ALL_MACHINES, "A serial modem or null-modem link on the RS-232 port."),

    # ---- Software loaders ----
    _addon("auto-folder", "AUTO folder programs", "loader", ALL_MACHINES, "Programs in the AUTO folder of the boot drive, run by TOS before the desktop appears."),
    _addon("desktop-inf", "DESKTOP.INF / NEWDESK.INF", "loader", ALL_MACHINES, "A saved desktop layout that opens windows and installs applications at boot."),
    _addon("gemdos-hd-folder", "GEMDOS hard-drive folder", "loader", ALL_MACHINES, "A folder on the host computer that Hatari presents to the machine as drive C:.", emulator="hatari"),
]

GROUPS = {
    "firmware": {"label": "TOS firmware", "max": 1},
    "main-memory": {"label": "ST RAM", "max": 1},
    "expansion-memory": {"label": "TT RAM", "max": 1},
    "disk": {"label": "Floppy drives", "max": 3},
    "storage": {"label": "Mass storage", "max": 3},
    "driver": {"label": "Hard-disk driver", "max": 1},
    "accelerator": {"label": "Processor", "max": 1},
    "accelerator-option": {"label": "Processor options", "max": 2},
    "graphics": {"label": "Display", "max": 1},
    "ports": {"label": "Ports and peripherals", "max": 4},
    "loader": {"label": "Software loaders", "max": 3},
}

MACHINES = [
    {"id": "st", "label": "Atari 520ST / 1040ST", "baseRam": "512K", "processor": "68000 8 MHz"},
    {"id": "megast", "label": "Atari Mega ST 1 / 2 / 4", "baseRam": "1M", "processor": "68000 8 MHz"},
    {"id": "ste", "label": "Atari 520STE / 1040STE", "baseRam": "1M", "processor": "68000 8 MHz"},
    {"id": "megaste", "label": "Atari Mega STE", "baseRam": "1M", "processor": "68000 16 MHz"},
    {"id": "tt030", "label": "Atari TT030", "baseRam": "2M", "processor": "68030 32 MHz"},
    {"id": "falcon030", "label": "Atari Falcon030", "baseRam": "4M", "processor": "68030 16 MHz"},
]


def hardware_catalogue() -> dict:
    return {"machines": deepcopy(MACHINES), "groups": deepcopy(GROUPS), "addons": deepcopy(ADDONS)}


def normalise_hardware_profile(data: dict) -> dict:
    machine = str(data.get("machine") or "st").strip().lower()
    machine_ids = {row["id"] for row in MACHINES}
    if machine not in machine_ids:
        raise ValueError("Choose a supported base machine.")
    known = {row["id"]: row for row in ADDONS}
    addons = []
    for value in data.get("addons", []):
        identifier = str(value).strip().lower()
        if identifier and identifier not in addons:
            addons.append(identifier)
    invalid = [identifier for identifier in addons if identifier not in known or machine not in known[identifier]["machines"]]
    if invalid:
        raise ValueError(f"{', '.join(invalid)} cannot be fitted to {machine}.")
    for group, definition in GROUPS.items():
        selected = [identifier for identifier in addons if known[identifier]["group"] == group]
        if len(selected) > definition["max"]:
            raise ValueError(f"Choose no more than {definition['max']} option(s) from {definition['label']}.")
    selected = set(addons)
    for identifier in addons:
        conflicts = selected.intersection(known[identifier].get("conflicts", []))
        if conflicts:
            labels = ", ".join(known[conflict]["label"] for conflict in sorted(conflicts))
            raise ValueError(f"{known[identifier]['label']} cannot be fitted with {labels}.")
        for requirement in known[identifier]["requires"]:
            scoped_machine, _, expression = requirement.partition(":")
            if expression and scoped_machine != machine:
                continue
            choices = (expression or scoped_machine).split("|")
            if not any(choice in selected for choice in choices):
                labels = " or ".join(known[choice]["label"] for choice in choices)
                raise ValueError(f"{known[identifier]['label']} requires {labels}.")
    profile = dict(data)
    profile["machine"] = machine
    profile["addons"] = addons
    profile["accelerated"] = any(known[item]["group"] == "accelerator" for item in addons)
    return profile


def profile_addons(session) -> set[str]:
    profile = getattr(session, "hardware_profile", {}) or {}
    addons = {str(value) for value in profile.get("addons", []) if isinstance(value, str)}
    if profile.get("accelerated") and not any(value.startswith("acc-") for value in addons):
        addons.add("acc-68030-pak")
    return addons
