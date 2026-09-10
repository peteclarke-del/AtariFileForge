from __future__ import annotations

import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from .rom import DEFAULT_BANK_SIZE
from .rom_workbench import normalise_project


SESSION_OWNER: ContextVar[str | None] = ContextVar("atari_session_owner", default=None)


@dataclass
class ImageSession:
    """Mutable state for one image open in the workbench.

    The model lives outside ``DiskService`` because checkpoints, operations,
    downloads and analysis services all consume the same session contract.
    """

    id: str
    name: str
    kind: str
    path: Path
    dirty: bool = False
    #: The parsed MSA, DIM or STX container this session was opened from,
    #: cached the first time the header is read. A plain sector image has
    #: none, because there is no container in front of its sectors.
    container: object | None = None
    #: Which partition of a hard disk is open, by index into the drive's own
    #: partition list. A floppy or a bare volume image leaves this None, and
    #: so does a hard disk whose partition table is still being shown.
    partition: int | None = None
    source_names: dict[str, str] = field(default_factory=dict)
    distribution_name: str | None = None
    #: The machine or medium this image is being prepared for: ``floppy`` for
    #: a GEMDOS floppy, ``hd`` for a partitioned drive, ``volume`` for a bare
    #: partition image, ``tos`` for a TOS ROM, or ``auto`` for no claim.
    target_hardware: str = "auto"
    hardware_profile: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    #: Format and naming limits read from the mounted volume: FAT12 or FAT16,
    #: the 8.3 name limit, and the root directory's fixed entry count. An
    #: ``hd`` session records nothing here until a partition is mounted;
    #: the drive's own scheme and byte order live in the partition table
    #: report instead, which is where ``byteSwapped`` and ``scheme`` are read.
    gemdos_capabilities: dict = field(default_factory=dict)
    finalised_mtime_ns: int | None = None
    hfe_original_path: Path | None = None
    hfe_version: str | None = None
    hfe_read_only: bool = False
    hfe_export_path: Path | None = None
    scp_original_path: Path | None = None
    scp_read_only: bool = False
    scp_export_path: Path | None = None
    rom_bank_size: int = DEFAULT_BANK_SIZE
    rom_erase_byte: int = 0xFF
    rom_platform: str = "tos"
    rom_layout: str = "linear"
    rom_component_names: list[str] = field(default_factory=list)
    rom_project: dict = field(default_factory=lambda: normalise_project({}))
    editor_projects: dict[str, dict] = field(default_factory=dict)
    compatibility_reports: list[dict] = field(default_factory=list)
    content_kind_cache: dict[tuple, str] = field(default_factory=dict)
    owner_id: str | None = field(default_factory=lambda: SESSION_OWNER.get())
    lock: threading.RLock = field(default_factory=threading.RLock)

    def invalidate_cached_views(self) -> None:
        """Drop everything derived from the image bytes.

        Anything the workbench inferred from the previous contents, extracted
        cached capability reports and prepared container exports, describes bytes
        that no longer exist once the image is rewritten wholesale. Callers that
        replace image data must invalidate together or a later read will mix
        old conclusions with new bytes.

        The parsed container and the dirty flag are deliberately left to the
        caller: a restored checkpoint reparses its container and stays clean,
        while a raw write clears the container and marks the image changed.
        """
        self.content_kind_cache.clear()
        self.hfe_export_path = None
        self.scp_export_path = None
        self.finalised_mtime_ns = None


__all__ = ["ImageSession", "SESSION_OWNER"]
