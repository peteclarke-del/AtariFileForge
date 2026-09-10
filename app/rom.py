"""Inspection and safe editing helpers for Atari TOS ROM images.

A ROM is a byte image, not a filing system, so the workbench presents fixed
size *banks* as its objects and keeps layout choices in session metadata. What
makes a TOS ROM readable rather than opaque is its operating-system header and
the structures that header leads to, and this module decodes them:

* The **header**: a ``BRA.S`` to the reset code whose target the reset vector
  at ``$04`` confirms, then the OS version word, the address the ROM is mapped
  at, the build date as BCD and as a GEMDOS date word, and the country and
  video-standard word.
* The **entry points**: the ``TRAP`` handlers the ROM installs with explicit
  ``MOVE.L #handler,vector`` instructions, the BIOS and XBIOS dispatch tables,
  the VDI entry, and the AES initialisation routine named by the GEM memory
  usage parameter block.
* The **system fonts**, whose self-describing headers give exact byte ranges.

A cartridge ROM is the second shape recognised: ``$ABCDEF42`` followed by a
chain of application headers. A bank with neither is reported as raw data
rather than guessed at.
"""

from __future__ import annotations

import math
import zlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from atarinut.tosrom import (
    CARTRIDGE_BASE,
    CARTRIDGE_MAGIC,
    CARTRIDGE_SIZE,
    TOS_SIZES,
    CartridgeRom,
    TOSRom,
    build_cartridge_rom,
    is_cartridge_rom,
    parse_tos_header,
)
from atarinut.tosrom import ROM_BASES as _ENGINE_BASES

from .checksum import sha256_bytes

#: A TOS ROM is programmed as 64 KiB-wide pieces on every board, so that is the
#: bank a 192 KiB, 256 KiB or 512 KiB image divides into without remainder.
DEFAULT_BANK_SIZE = 64 * 1024
MIN_BANK_SIZE = 256
MAX_ROM_SIZE = 64 * 1024 * 1024

#: A TOS ROM is programmed as one 16-bit device or as byte-wide pairs holding
#: the even and odd bytes.
ROM_LAYOUTS = {"linear", "byte-interleaved-2", "byte-interleaved-4"}
ROM_PLATFORMS = {"tos", "cartridge", "custom"}

#: Where each ROM size appears in the 68000 address space.
ROM_BASES = dict(_ENGINE_BASES)
DEFAULT_ROM_BASE = 0xE00000

#: Cartridge application headers hold an 8.3 name in a 14-byte field at $14.
CARTRIDGE_APPLICATION_SIZE = 0x22
CARTRIDGE_NAME_OFFSET = 0x14
CARTRIDGE_NAME_SIZE = 14


class RomError(ValueError):
    pass


@dataclass(frozen=True)
class RomHeader:
    """The decoded identity of a TOS ROM bank."""

    title: str
    version: str
    release: str
    version_word: int
    base: int
    reset_vector: int
    os_end: int
    date: str
    dos_date: str
    country: str
    country_code: int
    country_short: str
    pal: bool
    machine: str
    emutos: bool
    emutos_version: str
    gem_mupb: int
    memory_pool: int
    kbshift: int
    run: int
    magic: int
    header_length: int
    size: int
    entry_count: int = 0
    font_count: int = 0
    missing_vectors: tuple[str, ...] = ()

    @property
    def roles(self) -> str:
        return "EmuTOS" if self.emutos else "TOS"

    @property
    def processor(self) -> str:
        if self.version_word >= 0x0300:
            return "68030"
        return "68000"

    @property
    def video_standard(self) -> str:
        return "PAL" if self.pal else "NTSC"

    @property
    def size_valid(self) -> bool:
        return self.size in TOS_SIZES

    @property
    def base_valid(self) -> bool:
        expected = ROM_BASES.get(self.size)
        return expected is None or expected == self.base

    @property
    def dates_agree(self) -> bool:
        return not self.dos_date or self.dos_date == self.date

    @property
    def copyright(self) -> str:
        parts = [self.country, self.video_standard, self.machine]
        if self.date:
            parts.append(self.date)
        return ", ".join(parts)

    @property
    def features(self) -> list[str]:
        features = []
        if self.version_word >= 0x0102:
            features.append("GEMDOS pool, kbshift and _run pointers")
        if self.emutos:
            features.append("ETOS header magic")
        return features


@dataclass(frozen=True)
class CartridgeHeader:
    """The decoded application chain of a cartridge ROM."""

    applications: tuple[dict, ...]
    size: int

    @property
    def title(self) -> str:
        for application in self.applications:
            if application["name"]:
                return application["name"]
        return "Cartridge"

    @property
    def base(self) -> int:
        return CARTRIDGE_BASE

    @property
    def size_valid(self) -> bool:
        return 0 < self.size <= CARTRIDGE_SIZE


def rom_base(size: int) -> int:
    """Return the address a ROM of this size is mapped at."""
    return ROM_BASES.get(int(size), DEFAULT_ROM_BASE)


def parse_rom_header(data: bytes) -> RomHeader | None:
    """Return a TOS ROM's identity when its header is sound, else ``None``.

    The whole image is decoded, not only the header, so the entry-point and
    font counts reflect what the ROM proves. Anything that is not a TOS ROM
    returns ``None`` rather than a header built from coincidence.
    """
    if parse_tos_header(data) is None:
        return None
    try:
        rom = TOSRom(data)
    except Exception:
        return None
    header = rom.header
    return RomHeader(
        title=rom.title,
        version=rom.version,
        release=rom.release,
        version_word=header.version_word,
        base=rom.base,
        reset_vector=header.reset_vector,
        os_end=header.os_end,
        date=header.date.isoformat() if header.date else "",
        dos_date=header.date_from_dos_word.isoformat() if header.date_from_dos_word else "",
        country=header.country,
        country_code=header.country_code,
        country_short=header.country_short,
        pal=header.pal,
        machine=header.machine,
        emutos=rom.emutos,
        emutos_version=rom.emutos_version,
        gem_mupb=header.gem_mupb,
        memory_pool=header.memory_pool if header.extended else 0,
        kbshift=header.kbshift if header.extended else 0,
        run=header.run if header.extended else 0,
        magic=header.magic if header.extended else 0,
        header_length=header.length,
        size=len(data),
        entry_count=len(rom.entry_points),
        font_count=len(rom.fonts),
        missing_vectors=tuple(
            label
            for label in ("GEMDOS TRAP #1 handler", "BIOS TRAP #13 handler", "XBIOS TRAP #14 handler")
            if label not in {point.name for point in rom.entry_points}
        ),
    )


def image_context(path: Path) -> RomHeader | None:
    """Decode the whole image's header so its banks can be judged against it.

    A TOS ROM is at most 1 MiB, so that is all that is read; a larger custom
    image cannot be a TOS ROM and returns ``None`` cheaply.
    """
    size = path.stat().st_size
    if size > 1024 * 1024:
        return None
    with path.open("rb") as image:
        return parse_rom_header(image.read(size))


def parse_cartridge_header(data: bytes) -> CartridgeHeader | None:
    """Return the application chain of a cartridge ROM, if the magic is present."""
    if not is_cartridge_rom(data):
        return None
    try:
        cartridge = CartridgeRom(data)
    except Exception:
        return None
    return CartridgeHeader(
        tuple(application.to_dict() for application in cartridge.applications), len(data)
    )


def is_erased(data: bytes, erase_byte: int = 0xFF) -> bool:
    return not data or not data.strip(bytes((erase_byte & 0xFF,)))


def validate_bank_size(value: int) -> int:
    size = int(value)
    if size < MIN_BANK_SIZE or size > MAX_ROM_SIZE or size % 256:
        raise RomError("ROM bank size must be a multiple of 256 bytes between 256 bytes and 64 MiB.")
    return size


def validate_layout(value: str) -> str:
    layout = str(value or "linear")
    if layout not in ROM_LAYOUTS:
        raise RomError("Choose a linear, two-chip or four-chip ROM byte layout.")
    return layout


def validate_platform(value: str) -> str:
    platform = str(value or "tos")
    if platform not in ROM_PLATFORMS:
        raise RomError("Choose a TOS, cartridge or custom ROM target.")
    return platform


def bank_count(size: int, bank_size: int) -> int:
    return (max(0, int(size)) + bank_size - 1) // bank_size


def printable_strings(data: bytes, minimum: int = 4, limit: int = 513, base: int | None = None) -> list[dict]:
    """Return bounded printable ASCII runs as evidence, never as guessed files."""
    origin = DEFAULT_ROM_BASE if base is None else base
    found = []
    start = None
    for offset, value in enumerate(data + b"\0"):
        if 32 <= value <= 126:
            if start is None:
                start = offset
            continue
        if start is not None and offset - start >= minimum:
            text = data[start:offset].decode("latin-1")
            found.append({
                "offset": start,
                "address": origin + start,
                "length": offset - start,
                "text": text[:160] + ("..." if len(text) > 160 else ""),
            })
            if len(found) >= limit:
                break
        start = None
    return found


def byte_diagnostics(data: bytes, erase_byte: int, deep: bool = True) -> dict:
    fingerprints = {
        "sha256": sha256_bytes(data),
        "crc32": f"{zlib.crc32(data) & 0xFFFFFFFF:08X}",
    }
    if not deep:
        return fingerprints
    counts = Counter(data)
    length = len(data)
    entropy = -sum(
        (count / length) * math.log2(count / length)
        for count in counts.values()
    ) if length else 0.0
    erased = erase_byte & 0xFF
    used_start = next((offset for offset, value in enumerate(data) if value != erased), None)
    used_end = next(
        (offset for offset in range(length - 1, -1, -1) if data[offset] != erased),
        None,
    )
    return {
        **fingerprints,
        "entropy": round(entropy, 3),
        "uniqueByteValues": len(counts),
        "zeroBytes": counts.get(0, 0),
        "ffBytes": counts.get(0xFF, 0),
        "printableBytes": sum(counts.get(value, 0) for value in range(32, 127)),
        "erasedBytes": counts.get(erased, 0),
        "usedStart": used_start,
        "usedEnd": used_end,
    }


def entry_point_candidates(data: bytes, limit: int = 64) -> list[dict]:
    """List the entry points and tables a TOS ROM proves, in address order.

    Every row is backed by an instruction or a magic number in the ROM: the
    reset vector, a ``MOVE.L #handler,vector`` install, the ``LEA`` a dispatch
    stub performs, the ``JSR`` the ``TRAP #2`` stub makes for VDI function
    ``$73``, or the ``$87654321`` magic of the GEM memory usage block. None is
    inferred from code shape alone.
    """
    if parse_tos_header(data) is None:
        return []
    try:
        rom = TOSRom(data)
    except Exception:
        return []
    rows = []
    for point in rom.entry_points[:limit]:
        rows.append({
            "offset": point.offset,
            "title": point.name,
            "help": point.evidence,
            "start": point.address,
            "handlerAddress": point.address,
            "length": point.length,
            "confidence": "declared",
        })
    return rows


def system_fonts(data: bytes) -> list[dict]:
    """List the VDI system fonts whose headers, tables and glyphs are in the ROM."""
    if parse_tos_header(data) is None:
        return []
    try:
        rom = TOSRom(data)
    except Exception:
        return []
    return [font.to_dict() for font in rom.fonts]


def entry_point_inventory(data: bytes, entries: list[dict] | None = None) -> list[dict]:
    """Present entry points as the inventory the decoder pane lists.

    The closest thing a TOS ROM has to a command inventory is the set of
    system calls it answers, and those are reached through the handlers and
    dispatch tables listed here.
    """
    inventory: list[dict] = []
    for entry in entries or []:
        inventory.append({
            "name": entry["title"],
            "offset": entry["offset"],
            "address": entry.get("start"),
            "module": entry["title"],
            "confidence": entry.get("confidence", "declared"),
            "helpText": entry.get("help", ""),
            "handlerOffset": entry.get("offset"),
            "handlerAddress": entry.get("handlerAddress"),
            "length": entry.get("length"),
        })
    return sorted(inventory, key=lambda item: (item["offset"], item["name"].casefold()))


def _header_structures(rom: TOSRom) -> list[dict]:
    base = rom.base
    structures = [{
        "kind": "header",
        "name": "Operating-system header: BRA.S, version, reset vector, base, dates, country",
        "offset": 0,
        "address": base,
        "length": rom.header.length,
    }]
    for point in rom.entry_points:
        structures.append({
            "kind": "table" if point.length else "entry",
            "name": point.name,
            "offset": point.offset,
            "address": point.address,
            "length": point.length,
        })
    for font in rom.fonts:
        structures.append({
            "kind": "font",
            "name": f"{font.name} ({font.point_size} point, {font.cell_width}x{font.cell_height})",
            "offset": font.header_offset,
            "address": base + font.header_offset,
            "length": 88,
        })
        structures.append({
            "kind": "font-data",
            "name": f"{font.name} glyph data",
            "offset": font.glyph_data[0],
            "address": base + font.glyph_data[0],
            "length": font.glyph_data[1] - font.glyph_data[0],
        })
    return structures


def _cartridge_structures(cartridge: CartridgeHeader) -> list[dict]:
    structures = [{
        "kind": "header",
        "name": "Cartridge magic $ABCDEF42",
        "offset": 0,
        "address": CARTRIDGE_BASE,
        "length": 4,
    }]
    for application in cartridge.applications:
        structures.append({
            "kind": "module",
            "name": f"Application header {application['name'] or '(unnamed)'}",
            "offset": application["offset"],
            "address": CARTRIDGE_BASE + application["offset"],
            "length": CARTRIDGE_APPLICATION_SIZE,
        })
        for role, target in (("init", application["init"]), ("run", application["run"])):
            if CARTRIDGE_BASE <= target < CARTRIDGE_BASE + CARTRIDGE_SIZE:
                structures.append({
                    "kind": "entry",
                    "name": f"{application['name'] or 'application'} {role} routine",
                    "offset": target - CARTRIDGE_BASE,
                    "address": target,
                    "length": None,
                })
    return structures


def _header_dict(header: RomHeader) -> dict:
    return {
        "title": header.title,
        "version": header.version,
        "release": header.release,
        "versionWord": header.version_word,
        "versionHex": f"{header.version_word:04X}",
        "copyright": header.copyright,
        "roles": header.roles,
        "processor": header.processor,
        "features": header.features,
        "base": header.base,
        "resetVector": header.reset_vector,
        "resetEntry": header.reset_vector,
        "osEnd": header.os_end,
        "date": header.date,
        "dosDate": header.dos_date,
        "datesAgree": header.dates_agree,
        "country": header.country,
        "countryCode": header.country_code,
        "countryShort": header.country_short,
        "videoStandard": header.video_standard,
        "pal": header.pal,
        "machine": header.machine,
        "emutos": header.emutos,
        "emutosVersion": header.emutos_version,
        "gemMupb": header.gem_mupb,
        "memoryPool": header.memory_pool,
        "kbshift": header.kbshift,
        "run": header.run,
        "magic": header.magic,
        "headerLength": header.header_length,
        "sizeValid": header.size_valid,
        "baseValid": header.base_valid,
        "entryCount": header.entry_count,
        "fontCount": header.font_count,
    }


def inspect_bank(
    data: bytes,
    number: int,
    erase_byte: int = 0xFF,
    image_header: RomHeader | None = None,
    include_contents: bool = False,
    include_entry_points: bool = False,
) -> dict:
    """Decode one bank.

    ``image_header`` is the header of the whole image the bank belongs to.
    Size, base and vector findings are judged against that whole image, so a
    64 KiB bank of a 192 KiB ROM is not reported as the wrong size, and a
    continuation bank is labelled as part of the ROM rather than as raw data.
    Without it, the bank is judged as an image in its own right.
    """
    header = parse_rom_header(data)
    cartridge = parse_cartridge_header(data) if header is None else None
    blank = is_erased(data, erase_byte)
    context = image_header if image_header is not None and header is not None else header
    notes: list[str] = []
    if header:
        base = header.base
    elif cartridge:
        base = CARTRIDGE_BASE
    elif image_header:
        base = image_header.base + number * len(data)
    else:
        base = rom_base(len(data))
    if header:
        title = header.title
    elif cartridge:
        title = cartridge.title
    elif blank:
        title = "Empty bank"
    elif image_header:
        title = f"{image_header.title} (continued)"
    else:
        title = f"Bank {number:03d}"
    structures: list[dict] = []
    warnings: list[str] = []
    rom: TOSRom | None = None
    if header:
        rom = TOSRom(data)
        structures = _header_structures(rom)
        if not context.size_valid:
            warnings.append(
                f"The image is {context.size:,} bytes, which is not a TOS size "
                "(192 KiB, 256 KiB, 512 KiB or 1 MiB). It may be a bank of a larger ROM, "
                "truncated, or padded."
            )
        if not context.base_valid:
            warnings.append(
                f"The header maps the OS at ${context.base:06X}, but a {context.size // 1024} KiB "
                f"ROM sits at ${ROM_BASES[context.size]:06X}. Absolute addresses inside it will "
                "not match the board it is fitted to."
            )
        if not context.dates_agree:
            warnings.append(
                "The GEMDOS date word at $1E disagrees with the BCD build date at $18."
            )
        if context.emutos and not context.emutos_version:
            warnings.append("The ROM is marked as EmuTOS but carries no version string.")
        if context.missing_vectors:
            notes.append(
                "No explicit vector install was found for: " + ", ".join(context.missing_vectors) + ". "
                "The ROM may install those vectors through a table copy instead."
            )
    elif cartridge:
        structures = _cartridge_structures(cartridge)
        if not cartridge.size_valid:
            warnings.append(
                f"A cartridge ROM is at most {CARTRIDGE_SIZE // 1024} KiB; this image is {len(data):,} bytes."
            )
        if not cartridge.applications:
            warnings.append("The cartridge header chain is empty.")
    elif not blank:
        structures.append({
            "kind": "payload",
            "name": (
                "Continuation of the operating system (no header in this bank)"
                if image_header
                else "Raw code and data (no TOS or cartridge header recognised)"
            ),
            "offset": 0,
            "address": base,
            "length": len(data),
        })
    strings = printable_strings(data, base=base) if include_contents and not blank else []
    entries = (
        entry_point_candidates(data)
        if include_contents and include_entry_points and header
        else []
    )
    fonts = system_fonts(data) if include_contents and header else []
    diagnostics = byte_diagnostics(data, erase_byte, deep=include_contents)
    programmed_bytes = len(data) - data.count(bytes((erase_byte & 0xFF,)))
    if header:
        filetype = f"{header.release} · {header.country_short.upper()} {header.video_standard}"
    elif cartridge:
        filetype = f"cartridge · {len(cartridge.applications)} application(s)"
    elif blank:
        filetype = "erased"
    elif image_header:
        filetype = f"{image_header.release} · continuation"
    else:
        filetype = "raw data"
    return {
        "slot": number,
        "bank": number,
        "name": title,
        "type": "rom-bank",
        "length": len(data),
        "attr": "EMPTY" if blank else "ROM",
        "empty": blank,
        "fileOffset": number * len(data),
        "programmedBytes": programmed_bytes,
        "programmedPercent": round(programmed_bytes * 100 / len(data), 1) if data else 0,
        "filetype": filetype,
        "header": _header_dict(header) if header else None,
        "cartridge": ({
            "base": CARTRIDGE_BASE,
            "applications": list(cartridge.applications),
            "sizeValid": cartridge.size_valid,
        } if cartridge else None),
        "structures": structures,
        "strings": strings[:512],
        "stringsTruncated": len(strings) > 512,
        "diagnostics": diagnostics,
        "warnings": warnings,
        "notes": notes,
        "modules": entries,
        "fonts": fonts,
        "starCommands": entry_point_inventory(data, entries) if include_contents and not blank else [],
    }


def inspect_image(path: Path, bank_size: int, erase_byte: int = 0xFF) -> list[dict]:
    size = path.stat().st_size
    rows = []
    image_header = image_context(path)
    with path.open("rb") as image:
        for number in range(bank_count(size, bank_size)):
            row = inspect_bank(image.read(bank_size), number, erase_byte, image_header)
            row["fileOffset"] = number * bank_size
            if image_header:
                row["imageHeader"] = _header_dict(image_header)
            rows.append(row)
    matches: dict[str, list[int]] = {}
    for row in rows:
        matches.setdefault(row["diagnostics"]["sha256"], []).append(row["bank"])
    for row in rows:
        row["matchingBanks"] = [
            bank for bank in matches[row["diagnostics"]["sha256"]]
            if bank != row["bank"]
        ]
    return rows


def read_bank(path: Path, number: int, bank_size: int) -> bytes:
    count = bank_count(path.stat().st_size, bank_size)
    if number < 0 or number >= count:
        raise RomError(f"ROM bank {number} does not exist.")
    with path.open("rb") as image:
        image.seek(number * bank_size)
        return image.read(bank_size)


def bank_number(path: str) -> int:
    value = str(path or "").strip().lower()
    for prefix in ("$.", ":", "/"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    if value.startswith("bank:"):
        value = value[5:]
    elif value.startswith("bank-"):
        value = value[5:]
    try:
        number = int(value, 10)
    except ValueError as exc:
        raise RomError("Choose a ROM bank.") from exc
    if number < 0:
        raise RomError("Choose a ROM bank.")
    return number


def make_cartridge_rom(size: int, title: str, erase_byte: int = 0xFF) -> bytes:
    """Build an empty but structurally valid cartridge ROM.

    The result is what a cartridge looks like before its program is linked in:
    the ``$ABCDEF42`` magic, one application header named after ``title``, and
    a run routine that is a single ``RTS``. That is a real, safe "nothing to
    do" answer rather than an address that would crash the machine if the
    cartridge were fitted before it was finished.
    """
    size = validate_bank_size(size)
    if size < 1024:
        raise RomError("A ROM template needs at least 1 KiB.")
    if size > CARTRIDGE_SIZE:
        raise RomError(f"A cartridge ROM is at most {CARTRIDGE_SIZE // 1024} KiB.")
    clean_title = "".join(
        character for character in str(title or "forge") if character.isalnum() or character in "_."
    )[:12] or "forge"
    if "." not in clean_title:
        clean_title = f"{clean_title[:8]}.PRG"
    return build_cartridge_rom(size, (clean_title,), erase_byte=erase_byte)


def rename_cartridge(data: bytes, title: str) -> bytes:
    """Rewrite the first application name of a cartridge ROM in place.

    The name field is fixed at 14 bytes, so nothing else in the ROM moves. A
    name that does not fit the 8.3 form is refused rather than shortened.
    """
    cartridge = parse_cartridge_header(data)
    if cartridge is None or not cartridge.applications:
        raise RomError("That bank has no cartridge application header to rename.")
    text = str(title or "").strip().upper()
    stem, _, extension = text.partition(".")
    if not stem or len(stem) > 8 or len(extension) > 3:
        raise RomError("A cartridge application name is up to 8 characters plus a 3-character extension.")
    if not all(character.isalnum() or character == "_" for character in stem + extension):
        raise RomError("Cartridge application names use letters, digits and underscores only.")
    name = f"{stem}.{extension}" if extension else stem
    offset = cartridge.applications[0]["offset"] + CARTRIDGE_NAME_OFFSET
    updated = bytearray(data)
    updated[offset : offset + CARTRIDGE_NAME_SIZE] = name.encode("ascii").ljust(CARTRIDGE_NAME_SIZE, b"\0")
    return bytes(updated)


#: Retained until the application layer is ported; ``make_cartridge_rom`` is
#: the name to call.
make_expansion_rom = make_cartridge_rom


__all__ = [
    "CARTRIDGE_BASE",
    "CARTRIDGE_MAGIC",
    "CARTRIDGE_SIZE",
    "DEFAULT_BANK_SIZE",
    "DEFAULT_ROM_BASE",
    "MAX_ROM_SIZE",
    "MIN_BANK_SIZE",
    "ROM_BASES",
    "ROM_LAYOUTS",
    "ROM_PLATFORMS",
    "TOS_SIZES",
    "CartridgeHeader",
    "RomError",
    "RomHeader",
    "bank_count",
    "bank_number",
    "byte_diagnostics",
    "entry_point_candidates",
    "entry_point_inventory",
    "image_context",
    "inspect_bank",
    "inspect_image",
    "is_erased",
    "make_cartridge_rom",
    "make_expansion_rom",
    "parse_cartridge_header",
    "parse_rom_header",
    "printable_strings",
    "read_bank",
    "rename_cartridge",
    "rom_base",
    "system_fonts",
    "validate_bank_size",
    "validate_layout",
    "validate_platform",
]
