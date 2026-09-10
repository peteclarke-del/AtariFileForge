"""Safe subprocess adapter for reading and writing Atari floppies with Greaseweazle.

The module deliberately has no Flask, GTK or Nautilus dependencies. Both
Atari File Forge and a file-manager extension can therefore use the same
probe, validation, progress and verification policy.

Formats and geometry
--------------------

``gw`` decides what a file is by its suffix, and for a sector image it also
needs to be told the disk's shape. An ``.st`` maps to gw's plain ``IMG``
class, which has no default format, so ``gw read disk.st`` and ``gw write
disk.st`` both stop with "Sector image requires a disk format to be
specified" unless ``--format`` is given. An ``.msa`` carries its own shape,
so writing one needs no format, but reading a disk into one does: gw has no
sectors to describe until a format tells it how to decode the flux. Flux
targets (``.hfe``, ``.scp``) and ``.ipf`` never take a format.

The format names are gw's own ``atarist.*`` definitions, which cover eighty
cylinders at nine, ten and eleven sectors on one or two sides, plus the IBM
definitions for high density and 5.25-inch media. ``gw_format`` turns a
layout into one of those names and refuses a layout gw has no definition
for, rather than letting gw write the first eighty tracks of an 82-track
image and call it done.

Two suffixes are refused outright because gw would misread them. ``.stx`` is
a Pasti capture gw does not support at all; the disk it came from is captured
as ``.scp`` or ``.hfe`` flux instead. ``.dim`` is, to gw, the PC-98 DIFC
format, not the FastCopy Pro image an ST user means; convert it to ``.st``
first.
"""

from __future__ import annotations

import os
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator


class GreaseweazleError(RuntimeError):
    """A user-facing hardware, media or command failure."""


@dataclass(frozen=True)
class ImageFormat:
    suffix: str
    label: str
    automatic_verification: bool
    #: Whether gw needs ``--format`` to read a disk into this file.
    format_on_read: bool = False
    #: Whether gw needs ``--format`` to write this file to a disk.
    format_on_write: bool = False

    @property
    def sector_image(self) -> bool:
        return self.automatic_verification


@dataclass(frozen=True)
class ProbeResult:
    available: bool
    command: str | None
    detail: str


@dataclass(frozen=True)
class ReadResult:
    drive: str
    image: str
    tracks_read: int
    size: int
    output_tail: tuple[str, ...]


@dataclass(frozen=True)
class WriteResult:
    drive: str
    image: str
    verified: bool
    verification_supported: bool
    tracks_written: int
    output_tail: tuple[str, ...]


#: What Greaseweazle can put on, or take off, a real Atari floppy. A sector
#: image can be verified by reading the disk back and comparing it; a flux
#: capture cannot, because two reads of the same disk are never bit-identical.
IMAGE_FORMATS = {
    ".st": ImageFormat(".st", "Atari ST sector image", True, format_on_read=True, format_on_write=True),
    ".msa": ImageFormat(".msa", "Magic Shadow Archiver image", True, format_on_read=True),
    ".hfe": ImageFormat(".hfe", "HFE flux-level disk", False),
    ".scp": ImageFormat(".scp", "SuperCard Pro flux capture", False),
    ".ipf": ImageFormat(".ipf", "SPS preservation image", False),
}

#: Suffixes gw would accept or misread, and what to do instead.
REFUSED_FORMATS = {
    ".stx": (
        "Greaseweazle cannot read or write Pasti .stx captures. Capture the disk as "
        "SCP or HFE flux instead, or convert the STX to .st to write its plain sectors."
    ),
    ".dim": (
        "Greaseweazle reads .dim as the PC-98 DIFC format, not a FastCopy Pro image. "
        "Convert the DIM to .st before writing it."
    ),
}

#: gw's own disk definitions, keyed by (tracks, sides, sectors per track).
GW_FORMATS: dict[tuple[int, int, int], str] = {
    (80, 1, 9): "atarist.360",
    (80, 1, 10): "atarist.400",
    (80, 1, 11): "atarist.440",
    (80, 2, 9): "atarist.720",
    (80, 2, 10): "atarist.800",
    (80, 2, 11): "atarist.880",
    (80, 2, 18): "ibm.1440",
    (40, 1, 9): "ibm.180",
    (40, 2, 9): "ibm.360",
}
_FORMAT_NAME = re.compile(r"^[a-z0-9]+(\.[a-z0-9]+)+$")

DRIVE_CHOICES = ("A", "B", "0", "1", "2", "3")
_DRIVE_PATTERN = re.compile(r"[A-Za-z0-9]+")
_TRACK_PATTERN = re.compile(r"^\s*T(\d+)\.(\d+):")
_GEOMETRY_PATTERN = re.compile(r"(?:Writing|Reading) c=(\d+)-(\d+):h=(\d+)-(\d+)", re.I)


def image_format(path_or_name: str | Path) -> ImageFormat:
    suffix = Path(path_or_name).suffix.casefold()
    if suffix in REFUSED_FORMATS:
        raise GreaseweazleError(REFUSED_FORMATS[suffix])
    try:
        return IMAGE_FORMATS[suffix]
    except KeyError as exc:
        supported = ", ".join(sorted(IMAGE_FORMATS))
        raise GreaseweazleError(
            f"Greaseweazle writing supports {supported}; {suffix or 'this file'} is not a floppy image."
        ) from exc


def gw_format(tracks: int, sides: int, sectors: int) -> str:
    """The gw ``--format`` name for a layout, or a refusal naming the gap."""
    name = GW_FORMATS.get((int(tracks), int(sides), int(sectors)))
    if name is None:
        raise GreaseweazleError(
            f"Greaseweazle has no disk definition for {tracks} tracks, {sides} side(s), "
            f"{sectors} sectors per track. Its Atari ST definitions cover eighty tracks at "
            "9, 10 or 11 sectors; capture or write other layouts as HFE or SCP flux."
        )
    return name


def _validated_format(value: str | None) -> str | None:
    if value is None:
        return None
    name = str(value).strip()
    if name not in set(GW_FORMATS.values()) and not _FORMAT_NAME.fullmatch(name):
        raise GreaseweazleError(f"“{value}” is not a Greaseweazle disk format name.")
    return name


@contextmanager
def stable_snapshot(source: str | Path, directory: str | Path | None = None) -> Iterator[Path]:
    """Copy a stable image snapshot so later edits cannot alter a live write."""
    source_path = Path(source)
    if not source_path.is_file():
        raise GreaseweazleError(f"The image to write no longer exists: {source_path}")
    before = source_path.stat()
    temporary = tempfile.NamedTemporaryFile(
        prefix="atari-floppy-",
        suffix=source_path.suffix.lower(),
        dir=directory,
        delete=False,
    )
    snapshot = Path(temporary.name)
    try:
        with temporary, source_path.open("rb") as stream:
            shutil.copyfileobj(stream, temporary, length=1024 * 1024)
        after = source_path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise GreaseweazleError(
                "The working image changed while its physical-write snapshot was being made. Retry after the current edit finishes."
            )
        yield snapshot
    finally:
        snapshot.unlink(missing_ok=True)


class GreaseweazleClient:
    """Discover and run the official ``gw`` command without invoking a shell."""

    def __init__(self, command: str | None = None, timeout: float = 1800) -> None:
        self.command = command or shutil.which("gw")
        self.timeout = float(timeout)

    @staticmethod
    def _environment() -> dict[str, str]:
        return {
            "HOME": os.environ.get("HOME", "/tmp"),
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        }

    def probe(self) -> ProbeResult:
        if not self.command:
            return ProbeResult(
                False,
                None,
                "The gw command is not installed. Install the official Greaseweazle tools and reconnect the device.",
            )
        try:
            result = subprocess.run(
                [self.command, "info"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=10,
                env=self._environment(),
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return ProbeResult(False, self.command, f"Could not query Greaseweazle: {exc}")
        detail = (result.stdout or "").strip()
        if result.returncode:
            return ProbeResult(
                False,
                self.command,
                detail or "Greaseweazle did not find an accessible device. Check USB access and udev rules.",
            )
        return ProbeResult(True, self.command, detail or "Greaseweazle device detected.")

    @staticmethod
    def _drive(value: str) -> str:
        drive = str(value or "").strip().upper()
        if drive not in DRIVE_CHOICES or not _DRIVE_PATTERN.fullmatch(drive):
            raise GreaseweazleError("Choose Greaseweazle drive A, B, 0, 1, 2 or 3.")
        return drive

    def _stream(
        self,
        command: list[str],
        report,
        *,
        activity: str,
        limit_message: str,
    ) -> tuple[int, list[str], set[tuple[int, int]], int | None]:
        """Run one gw command, following its per-track progress as it goes.

        Reading and writing differ only in the command and how the result is
        judged, so the process handling, cancellation boundary, timeout and
        track accounting live here once.
        """
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._environment(),
            )
        except OSError as exc:
            raise GreaseweazleError(f"Could not start Greaseweazle: {exc}") from exc

        lines: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            assert process.stdout is not None
            try:
                for line in process.stdout:
                    lines.put(line.rstrip())
            finally:
                lines.put(None)

        reader = threading.Thread(target=read_output, name="greaseweazle-output", daemon=True)
        reader.start()
        deadline = time.monotonic() + self.timeout
        output: list[str] = []
        tracks: set[tuple[int, int]] = set()
        total: int | None = None
        try:
            finished_output = False
            while not finished_output:
                if time.monotonic() >= deadline:
                    raise GreaseweazleError(limit_message)
                try:
                    line = lines.get(timeout=0.25)
                except queue.Empty:
                    # Calling progress is also the cooperative cancellation boundary.
                    report(activity, len(tracks), total)
                    continue
                if line is None:
                    finished_output = True
                    continue
                if line:
                    output.append(line)
                geometry = _GEOMETRY_PATTERN.search(line)
                if geometry:
                    first_cylinder, last_cylinder, first_head, last_head = map(int, geometry.groups())
                    total = (last_cylinder - first_cylinder + 1) * (last_head - first_head + 1)
                track = _TRACK_PATTERN.match(line)
                if track:
                    tracks.add((int(track.group(1)), int(track.group(2))))
                report(line or activity, len(tracks), total)
            return_code = process.wait(timeout=5)
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            raise
        finally:
            if process.stdout is not None:
                process.stdout.close()
            reader.join(timeout=1)
        return return_code, output, tracks, total

    def _ready_command(self) -> str:
        probe = self.probe()
        if not probe.available or not probe.command:
            raise GreaseweazleError(probe.detail)
        return probe.command

    def read(
        self,
        destination: str | Path,
        drive: str,
        progress: Callable[[str, int | None, int | None], None] | None = None,
        *,
        revolutions: int | None = None,
        disk_format: str | None = None,
    ) -> ReadResult:
        """Capture a physical disk into an image file.

        The destination suffix selects what gw produces, so an ``.scp`` target
        captures flux and a sector suffix such as ``.st`` or ``.msa`` decodes
        as it reads. A sector target needs ``disk_format``, one of gw's own
        names such as ``atarist.720``; ``gw_format`` supplies it from a
        layout. The file is only returned once gw has exited cleanly and left
        a non-empty image behind.
        """
        path = Path(destination)
        image_type = image_format(path)
        selected_drive = self._drive(drive)
        format_name = _validated_format(disk_format)
        if image_type.format_on_read and format_name is None:
            raise GreaseweazleError(
                f"Reading a disk into {image_type.suffix} needs its geometry: Greaseweazle "
                "cannot decode sectors without a disk format. Choose one, or capture flux as SCP or HFE."
            )
        command = self._ready_command()
        report = progress or (lambda _message, _current=None, _total=None: None)
        arguments = [command, "read", f"--drive={selected_drive}"]
        if format_name is not None:
            arguments.append(f"--format={format_name}")
        if revolutions is not None:
            if not 1 <= int(revolutions) <= 10:
                raise GreaseweazleError("Choose between 1 and 10 revolutions per track.")
            arguments.append(f"--revs={int(revolutions)}")
        arguments.append(str(path))
        report(f"Starting physical read on drive {selected_drive}", 0, None)
        return_code, output, tracks, total = self._stream(
            arguments,
            report,
            activity="Reading physical floppy",
            limit_message=(
                "Greaseweazle exceeded the 30 minute read limit. The capture was abandoned."
            ),
        )
        if return_code:
            tail = "\n".join(output[-12:])
            path.unlink(missing_ok=True)
            raise GreaseweazleError(
                "Greaseweazle could not read the physical disk."
                + (f"\n\n{tail}" if tail else "")
            )
        if not path.is_file() or not path.stat().st_size:
            raise GreaseweazleError(
                "Greaseweazle finished without producing an image. Check that a disk is inserted "
                "and that the drive is selected correctly."
            )
        size = path.stat().st_size
        report(
            f"Physical disk captured as {image_type.label}",
            total or len(tracks),
            total or len(tracks),
        )
        return ReadResult(
            drive=selected_drive,
            image=path.name,
            tracks_read=len(tracks),
            size=size,
            output_tail=tuple(output[-12:]),
        )

    def write(
        self,
        image: str | Path,
        drive: str,
        progress: Callable[[str, int | None, int | None], None] | None = None,
        *,
        disk_format: str | None = None,
    ) -> WriteResult:
        """Write an image to a physical disk.

        A ``.st`` needs ``disk_format`` because gw cannot tell its shape from
        the file; an ``.msa`` carries its own and a flux container needs none.
        """
        path = Path(image)
        image_type = image_format(path)
        selected_drive = self._drive(drive)
        format_name = _validated_format(disk_format)
        if image_type.format_on_write and format_name is None:
            raise GreaseweazleError(
                f"Writing a {image_type.suffix} needs its geometry: Greaseweazle cannot tell "
                "the shape of a plain sector image. Choose the disk format before writing."
            )
        command = self._ready_command()
        report = progress or (lambda _message, _current=None, _total=None: None)
        arguments = [command, "write", f"--drive={selected_drive}"]
        if format_name is not None:
            arguments.append(f"--format={format_name}")
        arguments.append(str(path))
        report(f"Starting physical write on drive {selected_drive}", 0, None)
        return_code, output, tracks, total = self._stream(
            arguments,
            report,
            activity="Writing physical floppy",
            limit_message=(
                "Greaseweazle exceeded the 30 minute write limit. "
                "The physical disk may be incomplete."
            ),
        )
        transcript = "\n".join(output)
        folded_transcript = transcript.casefold()
        if return_code:
            tail = "\n".join(output[-12:])
            raise GreaseweazleError(
                "Greaseweazle could not complete the physical write. The disk may be incomplete."
                + (f"\n\n{tail}" if tail else "")
            )
        if "verify failure" in folded_transcript:
            raise GreaseweazleError(
                "Greaseweazle wrote the disk but verification failed. Do not rely on this physical copy."
            )
        verified = "all tracks verified" in folded_transcript
        if image_type.automatic_verification and not verified:
            raise GreaseweazleError(
                "Greaseweazle finished without confirming that all tracks verified. Treat the physical disk as unverified."
            )
        report(
            "Physical disk written and verified" if verified else "Physical disk written; flux verification is not available",
            total or len(tracks),
            total or len(tracks),
        )
        return WriteResult(
            drive=selected_drive,
            image=path.name,
            verified=verified,
            verification_supported=image_type.automatic_verification,
            tracks_written=len(tracks),
            output_tail=tuple(output[-12:]),
        )
