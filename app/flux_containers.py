"""Shared policy for the flux containers HxCFE can decode and re-encode.

HFE and SCP are different files but the same workflow: decode the flux to raw
sectors, identify the GEMDOS filesystem inside, prove the sectors re-encode and
decode back byte-for-byte before permitting any edit, and prove it again before
handing the user a saved image.

That policy lived twice in ``disk_service``, once per container, and the two
copies had already drifted: only the HFE save path restored an omitted tail
sector, so saving an edited SCP failed its own verification. Expressing the
rules once here means a container cannot quietly miss a fix made for its
sibling, and lets the geometry rules be unit tested without an HxCFE binary.

The geometries themselves are not defined here. ``floppy_geometry`` is the one
table of shapes an ST reads, and this module only says which of them HxCFE
can wrap as flux and what to do when a decode comes back a sector short.

Nothing in this module runs a subprocess itself. ``FluxEngine`` is handed the
caller's ``run_hxcfe`` so the disk service keeps ownership of process
execution, error translation and timeouts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import DiskError
from .floppy_geometry import (
    GEOMETRIES,
    SECTOR_SIZE,
    canonical_sizes,
    geometries_for_size,
)


#: Every sector-image size the geometry table produces.
FLOPPY_SIZES = canonical_sizes()

#: The sizes that may be padded by one trailing sector, keyed by the kind of
#: filesystem the decode identified. GEMDOS is the only browseable kind on a
#: floppy, so there is one entry; the mapping shape is kept so the tail-sector
#: repair stays keyed by what was found rather than assuming it.
CANONICAL_SIZES: dict[str, frozenset[int]] = {
    "gemdos": FLOPPY_SIZES,
}

#: Filesystems the workbench can browse inside a flux container.
BROWSEABLE_KINDS = frozenset({"gemdos"})

#: The suffix HxCFE's own ST loader is selected by. A decoded sector image is
#: written under this name so the encode side of the round trip is read by
#: the loader that understands the boot sector, not by the generic raw loader.
SECTOR_IMAGE_SUFFIX = ".st"

#: The suffix for anything larger than a floppy.
HARD_DISK_SUFFIX = ".img"

# HxCFE's raw sector reader, used to decode every container back to sectors.
RAW_DECODER = "RAW_LOADER"

# ---------------------------------------------------------------------------
# Layout policy: no ``-uselayout``
# ---------------------------------------------------------------------------
# HxCFE chooses a loader by file extension, and its ``ATARI ST ST Loader``
# settles the geometry of a ``.st`` image on its own, in three steps: it
# reads the BIOS parameter block from the boot sector (sectors per track at
# 0x18, sides at 0x1A, total sectors at 0x13) and believes it when the
# sector count is plausible; failing that it matches the file size against
# its own table of ST sizes; failing that it tries every combination of one
# or two sides, up to 84 tracks and 8 to 11 sectors until one fits. It then
# picks ATARIST_DD_FLOPPYMODE, or the HD mode above fourteen sectors.
#
# Every sector image the workbench hands it carries a valid boot sector, so
# the first step always applies and the shape HxCFE wraps is the shape the
# boot sector names. Passing ``-uselayout`` would override that with a layout
# name that has to be kept in step with the geometry table by hand, and a
# name HxCFE does not know makes it refuse the input outright. The encode
# therefore passes no layout, and instead insists that the sector file is a
# ``.st`` so the right loader is the one that sees it.
#
# The 40-track PC geometries are not listed on their own. The 180 KiB one
# has no ST counterpart for HxCFE to read back, and the 360 KiB one shares
# its size with the single-sided 80-track ST disk, which is the shape HxCFE
# chooses for that size when the boot sector does not say otherwise.


@dataclass(frozen=True)
class FluxContainer:
    """One HxCFE-supported flux container and the words used to describe it."""

    identifier: str
    extension: str
    label: str
    plugin: str
    noun: str
    signature: bytes | None = None

    @property
    def display(self) -> str:
        return self.identifier.upper()


HFE = FluxContainer(
    identifier="hfe",
    extension=".hfe",
    label="HxC HFE flux image (.hfe)",
    plugin="HXC_HFE",
    noun="HFE image",
)

SCP = FluxContainer(
    identifier="scp",
    extension=".scp",
    label="SuperCard Pro flux image (.scp)",
    plugin="SCP_FLUX_STREAM",
    noun="SCP flux capture",
    signature=b"SCP",
)

FLUX_CONTAINERS: dict[str, FluxContainer] = {
    container.identifier: container for container in (HFE, SCP)
}


def sector_image_suffix(kind: str, size: int, sides: int | None = None) -> str:
    """Return the canonical sector-image extension for a decoded geometry.

    Every floppy an ST reads is written as ``.st`` whichever side count or
    sector count it has; ``.msa`` and ``.dim`` are containers chosen at
    export, not geometries. Anything larger than a floppy is a hard-disk
    image and takes ``.img``.

    ``sides`` narrows the geometry check to the side count the container
    reported. When no geometry of that side count fits but one of the other
    does, the image is still a floppy and still ``.st``: the container's
    side count is a claim to warn about, not a reason to call a floppy a
    hard disk.
    """
    del kind
    if geometries_for_size(size, sides) or geometries_for_size(size):
        return SECTOR_IMAGE_SUFFIX
    return HARD_DISK_SUFFIX


#: The floppy geometries HxCFE's ST loader reads back, and so can be wrapped
#: as flux and verified: the ST family and the high-density disk.
FLUX_ENCODABLE_SIZES = frozenset(
    item.size for item in GEOMETRIES.values() if not item.identifier.startswith("pc-")
)


def is_flux_encodable(kind: str, size: int) -> bool:
    """Whether these sectors can be wrapped as flux by HxCFE.

    Only a GEMDOS floppy of a shape the ST loader reads qualifies. A hard
    disk image has no flux equivalent, and the 40-track PC geometries share
    their size with an ST shape HxCFE would choose instead.
    """
    return kind in BROWSEABLE_KINDS and size in FLUX_ENCODABLE_SIZES


def restore_omitted_tail_sector(
    path: Path,
    kind: str,
    expected_size: int | None = None,
) -> bool:
    """Restore one omitted trailing sector from an otherwise complete decode.

    HxCFE's raw writer can omit an unreadable final 512-byte sector while still
    reporting every sector on the final track. A 720 KiB decode then arrives
    as 736,768 bytes instead of 737,280 and geometry detection can select a
    linear hard-disk view instead of a floppy.

    Padding is only ever safe at the physical end of a known geometry, so this
    refuses to act unless the file is exactly one sector short of a canonical
    size for ``kind`` and is not itself a canonical size. It never fills a gap
    in the middle of an image, and never grows a file by more than a single
    sector.

    Returns True when a sector was appended.
    """
    if not path.is_file():
        return False
    canonical = CANONICAL_SIZES.get(kind, frozenset())
    if not canonical:
        return False
    size = path.stat().st_size
    if size in canonical:
        return False
    target = expected_size if expected_size in canonical else None
    if target is None:
        target = size + SECTOR_SIZE if size + SECTOR_SIZE in canonical else None
    if target is None or size + SECTOR_SIZE != target:
        return False
    with path.open("ab") as image:
        image.write(bytes(SECTOR_SIZE))
    return True


class FluxEngine:
    """The four HxCFE conversions the workbench needs, in one vocabulary.

    The engine is constructed with the caller's ``run_hxcfe`` callable, which
    takes a list of HxCFE arguments and returns its combined output. Errors are
    raised by that callable as ``DiskError``.
    """

    def __init__(self, run_hxcfe: Callable[[list[str]], str]) -> None:
        self._run_hxcfe = run_hxcfe

    def decode_to_sectors(self, source: Path, output: Path) -> str:
        """Decode any flux container to a raw sector image."""
        return self._run_hxcfe([
            f"-finput:{source}",
            f"-conv:{RAW_DECODER}",
            f"-foutput:{output}",
        ])

    def container_info(self, source: Path) -> str:
        """Return HxCFE's descriptive report for a container."""
        return self._run_hxcfe([f"-finput:{source}", "-infos"])

    def encode_from_sectors(
        self,
        sectors: Path,
        container: FluxContainer,
        output: Path,
        *,
        kind: str,
        reference: Path | None = None,
    ) -> str:
        """Wrap a raw sector image as flux, reusing an original's timing.

        ``reference`` is the container the sectors were decoded from. HxCFE
        uses it to preserve track timing that the sector view cannot express,
        so an edited image stays as close to the capture as possible.

        The sector file must be a ``.st``: that is how HxCFE picks the loader
        that reads the boot sector geometry, so no layout is passed.
        """
        if not is_flux_encodable(kind, sectors.stat().st_size):
            raise DiskError(
                "This geometry has no flux equivalent HxCFE can write."
            )
        if sectors.suffix.casefold() != SECTOR_IMAGE_SUFFIX:
            raise DiskError(
                f"HxCFE selects its ST loader by the {SECTOR_IMAGE_SUFFIX} suffix; "
                f"{sectors.name} would be read as a generic raw image."
            )
        # No -uselayout: HxCFE's ST loader reads the boot sector and chooses
        # the matching floppy interface mode; see the policy note above.
        return self._run_hxcfe([
            f"-finput:{sectors}",
            f"-conv:{container.plugin}",
            f"-foutput:{output}",
            *([f"-reffile:{reference}"] if reference else []),
        ])

    def decodes_back_to(self, container_file: Path, sectors: Path, kind: str) -> bool:
        """Whether a container decodes back to exactly these sectors.

        The decode is normalised for a single omitted tail sector first, using
        the source image's size as the expected geometry, so a container is not
        rejected for the one artefact the workbench knows how to repair.
        """
        check = container_file.parent / f"{container_file.stem}-verify.img"
        check.unlink(missing_ok=True)
        try:
            self.decode_to_sectors(container_file, check)
            restore_omitted_tail_sector(
                check,
                kind,
                expected_size=sectors.stat().st_size,
            )
            return check.is_file() and check.read_bytes() == sectors.read_bytes()
        except DiskError:
            return False
        finally:
            check.unlink(missing_ok=True)

    def encode_and_verify(
        self,
        sectors: Path,
        container: FluxContainer,
        output: Path,
        *,
        kind: str,
        reference: Path | None = None,
        failure_message: str,
    ) -> Path:
        """Encode sectors as flux and refuse to return an inexact container.

        A flux image the workbench cannot decode back to the bytes it started
        from is never handed to the user: it would look like a saved disk while
        silently differing from what they edited.
        """
        output.unlink(missing_ok=True)
        self.encode_from_sectors(
            sectors,
            container,
            output,
            kind=kind,
            reference=reference,
        )
        if not output.is_file() or not output.stat().st_size:
            raise DiskError(
                f"HxCFE did not produce a usable {container.display} image."
            )
        if not self.decodes_back_to(output, sectors, kind):
            output.unlink(missing_ok=True)
            raise DiskError(failure_message)
        return output


__all__ = [
    "BROWSEABLE_KINDS",
    "CANONICAL_SIZES",
    "FLOPPY_SIZES",
    "FLUX_CONTAINERS",
    "FLUX_ENCODABLE_SIZES",
    "HARD_DISK_SUFFIX",
    "HFE",
    "RAW_DECODER",
    "SCP",
    "SECTOR_IMAGE_SUFFIX",
    "SECTOR_SIZE",
    "FluxContainer",
    "FluxEngine",
    "is_flux_encodable",
    "restore_omitted_tail_sector",
    "sector_image_suffix",
]
