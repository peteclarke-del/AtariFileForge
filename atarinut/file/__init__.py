"""Per-file Atari catalogue metadata.

A GEMDOS directory entry carries two things a workbench needs to preserve
when a file moves between volumes: its attribute byte and its datestamp.
There is no comment field, no load address and no owner. This module owns
the attribute bits, the FAT date and time words, and the ``AtariMeta`` value
that carries both across a copy.

Attributes are one byte in the directory entry. From bit 0 upwards: read-only,
hidden, system, volume label, directory, archive. The archive bit is set on
every file GEMDOS writes and cleared by backup tools, so a freshly created
file carries ``-----a``.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import IntFlag

from ..errors import DataError
from . import filetypes as filetypes  # re-exported for callers

FA_READONLY = 0x01
FA_HIDDEN = 0x02
FA_SYSTEM = 0x04
FA_VOLUME = 0x08
FA_DIRECTORY = 0x10
FA_ARCHIVE = 0x20

#: Every bit a directory entry can carry.
ATTRIBUTE_MASK = 0x3F

#: Bits a caller may change on an existing entry. The volume-label and
#: directory bits describe what the entry *is* and are managed by the volume.
EDITABLE_ATTRIBUTES = FA_READONLY | FA_HIDDEN | FA_SYSTEM | FA_ARCHIVE

#: A newly written file carries only the archive bit, as GEMDOS writes it.
DEFAULT_ATTRIBUTES = FA_ARCHIVE

#: Canonical display order: ``rhsvda``.
FLAG_ORDER = (
    ("r", FA_READONLY),
    ("h", FA_HIDDEN),
    ("s", FA_SYSTEM),
    ("v", FA_VOLUME),
    ("d", FA_DIRECTORY),
    ("a", FA_ARCHIVE),
)

#: FAT dates count from 1 January 1980 and run out at the end of 2107.
FAT_EPOCH_YEAR = 1980
FAT_LAST_YEAR = 2107


class Access(IntFlag):
    """Decoded attribute bits for one catalogue entry.

    ``readable`` is always true because GEMDOS has no bit that denies a
    read. ``locked`` is the read-only bit under the name the workbench's lock
    control uses.
    """

    READ_ONLY = FA_READONLY
    HIDDEN = FA_HIDDEN
    SYSTEM = FA_SYSTEM
    VOLUME = FA_VOLUME
    DIRECTORY = FA_DIRECTORY
    ARCHIVE = FA_ARCHIVE

    @property
    def readable(self) -> bool:
        return True

    @property
    def writable(self) -> bool:
        return not self & Access.READ_ONLY

    @property
    def hidden(self) -> bool:
        return bool(self & Access.HIDDEN)

    @property
    def system(self) -> bool:
        return bool(self & Access.SYSTEM)

    @property
    def is_volume_label(self) -> bool:
        return bool(self & Access.VOLUME)

    @property
    def is_directory(self) -> bool:
        return bool(self & Access.DIRECTORY)

    @property
    def archived(self) -> bool:
        return bool(self & Access.ARCHIVE)

    @property
    def locked(self) -> bool:
        """True when the entry is read-only and so cannot be deleted or written."""
        return bool(self & Access.READ_ONLY)

    def with_locked(self, locked: bool) -> "Access":
        if locked:
            return Access(self.value | FA_READONLY)
        return Access(self.value & ~FA_READONLY)

    def __str__(self) -> str:  # pragma: no cover - convenience
        return format_access_text(self)


def format_access_text(access: Access | int | None) -> str:
    """Render attributes in the fixed six-letter ``rhsvda`` form."""
    if access is None:
        return ""
    value = access.value if isinstance(access, Access) else int(access)
    return "".join(letter if value & mask else "-" for letter, mask in FLAG_ORDER)


_NUMBER = re.compile(r"(?:0[xX]|\$|&)([0-9A-Fa-f]{1,2})|([0-9]{1,3})")


def parse_attribute_value(text: str | int | None) -> int:
    """Parse an attribute byte written as decimal or ``0x``, ``$`` or ``&`` hex."""
    if text is None or text == "":
        return DEFAULT_ATTRIBUTES
    if isinstance(text, int):
        value = text
    else:
        cleaned = str(text).strip().replace("_", "")
        if not cleaned:
            return DEFAULT_ATTRIBUTES
        match = _NUMBER.fullmatch(cleaned)
        if match is None:
            raise DataError(f"{text!r} is not an attribute value.")
        value = int(match.group(1), 16) if match.group(1) is not None else int(match.group(2), 10)
    if not 0 <= value <= ATTRIBUTE_MASK:
        raise DataError("An attribute byte must be between 0 and 0x3F.")
    return value


def parse_access_text(text: str | int | None) -> Access:
    """Parse ``rhsvda`` style text, or a number, into attribute bits.

    The six-letter form is positional and ``-`` clears a bit. A shorter
    string is a set of letters to turn on, so ``r`` alone means read-only
    plus the archive bit GEMDOS gives every file.
    """
    if isinstance(text, int):
        return Access(parse_attribute_value(text))
    cleaned = str(text or "").strip()
    if not cleaned:
        return Access(DEFAULT_ATTRIBUTES)
    if _NUMBER.fullmatch(cleaned) and not re.fullmatch(r"[rhsvdaRHSVDA-]+", cleaned):
        return Access(parse_attribute_value(cleaned))
    lowered = cleaned.lower()
    if not re.fullmatch(r"[rhsvda-]{1,6}", lowered):
        raise DataError("Attribute flags may only contain r, h, s, v, d, a or -.")
    value = 0
    if len(lowered) == 6:
        for (letter, mask), character in zip(FLAG_ORDER, lowered):
            if character == "-":
                continue
            if character != letter:
                raise DataError(
                    "Six-letter attribute text must follow the rhsvda order, "
                    "with - for a clear bit."
                )
            value |= mask
        return Access(value)
    for letter, mask in FLAG_ORDER:
        if letter in lowered:
            value |= mask
    return Access(value | FA_ARCHIVE)


# ---------------------------------------------------------------------------
# Datestamps
# ---------------------------------------------------------------------------
def fat_to_datetime(date_word: int, time_word: int) -> datetime | None:
    """Convert FAT date and time words into an aware UTC datetime.

    A zero date word means the entry was never stamped; the result is None
    rather than the meaningless 0 January 1980. Out-of-range fields, which
    some formatters write, are clamped instead of raising so a listing never
    fails on one bad entry.
    """
    date_word = int(date_word) & 0xFFFF
    time_word = int(time_word) & 0xFFFF
    if date_word == 0:
        return None
    year = FAT_EPOCH_YEAR + (date_word >> 9)
    month = min(max((date_word >> 5) & 0x0F, 1), 12)
    day = max(date_word & 0x1F, 1)
    hour = min(time_word >> 11, 23)
    minute = min((time_word >> 5) & 0x3F, 59)
    second = min((time_word & 0x1F) * 2, 58)
    while day > 28:
        try:
            return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        except ValueError:
            day -= 1
    return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)


def datetime_to_fat(moment: datetime | None) -> tuple[int, int]:
    """Convert a datetime into FAT date and time words.

    Naive datetimes are taken as UTC. The result is clamped to the 1980 to
    2107 range the words can express and rounded down to the two-second
    resolution of the time word.
    """
    if moment is None:
        moment = datetime.now(timezone.utc)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    year = moment.year
    if year < FAT_EPOCH_YEAR:
        return (1 << 5) | 1, 0
    if year > FAT_LAST_YEAR:
        return (127 << 9) | (12 << 5) | 31, (23 << 11) | (59 << 5) | 29
    date_word = ((year - FAT_EPOCH_YEAR) << 9) | (moment.month << 5) | moment.day
    time_word = (moment.hour << 11) | (moment.minute << 5) | (moment.second // 2)
    return date_word, time_word


def clamp_datestamp(moment: datetime | None) -> datetime | None:
    """Round a datetime to what a directory entry can store."""
    if moment is None:
        return None
    return fat_to_datetime(*datetime_to_fat(moment))


class AtariMeta:
    """The catalogue metadata Atari File Forge preserves across a copy.

    A GEMDOS entry carries an attribute byte and one datestamp. There is
    deliberately no comment and no load address: GEMDOS records neither, and
    a program's load information lives in its own executable header.
    """

    __slots__ = ("attributes", "datestamp", "extra")

    def __init__(
        self,
        attributes: int = DEFAULT_ATTRIBUTES,
        datestamp: datetime | None = None,
        extra: dict | None = None,
        *,
        access: "Access | int | None" = None,
    ):
        if access is not None:
            attributes = access.value if isinstance(access, Access) else int(access)
        self.attributes = int(attributes) & ATTRIBUTE_MASK
        self.datestamp = datestamp
        self.extra = dict(extra or {})

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"AtariMeta(attributes=0x{self.attributes:02X}, datestamp={self.datestamp!r})"
        )

    def __eq__(self, other) -> bool:
        if not isinstance(other, AtariMeta):
            return NotImplemented
        return self.attributes == other.attributes and self.datestamp == other.datestamp

    @property
    def access(self) -> Access:
        return Access(self.attributes)

    def with_attributes(self, value: int | Access) -> "AtariMeta":
        raw = value.value if isinstance(value, Access) else int(value)
        return AtariMeta(attributes=raw, datestamp=self.datestamp, extra=dict(self.extra))

    def with_datestamp(self, moment: datetime | None) -> "AtariMeta":
        return AtariMeta(attributes=self.attributes, datestamp=moment, extra=dict(self.extra))


__all__ = [
    "ATTRIBUTE_MASK",
    "Access",
    "AtariMeta",
    "DEFAULT_ATTRIBUTES",
    "EDITABLE_ATTRIBUTES",
    "FA_ARCHIVE",
    "FA_DIRECTORY",
    "FA_HIDDEN",
    "FA_READONLY",
    "FA_SYSTEM",
    "FA_VOLUME",
    "FAT_EPOCH_YEAR",
    "FAT_LAST_YEAR",
    "FLAG_ORDER",
    "clamp_datestamp",
    "datetime_to_fat",
    "fat_to_datetime",
    "filetypes",
    "format_access_text",
    "parse_access_text",
    "parse_attribute_value",
]
