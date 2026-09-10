"""Atari file-type recognition.

GEMDOS keeps no type field in the directory. What a file *is* comes from its
extension, which the Desktop uses to decide whether to run it, and from its
content, which is what a loader actually checks. This module owns both routes
so the workbench classifies a file the same way whether it is listing a
directory or opening one file.

Kinds are short lower-case words (``executable``, ``picture``, ``archive``)
rather than numeric codes, because there is no on-disk code to round-trip.
"""

from __future__ import annotations

import struct

#: The first word of every GEMDOS executable: a ``BRA.S`` past the header.
GEMDOS_MAGIC = 0x601A

#: STOS BASIC files carry this signature after their header.
STOS_SIGNATURE = b"Lionpoubnk"

#: Kinds by extension, upper case as the Desktop shows them.
EXTENSION_KINDS: dict[str, str] = {
    "PRG": "executable",
    "TOS": "executable",
    "TTP": "executable",
    "APP": "executable",
    "GTP": "executable",
    "ACC": "accessory",
    "CPX": "accessory",
    "RSC": "resource",
    "INF": "configuration",
    "IMG": "picture",
    "PI1": "picture",
    "PI2": "picture",
    "PI3": "picture",
    "PC1": "picture",
    "PC2": "picture",
    "PC3": "picture",
    "NEO": "picture",
    "DEG": "picture",
    "SND": "sound",
    "AVR": "sound",
    "MOD": "music",
    "SNG": "music",
    "TXT": "text",
    "DOC": "text",
    "ASC": "text",
    "BAS": "basic",
    "GFA": "basic",
    "LST": "basic",
    "STO": "basic",
    "ZIP": "archive",
    "LZH": "archive",
    "ARC": "archive",
    "ARJ": "archive",
    "ZOO": "archive",
    "MSA": "diskimage",
    "ST": "diskimage",
}

#: Extensions the Desktop runs by double-click, and how it runs them.
EXECUTABLE_EXTENSIONS = {
    "PRG": "GEM program",
    "APP": "GEM application",
    "GTP": "GEM program that takes parameters",
    "TOS": "TOS program",
    "TTP": "TOS program that takes parameters",
    "ACC": "desk accessory",
    "CPX": "control panel extension",
}

KIND_LABELS = {
    "executable": "Program",
    "accessory": "Desk accessory",
    "resource": "GEM resource",
    "configuration": "Configuration",
    "picture": "Picture",
    "sound": "Sound sample",
    "music": "Music module",
    "text": "Text",
    "basic": "BASIC program",
    "archive": "Archive",
    "diskimage": "Disk image",
}


def split_extension(name: str) -> tuple[str, str]:
    """Split ``FOO.PRG`` into ``("FOO", "PRG")``, upper-cased."""
    text = str(name or "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1].strip()
    base, dot, extension = text.rpartition(".")
    if not dot:
        return text.upper(), ""
    return base.upper(), extension.upper()


def classify_name(name: str) -> str | None:
    """Classify a file by its extension alone."""
    _base, extension = split_extension(name)
    return EXTENSION_KINDS.get(extension)


def format_filetype(kind: str | None) -> str:
    """Render a kind as the label the workbench shows."""
    if not kind:
        return ""
    return KIND_LABELS.get(str(kind), str(kind).capitalize())


def is_gemdos_executable(data: bytes) -> bool:
    """True when ``data`` starts with a plausible GEMDOS program header.

    The header is 28 bytes: the magic word, then big-endian text, data,
    BSS and symbol-table sizes, a reserved long, a flags long and the
    absolute-flag word. A file whose declared sections do not fit inside it
    is not a program, whatever its first word says.
    """
    if len(data) < 28:
        return False
    magic, text, data_size, _bss, symbols = struct.unpack_from(">HIIII", data, 0)
    if magic != GEMDOS_MAGIC:
        return False
    return 28 + text + data_size + symbols <= len(data)


def is_gem_resource(data: bytes) -> bool:
    """True for a GEM resource file whose header describes its own length."""
    if len(data) < 36:
        return False
    version = struct.unpack_from(">H", data, 0)[0]
    size = struct.unpack_from(">H", data, 34)[0]
    if version in (0, 1):
        return size == len(data)
    if version in (3, 4):
        # Extended resources keep the 16-bit size for the old part and grow
        # beyond it; the header must at least fit and the old size be sane.
        return 36 <= size <= len(data)
    return False


def is_degas_picture(data: bytes) -> bool:
    """True for DEGAS and DEGAS Elite pictures, compressed or not."""
    if len(data) < 34:
        return False
    resolution = struct.unpack_from(">H", data, 0)[0]
    compressed = bool(resolution & 0x8000)
    resolution &= 0x7FFF
    if resolution > 2:
        return False
    if not compressed:
        return len(data) in (32034, 32066)
    return len(data) > 34


def is_neochrome_picture(data: bytes) -> bool:
    if len(data) != 32128:
        return False
    flag, resolution = struct.unpack_from(">HH", data, 0)
    return flag == 0 and resolution <= 2


def is_tokenised_basic(data: bytes) -> bool:
    """Recognise STOS and GFA BASIC 3 tokenised programs by their headers."""
    if STOS_SIGNATURE in data[:64]:
        return True
    if len(data) >= 40:
        version = struct.unpack_from(">H", data, 0)[0]
        if version == 3 and data[2:4] == b"\0\0":
            # GFA BASIC 3.x: a version word of 3, then the eight 32-bit
            # section sizes of the header. Their sum must lie within the file.
            sizes = struct.unpack_from(">8I", data, 4)
            return sum(sizes) <= len(data)
    return False


def detect_content_type(data: bytes) -> str | None:
    """Classify Atari content from its bytes alone.

    Returns ``executable``, ``resource``, ``picture``, ``basic``,
    ``archive`` or None when nothing is recognised.
    """
    if is_gemdos_executable(data):
        return "executable"
    if is_gem_resource(data):
        return "resource"
    if is_degas_picture(data) or is_neochrome_picture(data):
        return "picture"
    if is_tokenised_basic(data):
        return "basic"
    if data[:2] == b"PK" or data[2:5] == b"-lh" or data[:2] == b"\x60\xea" or data[:2] == b"ZOO":
        return "archive"
    if data[:2] == b"\x0e\x0f":
        return "diskimage"
    return None


def classify(name: str, data: bytes | None = None) -> str | None:
    """Classify by content first, then by extension."""
    if data:
        kind = detect_content_type(data)
        if kind is not None:
            return kind
    return classify_name(name)


__all__ = [
    "EXECUTABLE_EXTENSIONS",
    "EXTENSION_KINDS",
    "GEMDOS_MAGIC",
    "KIND_LABELS",
    "classify",
    "classify_name",
    "detect_content_type",
    "format_filetype",
    "is_degas_picture",
    "is_gem_resource",
    "is_gemdos_executable",
    "is_neochrome_picture",
    "is_tokenised_basic",
    "split_extension",
]
