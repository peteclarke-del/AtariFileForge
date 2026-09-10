"""Build validated, non-mutating hardware deployment packages.

A deployment package is a reviewed directory tree, never a write to a device.
The image is copied into a private snapshot, finalised and hashed there, and
the live session is left exactly as the operator left it. What comes out is a
ZIP holding the files the target expects, a manifest of every path with its
SHA-256, the compatibility report and the exact steps to install it.

The targets are the five ways an Atari image reaches real hardware: a
FlashFloppy USB stick, an SD card in an ACSI device, a CompactFlash or IDE
drive, a host folder Hatari presents as a GEMDOS drive, and a genuine ACSI
enclosure.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from copy import copy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from atarinut.filesystem.gemdos import tos_limit_notes

from . import atari_paths
from . import progress as progress_module
from .analysis_service import preflight_report
from .checksum import sha256_bytes, sha256_path
from .emulator_config import profile_machine
from .errors import DiskError
from .hardware_profiles import profile_addons
from .version import application_version


DEPLOYMENT_FORMAT = "atari-file-forge-hardware-deployment"
DEPLOYMENT_VERSION = 1
FAT32_FILE_LIMIT = 4 * 1024 * 1024 * 1024 - 1

#: The most a whole GEMDOS drive folder is copied out of an image, so a
#: mistaken target on a large partition fails early rather than after an hour.
GEMDOS_FOLDER_LIMIT = 512 * 1024 * 1024

MEBIBYTE = 1024 * 1024

#: The largest partition each TOS release will mount. EmuTOS is absent because
#: it is not bound by the classic ROM limits.
FIRMWARE_PARTITION_LIMITS = {
    "tos-100": 16 * MEBIBYTE,
    "tos-102": 256 * MEBIBYTE,
    "tos-104": 256 * MEBIBYTE,
    "tos-106": 256 * MEBIBYTE,
    "tos-162": 256 * MEBIBYTE,
    "tos-205": 256 * MEBIBYTE,
    "tos-206": 512 * MEBIBYTE,
    "tos-306": 512 * MEBIBYTE,
    "tos-4xx": 512 * MEBIBYTE,
}

#: The mass-storage options each target needs the profile to declare.
TARGET_INTERFACES = {
    "gotek": ("gotek",),
    "sd-card": ("acsi2stm", "ultrasatan", "cosmosex"),
    "cf-card": ("ide-internal", "ide-adapter", "cf-adapter"),
    "acsi-drive": ("acsi-megafile", "acsi-third-party"),
}

#: Targets whose device reads the bytes in ACSI order, and in IDE word order.
ACSI_TARGETS = frozenset({"sd-card", "acsi-drive"})
IDE_TARGETS = frozenset({"cf-card"})

#: Sector-image containers a FlashFloppy Gotek reads directly.
GOTEK_CONTAINERS = frozenset({".st", ".msa", ".hfe"})


TARGETS = (
    {
        "id": "gotek",
        "label": "Gotek with FlashFloppy",
        "description": "A USB stick of .st or .hfe floppy images, in native or indexed layout.",
    },
    {
        "id": "sd-card",
        "label": "SD card for an ACSI device",
        "description": "A raw drive image for UltraSatan, ACSI2STM or CosmosEx.",
    },
    {
        "id": "cf-card",
        "label": "CompactFlash or IDE drive",
        "description": "A raw drive image for an IDE adapter or the Falcon internal IDE.",
    },
    {
        "id": "gemdos-folder",
        "label": "GEMDOS drive folder",
        "description": "A host directory tree Hatari presents to the machine as a drive.",
    },
    {
        "id": "acsi-drive",
        "label": "ACSI hard drive",
        "description": "A drive image and the steps to write it to a Megafile or third-party enclosure.",
    },
)


@dataclass(frozen=True)
class DeploymentEntry:
    path: str
    role: str
    source: Path | None = None
    data: bytes | None = None

    @property
    def size(self) -> int:
        return len(self.data) if self.data is not None else int(self.source.stat().st_size)

    def digest(self, progress: Callable[[int, int], None] | None = None) -> str:
        if self.data is not None:
            return sha256_bytes(self.data)
        return sha256_path(self.source, progress)


def _safe_leaf(value: str, fallback: str = "DISK") -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(value or "")).strip(" ._")
    return stem or fallback


#: Everything but a letter, a digit and the punctuation GEMDOS allows in a name.
_NOT_IN_A_GEMDOS_NAME = re.compile(r"[^A-Za-z0-9_$#&@!%()~^{}\'`-]+")


def _gemdos_leaf(value: str, fallback: str = "FILE") -> str:
    """Upper-case a GEMDOS name and keep it inside 8.3, as TOS stores it.

    The full stop is split off before the rest is cleaned, because it
    separates the name from its extension rather than being part of either.
    """
    text = str(value or "").strip()
    base, dot, extension = text.rpartition(".")
    if not dot:
        base, extension = text, ""

    def clean(part: str) -> str:
        return _NOT_IN_A_GEMDOS_NAME.sub("_", part).strip("_")

    base = (clean(base) or fallback)[:8].upper()
    extension = clean(extension)[:3].upper()
    return f"{base}.{extension}" if extension else base


def _entry(path: str, role: str, *, source: Path | None = None, data: bytes | str | None = None) -> DeploymentEntry:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise DiskError(f"The deployment path is unsafe: {path}")
    encoded = data.encode("utf-8") if isinstance(data, str) else data
    if (source is None) == (encoded is None):
        raise DiskError("A deployment entry must have exactly one source.")
    return DeploymentEntry(str(pure), role, source=source, data=encoded)


def is_hard_drive_image(service, session) -> bool:
    """Whether this image is a hard drive, with or without a partition table.

    A drive image that carries a partition table opens as ``kind == "hd"``. A
    bare volume of hard-drive size opens as the single GEMDOS volume it holds.
    Both are written to a card the same way, so both are offered here.
    """
    if session.kind == "hd":
        return True
    return bool(service.summary(session).get("hardDisk"))


def is_floppy_image(service, session) -> bool:
    """Whether this image is a floppy a Gotek could present to the machine."""
    if session.kind in {"msa", "dim", "hfe"}:
        return True
    return session.kind == "gemdos" and not bool(service.summary(session).get("hardDisk"))


def available_deployment_targets(service, session) -> list[dict]:
    hard_drive = is_hard_drive_image(service, session)
    floppy = is_floppy_image(service, session)
    mounted_volume = session.kind == "gemdos" or (
        session.kind == "hd" and getattr(session, "partition", None) is not None
    )
    support = {
        "gotek": floppy,
        "sd-card": hard_drive,
        "cf-card": hard_drive,
        "gemdos-folder": mounted_volume,
        "acsi-drive": hard_drive,
    }
    reasons = {
        "gotek": (
            "A Gotek presents floppy images. Open an .st, .msa, .dim or .hfe "
            "floppy; a flux recording and a hard drive are not floppy images "
            "FlashFloppy can present."
        ),
        "sd-card": "An SD-card package needs a hard-drive image.",
        "cf-card": "A CompactFlash package needs a hard-drive image.",
        "gemdos-folder": (
            "A GEMDOS drive folder is copied from a mounted volume. Open a "
            "floppy or select a partition of the drive first."
        ),
        "acsi-drive": "An ACSI enclosure package needs a hard-drive image.",
    }
    return [
        {**target, "available": support[target["id"]], "reason": "" if support[target["id"]] else reasons[target["id"]]}
        for target in TARGETS
    ]


def _copy_sparse(
    source: Path,
    destination: Path,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Copy an image without materialising its zero-filled extents."""
    block_size = 4 * 1024 * 1024
    size = source.stat().st_size
    copied = 0
    with source.open("rb") as reader, destination.open("wb") as writer:
        while chunk := reader.read(block_size):
            if chunk.strip(b"\0"):
                writer.write(chunk)
            else:
                writer.seek(len(chunk), os.SEEK_CUR)
            copied += len(chunk)
            if progress:
                progress(copied, size)
        writer.truncate(size)
    shutil.copystat(source, destination)


@contextmanager
def prepared_snapshot(service, session, progress: Callable | None = None):
    """Yield a hardware-finalised session copy and leave the live session untouched."""
    with tempfile.TemporaryDirectory(dir=service.work_dir, prefix="deployment-snapshot-") as folder:
        root = Path(folder)
        configured = copy(session)
        configured.path = root / session.path.name
        _copy_sparse(
            session.path,
            configured.path,
            (lambda current, total: progress("Copying an isolated image snapshot", current, total))
            if progress else None,
        )
        if session.descriptor_path:
            configured.descriptor_path = root / session.descriptor_path.name
            shutil.copy2(session.descriptor_path, configured.descriptor_path)
        configured.lock = threading.RLock()
        configured.finalised_mtime_ns = None
        service.prepare_download(configured, progress)
        yield configured


# ---------------------------------------------------------------------------
# Target layouts
# ---------------------------------------------------------------------------
def _flashfloppy_config(mode: str) -> str:
    """The FF.CFG a FlashFloppy Gotek reads from the root of its USB stick.

    ``interface = shugart`` is the ST's floppy bus, and ``host = atari`` tells
    FlashFloppy to present 720 KiB double-sided media rather than the PC
    shapes it defaults to.
    """
    lines = [
        "# FF.CFG written by Atari File Forge",
        "interface = shugart",
        "host = atari",
        "display-type = auto",
        f"nav-mode = {mode}",
    ]
    if mode == "indexed":
        lines.append("indexed-prefix = DSKA")
    return "\n".join(lines) + "\n"


def _gotek_entries(service, session, options: dict) -> list[DeploymentEntry]:
    mode = str(options.get("gotekMode") or "native").strip().lower()
    if mode not in {"native", "indexed"}:
        raise DiskError("Choose Native or Indexed Gotek navigation.")
    try:
        start = int(options.get("startIndex") or 0)
    except (TypeError, ValueError) as exc:
        raise DiskError("The first Gotek index must be a number from 0 to 9999.") from exc
    if start < 0 or start > 9999:
        raise DiskError("The first Gotek index must be between 0 and 9999.")
    if session.kind == "hd":
        raise DiskError(
            "A Gotek package holds floppy images. Build a card package for a "
            "hard drive, or deploy its floppies individually."
        )
    source = service.prepare_download(session)
    suffix = Path(source.name).suffix.lower() or ".st"
    if suffix not in GOTEK_CONTAINERS:
        raise DiskError(
            f"FlashFloppy reads .st, .msa and .hfe images; {suffix} is not one of them."
        )
    if start >= 10_000:
        raise DiskError("The selected Gotek index range exceeds DSKA9999.")
    leaf = (
        f"DSKA{start:04d}{suffix}"
        if mode == "indexed"
        else _safe_leaf(source.name)
    )
    return [
        _entry(f"GOTEK-USB/{leaf}", "floppy image", source=source),
        _entry("GOTEK-USB/FF.CFG", "FlashFloppy configuration", data=_flashfloppy_config(mode)),
    ]


def _raw_image_entries(service, session, target: str) -> list[DeploymentEntry]:
    """The whole drive image, as one file to be written to a card."""
    source = service.prepare_download(session)
    folder = {"sd-card": "SD-CARD", "cf-card": "CF-CARD", "acsi-drive": "ACSI-DRIVE"}[target]
    leaf = f"{Path(_safe_leaf(session.name, 'DRIVE')).stem}.img"
    return [_entry(f"{folder}/{leaf}", "whole drive image", source=source)]


def _gemdos_folder_entries(service, session) -> list[DeploymentEntry]:
    """Copy the mounted volume out as a host directory tree.

    Hatari's ``--harddrive`` takes a host folder and presents it to the machine
    as a GEMDOS drive, so the names in it have to be names TOS can see: upper
    case, eight characters and a three-character extension. ``AUTO`` keeps its
    name because TOS runs what is inside it at boot.
    """
    scratch = session.path.parent / "gemdos-folder"
    scratch.mkdir(parents=True, exist_ok=True)
    entries: list[DeploymentEntry] = []
    total = 0
    pending: list[tuple[str, str]] = [("", "")]
    visited: set[str] = set()
    while pending:
        inner, outer = pending.pop(0)
        if inner.casefold() in visited:
            continue
        visited.add(inner.casefold())
        listing = service.list_directory(session, inner)
        for row in listing["entries"]:
            name = str(row.get("name") or "UNTITLED").replace("\\", atari_paths.SEPARATOR)
            child_inner = atari_paths.join(inner, name)
            child_outer = f"{outer}/{_gemdos_leaf(name)}" if outer else _gemdos_leaf(name)
            if str(row.get("type") or "") in {"dir", "directory"}:
                pending.append((child_inner, child_outer))
                continue
            total += int(row.get("length") or 0)
            if total > GEMDOS_FOLDER_LIMIT:
                raise DiskError(
                    "This volume holds more than "
                    f"{GEMDOS_FOLDER_LIMIT // MEBIBYTE} MiB, which is more than a "
                    "GEMDOS drive folder package copies out. Use a card target instead."
                )
            exported = service.export_file(session, child_inner, None)
            destination = scratch / child_outer
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(exported), destination)
            entries.append(_entry(
                f"GEMDOS-DRIVE/{child_outer}", "GEMDOS drive file", source=destination
            ))
    entries.append(_entry(
        "hatari.cfg",
        "Hatari configuration fragment",
        data=(
            "; Add these lines to hatari.cfg, or pass the folder on the command\n"
            "; line as --harddrive /path/to/GEMDOS-DRIVE\n"
            "[HardDisk]\n"
            "bUseHardDiskDirectory = TRUE\n"
            "szHardDiskDirectory = /path/to/GEMDOS-DRIVE\n"
            "nGemdosDrive = 2\n"
            "nWriteProtection = 1\n"
        ),
    ))
    return entries


def _media_entries(service, session, target: str, options: dict) -> list[DeploymentEntry]:
    if target == "gotek":
        return _gotek_entries(service, session, options)
    if target in {"sd-card", "cf-card", "acsi-drive"}:
        return _raw_image_entries(service, session, target)
    if target == "gemdos-folder":
        return _gemdos_folder_entries(service, session)
    raise DiskError("The open image is not compatible with that deployment target.")


# ---------------------------------------------------------------------------
# Profile validation
# ---------------------------------------------------------------------------
def _selected_firmware(addons: set[str]) -> str:
    for identifier in addons:
        if identifier.startswith("tos-"):
            return identifier
    return ""


def _profile_findings(
    session,
    target: str,
    *,
    has_partition_table: bool = True,
    partitions: list[dict] | None = None,
    byte_swapped: bool = False,
) -> list[dict]:
    profile = session.hardware_profile or {}
    addons = profile_addons(session)
    machine = profile_machine(session)
    findings: list[dict] = []

    def warn(message: str) -> None:
        findings.append({"severity": "warning", "message": message})

    if not profile:
        warn("No hardware profile is applied; machine-specific checks are limited.")
    required = TARGET_INTERFACES.get(target, ())
    if profile and required and not addons.intersection(required):
        labels = ", ".join(required)
        warn(
            f"The applied profile declares none of {labels}, so the machine has "
            "nothing to read this package with."
        )
    firmware = _selected_firmware(addons)
    limit = FIRMWARE_PARTITION_LIMITS.get(firmware)
    for index, partition in enumerate(partitions or []):
        size = int(partition.get("sizeBytes") or 0)
        device = str(partition.get("device") or partition.get("name") or f"{chr(ord('C') + index)}:")
        if limit and size > limit:
            warn(
                f"{device} is {size // MEBIBYTE} MiB, which is more than the "
                f"{limit // MEBIBYTE} MiB {firmware} will mount. Fit a later TOS, "
                "or repartition the drive."
            )
        for note in tos_limit_notes(size):
            warn(f"{device}: {note}")
    if session.kind == "hd" and target in ACSI_TARGETS and byte_swapped:
        warn(
            "The drive image is byte-swapped, which is IDE word order. An ACSI "
            "device reads the bytes as they stand, so un-swap the image before "
            "writing it to this card."
        )
    if session.kind == "hd" and target in IDE_TARGETS and not byte_swapped:
        warn(
            "The drive image is not byte-swapped. Most ST and STE IDE adapters "
            "wire the data bus swapped, so a plain image reads as noise on them. "
            f"Check whether the {machine} adapter expects swapped data, and note "
            "that Hatari reproduces the swapped case with --ide-swap."
        )
    if target in {"sd-card", "cf-card", "acsi-drive"} and not has_partition_table:
        # A bare volume is still a usable card, but nothing inside it says how
        # the drive is divided up. Saying so is more use than refusing to build.
        warn(
            "This image carries no partition table, so it holds one bare volume. "
            "The driver on the receiving machine has to be told the drive's "
            "geometry, or be one that assumes it."
        )
    if target == "gemdos-folder" and "gemdos-hd-folder" not in addons and profile:
        warn(
            "The applied profile does not declare a GEMDOS hard-drive folder, so "
            "nothing in it says the machine boots from a host directory."
        )
    return findings


# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------
def _instructions(session, target: str, options: dict) -> list[str]:
    indexed = str(options.get("gotekMode") or "native").strip().lower() == "indexed"
    instructions = {
        "gotek": [
            "Format the USB device as FAT32 with a single partition, which is what FlashFloppy reads.",
            "Copy the contents of GOTEK-USB to the root of the USB device, keeping FF.CFG beside the images.",
            (
                "Indexed navigation was selected, so the image is named DSKA<number> "
                "and FlashFloppy selects it by that number."
                if indexed
                else "Native navigation was selected, so FlashFloppy lists the image "
                "under its own filename."
            ),
            "Check that the image geometry matches its BIOS parameter block: an ST reads what the boot sector declares, so a 720 KiB double-sided image must say nine sectors and two sides.",
            "Insert the USB device, select the image, list the disk from the desktop and verify a read before enabling writes.",
        ],
        "sd-card": [
            "Back up the existing card. Writing the image replaces every byte on it.",
            "Identify the card device, then write the image with dd, for example: sudo dd if=SD-CARD/<image>.img of=/dev/sdX bs=1M conv=fsync status=progress",
            "Set the ACSI id on the device: UltraSatan and ACSI2STM present their first card as id 0, which is the id TOS boots from.",
            "Install a driver on the machine unless EmuTOS is fitted: AHDI, HDDRIVER, PPDRIVER or the ICD driver all read an ACSI card.",
            "An ACSI2STM card larger than 1 GiB needs HDDRIVER or the ICD driver; the built-in and AHDI drivers will not address it.",
            "Boot the machine, list the root of each partition and test a read before writing to the card.",
        ],
        "cf-card": [
            "Back up the existing card. Writing the image replaces every byte on it.",
            "Write the image to the card, for example: sudo dd if=CF-CARD/<image>.img of=/dev/sdX bs=1M conv=fsync status=progress",
            "Check the byte order the adapter expects. The Falcon internal IDE and most ST and STE IDE adapters swap the data bus, so the image on the card is byte-swapped.",
            "Reproduce the same case in Hatari with --ide-swap before trusting the card on hardware.",
            "Install a driver unless EmuTOS is fitted: HDDRIVER and the ICD driver both handle IDE and CompactFlash.",
            "Boot the machine, list each partition and test a read before writing to the card.",
        ],
        "gemdos-folder": [
            "Extract GEMDOS-DRIVE to a directory on the host computer.",
            "Point Hatari at it with --harddrive /path/to/GEMDOS-DRIVE, or paste the fragment from hatari.cfg in this package into your own hatari.cfg.",
            "Keep the names as they are: TOS sees eight characters and a three-character extension, upper case, and a longer host name is not visible to the machine.",
            "The AUTO folder keeps its name, so Hatari runs its programs at boot exactly as a real drive would.",
            "The fragment sets the Hatari drive read-only. Leave it that way until the drive has been listed and read, then allow writes if the software needs to save.",
        ],
        "acsi-drive": [
            "Back up whatever the enclosure currently holds. The drive inside it is replaced wholesale.",
            "Write ACSI-DRIVE/<image>.img to the drive. A Megafile, SH204, SH205 or third-party enclosure has no removable card, so either connect its drive to the host computer directly, or write the image to a card in a CosmosEx or UltraSatan and copy it across on the machine.",
            "Set the ACSI id with the switch on the back of the enclosure. Id 0 is the drive TOS boots from.",
            "Install a driver on the machine: HDX ships with AHDI, HDDRIVER installs itself from the desktop, and the ICD tools drive most third-party host adapters.",
            "Respect the TOS partition limits recorded in this package: TOS 1.00 stops at 16 MiB, TOS 1.02 to 1.62 at 256 MiB, and TOS 2.06, 3.06 and 4.0x at 512 MiB.",
            "Boot from the drive, list each partition and test a read before writing to it.",
        ],
    }
    return instructions[target]


# ---------------------------------------------------------------------------
# Plan and package
# ---------------------------------------------------------------------------
def _partition_table(service, session) -> list[dict]:
    if session.kind != "hd":
        return []
    lister = getattr(service, "list_partitions", None)
    if not callable(lister):
        return []
    try:
        return list(lister(session) or [])
    except DiskError:
        return []


def _deployment_plan(service, session, payload: dict, progress: Callable | None = None) -> tuple[dict, list[DeploymentEntry]]:
    report = progress_module.reporter(progress)
    target = str(payload.get("target") or "").strip().lower()
    availability = {item["id"]: item for item in available_deployment_targets(service, session)}
    if target not in availability:
        raise DiskError("Choose a supported deployment target.")
    if not availability[target]["available"]:
        raise DiskError(availability[target]["reason"])
    report("Planning target paths and filenames", 0, 4)
    entries = _media_entries(service, session, target, payload)
    paths = [entry.path.casefold() for entry in entries]
    if len(paths) != len(set(paths)):
        raise DiskError("The deployment would create two files with the same target path.")
    report("Checking capacity and target profile", 1, 4)
    summary = service.summary(session)
    partitions = _partition_table(service, session)
    issues = _profile_findings(
        session,
        target,
        has_partition_table=bool(partitions),
        partitions=partitions,
        byte_swapped=bool(summary.get("byteSwapped")),
    )
    for entry in entries:
        if entry.size > FAT32_FILE_LIMIT:
            issues.append({
                "severity": "error",
                "message": (
                    f"{entry.path} is {entry.size:,} bytes, which exceeds the FAT32 "
                    "single-file limit. Neither a FlashFloppy stick nor a FAT card "
                    "can hold it."
                ),
            })
    report("Hashing deployment files", 2, 4)
    total_bytes = sum(entry.size for entry in entries)
    hashed = 0
    manifest_entries = []
    for entry in entries:
        digest = entry.digest(
            lambda current, _total, entry=entry, completed=hashed: report(
                f"Hashing {entry.path}", completed + current, total_bytes,
            )
        )
        manifest_entries.append({
            "path": entry.path,
            "role": entry.role,
            "size": entry.size,
            "sha256": digest,
        })
        hashed += entry.size
        report(f"Hashed {entry.path}", hashed, total_bytes)
    compatibility = preflight_report(service, session, {
        "operation": f"deploy-{target}",
        "sourceKind": session.kind,
        "targetKind": "gemdos-folder" if target == "gemdos-folder" else "host",
        "changes": [
            {
                "name": PurePosixPath(entry.path).name,
                "nameIsLeaf": True,
                "parent": str(PurePosixPath(entry.path).parent),
                "source": session.name,
                "type": entry.role,
            }
            for entry in entries
        ],
    })
    issues.extend(compatibility["issues"])
    plan = {
        "format": DEPLOYMENT_FORMAT,
        "version": DEPLOYMENT_VERSION,
        "applicationVersion": application_version(),
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": target,
        "targetLabel": availability[target]["label"],
        "source": {
            "image": session.name,
            "kind": session.kind,
            "revision": summary["revision"],
            "byteSwapped": bool(summary.get("byteSwapped")),
            "hardwareProfile": session.hardware_profile or {},
        },
        "entries": manifest_entries,
        "issues": issues,
        "canProceed": not any(item["severity"] == "error" for item in issues),
        "instructions": _instructions(session, target, payload),
        "compatibilityReport": compatibility,
    }
    report("Deployment plan validated", 4, 4)
    return plan, entries


def deployment_plan(service, session, payload: dict, progress: Callable | None = None) -> dict:
    """Build an exact plan from a disposable, hardware-finalised snapshot."""
    with prepared_snapshot(service, session, progress) as snapshot:
        plan, _entries = _deployment_plan(service, snapshot, payload, progress)
    # The revision protects the real session, not the disposable snapshot.
    plan["source"]["revision"] = service.summary(session)["revision"]
    return plan


def deployment_readme(plan: dict) -> str:
    lines = [
        f"# {plan['targetLabel']} deployment",
        "",
        f"Created by Atari File Forge {plan['applicationVersion']}.",
        f"Source image: `{plan['source']['image']}`",
        f"Source revision: `{plan['source']['revision']}`",
        "",
        "## Installation",
        "",
    ]
    lines.extend(f"{index}. {step}" for index, step in enumerate(plan["instructions"], 1))
    lines.extend(["", "## Files", ""])
    lines.extend(
        f"- `{entry['path']}`: {entry['role']}, {entry['size']:,} bytes, SHA-256 `{entry['sha256']}`"
        for entry in plan["entries"]
    )
    lines.extend(["", "## Validation findings", ""])
    lines.extend(
        f"- {item['severity'].upper()}: {item['message']}" for item in plan["issues"]
    )
    if not plan["issues"]:
        lines.append("- No target-layout problems were detected.")
    lines.extend([
        "",
        "## Verification",
        "",
        "Compare each SHA-256 above against the file you wrote or copied, then boot the machine and list the root of every volume before writing anything to it.",
        "",
        "## Recovery",
        "",
        "Keep the previous working media unchanged until the new deployment has passed its read, write and reboot checks. Restore that backup if any check fails.",
        "",
    ])
    return "\n".join(lines)


def build_deployment_archive(service, session, payload: dict, output: Path, progress: Callable | None = None) -> dict:
    report = progress_module.reporter(progress)
    expected = str(payload.get("expectedRevision") or "")
    live_revision = service.summary(session)["revision"]
    if expected and expected != live_revision:
        raise DiskError("The image changed after deployment review. Build a new plan before downloading.")
    with prepared_snapshot(service, session, report) as snapshot:
        plan, entries = _deployment_plan(service, snapshot, payload, report)
        plan["source"]["revision"] = live_revision
        if not plan["canProceed"]:
            raise DiskError("The deployment plan contains blocking findings.")
        total = sum(entry.size for entry in entries)
        written = 0
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            for entry in entries:
                report(f"Adding {entry.path}", written, total)
                if entry.data is not None:
                    archive.writestr(entry.path, entry.data)
                    written += len(entry.data)
                else:
                    with entry.source.open("rb") as source, archive.open(entry.path, "w", force_zip64=True) as target:
                        while chunk := source.read(4 * 1024 * 1024):
                            target.write(chunk)
                            written += len(chunk)
                            report(f"Adding {entry.path}", written, total)
                report(f"Added {entry.path}", written, total)
            archive.writestr("README.md", deployment_readme(plan))
            archive.writestr("Deployment/manifest.json", json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
            archive.writestr("Deployment/compatibility-report.md", plan["compatibilityReport"]["markdown"])
    report("Deployment package complete", total, total)
    return plan


__all__ = [
    "DEPLOYMENT_FORMAT",
    "DEPLOYMENT_VERSION",
    "TARGETS",
    "available_deployment_targets",
    "build_deployment_archive",
    "deployment_plan",
    "deployment_readme",
    "is_floppy_image",
    "is_hard_drive_image",
    "prepared_snapshot",
]
