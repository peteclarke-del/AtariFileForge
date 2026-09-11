"""Reading Atari software out of whatever it arrived in.

A driver or a desktop reaches this application in one of four shapes: unpacked
into a folder, inside a ZIP, on a floppy image, or inside a ZIP of floppy
images. The last is not an oddity: both desktops that can be downloaded from
their own authors today are exactly that, because a floppy is how this
software was published and nobody has repackaged it since.

Files are matched on their own names wherever they sit inside the bundle.
Every distribution arranges its folders differently, and the names do not
change, so a path would be the wrong thing to match on.
"""

from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

#: The disk images a distribution arrives on.
DISK_SUFFIXES = (".st", ".msa", ".dim")

#: Everything a single file can be, when it is not a folder.
BUNDLE_SUFFIXES = (".zip", *DISK_SUFFIXES)

#: How deep a distribution floppy is walked. Two folders is enough for every
#: one of these: one per product, and one inside it.
MAX_DISK_DEPTH = 3


def volume_files(image: Path, wanted: dict[str, str]) -> dict[str, bytes]:
    """Read the wanted files off a GEMDOS floppy, wherever they sit on it."""
    try:
        from atarinut.filesystem import reader_for
        from atarinut.filesystem.gemdos import GEMDOSVolume

        volume = GEMDOSVolume(reader_for(image))
    except Exception:
        return {}
    held: dict[str, bytes] = {}

    def walk(folder: str, depth: int) -> None:
        if depth > MAX_DISK_DEPTH:
            return
        try:
            entries = list(volume.iter_entries(folder))
        except Exception:
            return
        for entry in entries:
            path = f"{folder}\\{entry.name}" if folder else entry.name
            if entry.is_dir:
                walk(path, depth + 1)
                continue
            proper = wanted.get(entry.name.casefold())
            if proper is None or proper in held:
                continue
            try:
                held[proper] = volume.read_bytes(path)
            except Exception:
                continue

    walk("", 0)
    return held


def archive_files(archive: Path, wanted: dict[str, str]) -> dict[str, bytes]:
    """Read the wanted files out of a ZIP, including off any floppies in it."""
    held: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(archive) as bundle:
            disks = []
            for entry in bundle.infolist():
                if entry.is_dir():
                    continue
                leaf = entry.filename.replace("\\", "/").rsplit("/", 1)[-1]
                if Path(leaf).suffix.casefold() in DISK_SUFFIXES:
                    disks.append(entry)
                    continue
                proper = wanted.get(leaf.casefold())
                if proper is None or proper in held:
                    continue
                held[proper] = bundle.read(entry)
            for entry in disks:
                if all(name in held for name in wanted.values()):
                    break
                with tempfile.TemporaryDirectory(prefix="aff-distribution-") as folder:
                    image = Path(folder) / Path(entry.filename).name
                    image.write_bytes(bundle.read(entry))
                    for name, payload in volume_files(image, wanted).items():
                        held.setdefault(name, payload)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return {}
    return held


def bundle_files(path: Path, wanted: dict[str, str]) -> dict[str, bytes]:
    """Read the wanted files out of whatever single file this is."""
    suffix = Path(path).suffix.casefold()
    if suffix == ".zip":
        return archive_files(Path(path), wanted)
    if suffix in DISK_SUFFIXES:
        return volume_files(Path(path), wanted)
    return {}


__all__ = [
    "BUNDLE_SUFFIXES",
    "DISK_SUFFIXES",
    "MAX_DISK_DEPTH",
    "archive_files",
    "bundle_files",
    "volume_files",
]
