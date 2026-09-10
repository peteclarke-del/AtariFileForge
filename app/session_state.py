from __future__ import annotations

import re

from .image_session import ImageSession


def normalise_warnings(warnings: list[str]) -> list[str]:
    """Keep durable image history concise and discard superseded diagnostics."""
    result: list[str] = []
    partition_notes = False
    byte_swapped = False
    for value in warnings:
        warning = str(value).strip()
        if not warning:
            continue
        # A point-in-time diagnosis from an older release is replaced by the
        # current one, because the check that produced it has changed.
        if re.match(r"^Repaired \d+ directory block checksum", warning):
            continue
        if "selected hardware profile fits a CPU accelerator" in warning:
            continue
        if re.match(r"^Opened an? [A-Z]+ hard disk with", warning):
            partition_notes = True
            continue
        if "byte-swapping IDE adapter" in warning:
            byte_swapped = True
            continue
        if warning not in result:
            result.append(warning)
    if partition_notes:
        result.append(
            "This image was opened as a partitioned hard disk. Choose a partition "
            "to mount one of its volumes."
        )
    if byte_swapped:
        result.append(
            "This image was taken through a byte-swapping IDE adapter: every "
            "sector's byte pairs are reversed. The workbench reads through the "
            "swap, so the contents are correct here even though a hex editor "
            "shows the bytes transposed."
        )
    return result


def session_metadata(session: ImageSession) -> dict:
    """Build the stable JSON representation of a recoverable image session."""
    return {
        "id": session.id,
        "name": session.name,
        "kind": session.kind,
        "descriptorName": session.descriptor_name,
        "descriptorFile": session.descriptor_path.name if session.descriptor_path else None,
        "partition": session.partition,
        "sourceNames": session.source_names,
        "distributionName": session.distribution_name,
        "targetHardware": session.target_hardware,
        "hardwareProfile": session.hardware_profile,
        "gemdosCapabilities": session.gemdos_capabilities,
        "workingFile": session.path.name,
        "hfeOriginalFile": session.hfe_original_path.name if session.hfe_original_path else None,
        "hfeVersion": session.hfe_version,
        "hfeReadOnly": session.hfe_read_only,
        "hfeExportFile": session.hfe_export_path.name if session.hfe_export_path else None,
        "scpOriginalFile": session.scp_original_path.name if session.scp_original_path else None,
        "scpReadOnly": session.scp_read_only,
        "scpExportFile": session.scp_export_path.name if session.scp_export_path else None,
        "romBankSize": session.rom_bank_size,
        "romEraseByte": session.rom_erase_byte,
        "romPlatform": session.rom_platform,
        "romLayout": session.rom_layout,
        "romComponentNames": session.rom_component_names,
        "romProject": session.rom_project,
        "editorProjects": session.editor_projects,
        "compatibilityReports": session.compatibility_reports[-10:],
        "dirty": session.dirty,
        "finalisedMtimeNs": session.finalised_mtime_ns,
        "ownerId": session.owner_id,
        "warnings": session.warnings,
    }
