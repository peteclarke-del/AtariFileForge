"""The README that travels with every saved Atari File Forge package.

A saved image is only useful if the person who opens the archive next year can
tell what it is. This module writes that: what the image holds, how it is
shaped, what the catalogue contains, which checksums it was saved with, and
which TOS releases can use it. It reads through the disk service rather than
from the raw sectors, so the README describes exactly what the application
showed rather than a second, possibly disagreeing, decode.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from atarinut.filesystem.gemdos import tos_limit_notes

from . import atari_paths
from .checksum import sha256_path
from .floppy_geometry import resolve_geometry

if TYPE_CHECKING:  # pragma: no cover - import for type checking only
    from .disk_service import DiskService, ImageSession


#: How each session kind is described in the identity block.
KIND_LABELS = {
    "gemdos": "GEMDOS volume",
    "hd": "Partitioned hard drive",
    "msa": "Magic Shadow Archiver container",
    "dim": "FastCopy Pro container",
    "stx": "Pasti flux container",
    "hfe": "HxC flux container",
    "scp": "SuperCard Pro flux container",
    "ipf": "Interchangeable Preservation Format container",
    "iso": "ISO 9660 disc image",
    "rom": "ROM image",
    "tosrom": "TOS ROM image",
}

#: What the AHDI partition ids mean to a TOS driver.
PARTITION_IDS = {
    "GEM": "GEM, up to 16 MiB, mounted by every TOS release",
    "BGM": "BGM, over 16 MiB, needs TOS 1.02 or later",
    "RAW": "RAW, not a GEMDOS volume",
    "LNX": "LNX, a Linux partition TOS will not mount",
    "SWP": "SWP, swap space rather than a filing system",
}


def timestamped_archive_name(image_name: str, generated: datetime | None = None) -> str:
    moment = generated or datetime.now().astimezone()
    stem = Path(image_name).stem or "atari-image"
    return f"{stem}-{moment:%Y%m%d-%H%M%S}.zip"


def _safe_cell(value: object) -> str:
    return str(value if value not in (None, "") else "-").replace("|", "\\|").replace("\n", " ")


def _summary(service, session) -> dict:
    try:
        return service.summary(session) or {}
    except Exception:  # pragma: no cover - a summary is a convenience here
        return {}


def _capabilities(session) -> dict:
    """The mounted volume's declared limits, whatever the service calls them."""
    for name in ("capabilities", "gemdos_capabilities", "ffs_capabilities"):
        value = getattr(session, name, None)
        if isinstance(value, dict) and value:
            return value
    return {}


def _geometry_line(session, summary: dict, image_path: Path) -> str:
    """Describe a floppy's shape, preferring what the service already decided."""
    described = str(summary.get("geometry") or summary.get("geometryLabel") or "")
    if described:
        return described
    try:
        with image_path.open("rb") as image:
            boot = image.read(512)
        geometry = resolve_geometry(image_path.stat().st_size, boot)
    except OSError:
        geometry = None
    if geometry is None:
        return "not determined from the image size or its BIOS parameter block"
    return f"{geometry.label} ({geometry.describe()}, {geometry.kibibytes} KiB)"


def _partition_catalogue(service, session) -> list[str]:
    """Describe every partition the drive declares.

    The table reports the drive letter TOS assigns, the three-letter id its
    driver reads, where the partition starts and how large it is, because
    those four values together decide whether a given TOS release will mount
    it at all.
    """
    lines = ["## Partition table", ""]
    try:
        partitions = service.list_partitions(session)
    except Exception as error:
        lines.extend((f"The partition table could not be read: {error}", ""))
        return lines
    if not partitions:
        lines.extend(("This drive declares no partitions.", ""))
        return lines
    lines.extend((
        "| Drive | Id | Start sector | Size | Filing system | Boot |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ))
    for index, partition in enumerate(partitions):
        device = str(partition.get("device") or partition.get("name") or f"{chr(ord('C') + index)}:")
        identifier = str(partition.get("id") or "")
        size = int(partition.get("sizeBytes") or 0)
        lines.append(
            f"| `{_safe_cell(device)}` | {_safe_cell(identifier)} | "
            f"{int(partition.get('startSector') or 0):,} | {size:,} bytes | "
            f"{_safe_cell(partition.get('format'))} | "
            f"{'yes' if partition.get('bootable') else 'no'} |"
        )
    lines.append("")
    described = [
        f"- `{partition.get('device') or partition.get('name')}` is "
        f"{PARTITION_IDS.get(str(partition.get('id') or '').upper(), 'an id no TOS driver recognises')}."
        for partition in partitions
        if str(partition.get("id") or "").upper() in PARTITION_IDS
    ]
    if described:
        lines.extend([*described, ""])
    notes = [
        f"- `{partition.get('device') or partition.get('name')}`: {note}"
        for partition in partitions
        for note in tos_limit_notes(int(partition.get("sizeBytes") or 0))
    ]
    if notes:
        lines.extend(("### TOS partition limits", "", *notes, ""))
    return lines


def _row_line(path: str, row: dict) -> str:
    kind = "directory" if str(row.get("type") or "") in {"dir", "directory"} else str(
        row.get("filetype") or row.get("contentKind") or "file"
    )
    size = row.get("length", row.get("size", "-"))
    attributes = str(row.get("attributes") or row.get("attr") or "")
    datestamp = str(row.get("datestamp") or "")
    return (
        f"| `{_safe_cell(path)}` | `{_safe_cell(attributes)}` | "
        f"{_safe_cell(datestamp)} | {_safe_cell(size)} | {_safe_cell(kind)} |"
    )


def _rom_catalogue(service, session) -> list[str]:
    lines = [
        "## ROM bank catalogue", "",
        "| Bank | Title | Bytes | Kind | Header | SHA-256 |",
        "|---:|---|---:|---|---|---|",
    ]
    for row in service.list_rom_banks(session):
        header = row.get("header") or {}
        if header:
            detail = (
                f"{header.get('roles', 'TOS')} {header.get('release') or header.get('version')} · "
                f"{header.get('country')} · {header.get('videoStandard')} · "
                f"base &{int(header.get('base') or 0):06X}"
            )
        else:
            detail = "not recognised"
        lines.append("| " + " | ".join((
            f"{row['bank']:03d}",
            _safe_cell(row.get("name")),
            f"{int(row.get('length') or 0):,}",
            _safe_cell(row.get("filetype")),
            _safe_cell(detail),
            f"`{(row.get('diagnostics') or {}).get('sha256', '')}`",
        )) + " |")
    return [*lines, ""]


def _rom_identity(service, session) -> list[str]:
    """The facts a TOS ROM's own header records about itself."""
    try:
        banks = service.list_rom_banks(session)
    except Exception:
        return []
    header = next((row.get("header") for row in banks if row.get("header")), None)
    if not header:
        return ["## ROM header", "", "No TOS or EmuTOS header was recognised in this image.", ""]
    return [
        "## ROM header",
        "",
        f"- Release: {header.get('release') or header.get('version') or 'unknown'}",
        f"- Version word: &{header.get('versionHex', '????')}",
        f"- Country: {header.get('country') or 'unknown'} ({header.get('countryShort') or '--'})",
        f"- Video standard: {header.get('videoStandard') or 'unknown'}",
        f"- Mapped base address: &{int(header.get('base') or 0):06X}",
        f"- Machine: {header.get('machine') or 'unknown'}",
        "- EmuTOS: " + (
            f"yes, {header.get('emutosVersion') or 'version not recorded'}"
            if header.get("emutos") else "no, this is an Atari TOS ROM"
        ),
        f"- Built: {header.get('date') or 'not recorded'}",
        "",
    ]


def _filesystem_catalogue(service: DiskService, session: ImageSession) -> list[str]:
    if session.kind in {"rom", "tosrom"}:
        return _rom_catalogue(service, session)
    lines = [
        "## Filesystem catalogue",
        "",
        "| Name | Attributes | Datestamp | Size | Kind |",
        "|---|---|---|---:|---|",
    ]
    pending: list[str] = [""]
    visited: set[str] = set()
    object_count = 0
    while pending:
        directory = pending.pop(0)
        if directory.casefold() in visited:
            continue
        visited.add(directory.casefold())
        try:
            listing = service.list_directory(session, directory)
        except Exception as error:
            lines.append(f"| `{_safe_cell(directory)}` | - | - | - | unreadable: {_safe_cell(error)} |")
            continue
        for row in listing["entries"]:
            name = str(row.get("name") or "UNTITLED")
            inner_path = atari_paths.join(directory, name.replace("\\", atari_paths.SEPARATOR))
            lines.append(_row_line(inner_path, row))
            object_count += 1
            if str(row.get("type") or "") in {"dir", "directory"}:
                pending.append(inner_path)
            if object_count >= 100_000:
                lines.extend(("", "Catalogue stopped at the 100,000-object safety limit."))
                pending.clear()
                break
    if object_count == 0:
        lines.append("| _(empty)_ | - | - | - | - |")
    return [*lines, ""]


def _deployment_section(deployment: dict) -> list[str]:
    """The installation steps, when this package is a hardware deployment."""
    lines = [
        "## Hardware deployment",
        "",
        f"This package was built for the {deployment.get('targetLabel') or deployment.get('target')} target.",
        "",
    ]
    steps = list(deployment.get("instructions") or [])
    if steps:
        lines.extend([*(f"{index}. {step}" for index, step in enumerate(steps, 1)), ""])
    issues = list(deployment.get("issues") or [])
    if issues:
        lines.extend((
            "### Deployment findings",
            "",
            *(f"- {item.get('severity', 'note').upper()}: {item.get('message', '')}" for item in issues),
            "",
        ))
    return lines


def build_download_readme(
    service: DiskService,
    session: ImageSession,
    image_path: Path,
    generated: datetime | None = None,
    *,
    image_checksum: str | None = None,
    deployment: dict | None = None,
) -> str:
    moment = generated or datetime.now().astimezone()
    summary = _summary(service, session)
    capabilities = _capabilities(session)
    kind = KIND_LABELS.get(session.kind, session.kind.upper())
    lines = [
        f"# {session.name}",
        "",
        "This archive was prepared by Atari File Forge, the open-source Atari image workshop.",
        "Project: https://github.com/peteclarke-del/AtariFileForge",
        "",
        "## Image details",
        "",
        f"- Generated: {moment.isoformat(timespec='seconds')}",
        f"- Image kind: {kind}",
        f"- Image filename: `{session.name}`",
        f"- Image size: {image_path.stat().st_size:,} bytes",
        f"- Image SHA-256: `{image_checksum or sha256_path(image_path)}`",
        f"- Target hardware: {session.target_hardware}",
    ]
    if session.kind == "gemdos":
        lines.append(f"- Floppy geometry: {_geometry_line(session, summary, image_path)}")
    if session.kind == "hd":
        scheme = str(summary.get("scheme") or summary.get("partitionScheme") or "AHDI").upper()
        lines.append(f"- Partition scheme: {scheme}")
    if summary.get("byteSwapped"):
        lines.append(
            "- Byte order: byte-swapped. This is the word order an IDE or "
            "CompactFlash adapter writes. An ACSI device needs the un-swapped bytes."
        )
    elif session.kind == "hd":
        lines.append("- Byte order: plain, as an ACSI device reads it.")
    label = str(summary.get("label") or capabilities.get("label") or "")
    if session.kind in {"gemdos", "hd"}:
        fat = str(capabilities.get("format") or summary.get("format") or "not identified")
        lines.extend((
            f"- Filing system: {fat}",
            f"- Volume label: {label or 'none'}",
            "- Boot sector: " + (
                "executable, so TOS runs it"
                if capabilities.get("bootable") or summary.get("bootable")
                else "not executable, so TOS reads the BIOS parameter block and stops"
            ),
        ))
        entry_limit = capabilities.get("directoryEntryLimit")
        lines.extend((
            f"- Filename limit: {capabilities.get('nameLimit', 12)} characters, as 8.3",
            f"- Volume label limit: {capabilities.get('labelLimit', 11)} characters",
            "- Root directory entries: " + (
                f"{entry_limit}" if entry_limit is not None else "set by the partition's boot sector"
            ),
            "- Name matching: "
            + ("case-insensitive, and every name is stored upper case"
               if capabilities.get("caseInsensitive", True)
               else "case-sensitive"),
        ))
    profile = session.hardware_profile or {}
    if profile:
        lines.extend((
            f"- Hardware profile: {profile.get('name') or 'Custom'}",
            f"- Base machine: {profile.get('machine') or 'not specified'}",
            "- Fitted options: " + (", ".join(profile.get("addons") or []) or "stock machine"),
            f"- Managed emulator: {profile.get('emulator') or 'automatic'}",
        ))
    if session.compatibility_reports:
        accepted = session.compatibility_reports[-1]
        lines.extend((
            f"- Accepted compatibility report: {accepted.get('acceptedAt') or 'retained with this package'}",
            f"- Accepted operation: {accepted.get('operation') or 'review'}",
            "- Compatibility evidence: `Compatibility/accepted-report.json` and `Compatibility/accepted-report.md`",
        ))
    if session.hfe_original_path:
        lines.extend((
            f"- HFE version: {session.hfe_version or 'unknown'}",
            f"- HFE write support: {'read-only' if session.hfe_read_only else 'editable and sector-verified'}",
        ))
    if session.kind in {"rom", "tosrom"}:
        lines.extend((
            f"- ROM target family: {session.rom_platform}",
            f"- Logical bank size: {session.rom_bank_size:,} bytes",
            f"- Erased byte: `&{session.rom_erase_byte:02X}`",
            f"- Byte layout: {session.rom_layout}",
            "- Original component order: "
            + (", ".join(session.rom_component_names) or "single image or unspecified"),
            f"- Project hardware notes: {session.rom_project.get('hardware') or 'not recorded'}",
            f"- Saved project symbols: {len(session.rom_project.get('symbols', {}))}",
        ))
    lines.extend((
        "",
        "## Using this archive",
        "",
        "Keep this README beside the image so its catalogue, target and checksums stay with it.",
        "Verify the SHA-256 value after copying the image or writing it to media. Work from a backup, then test the edited image in Hatari or on disposable media before replacing a known-good card or disk.",
        "Before using important media on hardware, reopen a copy in Atari File Forge and run Analyse > Image health dashboard, then review every itemised failure.",
    ))
    if deployment:
        lines.extend(("", *_deployment_section(deployment)))
    if session.kind in {"rom", "tosrom"}:
        lines.extend((
            "",
            *_rom_identity(service, session),
            "## ROM interpretation and maintenance",
            "",
            "A ROM image holds raw bytes rather than a filing system. The bank catalogue is a view over the saved byte image in ascending order.",
            "An ST or STE TOS is 192 KiB or 256 KiB, a TT or Falcon TOS is 512 KiB, and a cartridge is up to 128 KiB. Test an edited ROM in Hatari or on a spare programmable device before fitting it to valuable hardware.",
            "A release, country, video standard and mapped base address are decoded from the TOS header at the start of the image. Printable strings and plausible modules remain evidence rather than invented files or a guarantee of compatibility.",
            "The programmed-byte count means bytes that differ from the configured erased value. It is not filesystem free space. File offsets refer to the complete image; mapped addresses refer to the configured target window.",
            "`ROM-project.json` holds notes, symbols and analysed regions. It is Atari File Forge metadata and is not programmed into the ROM device.",
            "Programmer export does not rewrite the logical ROM. It applies padding or mirroring, optional adjacent-byte and 16-bit word swaps, address-line swaps, then one, two or four physical byte lanes to the programmer download.",
            "Exact ROM identities are keyed by complete SHA-256. Different padding, a one-byte edit or a concatenated bank set is a different identity even when the visible title matches.",
        ))
    if session.kind == "hd" and session.partition is None:
        lines.extend((
            "",
            "This is a partitioned hard drive. Each partition is an ordinary "
            "GEMDOS volume, mounted at the drive letter its position in the "
            "table gives it, and is browsed by opening it in Atari File Forge.",
            "",
            *_partition_catalogue(service, session),
        ))
    else:
        lines.extend(("", *_filesystem_catalogue(service, session)))
    warnings = list(getattr(session, "warnings", []) or [])
    lines.extend(("## Warnings and compatibility notes", ""))
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- No compatibility warnings were recorded for this working copy.")
    volume_notes = (
        capabilities.get("tosLimits")
        or summary.get("tosLimits")
        or (tos_limit_notes(image_path.stat().st_size) if session.kind in {"gemdos", "hd"} else [])
    )
    if volume_notes:
        lines.extend(("", "### TOS release limits", ""))
        lines.extend(f"- {note}" for note in volume_notes)
    lines.extend((
        "",
        "## Technical notes",
        "",
        "GEMDOS names are 8.3 and are stored upper case. Renaming a program or moving software between drives can break a launcher that names its files, even when every file copied successfully.",
        "A GEMDOS directory entry records one attribute byte and one datestamp. Datestamps run from 1980 to 2107 and nothing outside that range can be stored.",
        "TOS runs every `.PRG` in the `AUTO` folder of the boot drive, in the order the directory holds the entries, before the desktop appears. Changing that order changes what the machine does at boot.",
        "A flux container can hold track-level information that is not representable once the image is edited as a filing system.",
        "For current documentation, releases and issue reporting, visit https://github.com/peteclarke-del/AtariFileForge.",
        "",
    ))
    return "\n".join(lines)


def write_download_readme(
    service: DiskService,
    session: ImageSession,
    image_path: Path,
    generated: datetime | None = None,
    *,
    image_checksum: str | None = None,
    deployment: dict | None = None,
) -> Path:
    target = session.path.parent / "download-README.md"
    target.write_text(
        build_download_readme(
            service,
            session,
            image_path,
            generated,
            image_checksum=image_checksum,
            deployment=deployment,
        ),
        encoding="utf-8",
    )
    return target


__all__ = [
    "build_download_readme",
    "timestamped_archive_name",
    "write_download_readme",
]
