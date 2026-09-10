"""Describe the GEMDOS layout exposed by a mounted volume.

The pane needs to know several things before it lets a user type a name or
create a directory: whether this volume is FAT12 or FAT16, how long a name
may be, how many entries its root directory holds, and whether two names that
differ only in case are the same name. All of them come from the mounted
volume's boot sector rather than from the file extension, because a ``.st``
says nothing about the filing system inside it.

The name limit is the interesting one. GEMDOS stores a name in a fixed
eleven-byte field, eight characters and a three-character extension, and
folds it to upper case on the way in. A person reads that as "8.3", so both
spellings are reported: the count a length check needs and the form a message
should print.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

#: ``NAME.EXT`` is eight characters, a full stop and three more.
GEMDOS_NAME_LIMIT = 12

#: How the same limit is written when a person has to read it.
GEMDOS_NAME_FORM = "8.3"

#: A volume label occupies one directory entry's eleven name bytes, with no
#: separating full stop, so it holds eleven characters rather than twelve.
GEMDOS_LABEL_LIMIT = 11


@dataclass(frozen=True)
class GEMDOSCapabilities:
    """Pane-facing limits derived from the mounted on-disc structures."""

    format: str
    fat_bits: int
    name_limit: int
    name_form: str
    directory_entry_limit: int | None
    case_insensitive: bool
    label_limit: int
    label: str = ""
    clusters: int = 0
    cluster_bytes: int = 0
    size_bytes: int = 0
    bootable: bool = False
    tos_limits: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        record = asdict(self)
        record["tos_limits"] = list(self.tos_limits)
        return record


def capabilities_from_mount(mount) -> GEMDOSCapabilities:
    """Return the format and directory limits for a mounted GEMDOS volume.

    ``directory_entry_limit`` is the root directory's fixed entry count,
    because that is a real ceiling: the root of a FAT volume is a fixed-size
    area written at format time and cannot grow. A subdirectory is an
    ordinary cluster chain and has no such limit, which is why the number is
    reported for the root alone and callers listing a subdirectory ignore it.

    ``tos_limits`` names any TOS release that cannot mount a volume this
    large. TOS 1.00 stops at 16 MiB, 1.04 at 256 MiB and every release at
    512 MiB without a replacement DOS, so a volume built past one of those
    lines works here and fails on the machine it was made for.
    """
    from atarinut.filesystem.gemdos import tos_limit_notes

    volume = getattr(mount, "volume", None)
    if volume is None:
        raise TypeError("The mounted filesystem is not a GEMDOS volume.")

    geometry = volume.geometry
    try:
        bootable = bool(mount.boot_option())
    except Exception:
        bootable = False
    return GEMDOSCapabilities(
        format=volume.format,
        fat_bits=int(volume.fat_bits),
        name_limit=GEMDOS_NAME_LIMIT,
        name_form=GEMDOS_NAME_FORM,
        directory_entry_limit=int(geometry.root_entries),
        case_insensitive=True,
        label_limit=GEMDOS_LABEL_LIMIT,
        label=str(getattr(mount, "title", "") or ""),
        clusters=int(geometry.data_clusters),
        cluster_bytes=int(geometry.cluster_bytes),
        size_bytes=int(geometry.size_bytes),
        bootable=bootable,
        tos_limits=tuple(tos_limit_notes(geometry.size_bytes)),
    )


def format_label(volume_format: str, size_bytes: int) -> str:
    """Return the familiar name for a volume, including its media size."""
    if size_bytes == 720 * 1024:
        media = "720 KiB floppy"
    elif size_bytes == 800 * 1024:
        media = "800 KiB floppy"
    elif size_bytes == 1440 * 1024:
        media = "1.44 MiB high-density floppy"
    elif size_bytes > 4 * 1024 * 1024:
        media = "hard-disk volume"
    else:
        media = "volume"
    return f"{volume_format} {media}"


__all__ = [
    "GEMDOS_LABEL_LIMIT",
    "GEMDOS_NAME_FORM",
    "GEMDOS_NAME_LIMIT",
    "GEMDOSCapabilities",
    "capabilities_from_mount",
    "format_label",
]
