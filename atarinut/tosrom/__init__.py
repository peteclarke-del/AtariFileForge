"""TOS ROM decoding, presented as a read-only filing system.

A TOS ROM is not a disk, but it has an identity and a handful of provable
parts: the operating-system header, the entry points it installs at reset,
the system fonts, and the code body that holds the BIOS, XBIOS, GEMDOS, VDI,
AES and desktop. Presenting those as a flat volume of named segments lets the
workbench browse, export and compare a ROM with the tools it uses for a floppy.
"""

from .tosrom import (
    CARTRIDGE_BASE,
    CARTRIDGE_MAGIC,
    CARTRIDGE_SIZE,
    COUNTRIES,
    COUNTRY_CODES,
    ROM_BASES,
    TOS_MACHINES,
    TOS_RELEASES,
    TOS_SIZES,
    TOSROM,
    CartridgeApplication,
    CartridgeRom,
    EntryPoint,
    Segment,
    SystemFont,
    TOSHeader,
    TOSMount,
    TOSRom,
    build_cartridge_rom,
    decode_bcd_date,
    decode_dos_date,
    encode_dos_date,
    is_cartridge_rom,
    is_tos_rom,
    parse_tos_header,
)

__all__ = [
    "CARTRIDGE_BASE",
    "CARTRIDGE_MAGIC",
    "CARTRIDGE_SIZE",
    "COUNTRIES",
    "COUNTRY_CODES",
    "ROM_BASES",
    "TOS_MACHINES",
    "TOS_RELEASES",
    "TOS_SIZES",
    "TOSROM",
    "CartridgeApplication",
    "CartridgeRom",
    "EntryPoint",
    "Segment",
    "SystemFont",
    "TOSHeader",
    "TOSMount",
    "TOSRom",
    "build_cartridge_rom",
    "decode_bcd_date",
    "decode_dos_date",
    "encode_dos_date",
    "is_cartridge_rom",
    "is_tos_rom",
    "parse_tos_header",
]
