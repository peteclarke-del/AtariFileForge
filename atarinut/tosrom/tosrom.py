"""Atari TOS ROM identity and structure decoding.

A TOS ROM starts with a fixed operating-system header. The first word is a
``BRA.S`` to the reset code, and the longword at ``$04`` is the reset vector,
so the two agree on where the code begins and that agreement is what proves an
image is a TOS ROM rather than a file that happens to start with ``$60``. The
rest of the header gives the OS version word, the address the ROM is mapped at,
the build date twice (once as BCD, once as a GEMDOS date word), the country and
video-standard word, and pointers into RAM that later versions added.

Beyond the header, TOS records no table of its components. The BIOS, XBIOS,
GEMDOS, VDI, AES and desktop are linked into one image and nothing in the ROM
marks where one ends and the next begins. What *is* provable are entry points:
the reset code, the ``TRAP`` handlers the ROM installs with explicit
``MOVE.L #handler,vector`` instructions, the BIOS and XBIOS dispatch tables
those handlers reach, the VDI entry the ``TRAP #2`` stub calls, the AES
initialisation routine named by the GEM memory usage parameter block, and the
system fonts, which carry self-describing headers. This module reports those
and refuses to invent boundaries between them.

EmuTOS uses the same header, marks itself with ``ETOS`` in the reserved
longword at ``$2C``, and carries its own version string, which is reported in
place of the compatibility version word it fills the header with.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from datetime import date

from ..errors import DataError

#: The name Atari File Forge uses when it asks for the TOS ROM filesystem.
TOSROM = "tosrom"

SIZE_128K = 128 * 1024
SIZE_192K = 192 * 1024
SIZE_256K = 256 * 1024
SIZE_512K = 512 * 1024
SIZE_1M = 1024 * 1024

#: The image sizes a TOS ROM comes in.
TOS_SIZES = (SIZE_192K, SIZE_256K, SIZE_512K, SIZE_1M)

#: Where each ROM size is mapped in the 68000 address space.
ROM_BASES = {
    SIZE_192K: 0xFC0000,
    SIZE_256K: 0xE00000,
    SIZE_512K: 0xE00000,
    SIZE_1M: 0xE00000,
    SIZE_128K: 0xFA0000,
}

#: A cartridge is mapped at ``$FA0000`` and announces itself with this longword.
CARTRIDGE_BASE = 0xFA0000
CARTRIDGE_MAGIC = 0xABCDEF42
CARTRIDGE_SIZE = SIZE_128K

#: EmuTOS writes this into the reserved header longword at ``$2C``.
EMUTOS_MAGIC = b"ETOS"

#: The GEM memory usage parameter block begins with this longword.
MUPB_MAGIC = 0x87654321

#: The header is 32 bytes on TOS 1.00 and 48 bytes from TOS 1.02 onwards.
HEADER_SHORT = 0x20
HEADER_LONG = 0x30

#: OS version words and the release each one names.
TOS_RELEASES = {
    0x0100: "TOS 1.00",
    0x0102: "TOS 1.02",
    0x0104: "TOS 1.04",
    0x0106: "TOS 1.06",
    0x0162: "TOS 1.62",
    0x0205: "TOS 2.05",
    0x0206: "TOS 2.06",
    0x0306: "TOS 3.06",
    0x0400: "TOS 4.00",
    0x0402: "TOS 4.02",
    0x0404: "TOS 4.04",
    0x0492: "TOS 4.92",
}

#: The machine each release shipped in.
TOS_MACHINES = {
    0x0100: "ST",
    0x0102: "ST and Mega ST",
    0x0104: "ST and Mega ST",
    0x0106: "STE",
    0x0162: "STE",
    0x0205: "Mega STE",
    0x0206: "ST, STE and Mega STE",
    0x0306: "TT",
    0x0400: "Falcon",
    0x0402: "Falcon",
    0x0404: "Falcon",
    0x0492: "Falcon",
}

#: The country code in bits 1 to 7 of the configuration word.
COUNTRIES = {
    0: "USA", 1: "Germany", 2: "France", 3: "United Kingdom", 4: "Spain",
    5: "Italy", 6: "Sweden", 7: "Switzerland (French)", 8: "Switzerland (German)",
    9: "Turkey", 10: "Finland", 11: "Norway", 12: "Denmark", 13: "Saudi Arabia",
    14: "Netherlands", 15: "Czech Republic", 16: "Hungary", 17: "Poland",
    18: "Lithuania", 19: "Russia", 20: "Estonia", 21: "Belarus", 22: "Ukraine",
    23: "Slovakia", 24: "Latvia", 25: "Israel", 26: "South Africa", 27: "Portugal",
    28: "Belgium", 29: "Japan", 30: "China", 31: "Korea", 32: "Vietnam",
    33: "India", 34: "Iran", 35: "Mongolia", 36: "Nepal", 37: "Laos",
    38: "Cambodia", 39: "Indonesia", 40: "Bangladesh", 127: "multi-language",
}

#: Short codes for the same countries, matching the names TOS images are
#: conventionally filed under.
COUNTRY_CODES = {
    0: "us", 1: "de", 2: "fr", 3: "uk", 4: "es", 5: "it", 6: "se", 7: "sf",
    8: "sg", 9: "tr", 10: "fi", 11: "no", 12: "dk", 13: "sa", 14: "nl", 15: "cz",
    16: "hu", 17: "pl", 18: "lt", 19: "ru", 20: "ee", 21: "by", 22: "ua", 23: "sk",
    24: "lv", 25: "il", 26: "za", 27: "pt", 28: "be", 29: "jp", 30: "cn", 31: "kr",
    32: "vn", 33: "in", 34: "ir", 35: "mn", 36: "np", 37: "la", 38: "kh", 39: "id",
    40: "bd", 127: "ml",
}

#: The exception vectors a TOS ROM installs its entry points into.
VECTOR_NAMES = {
    0x28: "Line-A",
    0x84: "GEMDOS",
    0x88: "AES/VDI",
    0xB4: "BIOS",
    0xB8: "XBIOS",
}
VECTOR_TRAPS = {0x84: "TRAP #1", 0x88: "TRAP #2", 0xB4: "TRAP #13", 0xB8: "TRAP #14"}

#: A system font header is 88 bytes; the name field holds 32.
FONT_HEADER_SIZE = 88
FONT_NAME_SIZE = 32


def _bcd(value: int, digits: int) -> int | None:
    """Decode ``digits`` BCD digits, or ``None`` when a nibble is not decimal."""
    result = 0
    for position in range(digits):
        nibble = (value >> (4 * (digits - 1 - position))) & 0xF
        if nibble > 9:
            return None
        result = result * 10 + nibble
    return result


def decode_bcd_date(value: int) -> date | None:
    """Decode the ``MMDDYYYY`` BCD date at header offset ``$18``."""
    month = _bcd((value >> 24) & 0xFF, 2)
    day = _bcd((value >> 16) & 0xFF, 2)
    year = _bcd(value & 0xFFFF, 4)
    if month is None or day is None or year is None:
        return None
    try:
        return date(year, month, day)
    except ValueError:
        return None


def decode_dos_date(value: int) -> date | None:
    """Decode a GEMDOS date word: seven bits of year from 1980, month, day."""
    try:
        return date(1980 + (value >> 9), (value >> 5) & 0xF, value & 0x1F)
    except ValueError:
        return None


def encode_dos_date(when: date) -> int:
    return ((when.year - 1980) << 9) | (when.month << 5) | when.day


@dataclass(frozen=True)
class TOSHeader:
    """The operating-system header at the start of a TOS ROM."""

    bra_word: int
    version_word: int
    reset_vector: int
    os_base: int
    os_end: int
    reserved: int
    gem_mupb: int
    date_bcd: int
    configuration: int
    dos_date: int
    memory_pool: int
    kbshift: int
    run: int
    magic: int

    @property
    def extended(self) -> bool:
        """True when the pointers TOS 1.02 added are present."""
        return self.version_word >= 0x0102

    @property
    def length(self) -> int:
        return HEADER_LONG if self.extended else HEADER_SHORT

    @property
    def reset_offset(self) -> int:
        return self.reset_vector - self.os_base

    @property
    def version(self) -> str:
        return f"{self.version_word >> 8}.{self.version_word & 0xFF:02X}"

    @property
    def release(self) -> str:
        return TOS_RELEASES.get(self.version_word, f"TOS {self.version}")

    @property
    def machine(self) -> str:
        return TOS_MACHINES.get(self.version_word, "unknown machine")

    @property
    def date(self) -> date | None:
        return decode_bcd_date(self.date_bcd)

    @property
    def date_from_dos_word(self) -> date | None:
        return decode_dos_date(self.dos_date) if self.extended else None

    @property
    def country_code(self) -> int:
        return (self.configuration >> 1) & 0x7F

    @property
    def country(self) -> str:
        return COUNTRIES.get(self.country_code, f"country {self.country_code}")

    @property
    def country_short(self) -> str:
        return COUNTRY_CODES.get(self.country_code, str(self.country_code))

    @property
    def pal(self) -> bool:
        return bool(self.configuration & 1)

    @property
    def video_standard(self) -> str:
        return "PAL" if self.pal else "NTSC"

    @property
    def emutos_magic(self) -> bool:
        return self.magic == int.from_bytes(EMUTOS_MAGIC, "big")


@dataclass(frozen=True)
class EntryPoint:
    """One proven entry point or table inside the ROM."""

    name: str
    offset: int
    address: int
    evidence: str
    length: int | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "offset": self.offset,
            "address": self.address,
            "length": self.length,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class SystemFont:
    """A VDI font whose header, offset table and glyph data are all in the ROM."""

    name: str
    font_id: int
    point_size: int
    first_ade: int
    last_ade: int
    cell_width: int
    cell_height: int
    header_offset: int
    offset_table: tuple[int, int]
    glyph_data: tuple[int, int]
    horizontal_offsets: tuple[int, int] | None = None

    @property
    def ranges(self) -> list[tuple[int, int]]:
        found = [
            (self.header_offset, self.header_offset + FONT_HEADER_SIZE),
            self.offset_table,
            self.glyph_data,
        ]
        if self.horizontal_offsets:
            found.append(self.horizontal_offsets)
        return found

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "id": self.font_id,
            "pointSize": self.point_size,
            "firstCharacter": self.first_ade,
            "lastCharacter": self.last_ade,
            "cellWidth": self.cell_width,
            "cellHeight": self.cell_height,
            "header": self.header_offset,
            "offsetTable": list(self.offset_table),
            "glyphData": list(self.glyph_data),
        }


@dataclass(frozen=True)
class Segment:
    """A named byte range of the ROM presented as a volume entry."""

    name: str
    start: int
    end: int
    evidence: str
    proven: bool = True
    data: bytes = field(repr=False, default=b"")

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)

    @property
    def blocks(self) -> int:
        return max(1, -(-self.length // 512))

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "offset": self.start,
            "length": self.length,
            "evidence": self.evidence,
            "proven": self.proven,
        }


@dataclass(frozen=True)
class CartridgeApplication:
    """One entry of the application header chain in a cartridge ROM."""

    offset: int
    next: int
    init: int
    init_flags: int
    run: int
    time: int
    date: int
    size: int
    name: str

    def to_dict(self) -> dict:
        return {
            "offset": self.offset,
            "next": self.next,
            "init": self.init,
            "initFlags": self.init_flags,
            "run": self.run,
            "time": self.time,
            "date": self.date,
            "size": self.size,
            "name": self.name,
        }


def is_tos_rom(data: bytes) -> bool:
    """True when the image begins with a coherent TOS operating-system header."""
    return parse_tos_header(data) is not None


def is_cartridge_rom(data: bytes) -> bool:
    return len(data) >= 8 and struct.unpack_from(">I", data, 0)[0] == CARTRIDGE_MAGIC


def parse_tos_header(data: bytes) -> TOSHeader | None:
    """Decode the header when its ``BRA.S`` and reset vector agree.

    The check is deliberately structural: the branch word must be a short
    branch, the OS base must be one of the two addresses TOS ROMs are mapped
    at, and the reset vector must name the byte the branch lands on. A file
    that meets all three is a TOS ROM or something built to look exactly like
    one; anything else returns ``None``.
    """
    if len(data) < HEADER_LONG:
        return None
    (bra_word, version_word, reset_vector, os_base, os_end, reserved, gem_mupb,
     date_bcd, configuration, dos_date, memory_pool, kbshift, run, magic) = struct.unpack_from(
        ">HHIIIIIIHHIIII", data, 0
    )
    if bra_word >> 8 != 0x60:
        return None
    displacement = bra_word & 0xFF
    if displacement == 0 or displacement >= 0x80:
        return None
    if os_base not in {0xE00000, 0xFC0000}:
        return None
    if reset_vector != os_base + 2 + displacement:
        return None
    if version_word >> 8 not in range(1, 10):
        return None
    return TOSHeader(
        bra_word, version_word, reset_vector, os_base, os_end, reserved, gem_mupb,
        date_bcd, configuration, dos_date, memory_pool, kbshift, run, magic,
    )


_EMUTOS_VERSION = re.compile(rb"\x00(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?(?:-[A-Za-z0-9]{1,12})?)\x00")


def _emutos_version(data: bytes) -> str:
    """Return the version string an EmuTOS build carries, or ``""``.

    EmuTOS keeps its version as a plain NUL-terminated string that it prints
    on the boot screen. The resource file also holds a ``0.0.0`` placeholder
    that the about dialog overwrites at run time, so that one is skipped.
    """
    for match in _EMUTOS_VERSION.finditer(data):
        text = match.group(1).decode("ascii")
        if text != "0.0.0":
            return text
    return ""


class TOSRom:
    """A decoded TOS or EmuTOS ROM."""

    def __init__(self, data: bytes):
        self.data = bytes(data)
        header = parse_tos_header(self.data)
        if header is None:
            raise DataError(
                "The image does not begin with a TOS operating-system header "
                "(a BRA.S to the reset code whose target the reset vector confirms)."
            )
        self.header = header
        self.base = header.os_base
        if not 0 < header.reset_offset < len(self.data):
            raise DataError("The TOS reset vector points outside the image.")
        self.emutos = header.emutos_magic or b"EmuTOS" in self.data[:65536]
        self.emutos_version = _emutos_version(self.data) if self.emutos else ""
        self.entry_points = self._scan_entry_points()
        self.fonts = self._scan_fonts()
        self.segments = self._build_segments()

    # ---- identity -----------------------------------------------------
    @property
    def version(self) -> str:
        if self.emutos:
            return self.emutos_version or self.header.version
        return self.header.version

    @property
    def release(self) -> str:
        if self.emutos:
            return f"EmuTOS {self.emutos_version}".strip()
        return self.header.release

    @property
    def title(self) -> str:
        return f"{self.release} {self.header.country_short.upper()}"

    @property
    def header_title(self) -> str:
        return self.release

    @property
    def copyright(self) -> str:
        """The description the workbench shows beside the title."""
        parts = [self.header.country, self.header.video_standard, self.header.machine]
        when = self.header.date
        if when is not None:
            parts.append(when.isoformat())
        if self.emutos:
            parts.append(f"compatibility version {self.header.version}")
        return ", ".join(parts)

    @property
    def rom_type(self) -> str:
        label = "EmuTOS" if self.emutos else "TOS"
        return f"{len(self.data) // 1024} KiB {label} ROM"

    @property
    def country(self) -> str:
        return self.header.country

    @property
    def country_code(self) -> int:
        return self.header.country_code

    @property
    def pal(self) -> bool:
        return self.header.pal

    @property
    def date(self) -> date | None:
        return self.header.date

    @property
    def size_valid(self) -> bool:
        return len(self.data) in TOS_SIZES

    @property
    def base_valid(self) -> bool:
        """True when the header's OS base is the address a ROM of this size sits at."""
        expected = ROM_BASES.get(len(self.data))
        return expected is None or expected == self.base

    @property
    def dates_agree(self) -> bool:
        if not self.header.extended:
            return True
        return self.header.date == self.header.date_from_dos_word

    @property
    def is_complete(self) -> bool:
        return self.size_valid and self.base_valid

    @property
    def data_offset(self) -> int:
        return self.header.reset_offset

    @property
    def data_files(self) -> list[Segment]:
        return self.segments

    # ---- entry points -------------------------------------------------
    def _in_rom(self, address: int) -> bool:
        return self.base <= address < self.base + len(self.data)

    def _scan_entry_points(self) -> list[EntryPoint]:
        data = self.data
        found: list[EntryPoint] = [
            EntryPoint(
                "Reset code",
                self.header.reset_offset,
                self.header.reset_vector,
                "header reset vector and BRA.S",
            )
        ]
        installed: dict[int, tuple[int, int]] = {}
        limit = len(data) - 10
        for offset in range(0, limit, 2):
            opcode = data[offset] << 8 | data[offset + 1]
            if opcode == 0x21FC:
                (target, vector) = struct.unpack_from(">IH", data, offset + 2)
            elif opcode == 0x23FC:
                (target, vector) = struct.unpack_from(">II", data, offset + 2)
            else:
                continue
            if vector in VECTOR_NAMES and vector not in installed and self._in_rom(target):
                installed[vector] = (target, offset)
        for vector, (target, at) in sorted(installed.items()):
            name = VECTOR_NAMES[vector]
            trap = VECTOR_TRAPS.get(vector)
            label = f"{name} {trap} handler" if trap else f"{name} vector"
            found.append(
                EntryPoint(
                    label,
                    target - self.base,
                    target,
                    f"MOVE.L #handler,${vector:02X} at offset ${at:X}",
                )
            )
            if vector in (0xB4, 0xB8):
                found.extend(self._dispatch_table(name, target - self.base))
            if vector == 0x88:
                vdi = self._vdi_entry(target - self.base)
                if vdi is not None:
                    found.append(vdi)
        mupb = self._mupb()
        if mupb is not None:
            found.extend(mupb)
        found.sort(key=lambda point: point.offset)
        return found

    def _dispatch_table(self, name: str, stub: int) -> list[EntryPoint]:
        """Follow a BIOS or XBIOS stub to the function table it dispatches through.

        TOS stubs begin ``LEA table(PC),A0``. EmuTOS stubs begin
        ``MOVE.W count,D1`` then ``LEA table,A0``, which also gives the number
        of functions the table holds.
        """
        data = self.data
        if stub + 12 > len(data):
            return []
        opcode = struct.unpack_from(">H", data, stub)[0]
        if opcode == 0x41FA:
            (displacement,) = struct.unpack_from(">h", data, stub + 2)
            table = stub + 2 + displacement
            if 0 <= table < len(data):
                return [
                    EntryPoint(
                        f"{name} dispatch table",
                        table,
                        self.base + table,
                        f"LEA table(PC),A0 in the {name} handler",
                    )
                ]
            return []
        if opcode == 0x3239 and struct.unpack_from(">H", data, stub + 6)[0] == 0x41F9:
            (count_address,) = struct.unpack_from(">I", data, stub + 2)
            (table_address,) = struct.unpack_from(">I", data, stub + 8)
            if self._in_rom(count_address) and self._in_rom(table_address):
                count = struct.unpack_from(">H", data, count_address - self.base)[0]
                table = table_address - self.base
                if table + count * 4 <= len(data):
                    return [
                        EntryPoint(
                            f"{name} dispatch table",
                            table,
                            table_address,
                            f"MOVE.W count,D1 / LEA table,A0 in the {name} handler ({count} functions)",
                            count * 4,
                        )
                    ]
        return []

    def _vdi_entry(self, stub: int) -> EntryPoint | None:
        """Find the VDI entry the TRAP #2 stub calls for function $73."""
        window = self.data[stub : stub + 48]
        for pattern in (b"\xb0\x7c\x00\x73", b"\x0c\x40\x00\x73"):
            position = window.find(pattern)
            if position < 0:
                continue
            at = stub + position + 4
            if at + 2 > len(self.data) or self.data[at] != 0x66:
                continue
            call = at + 2
            if call + 6 > len(self.data):
                continue
            (opcode,) = struct.unpack_from(">H", self.data, call)
            if opcode == 0x4EB9:
                target = struct.unpack_from(">I", self.data, call + 2)[0]
            elif opcode == 0x4EBA:
                target = self.base + call + 2 + struct.unpack_from(">h", self.data, call + 2)[0]
            else:
                continue
            if self._in_rom(target):
                return EntryPoint(
                    "VDI entry",
                    target - self.base,
                    target,
                    "CMP.W #$73,D0 / BNE / JSR in the TRAP #2 handler",
                )
        return None

    def _mupb(self) -> list[EntryPoint]:
        """Decode the GEM memory usage parameter block the header points at."""
        address = self.header.gem_mupb
        if not self._in_rom(address):
            return []
        offset = address - self.base
        if offset + 12 > len(self.data):
            return []
        (magic, _end, init) = struct.unpack_from(">III", self.data, offset)
        if magic != MUPB_MAGIC:
            return []
        found = [
            EntryPoint(
                "GEM memory usage parameter block",
                offset,
                address,
                "header pointer at $14 and magic $87654321",
                12,
            )
        ]
        if self._in_rom(init):
            found.append(
                EntryPoint(
                    "AES initialisation",
                    init - self.base,
                    init,
                    "gm_init in the GEM memory usage parameter block",
                )
            )
        return found

    # ---- fonts --------------------------------------------------------
    _FONT_NAME = re.compile(rb"\d{1,2}[xX]\d{1,2} system font")

    def _scan_fonts(self) -> list[SystemFont]:
        data = self.data
        size = len(data)
        found: list[SystemFont] = []
        for match in self._FONT_NAME.finditer(data):
            header = match.start() - 4
            if header < 0 or header + FONT_HEADER_SIZE > size:
                continue
            (font_id, point_size) = struct.unpack_from(">HH", data, header)
            name_field = data[header + 4 : header + 4 + FONT_NAME_SIZE]
            name = name_field.split(b"\0")[0]
            # A real header NUL-terminates the name; the same words padded
            # with spaces inside a message are not a font.
            if b"\0" not in name_field or not name.endswith(b"system font"):
                continue
            (first_ade, last_ade) = struct.unpack_from(">HH", data, header + 36)
            (cell_width,) = struct.unpack_from(">H", data, header + 52)
            (flags,) = struct.unpack_from(">H", data, header + 66)
            (horizontal, offsets, glyphs) = struct.unpack_from(">III", data, header + 68)
            (form_width, form_height) = struct.unpack_from(">HH", data, header + 80)
            if not (0 < point_size < 256 and first_ade <= last_ade <= 255):
                continue
            if not (1 <= form_height <= 64 and form_width):
                continue
            if not (self._in_rom(offsets) and self._in_rom(glyphs)):
                continue
            table_length = (last_ade - first_ade + 2) * 2
            glyph_length = form_width * form_height
            offset_table = (offsets - self.base, offsets - self.base + table_length)
            glyph_data = (glyphs - self.base, glyphs - self.base + glyph_length)
            if offset_table[1] > size or glyph_data[1] > size:
                continue
            horizontal_offsets = None
            if flags & 0x2 and self._in_rom(horizontal):
                horizontal_offsets = (horizontal - self.base, horizontal - self.base + table_length)
            found.append(
                SystemFont(
                    name.decode("latin-1"),
                    font_id,
                    point_size,
                    first_ade,
                    last_ade,
                    cell_width,
                    form_height,
                    header,
                    offset_table,
                    glyph_data,
                    horizontal_offsets,
                )
            )
        found.sort(key=lambda font: font.header_offset)
        return found

    # ---- segments -----------------------------------------------------
    def _build_segments(self) -> list[Segment]:
        """Name the byte ranges the ROM proves, and one ``OS`` range for the rest.

        ``HEADER`` ends where the reset vector says the code begins. ``DATA``
        is the block of system fonts, whose headers give every table and glyph
        range exactly; it is reported only when those ranges account for the
        block, so a gap holding unrelated code is not passed off as font
        data. Everything from the reset code to the end of the image is
        ``OS``: TOS records no boundary between its BIOS, XBIOS, GEMDOS, VDI,
        AES and desktop, so none is claimed. ``DATA`` lies inside ``OS``.
        """
        reset = self.header.reset_offset
        segments = [
            Segment("HEADER", 0, reset, "operating-system header up to the reset code"),
            Segment(
                "OS",
                reset,
                len(self.data),
                "reset code to end of image; component boundaries are not recorded",
                proven=False,
            ),
        ]
        for index, (start, end, count) in enumerate(self._font_blocks()):
            name = "DATA" if index == 0 else f"DATA{index + 1}"
            segments.append(
                Segment(name, start, end, f"{count} system font(s) with self-describing headers")
            )
        return segments

    def _font_blocks(self) -> list[tuple[int, int, int]]:
        """Group the font structures into blocks whose bytes they account for.

        A block is a run of font headers, offset tables and glyph data with
        no gap wider than a kilobyte between consecutive parts, and it is
        reported only when those parts cover at least nine tenths of it. A
        ROM that carries two font sets for different character sets, as the
        1 MiB EmuTOS build does, yields two blocks.
        """
        if not self.fonts:
            return []
        ranges = sorted(part for font in self.fonts for part in font.ranges)
        headers = sorted(font.header_offset for font in self.fonts)
        blocks: list[tuple[int, int, int]] = []
        start, end, covered = ranges[0][0], ranges[0][1], ranges[0][1] - ranges[0][0]
        for low, high in ranges[1:]:
            if low > end + 1024:
                blocks.append((start, end, covered))
                start, end, covered = low, high, high - low
                continue
            if high > end:
                covered += high - max(low, end)
                end = high
        blocks.append((start, end, covered))
        found = []
        for start, end, covered in blocks:
            count = sum(1 for header in headers if start <= header < end)
            if count and covered * 10 >= (end - start) * 9:
                found.append((start, end, count))
        return found

    def segment(self, name: str) -> Segment | None:
        target = str(name).casefold()
        for candidate in self.segments:
            if candidate.name.casefold() == target:
                return candidate
        return None

    def read_segment(self, name: str) -> bytes:
        segment = self.segment(name)
        if segment is None:
            raise DataError(f"{name} is not a segment of this ROM.")
        return self.data[segment.start : segment.end]

    def entry_point(self, name: str) -> EntryPoint | None:
        target = str(name).casefold()
        for candidate in self.entry_points:
            if candidate.name.casefold() == target:
                return candidate
        return None

    # ---- text ---------------------------------------------------------
    def strings(self, minimum: int = 4, limit: int = 512) -> list[dict]:
        """Return bounded printable ASCII runs with their ROM addresses."""
        found: list[dict] = []
        start = None
        for offset, value in enumerate(self.data + b"\0"):
            if 32 <= value <= 126:
                if start is None:
                    start = offset
                continue
            if start is not None and offset - start >= minimum:
                found.append({
                    "offset": start,
                    "address": self.base + start,
                    "length": offset - start,
                    "text": self.data[start:offset].decode("latin-1"),
                })
                if len(found) >= limit:
                    break
            start = None
        return found

    # ---- constructors -------------------------------------------------
    @classmethod
    def from_bytes(cls, data: bytes) -> "TOSRom":
        return cls(data)

    def to_dict(self) -> dict:
        header = self.header
        return {
            "release": self.release,
            "version": self.version,
            "versionWord": header.version_word,
            "emutos": self.emutos,
            "size": len(self.data),
            "base": self.base,
            "resetVector": header.reset_vector,
            "osEnd": header.os_end,
            "date": header.date.isoformat() if header.date else None,
            "dosDate": header.date_from_dos_word.isoformat() if header.date_from_dos_word else None,
            "country": header.country,
            "countryCode": header.country_code,
            "countryShort": header.country_short,
            "pal": header.pal,
            "machine": header.machine,
            "sizeValid": self.size_valid,
            "baseValid": self.base_valid,
            "entryPoints": [point.to_dict() for point in self.entry_points],
            "fonts": [font.to_dict() for font in self.fonts],
            "segments": [segment.to_dict() for segment in self.segments],
        }


class CartridgeRom:
    """A decoded 128 KiB cartridge ROM and its application header chain."""

    def __init__(self, data: bytes):
        self.data = bytes(data)
        if not is_cartridge_rom(self.data):
            raise DataError("The image does not begin with the cartridge magic $ABCDEF42.")
        self.base = CARTRIDGE_BASE
        self.applications = self._chain()

    def _chain(self) -> list[CartridgeApplication]:
        found: list[CartridgeApplication] = []
        offset = 4
        seen: set[int] = set()
        while 0 < offset <= len(self.data) - 0x22 and offset not in seen and len(found) < 64:
            seen.add(offset)
            (next_pointer, init, run, time, day, size) = struct.unpack_from(">IIIHHI", self.data, offset)
            name = self.data[offset + 0x14 : offset + 0x22].split(b"\0")[0].decode("latin-1", "replace")
            found.append(
                CartridgeApplication(
                    offset, next_pointer, init & 0xFFFFFF, init >> 24, run, time, day, size, name,
                )
            )
            if not next_pointer:
                break
            offset = next_pointer - self.base
        return found

    @property
    def title(self) -> str:
        return self.applications[0].name if self.applications and self.applications[0].name else "Cartridge"

    def to_dict(self) -> dict:
        return {
            "size": len(self.data),
            "base": self.base,
            "applications": [application.to_dict() for application in self.applications],
        }


def build_cartridge_rom(
    size: int = CARTRIDGE_SIZE,
    names: tuple[str, ...] | list[str] = ("FORGE.PRG",),
    *,
    erase_byte: int = 0xFF,
    when: date | None = None,
) -> bytes:
    """Build an inert but structurally valid cartridge ROM.

    Each name becomes one application header in the chain. Its run routine is
    a single ``RTS`` and it asks for no initialisation, so a cartridge built
    from this can be fitted and listed by the desktop without doing anything.
    """
    if not 1024 <= int(size) <= CARTRIDGE_SIZE:
        raise DataError("A cartridge ROM is from 1 KiB to 128 KiB.")
    stamp = when or date(2026, 1, 1)
    rom = bytearray(bytes((int(erase_byte) & 0xFF,)) * int(size))
    struct.pack_into(">I", rom, 0, CARTRIDGE_MAGIC)
    code_offset = 0x100
    struct.pack_into(">H", rom, code_offset, 0x4E75)
    cleaned = [_cartridge_name(name) for name in names] or ["FORGE.PRG"]
    offset = 4
    for index, name in enumerate(cleaned):
        following = offset + 0x22 if index + 1 < len(cleaned) else 0
        if offset + 0x22 > code_offset:
            raise DataError("Too many application names for the cartridge header area.")
        struct.pack_into(
            ">IIIHHI",
            rom,
            offset,
            CARTRIDGE_BASE + following if following else 0,
            0,
            CARTRIDGE_BASE + code_offset,
            0,
            encode_dos_date(stamp),
            0,
        )
        encoded = name.encode("latin-1")
        rom[offset + 0x14 : offset + 0x22] = encoded.ljust(14, b"\0")
        offset += 0x22
    return bytes(rom)


def _cartridge_name(value: str) -> str:
    stem, _, extension = str(value or "").strip().upper().partition(".")
    stem = "".join(character for character in stem if character.isalnum() or character == "_")[:8]
    extension = "".join(character for character in extension if character.isalnum())[:3]
    stem = stem or "FORGE"
    return f"{stem}.{extension}" if extension else stem


class TOSMount:
    """A TOS ROM presented as a read-only directory of named segments."""

    def __init__(self, reader):
        self.reader = reader
        self.rom = TOSRom(reader.path.read_bytes())
        self.filesystem = TOSROM
        self.read_only = True

    @property
    def title(self) -> str:
        return self.rom.title

    def set_title(self, value: str) -> None:
        raise DataError("A TOS ROM's identity is fixed by its header.")

    def exists(self, path: str | None) -> bool:
        if not path or path in {"", ":", "$", "/"}:
            return True
        return self.rom.segment(str(path).strip("/:$")) is not None

    def stat(self, path: str | None):
        from ..filesystem.gemdos import Stat

        name = str(path or "").strip("/:$")
        if not name:
            return Stat(self.rom.title, "", True, 0, 1, 0, 1)
        segment = self.rom.segment(name)
        if segment is None:
            raise DataError(f"Path not found: {name}")
        return Stat(segment.name, segment.name, False, segment.length, segment.blocks, 0, -3)

    def iter_entries(self, path: str | None = None):
        from ..filesystem.gemdos import Entry

        if path and str(path).strip("/:$"):
            raise DataError("A TOS ROM has one flat segment list.")
        for segment in self.rom.segments:
            yield Entry(
                name=segment.name,
                path=segment.name,
                is_dir=False,
                length=segment.length,
                block=segment.start,
                secondary_type=-3,
            )

    def read_bytes(self, path: str) -> bytes:
        return self.rom.read_segment(str(path).strip("/:$"))

    def atari_meta(self, path: str):
        """Present a segment's provenance through the catalogue interface.

        A ROM segment has no protection bits, but the two things the workbench
        shows in their place fit well: whether the range is proven from the
        ROM's own structures, and the evidence for it as the comment.
        """
        from ..file import Access, AtariMeta

        segment = self.rom.segment(str(path).strip("/:$"))
        if segment is None:
            raise DataError(f"Path not found: {path}")
        protection = int(Access.W | Access.D)
        if segment.proven:
            protection |= int(Access.E)
        return AtariMeta(
            protection=protection,
            comment=segment.evidence,
            datestamp=None,
            filetype=None,
            extra={
                "offset": segment.start,
                "address": self.rom.base + segment.start,
                "proven": segment.proven,
                "version": self.rom.version,
            },
        )

    def datestamp(self, path: str):
        """A ROM carries one build date, on the header, not per segment."""
        return None

    def filetype(self, path: str):
        """A ROM segment has no desktop icon type."""
        return None

    def size_bytes(self) -> int:
        return len(self.rom.data)

    def free_bytes(self) -> int:
        return 0

    def validate(self) -> list[str]:
        rom = self.rom
        problems: list[str] = []
        if not rom.size_valid:
            problems.append(
                f"The ROM is {len(rom.data):,} bytes, which is not a TOS size "
                "(192 KiB, 256 KiB, 512 KiB or 1 MiB)."
            )
        if not rom.base_valid:
            problems.append(
                f"The header maps the OS at ${rom.base:06X}, but a "
                f"{len(rom.data) // 1024} KiB ROM sits at ${ROM_BASES[len(rom.data)]:06X}."
            )
        if not rom.dates_agree:
            problems.append(
                "The GEMDOS date word at $1E does not match the BCD build date at $18."
            )
        if rom.emutos and not rom.emutos_version:
            problems.append("The ROM is marked as EmuTOS but carries no version string.")
        if rom.emutos and not rom.header.emutos_magic:
            problems.append("EmuTOS text is present but the ETOS header magic is not.")
        names = {point.name for point in rom.entry_points}
        missing = [
            label
            for label in ("GEMDOS TRAP #1 handler", "BIOS TRAP #13 handler", "XBIOS TRAP #14 handler")
            if label not in names
        ]
        if missing:
            problems.append(
                "No explicit vector install was found for: " + ", ".join(missing) + ". "
                "The ROM may set those vectors through a table copy instead."
            )
        problems.append(
            "Component boundaries are not recorded in a TOS ROM, so the BIOS, XBIOS, "
            "GEMDOS, VDI, AES and desktop are presented as one OS segment; the proven "
            "entry points are: "
            + "; ".join(f"{point.name} at ${point.address:06X}" for point in rom.entry_points)
            + "."
        )
        return problems

    def close(self) -> None:
        self.reader.close()


__all__ = [
    "CARTRIDGE_BASE",
    "CARTRIDGE_MAGIC",
    "CARTRIDGE_SIZE",
    "COUNTRIES",
    "COUNTRY_CODES",
    "CartridgeApplication",
    "CartridgeRom",
    "EMUTOS_MAGIC",
    "EntryPoint",
    "MUPB_MAGIC",
    "ROM_BASES",
    "Segment",
    "SystemFont",
    "TOSHeader",
    "TOSMount",
    "TOSROM",
    "TOSRom",
    "TOS_MACHINES",
    "TOS_RELEASES",
    "TOS_SIZES",
    "VECTOR_NAMES",
    "build_cartridge_rom",
    "decode_bcd_date",
    "decode_dos_date",
    "encode_dos_date",
    "is_cartridge_rom",
    "is_tos_rom",
    "parse_tos_header",
]
