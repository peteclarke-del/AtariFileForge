from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.disk_service import DiskService, ImageSession


@dataclass(frozen=True)
class GeneratedMedium:
    format: str
    session: ImageSession


def generated_media_matrix(
    service: DiskService, *, include_flux: bool = False
) -> list[GeneratedMedium]:
    """Create representative media using only public application APIs.

    Every shape the workbench opens is here except the ones that need an
    external engine: a floppy at each geometry TOS writes, a bootable one, a
    bare volume, a partitioned hard disk, both ROM shapes, and the two
    track-based containers built by converting a generated floppy.

    Flux containers need the HxC engine, which is present in the application
    container but not necessarily on a development host, so they are opt-in.
    """
    rows = [
        GeneratedMedium("ds-720k", service.create_blank("ds-720k", "TESTDD")),
        GeneratedMedium("ds-800k", service.create_blank("ds-800k", "TEST800")),
        GeneratedMedium("ds-880k", service.create_blank("ds-880k", "TEST880")),
        GeneratedMedium("ss-360k", service.create_blank("ss-360k", "TESTSS")),
        GeneratedMedium("hd-1440k", service.create_blank("hd-1440k", "TESTHD")),
        GeneratedMedium(
            "ds-720k-boot",
            service.create_blank("ds-720k", "TESTBOOT", options={"bootable": True}),
        ),
        GeneratedMedium("volume", service.create_blank("volume", "TESTVOL", "32MB")),
        GeneratedMedium("hd", service.create_blank("hd", "TESTHDD", "32MB")),
        GeneratedMedium(
            "rom",
            service.create_blank(
                "rom",
                "TESTROM",
                options={"bankSize": 256 * 1024, "totalSize": 512 * 1024},
            ),
        ),
        GeneratedMedium("cartridge", service.create_blank("cartridge", "TESTCART")),
    ]
    if include_flux:
        rows.append(
            GeneratedMedium("hfe", service.create_blank("hfe-st-720k", "TESTHFE"))
        )
    # An MSA and a DIM are a floppy behind a header, so the honest way to
    # generate one is to write a floppy and export it as that container.
    source = service.create_blank("ds-720k", "TESTCONV")
    try:
        for container in ("msa", "dim"):
            exported, _name = service.export_image(source, container)
            rows.append(
                GeneratedMedium(container, service.create_from_path(exported))
            )
    finally:
        service.discard_session(source)
    return rows


def add_test_file(
    service: DiskService,
    session: ImageSession,
    host_root: Path,
    *,
    path: str = "TEST.DAT",
    payload: bytes = b"Atari File Forge generated fixture\n",
) -> None:
    source = host_root / f"fixture-{session.id}.bin"
    source.write_bytes(payload)
    service.put(session, path, source)
