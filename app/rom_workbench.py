"""Higher-level ROM maintenance tools built on the conservative ROM decoder.

The functions in this module never execute bytes from an uploaded image.  They
return bounded, serialisable reports and require source fingerprints before a
patch can alter an image.
"""

from __future__ import annotations

import base64
import json
import io
import zipfile
import zlib
import re
from pathlib import Path

from atarinut.tosrom import TOS_SIZES, decode_bcd_date, encode_dos_date

from .checksum import sha256_bytes
from .rom import (
    CARTRIDGE_SIZE,
    DEFAULT_ROM_BASE,
    inspect_bank,
    make_cartridge_rom,
    parse_cartridge_header,
    parse_rom_header,
    rom_base,
)
from .rom_components import BOARD_CHIP_SETS, split_into_chips

try:
    from capstone import (
        Cs,
        CS_ARCH_M68K,
        CS_MODE_BIG_ENDIAN,
        CS_MODE_M68K_000,
        CS_MODE_M68K_010,
        CS_MODE_M68K_020,
        CS_MODE_M68K_030,
        CS_MODE_M68K_040,
        CS_MODE_M68K_060,
    )
except ImportError:  # Host-side lightweight tests may not install production dependencies.
    Cs = None


PATCH_FORMAT = "atari-file-forge-rom-patch-1"
PROJECT_FORMAT = "atari-file-forge-rom-project-1"
MAX_DISASSEMBLY_BYTES = 256 * 1024
MAX_PATCH_BYTES = 16 * 1024 * 1024


class RomWorkbenchError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Atari system vocabulary
# ---------------------------------------------------------------------------
# A TOS program reaches the operating system through four TRAP instructions.
# The function number is pushed as a word immediately before the TRAP, so the
# interesting annotation is not "what address is this" but "which system call
# is this". These tables turn ``MOVE.W #$3D,-(SP) / TRAP #1`` into
# ``GEMDOS Fopen``.

GEMDOS_CALLS = {
    0x00: ("Pterm0", "Terminate the process with exit code 0"),
    0x01: ("Cconin", "Read a character from the console"),
    0x02: ("Cconout", "Write a character to the console"),
    0x03: ("Cauxin", "Read a character from the serial port"),
    0x04: ("Cauxout", "Write a character to the serial port"),
    0x05: ("Cprnout", "Write a character to the printer"),
    0x06: ("Crawio", "Raw console input and output"),
    0x07: ("Crawcin", "Read a console character without echo"),
    0x08: ("Cnecin", "Read a console character without echo, with control keys"),
    0x09: ("Cconws", "Write a string to the console"),
    0x0A: ("Cconrs", "Read an edited line from the console"),
    0x0B: ("Cconis", "Test whether a console character is waiting"),
    0x0E: ("Dsetdrv", "Set the default drive"),
    0x10: ("Cconos", "Test whether the console can accept output"),
    0x11: ("Cprnos", "Test whether the printer can accept output"),
    0x12: ("Cauxis", "Test whether a serial character is waiting"),
    0x13: ("Cauxos", "Test whether the serial port can accept output"),
    0x14: ("Maddalt", "Add alternative RAM to the GEMDOS pool"),
    0x19: ("Dgetdrv", "Return the default drive"),
    0x1A: ("Fsetdta", "Set the disk transfer address"),
    0x20: ("Super", "Enter or leave supervisor mode"),
    0x2A: ("Tgetdate", "Read the system date"),
    0x2B: ("Tsetdate", "Set the system date"),
    0x2C: ("Tgettime", "Read the system time"),
    0x2D: ("Tsettime", "Set the system time"),
    0x2F: ("Fgetdta", "Return the disk transfer address"),
    0x30: ("Sversion", "Return the GEMDOS version"),
    0x31: ("Ptermres", "Terminate and stay resident"),
    0x36: ("Dfree", "Report free space on a drive"),
    0x39: ("Dcreate", "Create a folder"),
    0x3A: ("Ddelete", "Delete a folder"),
    0x3B: ("Dsetpath", "Set the current folder"),
    0x3C: ("Fcreate", "Create a file"),
    0x3D: ("Fopen", "Open a file"),
    0x3E: ("Fclose", "Close a file"),
    0x3F: ("Fread", "Read from a file"),
    0x40: ("Fwrite", "Write to a file"),
    0x41: ("Fdelete", "Delete a file"),
    0x42: ("Fseek", "Move the file position"),
    0x43: ("Fattrib", "Read or set file attributes"),
    0x44: ("Mxalloc", "Allocate memory of a requested type"),
    0x45: ("Fdup", "Duplicate a file handle"),
    0x46: ("Fforce", "Redirect a standard handle"),
    0x47: ("Dgetpath", "Return the current folder"),
    0x48: ("Malloc", "Allocate memory"),
    0x49: ("Mfree", "Free memory"),
    0x4A: ("Mshrink", "Shrink a memory block"),
    0x4B: ("Pexec", "Load or execute a program"),
    0x4C: ("Pterm", "Terminate the process with an exit code"),
    0x4E: ("Fsfirst", "Find the first matching directory entry"),
    0x4F: ("Fsnext", "Find the next matching directory entry"),
    0x56: ("Frename", "Rename a file"),
    0x57: ("Fdatime", "Read or set a file's date and time"),
}

BIOS_CALLS = {
    0: ("Getmpb", "Fill in the memory parameter block"),
    1: ("Bconstat", "Test whether a device has a character waiting"),
    2: ("Bconin", "Read a character from a device"),
    3: ("Bconout", "Write a character to a device"),
    4: ("Rwabs", "Read or write disk sectors"),
    5: ("Setexc", "Read or set an exception vector"),
    6: ("Tickcal", "Return the system timer period"),
    7: ("Getbpb", "Return a drive's BIOS parameter block"),
    8: ("Bcostat", "Test whether a device can accept output"),
    9: ("Mediach", "Report whether the medium changed"),
    10: ("Drvmap", "Return the bitmap of connected drives"),
    11: ("Kbshift", "Read or set the keyboard shift state"),
}

XBIOS_CALLS = {
    0: ("Initmous", "Initialise the mouse"),
    1: ("Ssbrk", "Reserve memory at the top of RAM"),
    2: ("Physbase", "Return the physical screen address"),
    3: ("Logbase", "Return the logical screen address"),
    4: ("Getrez", "Return the screen resolution"),
    5: ("Setscreen", "Set the screen addresses and resolution"),
    6: ("Setpalette", "Load the colour palette"),
    7: ("Setcolor", "Read or set one palette entry"),
    8: ("Floprd", "Read floppy sectors"),
    9: ("Flopwr", "Write floppy sectors"),
    10: ("Flopfmt", "Format a floppy track"),
    11: ("Dbmsg", "Send a debugger message"),
    12: ("Midiws", "Write a MIDI string"),
    13: ("Mfpint", "Set an MFP interrupt vector"),
    14: ("Iorec", "Return a device's input record"),
    15: ("Rsconf", "Configure the serial port"),
    16: ("Keytbl", "Set the keyboard translation tables"),
    17: ("Random", "Return a pseudo-random number"),
    18: ("Protobt", "Build a floppy boot sector"),
    19: ("Flopver", "Verify floppy sectors"),
    20: ("Scrdmp", "Dump the screen to the printer"),
    21: ("Cursconf", "Configure the text cursor"),
    22: ("Settime", "Set the IKBD clock"),
    23: ("Gettime", "Read the IKBD clock"),
    24: ("Bioskeys", "Restore the default keyboard tables"),
    25: ("Ikbdws", "Write a string to the keyboard controller"),
    26: ("Jdisint", "Disable an MFP interrupt"),
    27: ("Jenabint", "Enable an MFP interrupt"),
    28: ("Giaccess", "Read or write a PSG register"),
    29: ("Offgibit", "Clear a PSG port A bit"),
    30: ("Ongibit", "Set a PSG port A bit"),
    31: ("Xbtimer", "Program an MFP timer"),
    32: ("Dosound", "Start a sound command sequence"),
    33: ("Setprt", "Read or set the printer configuration"),
    34: ("Kbdvbase", "Return the keyboard vector table"),
    35: ("Kbrate", "Set the key repeat rate"),
    36: ("Prtblk", "Print a block of memory"),
    37: ("Vsync", "Wait for the next vertical blank"),
    38: ("Supexec", "Run a routine in supervisor mode"),
    39: ("Puntaes", "Discard the AES and reboot"),
    41: ("Floprate", "Set the floppy seek rate"),
    42: ("DMAread", "Read ACSI sectors"),
    43: ("DMAwrite", "Write ACSI sectors"),
    44: ("Bconmap", "Map a serial device to a BIOS handle"),
    46: ("NVMaccess", "Read or write non-volatile memory"),
    64: ("Blitmode", "Read or set the blitter mode"),
    80: ("EsetShift", "Set the STE shifter mode"),
    81: ("EgetShift", "Read the STE shifter mode"),
    82: ("EsetBank", "Set the STE palette bank"),
    83: ("EsetColor", "Set one STE palette entry"),
    84: ("EsetPalette", "Load an STE palette bank"),
    85: ("EgetPalette", "Read an STE palette bank"),
    86: ("EsetGray", "Set grey-scale mode"),
    87: ("EsetSmear", "Set smear mode"),
    88: ("VsetMode", "Set the Falcon video mode"),
    89: ("VgetMonitor", "Return the Falcon monitor type"),
    90: ("VsetSync", "Set the Falcon video sync"),
    91: ("VgetSize", "Return the screen size for a mode"),
    93: ("VsetRGB", "Set Falcon palette entries"),
    94: ("VgetRGB", "Read Falcon palette entries"),
    128: ("Locksnd", "Lock the sound system"),
    129: ("Unlocksnd", "Unlock the sound system"),
    130: ("Soundcmd", "Configure the sound system"),
    131: ("Setbuffer", "Set the sound buffer addresses"),
    132: ("Setmode", "Set the sound sample format"),
    133: ("Settracks", "Set the number of sound tracks"),
    134: ("Setmontracks", "Set the monitored sound tracks"),
    135: ("Setinterrupt", "Set the sound interrupt"),
    136: ("Buffoper", "Start or stop sound buffers"),
    137: ("Dsptristate", "Tristate the DSP connections"),
    138: ("Gpio", "Read or write the DSP port GPIO pins"),
    139: ("Devconnect", "Connect sound devices"),
    140: ("Sndstatus", "Report the sound system status"),
    141: ("Buffptr", "Read the sound buffer positions"),
}

#: The selector in D0 when ``TRAP #2`` is taken.
GEM_SELECTORS = {
    0x73: ("VDI", "Call the VDI with the parameter block in D1"),
    0xC8: ("AES", "Call the AES with the parameter block in D1"),
    0xC9: ("AES", "Call the AES, application-level entry"),
    0xFFFF: ("GEM query", "Return the GEM dispatcher address in D0"),
}

#: Which table each TRAP dispatches through.
TRAP_TABLES = {
    1: ("GEMDOS", GEMDOS_CALLS),
    13: ("BIOS", BIOS_CALLS),
    14: ("XBIOS", XBIOS_CALLS),
}


def _symbol_labels(symbols: dict | None) -> dict[int, str]:
    """Accept decimal or conventional hexadecimal addresses from project files."""
    labels = {}
    for key, value in (symbols or {}).items():
        try:
            address = int(str(key).strip().replace("&", "0x", 1).replace("$", "0x", 1), 0)
        except ValueError:
            continue
        labels[address] = str(value)
    return labels


BRANCH_MEANINGS = {
    "BRA": "Branch always",
    "BSR": "Branch to subroutine",
    "BEQ": "Branch if equal",
    "BNE": "Branch if not equal",
    "BCC": "Branch if carry clear",
    "BCS": "Branch if carry set",
    "BPL": "Branch if positive",
    "BMI": "Branch if negative",
    "BVC": "Branch if overflow clear",
    "BVS": "Branch if overflow set",
    "BGE": "Branch if greater or equal, signed",
    "BLT": "Branch if less than, signed",
    "BGT": "Branch if greater than, signed",
    "BLE": "Branch if less or equal, signed",
    "BHI": "Branch if higher, unsigned",
    "BLS": "Branch if lower or same, unsigned",
}

RETURN_MNEMONICS = {"RTS", "RTE", "RTR", "RTD"}

#: The ST memory map, as a real machine decodes it.
HARDWARE_REGIONS = (
    (0x000000, 0x0003FF, "68000 exception vectors"),
    (0x000400, 0x0005FF, "TOS system variables"),
    (0x000600, 0x3FFFFF, "ST RAM"),
    (0x400000, 0xDFFFFF, "TT RAM and expansion space"),
    (0xE00000, 0xEFFFFF, "TOS ROM (256 KiB and 512 KiB images)"),
    (0xF00000, 0xF9FFFF, "IDE and VME space"),
    (0xFA0000, 0xFBFFFF, "cartridge port"),
    (0xFC0000, 0xFEFFFF, "TOS ROM (192 KiB image)"),
    (0xFF8000, 0xFF800F, "MMU memory configuration"),
    (0xFF8200, 0xFF823F, "shifter video control"),
    (0xFF8240, 0xFF825F, "shifter palette"),
    (0xFF8260, 0xFF827F, "shifter resolution"),
    (0xFF8600, 0xFF860F, "DMA, FDC and ACSI"),
    (0xFF8800, 0xFF8803, "PSG (YM2149) sound"),
    (0xFF8900, 0xFF893F, "STE DMA sound"),
    (0xFF8A00, 0xFF8A3F, "blitter"),
    (0xFF8C80, 0xFF8C8F, "SCC serial (Mega STE and TT)"),
    (0xFF9200, 0xFF923F, "STE joypads and paddles"),
    (0xFFFA00, 0xFFFA3F, "MFP 68901"),
    (0xFFFC00, 0xFFFC07, "ACIAs (keyboard and MIDI)"),
    (0xFFFC20, 0xFFFC3F, "real-time clock (Mega ST)"),
)

#: The hardware registers a ROM touches most, by their bus address.
HARDWARE_REGISTERS = {
    0xFF8001: "MMU memory configuration",
    0xFF8201: "video base high", 0xFF8203: "video base mid",
    0xFF8205: "video counter high", 0xFF8207: "video counter mid", 0xFF8209: "video counter low",
    0xFF820A: "sync mode", 0xFF820D: "video base low (STE)", 0xFF820F: "line width (STE)",
    0xFF8240: "palette colour 0", 0xFF8242: "palette colour 1", 0xFF8244: "palette colour 2",
    0xFF8246: "palette colour 3", 0xFF8248: "palette colour 4", 0xFF824A: "palette colour 5",
    0xFF824C: "palette colour 6", 0xFF824E: "palette colour 7", 0xFF8250: "palette colour 8",
    0xFF8252: "palette colour 9", 0xFF8254: "palette colour 10", 0xFF8256: "palette colour 11",
    0xFF8258: "palette colour 12", 0xFF825A: "palette colour 13", 0xFF825C: "palette colour 14",
    0xFF825E: "palette colour 15", 0xFF8260: "shifter resolution", 0xFF8265: "horizontal scroll (STE)",
    0xFF8604: "DMA data / FDC access", 0xFF8606: "DMA mode / status",
    0xFF8609: "DMA base high", 0xFF860B: "DMA base mid", 0xFF860D: "DMA base low",
    0xFF8800: "PSG register select / read", 0xFF8802: "PSG register write",
    0xFF8900: "DMA sound control", 0xFF8921: "DMA sound mode",
    0xFF8A00: "blitter halftone RAM", 0xFF8A3A: "blitter skew", 0xFF8A3C: "blitter line number / control",
    0xFFFA01: "MFP GPIP", 0xFFFA03: "MFP active edge", 0xFFFA05: "MFP data direction",
    0xFFFA07: "MFP interrupt enable A", 0xFFFA09: "MFP interrupt enable B",
    0xFFFA0B: "MFP interrupt pending A", 0xFFFA0D: "MFP interrupt pending B",
    0xFFFA0F: "MFP in-service A", 0xFFFA11: "MFP in-service B",
    0xFFFA13: "MFP interrupt mask A", 0xFFFA15: "MFP interrupt mask B",
    0xFFFA17: "MFP vector register", 0xFFFA19: "MFP timer A control",
    0xFFFA1B: "MFP timer B control", 0xFFFA1D: "MFP timer C and D control",
    0xFFFA1F: "MFP timer A data", 0xFFFA21: "MFP timer B data",
    0xFFFA23: "MFP timer C data", 0xFFFA25: "MFP timer D data",
    0xFFFA27: "MFP sync character", 0xFFFA29: "MFP USART control",
    0xFFFA2B: "MFP receiver status", 0xFFFA2D: "MFP transmitter status",
    0xFFFA2F: "MFP USART data",
    0xFFFC00: "keyboard ACIA control / status", 0xFFFC02: "keyboard ACIA data",
    0xFFFC04: "MIDI ACIA control / status", 0xFFFC06: "MIDI ACIA data",
}

#: The 68000 exception vectors and the TOS uses of the TRAP and MFP vectors.
EXCEPTION_VECTORS = {
    0x000: "Initial SSP", 0x004: "Initial PC", 0x008: "Bus error",
    0x00C: "Address error", 0x010: "Illegal instruction", 0x014: "Divide by zero",
    0x018: "CHK instruction", 0x01C: "TRAPV instruction", 0x020: "Privilege violation",
    0x024: "Trace", 0x028: "Line-A (VDI fast graphics)", 0x02C: "Line-F",
    0x060: "Spurious interrupt", 0x064: "Level 1 autovector",
    0x068: "Level 2 autovector (HBL)", 0x06C: "Level 3 autovector",
    0x070: "Level 4 autovector (VBL)", 0x074: "Level 5 autovector",
    0x078: "Level 6 autovector (MFP)", 0x07C: "Level 7 autovector (NMI)",
    0x080: "TRAP #0", 0x084: "TRAP #1 (GEMDOS)", 0x088: "TRAP #2 (AES and VDI)",
    0x08C: "TRAP #3", 0x090: "TRAP #4", 0x094: "TRAP #5", 0x098: "TRAP #6",
    0x09C: "TRAP #7", 0x0A0: "TRAP #8", 0x0A4: "TRAP #9", 0x0A8: "TRAP #10",
    0x0AC: "TRAP #11", 0x0B0: "TRAP #12", 0x0B4: "TRAP #13 (BIOS)",
    0x0B8: "TRAP #14 (XBIOS)", 0x0BC: "TRAP #15",
    0x100: "MFP parallel port busy", 0x104: "MFP RS232 DCD", 0x108: "MFP RS232 CTS",
    0x10C: "MFP blitter done", 0x110: "MFP timer D (RS232 baud)", 0x114: "MFP timer C (200 Hz)",
    0x118: "MFP ACIA (keyboard and MIDI)", 0x11C: "MFP FDC and ACSI", 0x120: "MFP timer B (HBL)",
    0x124: "MFP RS232 transmit error", 0x128: "MFP RS232 transmit buffer empty",
    0x12C: "MFP RS232 receive error", 0x130: "MFP RS232 receive buffer full",
    0x134: "MFP timer A (DMA sound)", 0x138: "MFP RS232 ring indicator",
    0x13C: "MFP monochrome monitor detect",
}

#: The TOS system variables at $380 to $5FF.
SYSTEM_VARIABLES = {
    0x380: "proc_lives", 0x384: "proc_dregs", 0x3A4: "proc_aregs", 0x3C4: "proc_enum",
    0x3C8: "proc_usp", 0x3CC: "proc_stk", 0x400: "etv_timer", 0x404: "etv_critic",
    0x408: "etv_term", 0x40C: "etv_xtra", 0x420: "memvalid", 0x424: "memcntlr",
    0x426: "resvalid", 0x42A: "resvector", 0x42E: "phystop", 0x432: "_membot",
    0x436: "_memtop", 0x43A: "memval2", 0x43E: "flock", 0x440: "seekrate",
    0x442: "_timr_ms", 0x444: "_fverify", 0x446: "_bootdev", 0x448: "palmode",
    0x44A: "defshiftmd", 0x44C: "sshiftmd", 0x44E: "_v_bas_ad", 0x452: "vblsem",
    0x454: "nvbls", 0x456: "_vblqueue", 0x45A: "colorptr", 0x45E: "screenpt",
    0x462: "_vbclock", 0x466: "_frclock", 0x46A: "hdv_init", 0x46E: "swv_vec",
    0x472: "hdv_bpb", 0x476: "hdv_rw", 0x47A: "hdv_boot", 0x47E: "hdv_mediach",
    0x482: "_cmdload", 0x484: "conterm", 0x48E: "themd", 0x49E: "___md",
    0x4A2: "savptr", 0x4A6: "_nflops", 0x4A8: "con_state", 0x4AC: "save_row",
    0x4AE: "sav_context", 0x4B2: "_bufl", 0x4BA: "_hz_200", 0x4BE: "the_env",
    0x4C2: "_drvbits", 0x4C6: "_dskbufp", 0x4CA: "_autopath", 0x4CE: "_vbl_list",
    0x4EE: "_dumpflg", 0x4F0: "_prtabt", 0x4F2: "_sysbase", 0x4F6: "_shell_p",
    0x4FA: "end_os", 0x4FE: "exec_os", 0x502: "scr_dump", 0x506: "prv_lsto",
    0x50A: "prv_lst", 0x50E: "prv_auxo", 0x512: "prv_aux", 0x516: "pun_ptr",
    0x51A: "memval3", 0x51E: "xconstat", 0x53E: "xconin", 0x55E: "xcostat",
    0x57E: "xconout", 0x59E: "_longframe", 0x5A0: "_p_cookies", 0x5A4: "ramtop",
    0x5A8: "ramvalid", 0x5AC: "bell_hook", 0x5B0: "kcl_hook",
}


def _hex_value(operand: str) -> int | None:
    """Parse the first numeric literal in a Capstone operand string.

    Capstone renders operands in many shapes -- ``#$1F``, ``$ff8240.l``,
    ``-$228(a6)``, ``$e00014(pc)`` -- so the value is extracted by pattern
    rather than by trimming.
    """
    match = re.search(r"(-?)\$([0-9A-Fa-f]+)|(-?)\b(\d+)\b", str(operand or ""))
    if not match:
        return None
    if match.group(2) is not None:
        value = int(match.group(2), 16)
        return -value if match.group(1) == "-" else value
    value = int(match.group(4))
    return -value if match.group(3) == "-" else value


def _hex_values(operand: str) -> list[int]:
    """Return every numeric literal in an operand, in the order they appear."""
    values: list[int] = []
    for match in re.finditer(r"(-?)\$([0-9A-Fa-f]+)|(-?)\b(\d+)\b", str(operand or "")):
        if match.group(2) is not None:
            value = int(match.group(2), 16)
            values.append(-value if match.group(1) == "-" else value)
        else:
            value = int(match.group(4))
            values.append(-value if match.group(3) == "-" else value)
    return values


_ABSOLUTE = re.compile(r"(?<![#(\w])\$([0-9A-Fa-f]+)(\.[wlWL])?(?![\w(])")


def _absolute_addresses(operand: str) -> list[int]:
    """Return the 24-bit bus addresses of the absolute operands in a string.

    An immediate (``#$...``) and a displacement (``$...(a0)``) are not
    addresses. A short absolute operand is sign-extended by the processor, so
    ``$8240.w`` reaches ``$FF8240``; a long one is masked to the 24 lines an
    ST actually drives, so ``$ffff8240.l`` lands on the same register.
    """
    found: list[int] = []
    for match in _ABSOLUTE.finditer(str(operand or "")):
        value = int(match.group(1), 16)
        size = (match.group(2) or "").lower()
        if size == ".w" and value >= 0x8000:
            value |= 0xFFFF0000
        found.append(value & 0xFFFFFF)
    return found


def _character(value: int | None) -> str:
    if value is None or not 32 <= value <= 126:
        return ""
    return f"'{chr(value)}'"


def _hardware_region(address: int | None) -> str:
    if address is None:
        return ""
    return next(
        (name for start, end, name in HARDWARE_REGIONS if start <= address <= end), ""
    )


def _trap_number(operand: str) -> int | None:
    value = _hex_value(operand)
    return value if value is not None and 0 <= value <= 15 else None


def _pushed_word(mnemonic: str, compact: str, operand: str) -> int | None:
    """Return the immediate when the row is ``MOVE.W #imm,-(SP)``."""
    if mnemonic != "MOVE" or not compact.startswith("#") or not compact.endswith(("-(a7)", "-(sp)")):
        return None
    value = _hex_value(operand)
    return value & 0xFFFF if value is not None else None


def _loaded_d0(mnemonic: str, compact: str, operand: str) -> int | None:
    """Return the immediate when the row is ``MOVE.L #imm,D0`` or ``MOVEQ #imm,D0``."""
    if mnemonic not in {"MOVE", "MOVEQ"} or not compact.startswith("#") or not compact.endswith(",d0"):
        return None
    value = _hex_value(operand)
    return value & 0xFFFF if value is not None else None


def _trap_call(trap: int, function: int | None, selector: int | None) -> tuple[str, str]:
    """Name a system call from the TRAP number and the word pushed before it.

    Returns the short label used for routine names and the full comment.
    """
    if trap == 2:
        if selector is None:
            return "gem_call", "AES or VDI call through TRAP #2 (selector in D0 not visible here)"
        name, summary = GEM_SELECTORS.get(selector, (f"TRAP #2 selector ${selector:X}", "Call the GEM dispatcher"))
        return name.lower().replace(" ", "_"), f"{name}: {summary}"
    table = TRAP_TABLES.get(trap)
    if table is None:
        return f"trap_{trap}", f"TRAP #{trap}: not a TOS system call vector"
    system, calls = table
    if function is None:
        return system.lower(), f"{system} call through TRAP #{trap} (function number not visible here)"
    entry = calls.get(function)
    if entry is None:
        return f"{system.lower()}_{function:02x}", f"{system} function ${function:02X}: not a documented call"
    name, summary = entry
    return name.lower(), f"{system} {name} (${function:02X}): {summary}"


def _trap_in_block(block: list[dict]) -> str | None:
    """Return the short label of the first named system call in a routine."""
    function: int | None = None
    selector: int | None = None
    for row in block:
        mnemonic = base_mnemonic(row.get("mnemonic"))
        operand = str(row.get("operand") or "")
        compact = operand.replace(" ", "").lower()
        pushed = _pushed_word(mnemonic, compact, operand)
        if pushed is not None:
            function = pushed
        loaded = _loaded_d0(mnemonic, compact, operand)
        if loaded is not None:
            selector = loaded
        if mnemonic == "TRAP":
            trap = _trap_number(operand)
            if trap is not None:
                return _trap_call(trap, function, selector)[0]
    return None


def _semantic_68000_labels(report: dict) -> None:
    """Assign stable labels from proved control flow and routine behaviour."""
    rows = report["rows"]
    by_address = {int(row["address"]): row for row in rows}
    index_by_address = {int(row["address"]): index for index, row in enumerate(rows)}
    call_mnemonics = {"JSR", "BSR"}
    call_targets = {
        int(row["target"])
        for row in rows
        if base_mnemonic(row.get("mnemonic")) in call_mnemonics
        and isinstance(row.get("target"), int)
        and int(row["target"]) in by_address
    }

    def routine_rows(target: int) -> list[dict]:
        start = index_by_address.get(target)
        if start is None:
            return []
        block = []
        for row in rows[start : start + 96]:
            if block and int(row["address"]) in call_targets:
                break
            block.append(row)
            if base_mnemonic(row.get("mnemonic")) in RETURN_MNEMONICS | {"JMP", "BRA"}:
                break
        return block

    for target in sorted(call_targets):
        target_row = by_address[target]
        existing = str(target_row.get("label") or "")
        if existing and not existing.startswith(("sub_", "loc_", "subroutine_")):
            continue
        block = routine_rows(target)
        endings = {base_mnemonic(row.get("mnemonic")) for row in block}
        backwards_branch = any(
            isinstance(row.get("target"), int) and int(row["target"]) <= int(row["address"])
            for row in block
            if base_mnemonic(row.get("mnemonic")) in BRANCH_MEANINGS
        )
        system_call = _trap_in_block(block)
        if "RTE" in endings:
            purpose = "exception_handler"
        elif system_call:
            purpose = f"call_{system_call}"
        elif backwards_branch:
            purpose = "loop_routine"
        else:
            hardware = next(
                (
                    _hardware_region(address)
                    for row in block
                    for address in _absolute_addresses(str(row.get("operand") or ""))
                    if address >= 0xFF8000
                ),
                "",
            )
            purpose = "access_hardware" if hardware else "subroutine"
        target_row["label"] = f"{purpose}_{target:06X}"

    branch_names = {
        "BEQ": "equal", "BNE": "not_equal", "BCC": "carry_clear",
        "BCS": "carry_set", "BMI": "negative", "BPL": "positive",
        "BVC": "overflow_clear", "BVS": "overflow_set", "BGE": "greater_equal",
        "BLT": "less_than", "BGT": "greater_than", "BLE": "less_equal",
        "BHI": "higher", "BLS": "lower_same", "BRA": "always",
    }
    flow_references: dict[int, list[dict]] = {}
    for source in rows:
        target = source.get("target")
        if base_mnemonic(source.get("mnemonic")) in {*BRANCH_MEANINGS, "JMP"} and isinstance(target, int):
            flow_references.setdefault(target, []).append(source)
    for target, references in flow_references.items():
        target_row = by_address.get(target)
        if target_row is None or target in call_targets or target_row.get("label"):
            continue
        if any(target <= int(source["address"]) for source in references):
            purpose = "loop"
        else:
            mnemonics = {base_mnemonic(source.get("mnemonic")) for source in references}
            if len(mnemonics) == 1:
                mnemonic = next(iter(mnemonics))
                purpose = branch_names.get(mnemonic, "dispatch" if mnemonic == "JMP" else "continue")
            else:
                purpose = "continue"
        target_row["label"] = f"{purpose}_{target:06X}"


def base_mnemonic(mnemonic: str) -> str:
    """Return an instruction's operation without its ``.B``/``.W``/``.L`` size."""
    return str(mnemonic or "").upper().split(".", 1)[0]


def _annotate_68000(report: dict, data: bytes) -> dict:
    """Explain a 68000 listing in Atari terms.

    The two things that make TOS machine code readable are knowing which
    system call a ``TRAP`` makes, and knowing which chip a memory reference
    touches. Both are tracked here: the function word pushed before the TRAP
    (and the selector loaded into D0 for ``TRAP #2``), and the address ranges
    the ST hardware decodes.
    """
    rows = report["rows"]
    by_address = {int(row["address"]): row for row in rows}
    _semantic_68000_labels(report)
    call_mnemonics = {"JSR", "BSR"}
    call_targets = {
        int(row["target"])
        for row in rows
        if base_mnemonic(row.get("mnemonic")) in call_mnemonics
        and isinstance(row.get("target"), int)
    }
    flow_targets = {
        int(row["target"])
        for row in rows
        if base_mnemonic(row.get("mnemonic")) in set(BRANCH_MEANINGS) | {"JMP"}
        and isinstance(row.get("target"), int)
    }
    for target in call_targets | flow_targets:
        target_row = by_address.get(target)
        if target_row is not None and not target_row.get("label"):
            target_row["label"] = f"{'sub' if target in call_targets else 'loc'}_{target:06X}"
    for row in rows:
        target = row.get("target")
        if (
            isinstance(target, int)
            and target in by_address
            and base_mnemonic(row.get("mnemonic")) in {*call_mnemonics, "JMP", *BRANCH_MEANINGS}
        ):
            row["operand"] = by_address[target].get("label") or row["operand"]

    function: int | None = None
    selector: int | None = None
    for row in rows:
        mnemonic = base_mnemonic(row.get("mnemonic"))
        # Capstone spaces its operands; compare against a space-free form so a
        # destination register test does not depend on formatting.
        operand = str(row.get("operand") or "")
        compact = operand.replace(" ", "").lower()
        target = row.get("target")
        comment = ""

        pushed = _pushed_word(mnemonic, compact, operand)
        loaded = _loaded_d0(mnemonic, compact, operand)
        if pushed is not None:
            function = pushed
            comment = f"Push function number ${pushed:02X} for the next TRAP"
        elif loaded is not None and mnemonic in {"MOVE", "MOVEQ"}:
            selector = loaded
            if loaded in GEM_SELECTORS:
                comment = f"Select the {GEM_SELECTORS[loaded][0]} entry for TRAP #2"
        if mnemonic == "TRAP":
            trap = _trap_number(operand)
            if trap is not None:
                comment = _trap_call(trap, function, selector)[1]
            else:
                comment = "Raise a processor trap"
            function = None
            selector = None
        elif mnemonic in {"JSR", "BSR"}:
            if isinstance(target, int):
                comment = f"Call subroutine {operand}"
            function = None
        elif mnemonic in BRANCH_MEANINGS:
            comment = f"{BRANCH_MEANINGS[mnemonic]} to {operand}"
        elif mnemonic == "JMP":
            comment = f"Continue execution at {operand}"
        elif mnemonic in RETURN_MNEMONICS:
            comment = {
                "RTS": "Return from subroutine",
                "RTE": "Return from exception",
                "RTR": "Return and restore condition codes",
                "RTD": "Return and deallocate stack",
            }[mnemonic]
        elif not comment and mnemonic.startswith(("MOVE", "LEA", "PEA", "BTST", "BSET", "BCLR", "BCHG", "AND", "OR", "CLR", "TST", "ADD", "SUB", "CMP")):
            addresses = _absolute_addresses(operand)
            address = next(
                (
                    candidate
                    for candidate in addresses
                    if candidate in HARDWARE_REGISTERS
                    or candidate in EXCEPTION_VECTORS
                    or candidate in SYSTEM_VARIABLES
                ),
                addresses[0] if addresses else None,
            )
            register = HARDWARE_REGISTERS.get(address) if address is not None else None
            vector = EXCEPTION_VECTORS.get(address) if address is not None else None
            variable = SYSTEM_VARIABLES.get(address) if address is not None else None
            region = _hardware_region(address)
            if register:
                comment = f"Access the {register} register at ${address:06X}"
            elif vector:
                comment = f"Access the {vector} vector at ${address:03X}"
            elif variable:
                comment = f"Access the {variable} system variable at ${address:03X}"
            elif region and address is not None and address >= 0xFF8000:
                comment = f"Access {region} at ${address:06X}"
            elif operand.startswith("#"):
                value = _hex_value(operand)
                if value is not None:
                    display = _character(value)
                    comment = f"Load ${value:X}{f' ({display})' if display else ''}"
        if comment:
            row["comment"] = comment
        else:
            row["comment"] = str(row.get("comment") or "")
    return report


#: Capstone modes for each processor the workbench offers.
M68K_MODES = {
    "68000": "CS_MODE_M68K_000",
    "68010": "CS_MODE_M68K_010",
    "68020": "CS_MODE_M68K_020",
    "68030": "CS_MODE_M68K_030",
    "68040": "CS_MODE_M68K_040",
    "68060": "CS_MODE_M68K_060",
    "m68k": "CS_MODE_M68K_000",
}


def disassemble_68000(data: bytes, *, origin: int = DEFAULT_ROM_BASE, start: int = 0,
                      length: int | None = None, symbols: dict | None = None) -> dict:
    """Disassemble MC68000 code and annotate it in Atari terms."""
    report = disassemble_capstone(
        data,
        architecture="68000",
        origin=origin,
        start=start,
        length=length,
        symbols=symbols,
    )
    return _annotate_68000(report, data)


def _with_control_flow(report: dict, entry_points: list[int]) -> dict:
    rows = report["rows"]
    by_address = {int(row["address"]): row for row in rows}
    xrefs: dict[int, list[int]] = {}
    for row in rows:
        target = row.get("target")
        if isinstance(target, int):
            xrefs.setdefault(target, []).append(int(row["address"]))
    starts = [point for point in entry_points if point in by_address]
    if not starts and rows:
        starts = [int(rows[0]["address"])]
    reachable, pending = set(), list(starts)
    while pending:
        address = pending.pop()
        row = by_address.get(address)
        if row is None or address in reachable:
            continue
        reachable.add(address)
        mnemonic = str(row.get("mnemonic") or "").upper()
        target = row.get("target")
        size = max(1, len(str(row.get("bytes") or "").split()))
        fallthrough = address + size
        if isinstance(target, int) and (mnemonic.startswith("B") or mnemonic in {"JSR", "JSL", "JMP", "JML", "BL", "BLX", "BSR", "BRA", "BRL"}):
            pending.append(target)
        if mnemonic not in {"JMP", "JML", "BRA", "BRL", "RTS", "RTL", "RTI", "BRK", "RTE"} and not mnemonic.startswith("B."):
            pending.append(fallthrough)
    for row in rows:
        row["reachable"] = int(row["address"]) in reachable
        row["references"] = xrefs.get(int(row["address"]), [])
    report["entryPoints"] = starts
    report["crossReferences"] = [
        {"target": target, "sources": sources}
        for target, sources in sorted(xrefs.items())
    ]
    report["reachableInstructions"] = len(reachable)
    return report


def _annotate_generic_control_flow(report: dict) -> dict:
    rows = report["rows"]
    by_address = {int(row["address"]): row for row in rows}
    call_names = {"BL", "BLX", "BSR", "JSR", "JSL"}
    jump_names = {"B", "BRA", "BRL", "JMP", "JML"}
    for row in rows:
        target = row.get("target")
        mnemonic = base_mnemonic(row.get("mnemonic"))
        target_row = by_address.get(target) if isinstance(target, int) else None
        if target_row is not None and not target_row.get("label"):
            if mnemonic in call_names:
                purpose = "subroutine"
            elif int(target) <= int(row["address"]):
                purpose = "loop"
            elif mnemonic in jump_names:
                purpose = "dispatch"
            else:
                purpose = "continue"
            target_row["label"] = f"{purpose}_{int(target):X}"
    for row in rows:
        mnemonic = base_mnemonic(row.get("mnemonic"))
        operand = str(row.get("operand") or "")
        target = row.get("target")
        target_row = by_address.get(target) if isinstance(target, int) else None
        if target_row is not None:
            operand = row["operand"] = target_row.get("label") or operand
        if row.get("comment"):
            continue
        if mnemonic in call_names:
            row["comment"] = f"Call subroutine {operand}"
        elif mnemonic in jump_names:
            row["comment"] = f"Continue execution at {operand}"
        elif mnemonic.startswith("B") and isinstance(target, int):
            row["comment"] = f"Conditional branch to {operand}"
        elif mnemonic in {"RTS", "RTL", "RTI", "RTE"} or (mnemonic == "BX" and operand.upper() == "LR"):
            row["comment"] = "Return from subroutine"
    return report


def disassemble_capstone(data: bytes, *, architecture: str, origin: int = 0,
                         start: int = 0, length: int | None = None,
                         symbols: dict | None = None,
                         entry_points: list[int] | None = None) -> dict:
    if Cs is None:
        raise RomWorkbenchError("The production disassembly engine is not installed.")
    if start < 0 or start >= len(data):
        raise RomWorkbenchError("The disassembly start is outside this ROM bank.")
    requested = len(data) - start if length is None else max(1, int(length))
    end = min(len(data), start + requested, start + MAX_DISASSEMBLY_BYTES)
    mode = {
        "68000": CS_MODE_M68K_000,
        "68010": CS_MODE_M68K_010,
        "68020": CS_MODE_M68K_020,
        "68030": CS_MODE_M68K_030,
        "68040": CS_MODE_M68K_040,
        "68060": CS_MODE_M68K_060,
        "m68k": CS_MODE_M68K_000,
    }.get(architecture)
    if mode is None:
        raise RomWorkbenchError(
            "Choose 68000, 68010, 68020, 68030, 68040 or 68060 disassembly."
        )
    # The 68000 family is big-endian in every Atari, so the mode is fixed
    # rather than offered as a choice that could only ever be wrong.
    engine = Cs(CS_ARCH_M68K, mode | CS_MODE_BIG_ENDIAN)
    engine.skipdata = True
    rows = []
    labels = _symbol_labels(symbols)
    branch_names = {
        "bra", "bsr", "jmp", "jsr",
        "bcc", "bcs", "beq", "bne", "bmi", "bpl", "bvc", "bvs",
        "bge", "blt", "bgt", "ble", "bhi", "bls",
        "dbra", "dbf", "dbeq", "dbne",
    }
    for instruction in engine.disasm(data[start:end], origin + start):
        mnemonic = instruction.mnemonic.upper()
        operand = instruction.op_str
        target = None
        if instruction.mnemonic.lower().split(".", 1)[0] in branch_names:
            token = operand.rsplit(",", 1)[-1].strip().lstrip("#")
            try:
                target = int(token[1:], 16) if token.startswith("$") else int(token, 0)
            except ValueError:
                target = None
        rows.append({"offset": instruction.address - origin, "address": instruction.address,
                     "bytes": instruction.bytes.hex(" ").upper(), "mnemonic": mnemonic,
                     "operand": operand, "target": target,
                     "label": labels.get(instruction.address, ""), "comment": ""})
    report = {"architecture": architecture, "origin": origin, "start": start,
              "end": end, "truncated": end < start + requested, "rows": rows}
    return _annotate_generic_control_flow(_with_control_flow(report, entry_points or []))


def disassemble(data: bytes, *, architecture: str, origin: int, start: int = 0,
                length: int | None = None, symbols: dict | None = None,
                entry_points: list[int] | None = None) -> dict:
    """Disassemble a range and annotate it with Atari system knowledge."""
    report = disassemble_capstone(
        data,
        architecture=architecture,
        origin=origin,
        start=start,
        length=length,
        symbols=symbols,
        entry_points=entry_points,
    )
    return _annotate_68000(report, data)


def bank_map(data: bytes, bank_size: int, erase_byte: int = 0xFF) -> dict:
    """Map each bank of a ROM image to the addresses it answers at.

    A TOS image is mapped as one contiguous block at the base its size
    implies, so a bank's window is its file offset added to that base rather
    than a fixed paging window.
    """
    rows, hashes = [], {}
    base = rom_base(len(data))
    image_header = parse_rom_header(data)
    for bank, offset in enumerate(range(0, len(data), bank_size)):
        block = data[offset:offset + bank_size]
        decoded = inspect_bank(block, bank, erase_byte, image_header)
        digest = decoded["diagnostics"]["sha256"]
        hashes.setdefault(digest, []).append(bank)
        rows.append({"bank": bank, "fileOffset": offset,
                     "cpuWindow": f"${base + offset:06X}-${base + offset + max(1, len(block)) - 1:06X}",
                     "length": len(block), "title": decoded["name"], "type": decoded["filetype"],
                     "empty": decoded["empty"], "sha256": digest})
    for row in rows:
        row["duplicates"] = [number for number in hashes[row["sha256"]] if number != row["bank"]]
    return {"bankSize": bank_size, "bankCount": len(rows), "banks": rows}


def compare_roms(left: bytes, right: bytes, *, max_ranges: int = 10000) -> dict:
    maximum = max(len(left), len(right))
    ranges, start, changed_bytes, captured_hex, omitted_bytes = [], None, 0, 0, False
    for offset in range(maximum + 1):
        different = offset < maximum and (
            offset >= len(left) or offset >= len(right) or left[offset] != right[offset]
        )
        if different and start is None:
            start = offset
        elif not different and start is not None:
            length = offset - start
            changed_bytes += length
            if len(ranges) < max_ranges:
                left_bytes, right_bytes = left[start:offset], right[start:offset]
                keep_bytes = captured_hex + 2 * (len(left_bytes) + len(right_bytes)) <= MAX_PATCH_BYTES * 4
                left_hex = left_bytes.hex().upper() if keep_bytes else ""
                right_hex = right_bytes.hex().upper() if keep_bytes else ""
                ranges.append({"start": start, "end": offset, "length": length,
                               "left": left_hex, "right": right_hex})
                captured_hex += len(left_hex) + len(right_hex)
                omitted_bytes = omitted_bytes or not keep_bytes
            start = None
    return {"leftSize": len(left), "rightSize": len(right), "leftSha256": sha256_bytes(left),
            "rightSha256": sha256_bytes(right), "changedBytes": changed_bytes,
            "ranges": ranges, "rangesTruncated": changed_bytes > sum(row["length"] for row in ranges),
            "bytesOmitted": omitted_bytes}


def make_patch(left: bytes, right: bytes) -> dict:
    report = compare_roms(left, right)
    if report["changedBytes"] > MAX_PATCH_BYTES or report["rangesTruncated"] or report["bytesOmitted"]:
        raise RomWorkbenchError("That patch exceeds the 16 MiB safety limit.")
    return {"format": PATCH_FORMAT, "sourceSha256": report["leftSha256"],
            "targetSha256": report["rightSha256"], "sourceSize": len(left), "targetSize": len(right),
            "ranges": [{"offset": row["start"], "remove": len(bytes.fromhex(row["left"])),
                        "data": base64.b64encode(bytes.fromhex(row["right"])).decode("ascii")}
                       for row in report["ranges"]]}


def make_selective_patch(left: bytes, right: bytes, indexes: list[int]) -> dict:
    report = compare_roms(left, right)
    selected = sorted(set(int(index) for index in indexes))
    if not selected or any(index < 0 or index >= len(report["ranges"]) for index in selected):
        raise RomWorkbenchError("Choose one or more valid changed ranges.")
    result = bytearray(left)
    adjustment = 0
    for index in selected:
        row = report["ranges"][index]
        if not row.get("right"):
            raise RomWorkbenchError("That changed range is too large for a selective patch.")
        offset = row["start"] + adjustment
        remove = len(bytes.fromhex(row["left"]))
        replacement = bytes.fromhex(row["right"])
        result[offset:offset + remove] = replacement
        adjustment += len(replacement) - remove
    return make_patch(left, bytes(result))


def apply_patch(source: bytes, document: dict) -> bytes:
    if document.get("format") != PATCH_FORMAT or sha256_bytes(source) != document.get("sourceSha256"):
        raise RomWorkbenchError("This patch does not match the selected source ROM checksum.")
    result = bytearray(source)
    adjustment = 0
    for row in document.get("ranges", []):
        offset, remove = int(row["offset"]) + adjustment, int(row["remove"])
        replacement = base64.b64decode(row["data"], validate=True)
        if offset < 0 or remove < 0 or offset + remove > len(result):
            raise RomWorkbenchError("The patch contains an invalid byte range.")
        result[offset:offset + remove] = replacement
        adjustment += len(replacement) - remove
    if len(result) != int(document.get("targetSize", -1)) or sha256_bytes(result) != document.get("targetSha256"):
        raise RomWorkbenchError("The patched bytes did not produce the expected target ROM.")
    return bytes(result)


def audit_rom(data: bytes, bank_size: int, erase_byte: int = 0xFF) -> dict:
    findings, repairable = [], []
    mapping = bank_map(data, bank_size, erase_byte)
    if len(data) % bank_size:
        findings.append({"level": "warning", "code": "partial-bank", "message":
                         f"The final bank contains {len(data) % bank_size:,} bytes."})
    image_header = parse_rom_header(data)
    for row in mapping["banks"]:
        block = data[row["fileOffset"]:row["fileOffset"] + bank_size]
        decoded = inspect_bank(block, row["bank"], erase_byte, image_header)
        for warning in decoded["warnings"]:
            findings.append({"level": "error", "code": "tos-header", "bank": row["bank"], "message": warning})
        for note in decoded["notes"]:
            findings.append({"level": "info", "code": "vector-install", "bank": row["bank"], "message": note})
        if row["duplicates"] and row["bank"] < min(row["duplicates"]):
            findings.append({"level": "info", "code": "duplicate-bank", "bank": row["bank"],
                             "message": f"Bank {row['bank']} is identical to bank(s) {', '.join(map(str, row['duplicates']))}."})
    if image_header is not None:
        if not image_header.dates_agree and image_header.date:
            findings.append({"level": "error", "code": "date-word", "message":
                             "The GEMDOS date word at $1E does not match the BCD build date at $18."})
            repairable.append("date-word")
        if image_header.emutos:
            findings.append({"level": "info", "code": "emutos", "message":
                             f"This is EmuTOS {image_header.emutos_version or '(version unknown)'}; "
                             f"the header carries compatibility version word ${image_header.version_word:04X}."})
    return {"healthy": not any(row["level"] == "error" for row in findings),
            "sha256": sha256_bytes(data), "crc32": f"{zlib.crc32(data) & 0xFFFFFFFF:08X}",
            "findings": findings, "repairable": repairable, "map": mapping}


def repair_date_word(data: bytes) -> bytes:
    """Rewrite the GEMDOS date word at ``$1E`` from the BCD build date at ``$18``.

    The BCD date is the one TOS prints and the one every catalogue records, so
    it is treated as authoritative. TOS 1.00 has no date word to repair.
    """
    header = parse_rom_header(data)
    if header is None:
        raise RomWorkbenchError("No TOS header was found, so there is no date word to repair.")
    if header.version_word < 0x0102:
        raise RomWorkbenchError("TOS 1.00 carries no GEMDOS date word.")
    when = decode_bcd_date(int.from_bytes(data[0x18:0x1C], "big"))
    if when is None:
        raise RomWorkbenchError("The BCD build date is not a valid date, so the date word cannot be derived from it.")
    if header.dates_agree:
        raise RomWorkbenchError("The GEMDOS date word already matches the build date.")
    result = bytearray(data)
    result[0x1E:0x20] = encode_dos_date(when).to_bytes(2, "big")
    return bytes(result)


def repair_extension_checksum(data: bytes) -> bytes:
    """Retained only so the un-ported route module still imports."""
    raise RomWorkbenchError("A TOS ROM carries no checksum trailer; the available repair is date-word.")


def repair_header_role_flags(data: bytes, bank_size: int) -> bytes:
    """Retained only so the un-ported route module still imports."""
    raise RomWorkbenchError("A TOS ROM header has no role flags; the available repair is date-word.")


def normalise_project(document: dict | None) -> dict:
    source = document if isinstance(document, dict) else {}
    identity_source = source.get("identity") if isinstance(source.get("identity"), dict) else {}
    identity = {
        key: str(identity_source.get(key) or "")[:limit]
        for key, limit in {"title": 160, "version": 80, "publisher": 160,
                           "platform": 120, "notes": 2000}.items()
    }
    return {"format": PROJECT_FORMAT, "notes": str(source.get("notes") or "")[:20000],
            "hardware": str(source.get("hardware") or "")[:200],
            "symbols": {str(key): str(value)[:80] for key, value in dict(source.get("symbols") or {}).items()},
            "regions": [row for row in source.get("regions", []) if isinstance(row, dict)][:2048],
            "tests": [row for row in source.get("tests", []) if isinstance(row, dict)][:512],
            "identity": identity}


def project_json(document: dict) -> bytes:
    return json.dumps(normalise_project(document), indent=2, sort_keys=True).encode("utf-8") + b"\n"


def identify_rom(data: bytes, catalogue_path: Path | None = None) -> dict:
    """Identify a ROM by exact hash and by what its header declares.

    The catalogue match is exact SHA-256 and is the only thing reported as a
    confirmed title. The ``tos`` block is what the header itself says, which
    is enough to name a release and country but not to prove the dump is
    unaltered.
    """
    digest, crc = sha256_bytes(data), f"{zlib.crc32(data) & 0xFFFFFFFF:08X}"
    records = []
    if catalogue_path and catalogue_path.is_file():
        try:
            document = json.loads(catalogue_path.read_text(encoding="utf-8"))
            records = document.get("roms", []) if isinstance(document, dict) else []
        except (OSError, ValueError, json.JSONDecodeError):
            records = []
    exact = next((row for row in records if str(row.get("sha256", "")).lower() == digest), None)
    transformations = []
    if len(data) % 2 == 0 and data[:len(data)//2] == data[len(data)//2:]:
        transformations.append("The image contains two identical mirrored halves.")
    if len(data) in TOS_SIZES:
        transformations.append(f"The size is a conventional {len(data) // 1024} KiB TOS ROM.")
    elif len(data) == CARTRIDGE_SIZE:
        transformations.append("The size is a conventional 128 KiB cartridge ROM.")
    header = parse_rom_header(data)
    cartridge = parse_cartridge_header(data) if header is None else None
    declared = None
    if header is not None:
        declared = {
            "kind": "emutos" if header.emutos else "tos",
            "release": header.release,
            "version": header.version,
            "versionWord": f"{header.version_word:04X}",
            "country": header.country,
            "countryShort": header.country_short,
            "videoStandard": header.video_standard,
            "machine": header.machine,
            "date": header.date,
            "base": header.base,
            "sizeValid": header.size_valid,
            "baseValid": header.base_valid,
        }
    elif cartridge is not None:
        declared = {
            "kind": "cartridge",
            "applications": [application["name"] for application in cartridge.applications],
            "base": cartridge.base,
            "sizeValid": cartridge.size_valid,
        }
    return {"matched": exact is not None, "record": exact, "sha256": digest, "crc32": crc,
            "transformations": transformations, "declared": declared}


CARTRIDGE_BUILD_SIZES = {16 * 1024, 32 * 1024, 64 * 1024, 128 * 1024}


def build_cartridge_rom(title: str, applications: list[dict] | None = None,
                        size: int = 128 * 1024, erase_byte: int = 0xFF) -> bytes:
    """Build an inert but structurally valid cartridge ROM.

    TOS finds a cartridge's contents through the ``$ABCDEF42`` magic and the
    application header chain that follows it, so the scaffold is one real
    header per name whose run routine is a single ``RTS``. That is a genuine
    "nothing to do" answer, so a scaffold fitted to a machine before its
    program is written cannot do anything unexpected. Any further names are
    recorded as headers in the chain; they are not pretended to be working
    programs.
    """
    if size not in CARTRIDGE_BUILD_SIZES:
        raise RomWorkbenchError("A cartridge ROM scaffold must be 16K, 32K, 64K or 128K.")
    def application_name(value: str) -> str:
        clean = "".join(
            character for character in str(value or "").strip() if character.isalnum() or character in "_."
        )[:12]
        if clean and "." not in clean:
            clean = f"{clean[:8]}.PRG"
        return clean

    names = [application_name(title) or "FORGE.PRG"]
    for row in applications or []:
        name = application_name(row.get("name"))
        if name and name.upper() not in {existing.upper() for existing in names}:
            names.append(name)
    if len(names) > 7:
        raise RomWorkbenchError("A cartridge scaffold holds at most seven application headers.")
    data = bytearray(make_cartridge_rom(size, names[0], erase_byte))
    if len(names) > 1:
        from atarinut.tosrom import build_cartridge_rom as engine_build

        data = bytearray(engine_build(size, tuple(names), erase_byte=erase_byte))
    return bytes(data)


#: Retained under its previous name so the un-ported route module still imports.
build_expansion_rom = build_cartridge_rom


#: The identity of the workbench's own ROM file archive, so a reader can tell
#: which release wrote it.
DATA_ARCHIVE_SIGNATURE = b"AFFARCHIVE1"


def build_data_archive(title: str, files: list[tuple[str, bytes]], *,
                       size: int = 128 * 1024, erase_byte: int = 0xFF) -> bytes:
    """Build a documented file archive inside a valid cartridge ROM.

    This is a deterministic storage layout for companion data. TOS will list
    the cartridge's application header but has no idea what the archive means,
    so a program of the developer's own has to read it.
    """
    data = bytearray(build_cartridge_rom(title, [], size, erase_byte))
    directory = bytearray(DATA_ARCHIVE_SIGNATURE)
    payload = bytearray()
    for name, content in files:
        encoded = str(name).encode("latin-1", "replace")[:31]
        # Every field is big-endian, because the 68000 that reads it is.
        directory.extend(
            bytes((len(encoded),)) + encoded
            + len(payload).to_bytes(4, "big") + len(content).to_bytes(4, "big")
        )
        payload.extend(content)
    directory.append(0)
    start = 0x400
    if start + len(directory) + len(payload) > size:
        raise RomWorkbenchError("Those files do not fit in the selected ROM size.")
    data[start:start + len(directory)] = directory
    data[start + len(directory):start + len(directory) + len(payload)] = payload
    return bytes(data)


def board_chip_sets(size: int) -> list[dict]:
    """Describe the chip sets a real board takes for a ROM of this size."""
    return [
        {
            "chips": chips,
            "chipSize": chip_size,
            "lanes": lanes,
            "label": label,
        }
        for chips, chip_size, lanes, label in BOARD_CHIP_SETS.get(int(size), ())
    ]


def hardware_export(data: bytes, *, device_size: int, erase_byte: int = 0xFF,
                    mirror: bool = False, lanes: int = 1, byte_swap: bool = False,
                    word_swap: bool = False,
                    address_swaps: list[tuple[int, int]] | None = None,
                    chip_count: int | None = None) -> dict:
    """Prepare programmer files for a ROM.

    ``lanes`` splits the image into byte-interleaved even and odd halves, as
    a 16-bit board with byte-wide chips needs. ``chip_count`` then divides
    each lane into consecutive chips, so a 192 KiB ST ROM becomes six 32 KiB
    chips (three even/odd pairs), a 256 KiB STE ROM two 128 KiB chips, and a
    512 KiB TT ROM two 256 KiB or four 128 KiB chips.
    """
    if device_size < max(1, len(data)) or device_size > 64 * 1024 * 1024:
        raise RomWorkbenchError("Choose a device size at least as large as the ROM, up to 64 MiB.")
    power_of_two = not device_size & (device_size - 1)
    if address_swaps and not power_of_two:
        raise RomWorkbenchError("Address-line swaps need a power-of-two device size.")
    if lanes not in {1, 2, 4} or device_size % lanes:
        raise RomWorkbenchError("Choose one, two or four equal byte lanes.")
    chips = int(chip_count or lanes)
    if chips < lanes or chips % lanes or device_size % chips:
        raise RomWorkbenchError("The chip count must be a multiple of the lane count that divides the device size.")
    if mirror and data:
        repeats = (device_size + len(data) - 1) // len(data)
        prepared = (data * repeats)[:device_size]
    else:
        prepared = data.ljust(device_size, bytes((erase_byte & 0xFF,)))
    if byte_swap:
        swapped = bytearray(prepared)
        for offset in range(0, len(swapped) - 1, 2):
            swapped[offset], swapped[offset + 1] = swapped[offset + 1], swapped[offset]
        prepared = bytes(swapped)
    if word_swap:
        swapped = bytearray(prepared)
        for offset in range(0, len(swapped) - 3, 4):
            swapped[offset:offset + 4] = swapped[offset + 2:offset + 4] + swapped[offset:offset + 2]
        prepared = bytes(swapped)
    swaps = []
    maximum_bit = device_size.bit_length() - 1
    for left, right in address_swaps or []:
        left, right = int(left), int(right)
        if left == right or min(left, right) < 0 or max(left, right) >= maximum_bit:
            raise RomWorkbenchError("Address-line swaps must name two different address bits used by the device.")
        swaps.append((left, right))
    if swaps:
        rewired = bytearray(len(prepared))
        for source, value in enumerate(prepared):
            target = source
            for left, right in swaps:
                left_value, right_value = (target >> left) & 1, (target >> right) & 1
                if left_value != right_value:
                    target ^= (1 << left) | (1 << right)
            rewired[target] = value
        prepared = bytes(rewired)
    parts = split_into_chips(prepared, lanes, chips // lanes)
    return {"deviceSize": device_size, "lanes": lanes, "chipCount": chips,
            "chipSize": device_size // chips, "eraseByte": erase_byte & 0xFF,
            "mirrored": mirror, "byteSwapped": byte_swap, "wordSwapped": word_swap,
            "addressSwaps": [list(pair) for pair in swaps], "sha256": sha256_bytes(prepared),
            "components": [content for _name, content in parts],
            "componentNames": [name for name, _content in parts]}


def hardware_export_zip(result: dict, stem: str = "rom") -> bytes:
    output = io.BytesIO()
    names = result.get("componentNames") or []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, content in enumerate(result["components"]):
            if len(result["components"]) == 1:
                name = f"{stem}.rom"
            elif index < len(names) and names[index]:
                name = f"{stem}-{names[index]}.rom"
            else:
                name = f"{stem}-lane-{index + 1}.rom"
            archive.writestr(name, content)
        report = {key: value for key, value in result.items() if key != "components"}
        archive.writestr("PROGRAMMING.md", "# ROM programming export\n\n```json\n" + json.dumps(report, indent=2) + "\n```\n")
    return output.getvalue()
