"""Direct floppy access through a Linux block device.

This is the adapter for a machine that has a real floppy controller, such as a
Raspberry Pi or a PC with a drive attached, where the disk appears as
``/dev/fd0``. It complements the Greaseweazle adapter rather than replacing it.

The two are not equivalent, and the difference matters when choosing one:

* A floppy controller reads **decoded sectors** at whatever geometry the kernel
  has been told the disk uses. It cannot see anything the controller will not
  decode, so a damaged, copy-protected or unusual disk fails rather than being
  captured.
* Greaseweazle reads **flux**, so it captures a disk whether or not any
  filesystem decoder accepts it.

An ST floppy is ordinary IBM-style MFM, which is why a PC controller reads
one at all: 512-byte sectors, nine per track on a TOS-formatted disk, ten or
eleven when a formatter squeezed more in, on one or two sides. The kernel
must already be told that shape, either through ``setfdprm`` or by opening a
device node that carries it, such as ``/dev/fd0u720`` for the everyday
double-sided disk, ``/dev/fd0u800`` and ``/dev/fd0u880`` for ten and eleven
sectors, ``/dev/fd0u360`` for a 5.25-inch PC disk and ``/dev/fd0u1440`` for
high density. This module therefore verifies what it read against the
geometry the caller chose and refuses anything that does not match, instead
of handing back a plausible-looking image of the wrong shape. Which geometry
to choose is the caller's decision, made from the boot sector where one is
available; the shapes themselves live in ``app.floppy_geometry``.

Nothing here runs a subprocess: the device is read and written directly, so the
module has no dependency on external tooling.
"""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from app.floppy_geometry import (
    GEOMETRIES,
    FloppyGeometry,
    geometries_for_size,
    geometry_for_size,
    resolve_geometry,
)
from app.progress import Progress, reporter


class FloppyError(RuntimeError):
    """A user-facing floppy device, geometry or media failure."""


# The geometries the workbench can open again, shared with every other part
# of the workbench through the one table.
ATARI_GEOMETRIES: dict[str, FloppyGeometry] = GEOMETRIES

#: The device-node suffix Linux gives each shape, where it has one. Opening
#: the suffixed node tells the kernel the geometry without ``setfdprm``.
#: Single-sided 80-track ST disks and the extended track counts have no
#: stock node and need ``setfdprm``.
DEVICE_SUFFIXES: dict[str, str] = {
    "ds-80t-9s": "u720",
    "ds-80t-10s": "u800",
    "ds-80t-11s": "u880",
    "pc-360k": "u360",
    "hd-1440k": "u1440",
}

# Read and write in whole tracks so progress is reported at a boundary the
# hardware actually works in, and a failure names the track it stopped on.
_MAX_CHUNK = 64 * 1024


def is_block_device(path: Path) -> bool:
    """Whether this path is a block device.

    Isolated so a host without a floppy controller, which is every development
    machine, can still exercise the adapter against an ordinary file.
    """
    try:
        return stat.S_ISBLK(path.stat().st_mode)
    except OSError:
        return False


@dataclass(frozen=True)
class FloppyProbe:
    available: bool
    device: str | None
    detail: str
    size: int | None = None


@dataclass(frozen=True)
class FloppyReadResult:
    device: str
    image: str
    geometry: str
    size: int


@dataclass(frozen=True)
class FloppyWriteResult:
    device: str
    image: str
    size: int
    geometry: str = ""


def geometry(identifier: str) -> FloppyGeometry:
    """Return one supported geometry, or explain the accepted names."""
    found = ATARI_GEOMETRIES.get(str(identifier or "").strip().lower())
    if found is None:
        raise FloppyError(
            "Choose a floppy geometry: " + ", ".join(sorted(ATARI_GEOMETRIES)) + "."
        )
    return found


def device_suffix(layout: FloppyGeometry) -> str | None:
    """The ``/dev/fd0`` suffix that carries this geometry, if Linux has one."""
    return DEVICE_SUFFIXES.get(layout.identifier)


# Linux names floppy devices /dev/fd0 upward, optionally with a geometry
# suffix such as /dev/fd0u720. The complete set is small and fixed, so it is
# enumerated rather than matched: a request names a drive, and selecting a
# constant from this tuple keeps a request-supplied string from ever reaching
# the filesystem.
_DRIVE_COUNT = 4
_GEOMETRY_SUFFIXES = (
    "", "d360", "h360", "h720", "h880", "h1200", "h1440", "h1680", "h1722",
    "h1743", "h1760", "h1920", "h2880", "u360", "u720", "u800", "u820", "u830", "u880",
    "u1040", "u1120", "u1440", "u1600", "u1680", "u1722", "u1743", "u1760",
    "u1840", "u1920", "u2880", "u3200", "u3520", "u3840",
)
KNOWN_DEVICES: tuple[str, ...] = tuple(
    f"/dev/fd{index}{suffix}"
    for index in range(_DRIVE_COUNT)
    for suffix in _GEOMETRY_SUFFIXES
)


def validated_device(name: object) -> str:
    """Return a known floppy device path, or refuse anything that is not one.

    A request may name the drive to use, so the value is matched against the
    fixed set above and the matching constant is returned. That rejects a
    system disk such as /dev/sda outright, which is a block device too and
    whose first tracks would otherwise be readable as an image.
    """
    value = str(name or "").strip()
    for candidate in KNOWN_DEVICES:
        if candidate == value:
            return candidate
    raise FloppyError(
        f"“{value}” is not a floppy device. Choose one of the drives this host "
        "exposes, such as /dev/fd0."
    )


def available_devices(candidates: int = 4) -> list[str]:
    """List floppy block devices this host actually exposes."""
    found = []
    for index in range(candidates):
        path = Path(f"/dev/fd{index}")
        try:
            if stat.S_ISBLK(path.stat().st_mode):
                found.append(str(path))
        except OSError:
            continue
    return found


def image_geometry(image: Path, geometry_id: str | None = None) -> FloppyGeometry:
    """Decide the shape of an image that is about to be written.

    An explicit geometry wins, and must match the file's size. Otherwise the
    boot sector is read and believed when it agrees with the size, and only
    then does the size alone decide, and only when it names exactly one
    shape: a 360 KiB file is both a single-sided ST disk and a double-sided
    PC one, and writing it at the wrong shape scrambles every track.
    """
    try:
        size = image.stat().st_size
        with image.open("rb") as handle:
            boot = handle.read(512)
    except OSError as exc:
        raise FloppyError(f"The image could not be read: {exc}") from exc
    if geometry_id:
        layout = geometry(geometry_id)
        if layout.size != size:
            raise FloppyError(
                f"{image.name} is {size:,} bytes but {layout.label} is {layout.size:,} bytes."
            )
        return layout
    layout = resolve_geometry(size, boot)
    if layout is None:
        candidates = geometries_for_size(size)
        if candidates:
            raise FloppyError(
                f"{image.name} has no usable boot sector and its size fits more than one "
                "geometry (" + ", ".join(item.identifier for item in candidates) + "). "
                "Choose the geometry explicitly."
            )
        raise FloppyError(
            f"{image.name} is {size:,} bytes, which is not one of the floppy geometries "
            "this drive can write. Use Greaseweazle for other layouts."
        )
    return layout


class FloppyDevice:
    """Read and write one floppy block device without any external tool."""

    def __init__(self, device: str | Path = "/dev/fd0") -> None:
        self.device = Path(device)

    def probe(self) -> FloppyProbe:
        """Report whether this device exists, is a floppy, and holds a disk."""
        if not self.device.exists():
            return FloppyProbe(
                False,
                str(self.device),
                f"{self.device} does not exist. This host has no floppy controller, "
                "or the floppy driver is not loaded.",
            )
        if not is_block_device(self.device):
            return FloppyProbe(
                False, str(self.device), f"{self.device} is not a block device."
            )
        try:
            with self.device.open("rb") as handle:
                handle.read(512)
                size = handle.seek(0, os.SEEK_END)
        except PermissionError:
            return FloppyProbe(
                False,
                str(self.device),
                f"No permission to read {self.device}. Add the account to the group that "
                "owns the device, normally 'floppy' or 'disk'.",
            )
        except OSError as exc:
            if exc.errno in {errno.ENOMEDIUM, errno.ENXIO, errno.EIO}:
                return FloppyProbe(
                    False,
                    str(self.device),
                    "No readable disk in the drive, or the kernel geometry does not match "
                    "this disk. Set the geometry with setfdprm before reading.",
                )
            return FloppyProbe(False, str(self.device), f"Could not read {self.device}: {exc}")
        return FloppyProbe(True, str(self.device), "Floppy drive ready.", size or None)

    def read(
        self,
        destination: str | Path,
        geometry_id: str,
        progress: Progress | None = None,
    ) -> FloppyReadResult:
        """Capture the disk in the drive as an image of the chosen geometry.

        The read is checked against the geometry's exact size. A short read
        means the controller could not decode the whole disk, so the partial
        capture is removed rather than presented as a complete image.
        """
        layout = geometry(geometry_id)
        path = Path(destination)
        probe = self.probe()
        if not probe.available:
            raise FloppyError(probe.detail)
        report = reporter(progress)
        report(f"Reading {layout.label} from {self.device}", 0, layout.size)
        written = 0
        try:
            with self.device.open("rb") as source, path.open("wb") as target:
                while written < layout.size:
                    chunk = source.read(min(_MAX_CHUNK, layout.size - written))
                    if not chunk:
                        break
                    target.write(chunk)
                    written += len(chunk)
                    # Calling progress is also the cancellation boundary.
                    report(f"Reading {self.device}", written, layout.size)
        except OSError as exc:
            path.unlink(missing_ok=True)
            raise FloppyError(self._read_failure(exc, written, layout)) from exc
        if written != layout.size:
            path.unlink(missing_ok=True)
            raise FloppyError(
                f"The drive returned {written:,} bytes but {layout.label} is "
                f"{layout.size:,} bytes. The disk, the drive or the kernel geometry does "
                "not match the chosen format."
            )
        report(f"Captured {layout.label}", layout.size, layout.size)
        return FloppyReadResult(
            device=str(self.device),
            image=path.name,
            geometry=layout.identifier,
            size=layout.size,
        )

    @staticmethod
    def _read_failure(exc: OSError, written: int, layout: FloppyGeometry) -> str:
        track = written // (layout.sides * layout.track_size)
        if exc.errno in {errno.ENOMEDIUM, errno.ENXIO}:
            return "The drive reported no disk. Insert a disk and try again."
        return (
            f"The drive could not read track {track} of {layout.tracks}. "
            "The disk may be damaged, or its format may not be one a floppy controller "
            "can decode. Capture it with Greaseweazle as flux instead."
        )

    def write(
        self,
        image: str | Path,
        progress: Progress | None = None,
        *,
        confirm: bool = False,
        geometry_id: str | None = None,
    ) -> FloppyWriteResult:
        """Write an image to the disk in the drive, overwriting it completely.

        ``confirm`` must be set by the caller. Writing a physical disk is not
        reversible and there is no undo point on the far side of the drive, so
        the destructive step is never reached by default.

        The image's shape is settled by ``image_geometry``: the caller's
        choice, else the boot sector, else an unambiguous size. The kernel
        geometry must agree with it, which the drive's reported size checks.
        """
        path = Path(image)
        if not confirm:
            raise FloppyError(
                "Writing a physical disk erases it completely and cannot be undone. "
                "Confirm the write before it is attempted."
            )
        layout = image_geometry(path, geometry_id)
        size = layout.size
        probe = self.probe()
        if not probe.available:
            raise FloppyError(probe.detail)
        if probe.size is not None and probe.size != size:
            hint = device_suffix(layout)
            raise FloppyError(
                f"The drive reports {probe.size:,} bytes but {path.name} is {size:,} bytes "
                f"({layout.label}). Set the kernel geometry to match the disk before writing"
                + (f", for example by opening /dev/fd0{hint}." if hint else " with setfdprm.")
            )
        report = reporter(progress)
        report(f"Writing {layout.label} to {self.device}", 0, size)
        written = 0
        try:
            with path.open("rb") as source, self.device.open("wb") as target:
                while True:
                    chunk = source.read(_MAX_CHUNK)
                    if not chunk:
                        break
                    target.write(chunk)
                    written += len(chunk)
                    report(f"Writing {self.device}", written, size)
                target.flush()
                os.fsync(target.fileno())
        except OSError as exc:
            raise FloppyError(
                f"The drive stopped after {written:,} of {size:,} bytes. The physical disk is "
                f"incomplete and must not be relied on: {exc}"
            ) from exc
        report("Physical disk written", size, size)
        return FloppyWriteResult(
            device=str(self.device), image=path.name, size=size, geometry=layout.identifier
        )


__all__ = [
    "ATARI_GEOMETRIES",
    "DEVICE_SUFFIXES",
    "FloppyDevice",
    "FloppyError",
    "FloppyGeometry",
    "FloppyProbe",
    "FloppyReadResult",
    "FloppyWriteResult",
    "KNOWN_DEVICES",
    "available_devices",
    "device_suffix",
    "geometry",
    "geometry_for_size",
    "image_geometry",
    "validated_device",
]
