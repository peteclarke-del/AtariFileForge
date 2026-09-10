r"""GEMDOS directory metadata, in the forms it travels in.

A GEMDOS directory entry records very little: a name, a length, a first
cluster, a date and time, and one attribute byte. The attribute byte is the
whole of the file's metadata, and its six meaningful bits are printed here in
the order ``rhsvda``: read-only, hidden, system, volume label, directory and
archive. A dash stands for a bit that is clear, so ``----a-`` is an ordinary
file that has been written since the last backup, and ``r-----`` is one the
desktop will refuse to delete.

There is no comment, no icon type and no load or execution address. A GEMDOS
program carries its own relocation table in its 0x601A header and TOS decides
where to put it at run time, so there is nothing in the catalogue to record.
Anything that wants to travel with a file therefore travels as the attribute
byte and the datestamp, and nothing else is invented to fill the gap.
"""

from __future__ import annotations

import re

from atarinut.file import (
    ATTRIBUTE_MASK,
    format_access_text,
    parse_access_text,
    parse_attribute_value,
)


_RECORD_FIELDS = re.compile(r'"[^"]*"|\S+')


def _hex_field(value: str) -> int:
    return int(re.sub(r"^(?:&|0x|\$)", "", value, flags=re.IGNORECASE), 16)


#: The attribute letters, most significant bit last, as ``format_attributes``
#: prints them.
ATTRIBUTE_LETTERS = "rhsvda"

#: The extension Atari File Forge gives the sidecar it writes beside an
#: exported file. ``.INF`` is not used: on an Atari that names a desktop
#: configuration file, and a sidecar that collided with ``DESKTOP.INF`` would
#: be read by the machine as one.
ATTRIBUTE_SIDECAR_SUFFIX = ".attr"


def parse_attributes(text: object) -> int | None:
    """Read a six-letter attribute field such as ``r----a``.

    Returns ``None`` when the text is not in that form, so a caller can fall
    back to reading it as a number rather than having to guess first.
    """
    cleaned = str(text or "").strip()
    if len(cleaned) != len(ATTRIBUTE_LETTERS):
        return None
    for index, letter in enumerate(ATTRIBUTE_LETTERS):
        character = cleaned[index]
        if character not in {letter, letter.upper(), "-"}:
            return None
    return int(parse_access_text(cleaned)) & ATTRIBUTE_MASK


def format_attributes(value: object) -> str:
    """Print an attribute byte the way the workbench shows it."""
    return format_access_text(int(value or 0) & ATTRIBUTE_MASK)


def attribute_value(value: object) -> int:
    """Read an attribute byte from either the letters or a number."""
    letters = parse_attributes(value)
    if letters is not None:
        return letters
    return int(parse_attribute_value(value)) & ATTRIBUTE_MASK


def parse_attribute_record(data: bytes | str) -> dict | None:
    """Parse the sidecar Atari File Forge writes beside an exported file.

    The record is ``path attributes length`` with the length in hexadecimal,
    which is exactly the metadata a GEMDOS entry carries beyond its datestamp.
    There is no address field, because GEMDOS records none.
    """
    text = data.decode("latin-1", "replace") if isinstance(data, bytes) else str(data)
    fields = _RECORD_FIELDS.findall(text.strip())
    if len(fields) < 2:
        return None
    name = fields[0].strip('"')
    attributes = parse_attributes(fields[1])
    if attributes is None:
        return None
    length = None
    if len(fields) > 2:
        try:
            length = _hex_field(fields[2])
        except ValueError:
            length = None
    return {
        "name": name,
        "attributes": attributes,
        "access": attributes,
        "length": length,
        "locked": bool(attributes & 0x01),
    }


def format_attribute_record(path: str, metadata: dict) -> str:
    """Create one deterministic sidecar record from directory metadata."""
    catalogue_path = str(path or "File").strip() or "File"
    if any(character.isspace() for character in catalogue_path):
        catalogue_path = f'"{catalogue_path}"'
    attributes = format_attributes(
        metadata.get("attributes", metadata.get("access"))
    )
    length = int(metadata.get("length") or 0) & 0xFFFFFFFF
    return f"{catalogue_path} {attributes} {length:08X}\n"


#: ZIP's host-system code for an Atari ST. The TOS ports of Info-ZIP and the
#: archivers that follow them write this, and everything else does not.
ZIP_HOST_ATARI = 5

#: ZIP's host-system code for MS-DOS, which uses the same attribute byte in
#: the same place. A GEMDOS volume and a FAT volume record the same six bits,
#: so an archive made under either carries usable attributes.
ZIP_HOST_DOS = 0


def atari_zip_metadata(info) -> dict | None:
    """Read GEMDOS attributes from a ZIP entry's own directory fields.

    A ZIP written on an Atari records host system 5 and keeps the file's
    attribute byte in the low eight bits of the external attributes, in the
    same layout the volume itself uses; an archive written under MS-DOS
    records host system 0 and the identical byte. There is no extra field to
    decode, which is why an archive made on any other machine simply has
    nothing to report and this returns ``None`` rather than inventing a
    default.
    """
    host = getattr(info, "create_system", None)
    if host not in {ZIP_HOST_ATARI, ZIP_HOST_DOS}:
        return None
    attributes = int(getattr(info, "external_attr", 0) or 0) & ATTRIBUTE_MASK
    return {"attributes": attributes, "access": attributes}


__all__ = [
    "ATTRIBUTE_LETTERS",
    "ATTRIBUTE_SIDECAR_SUFFIX",
    "ZIP_HOST_ATARI",
    "ZIP_HOST_DOS",
    "atari_zip_metadata",
    "attribute_value",
    "format_attribute_record",
    "format_attributes",
    "parse_attribute_record",
    "parse_attributes",
]
