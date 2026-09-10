r"""The workbench's view of one Atari image, whatever shape it arrived in.

``DiskService`` owns every session: opening media, identifying it from its
bytes, listing and editing what is inside it, and handing back something the
user can put on a real machine. The knowledge that is specific to one kind of
media lives in a mixin beside this module; what is here is the part that is
true of all of them.

Six shapes of media reach it, and they are told apart by content:

* a GEMDOS floppy image, which is a FAT12 volume and nothing else;
* a bare volume image, which is the same thing at hard-disk size;
* a partitioned hard disk, which carries an AHDI, XGM, ICD or MBR table and
  is opened on that table until a partition is chosen;
* an MSA, DIM or Pasti container, which is a floppy behind a header and is
  decoded to a working ``.st`` before it can be browsed;
* an HFE, SCP or IPF flux capture, which is decoded the same way;
* a ROM image, either a cartridge or a TOS ROM.

Two rules run through all of it. The filename extension is a hint and never a
decision: everything is identified from its bytes. And nothing that cannot be
proved is written: a flux container is only released after it decodes back to
exactly the sectors on screen.
"""

from __future__ import annotations

import gzip
import io
import os
import re
import shutil
import subprocess
import threading
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Callable

from .gemdos_install_service import GemdosInstallMixin
from .install_service import InstallMixin
from .iso_disk_service import IsoDiskMixin
from .drive_preparation import DrivePreparationMixin
from .checkpoints import CheckpointStore
from .content_kind import LISTING_SNIFF_LIMIT, analyse_content, metadata_kind
from .disk_tools import decode_disc_json, friendly_engine_error, run_disc, run_hxcfe
from .errors import DiskError
from .image_session import (
    ImageSession as ImageSession,
    SESSION_OWNER as SESSION_OWNER,
)
from .formats import (
    DIM_EXTENSIONS,
    HARD_DISK_EXTENSIONS,
    HFE_EXTENSIONS,
    IPF_EXTENSIONS,
    ISO_EXTENSIONS,
    MSA_EXTENSIONS,
    ROM_EXTENSIONS,
    SCP_EXTENSIONS,
    ST_EXTENSIONS,
    STX_EXTENSIONS,
)
from .atari_metadata import attribute_value, format_attributes
from .filename_policy import session_name_policy
from .filesystem_disk_service import FilesystemDiskMixin
from .container_disk_service import CONTAINER_KINDS, ContainerDiskMixin
from .atarinut_internals import (
    ensure_directory_chain,
    file_copy_item,
    in_storage_order,
    natural_name_key,
    write_copy_item,
)
from .rom_disk_service import RomDiskMixin
from .partition_service import PartitionMixin
from .session_disk_service import SessionDiskMixin
from .session_state import normalise_warnings
from .rom import (
    DEFAULT_BANK_SIZE,
    MAX_ROM_SIZE,
    RomError,
    bank_number,
    make_cartridge_rom,
    validate_bank_size,
    validate_layout,
    validate_platform,
)
from .floppy_geometry import resolve_geometry
from .flux_containers import (
    BROWSEABLE_KINDS,
    FLOPPY_SIZES,
    FLUX_CONTAINERS,
    HFE,
    SCP,
    FluxContainer,
    FluxEngine,
    is_flux_encodable,
    restore_omitted_tail_sector,
    sector_image_suffix,
)
from .hfe import HFEError, HFEHeader, parse_hfe_header
from . import atari_paths
from . import progress as progress_module


COPY_BUFFER_SIZE = 8 * 1024 * 1024
FICLONE = 0x40049409

#: One mebibyte, spelled out because every capacity in this module is.
MIB = 1024 * 1024

#: The largest partition TOS 1.04 will mount. Later releases and replacement
#: drivers go further, but a drive built to this limit works everywhere.
TOS_PARTITION_LIMIT = 256 * MIB

#: The blank floppy formats, named by the engine's own geometry table.
FLOPPY_FORMATS = (
    "ss-360k",
    "ss-400k",
    "ss-440k",
    "ds-720k",
    "ds-800k",
    "ds-880k",
    "ds-720k-81",
    "ds-800k-81",
    "ds-880k-81",
    "ds-720k-82",
    "ds-800k-82",
    "ds-880k-82",
    "ds-720k-83",
    "ds-800k-83",
    "ds-880k-83",
    "hd-1440k",
)

#: Blank floppies wrapped as HxC flux, keyed by the geometry inside them.
HFE_FORMATS = {
    "hfe-st-360k": "ss-360k",
    "hfe-st-720k": "ds-720k",
    "hfe-st-800k": "ds-800k",
    "hfe-st-880k": "ds-880k",
    "hfe-st-1440k": "hd-1440k",
}

#: Everything ``create_blank`` accepts, in the order the pane offers it.
BLANK_FORMATS = (
    *FLOPPY_FORMATS,
    *HFE_FORMATS,
    "hd",
    "volume",
    "rom",
    "cartridge",
)

#: The partition-table schemes a new hard disk can be built with.
PARTITION_SCHEMES = ("ahdi", "mbr")

#: Extensions that name a ROM and nothing else. ``.img`` and ``.bin`` are
#: shared with a drive image and a bare volume, so only the bytes settle
#: those.
ROM_ONLY_EXTENSIONS = ROM_EXTENSIONS - HARD_DISK_EXTENSIONS


class DiskService(
    SessionDiskMixin,
    FilesystemDiskMixin,
    GemdosInstallMixin,
    InstallMixin,
    IsoDiskMixin,
    DrivePreparationMixin,
    PartitionMixin,
    RomDiskMixin,
    ContainerDiskMixin,
):
    _normalise_warnings = staticmethod(normalise_warnings)

    def __init__(self, work_dir: str | Path):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.sessions: dict[str, ImageSession] = {}
        self._lock = threading.RLock()
        self.checkpoints = CheckpointStore(self._copy_local_file)

    @staticmethod
    @contextmanager
    def _locked_sessions(*sessions: ImageSession):
        """Acquire one or more session locks once, in a stable order."""
        locks = {id(session.lock): session.lock for session in sessions}
        with ExitStack() as stack:
            for _identity, lock in sorted(locks.items()):
                stack.enter_context(lock)
            yield

    @staticmethod
    def _append_warning(session: ImageSession, warning: str) -> None:
        if warning not in session.warnings:
            session.warnings.append(warning)

    @staticmethod
    def safe_filename(name: str) -> str:
        name = Path(name or "image").name
        return re.sub(r"[^A-Za-z0-9._() +!-]", "_", name)[:180] or "image"

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------
    @staticmethod
    def detect_kind(name: str) -> str:
        """Guess a kind from the filename, to decide which probe runs first.

        The answer is never final. ``.img`` is used for a cartridge dump and
        for an ACSI drive image alike, and ``.bin`` for both of those and a
        bare volume, so anything this returns is confirmed against the bytes
        before a session is created.
        """
        ext = Path(name).suffix.lower()
        if ext in ST_EXTENSIONS:
            return "gemdos"
        if ext in MSA_EXTENSIONS:
            return "msa"
        if ext in DIM_EXTENSIONS:
            return "dim"
        if ext in STX_EXTENSIONS:
            return "stx"
        if ext in HFE_EXTENSIONS:
            return "hfe"
        if ext in SCP_EXTENSIONS:
            return "scp"
        if ext in IPF_EXTENSIONS:
            return "ipf"
        if ext in ISO_EXTENSIONS:
            return "iso"
        if ext in HARD_DISK_EXTENSIONS:
            return "hd"
        if ext in ROM_EXTENSIONS:
            return "rom"
        return "unknown"

    @staticmethod
    def _looks_like_iso(path: Path) -> bool:
        """Whether this file announces itself as an ISO 9660 disc.

        The identifier sits at the start of sector sixteen, so this reads two
        kilobytes at a known offset rather than scanning.
        """
        from .iso9660 import FIRST_DESCRIPTOR_SECTOR, SECTOR

        offset = FIRST_DESCRIPTOR_SECTOR * SECTOR
        try:
            with path.open("rb") as handle:
                handle.seek(offset)
                return handle.read(6)[1:6] == b"CD001"
        except OSError:
            return False

    #: How confident the volume probe has to be before a bootable disk is
    #: treated as a filing system rather than as a loader. A cracked game
    #: disk often carries a boot sector whose parameter block reads as
    #: plausible while the directory behind it is the loader's own data.
    MINIMUM_VOLUME_CONFIDENCE = 0.5

    @classmethod
    def _custom_loader_disk(cls, path: Path) -> bool:
        """Whether this is an Atari disk that boots without a filing system.

        A great many ST games were shipped this way: the boot sector is real
        68000 code carrying the 0x1234 checksum TOS looks for, and the rest
        of the disk is the loader's own layout rather than a FAT volume.
        Such a disk has nothing to list, but it is still a disk, and refusing
        to open it would put a genuine, working, preserved game beyond reach
        of the hex editor and of every conversion that works on whole tracks.

        Two things have to be true together. The boot sector must be one TOS
        will execute, which is what makes this a loader rather than damage.
        And the probe must not find a directory it believes in, because a
        disk that boots *and* carries a filing system is an ordinary
        bootable floppy and is opened as one.
        """
        try:
            from atarinut.filesystem import probe_volume, reader_for
            from atarinut.filesystem.blocks import is_executable_sector
        except ImportError:  # pragma: no cover - packaging failure
            return False
        try:
            if path.stat().st_size not in FLOPPY_SIZES:
                return False
            with path.open("rb") as image:
                if not is_executable_sector(image.read(512)):
                    return False
            reader = reader_for(path, writable=False)
            try:
                found = probe_volume(reader)
            finally:
                reader.close()
        except OSError:
            return False
        return found is None or found[0] < cls.MINIMUM_VOLUME_CONFIDENCE

    @staticmethod
    def _rom_kind(path: Path) -> str | None:
        """Say whether these bytes are a TOS ROM, a cartridge, or neither."""
        try:
            from atarinut.tosrom import is_cartridge_rom, is_tos_rom
        except ImportError:  # pragma: no cover - packaging failure
            return None
        try:
            data = path.read_bytes()
        except OSError:
            return None
        if is_tos_rom(data):
            return "tosrom"
        if is_cartridge_rom(data):
            return "rom"
        return None

    #: Which filing systems each named kind is worth probing for. Restricting
    #: the cascade keeps a 400 MiB drive image from being read end to end
    #: looking for a ROM header.
    PROBE_ORDER = {
        "gemdos": ("gemdos", "ahdi"),
        "hd": ("ahdi", "gemdos"),
        "tosrom": ("tosrom",),
    }

    def identify_kind(self, path: Path, expected_kind: str | None = None) -> str:
        """Identify media from its bytes, constraining probes when it is known."""
        # A CD carries no GEMDOS filing system, so the cascade below would
        # refuse it with a message about supplying a raw image. It identifies
        # itself at a fixed offset, which is cheap to check and is exactly the
        # "from its bytes, not from the name" rule the rest of this obeys.
        if self._looks_like_iso(path):
            return "iso"
        # A ROM probe is cheap and decisive, so it runs whenever the bytes
        # could be a ROM: either nothing else is expected, or the name is one
        # of the extensions a cartridge and a drive image share.
        if expected_kind in {None, "rom", "tosrom"} or path.suffix.lower() in ROM_EXTENSIONS:
            rom_kind = self._rom_kind(path)
            if rom_kind:
                return rom_kind
        try:
            from atarinut.filesystem import create_filesystem, identify
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise DiskError("The Atarinut identification API is unavailable.") from exc
        names = self.PROBE_ORDER.get(expected_kind or "")
        try:
            filesystems = (
                {name: create_filesystem(name) for name in names} if names else None
            )
            candidates = identify(
                path,
                suffix_hint=path.suffix.lower(),
                filesystems=filesystems,
            )
        except Exception as exc:
            raise DiskError(friendly_engine_error(str(exc))) from exc
        if not candidates:
            raise DiskError(
                "No GEMDOS filing system was found in the uploaded bytes. "
                "The filename extension is only a hint. Supply the raw, "
                "uncompressed image rather than an MSA or DIM container, an "
                "archive member or a flux capture. This build recognises "
                "FAT12 and FAT16 volumes, AHDI, XGM, ICD and MBR partitioned "
                "hard disks, and TOS ROMs. The source image has not been "
                "changed."
            )
        filesystem = str(candidates[0].filesystem).lower()
        if filesystem in {"gemdos", "fat12", "fat16"}:
            return "gemdos"
        if filesystem == "ahdi":
            return "hd"
        if filesystem == "tosrom":
            return "tosrom"
        raise DiskError(f"The detected {filesystem or 'unknown'} filesystem is not supported.")

    @staticmethod
    def validate_leaf_name(session: ImageSession, name: str) -> str:
        return session_name_policy(session).validate(name)

    @staticmethod
    def require_writable_geometry(session: ImageSession) -> None:
        """Refuse an edit to media whose bytes cannot be rewritten honestly."""
        if session.hfe_read_only:
            raise DiskError(
                "This HFE uses advanced track features or contains unreadable sectors. "
                "It can be browsed and copied from, but cannot be rewritten safely."
            )
        if session.scp_read_only:
            raise DiskError(
                "This SCP flux capture could not be re-encoded and decoded back to identical sectors. "
                "It can be browsed and copied from, but cannot be rewritten safely."
            )
        if session.kind == "stx":
            raise DiskError(
                "A Pasti capture records what the controller read from a physical "
                "disk, including timing and protection a sector image cannot hold. "
                "Convert it to a .st image to edit the sectors."
            )
        if session.kind == "tosrom":
            raise DiskError(
                "A TOS ROM is read-only. It is one linked image whose parts sit at "
                "the addresses the machine's reset vector expects, so nothing in it "
                "can be moved or rewritten in place."
            )
        if session.kind == "iso":
            raise DiskError("A CD image is read-only.")

    # ------------------------------------------------------------------
    # Opening
    # ------------------------------------------------------------------
    def create_from_stream(
        self,
        name: str,
        stream: BinaryIO,
        target_hardware: str = "auto",
        rom_options: dict | None = None,
        force_kind: str | None = None,
    ) -> ImageSession:
        safe_name, kind = self._new_session_source(name, force_kind)
        image_id = uuid.uuid4().hex
        folder = self.work_dir / image_id
        folder.mkdir()
        path = folder / safe_name
        try:
            self._copy_stream(stream, path)
            return self._finalize_new_session(
                image_id, safe_name, path, kind, target_hardware, rom_options,
                force_rom=force_kind == "rom",
            )
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def create_from_path(
        self,
        source: Path,
        target_hardware: str = "auto",
        rom_options: dict | None = None,
        force_kind: str | None = None,
    ) -> ImageSession:
        """Create a private session from a trusted local desktop path.

        Local paths use the filesystem clone/sparse-copy path instead of
        passing hundreds of megabytes through multipart and a spooled upload.
        The source remains untouched and all edits still target the session.
        """
        source = Path(source)
        safe_name, kind = self._new_session_source(source.name, force_kind)
        image_id = uuid.uuid4().hex
        folder = self.work_dir / image_id
        folder.mkdir()
        path = folder / safe_name
        try:
            self._copy_local_file(source, path)
            return self._finalize_new_session(
                image_id, safe_name, path, kind, target_hardware, rom_options,
                force_rom=force_kind == "rom",
            )
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def _new_session_source(
        self, name: str, force_kind: str | None
    ) -> tuple[str, str]:
        """Validate and normalise names shared by stream and local opens."""
        safe_name = self.safe_filename(name)
        kind = self.detect_kind(safe_name)
        if force_kind:
            if force_kind != "rom":
                raise DiskError("Only the raw ROM format override is supported.")
            kind = force_kind
        return safe_name, kind

    #: The largest image a gzip container is expanded into. A gzipped image
    #: holds an ordinary disk image, so anything past a full hard disk is a
    #: decompression bomb rather than a disk.
    MAX_EXPANDED_IMAGE = 2 * 1024 * 1024 * 1024

    @staticmethod
    def _expand_gzip_image(path: Path) -> Path:
        """Expand a gzip-compressed disk image in place.

        Atari images are routinely distributed gzipped, which is all a
        ``.st.gz`` means. The workbench reads sectors, so a compressed image
        is expanded once as it arrives and keeps the name the user gave it. A
        file that is not gzip is returned untouched, because the extension is
        a hint and never a decision.
        """
        try:
            with path.open("rb") as image:
                if image.read(2) != b"\x1f\x8b":
                    return path
        except OSError:
            return path
        expanded = path.with_name(path.name + ".expanded")
        try:
            with gzip.open(path, "rb") as compressed, expanded.open("wb") as output:
                written = 0
                while True:
                    chunk = compressed.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > DiskService.MAX_EXPANDED_IMAGE:
                        raise DiskError(
                            "This compressed image expands to more than 2 GiB, "
                            "which is larger than any disk the workbench opens."
                        )
                    output.write(chunk)
        except DiskError:
            expanded.unlink(missing_ok=True)
            raise
        except (OSError, EOFError) as exc:
            expanded.unlink(missing_ok=True)
            raise DiskError(
                "This image is gzip compressed but could not be expanded. "
                "The file is truncated or damaged."
            ) from exc
        expanded.replace(path)
        return path

    def is_double_sided(self, session: ImageSession) -> bool:
        """Whether the volume in this image occupies both sides of the disk.

        Single-sided ST disks exist and are still written by some copiers, so
        the side count is worth reporting; it is read from the boot sector's
        own BIOS parameter block rather than inferred from the file size.
        """
        if session.kind != "gemdos":
            return False
        try:
            size = session.path.stat().st_size
            with session.path.open("rb") as image:
                boot = image.read(512)
        except OSError:
            return False
        found = resolve_geometry(size, boot)
        return bool(found and found.sides == 2)

    def _finalize_new_session(
        self,
        image_id: str,
        name: str,
        path: Path,
        kind: str,
        target_hardware: str = "auto",
        rom_options: dict | None = None,
        force_rom: bool = False,
    ) -> ImageSession:
        path = self._expand_gzip_image(path)
        hfe_original = None
        hfe_header = None
        hfe_read_only = False
        hfe_warnings: list[str] = []
        ipf_warnings: list[str] = []
        scp_original = None
        scp_read_only = False
        scp_warnings: list[str] = []
        if kind == "hfe":
            path, kind, hfe_original, hfe_header, hfe_read_only, hfe_warnings = self._open_hfe(path)
        elif kind == "ipf":
            path, kind, ipf_warnings = self._open_ipf(path)
        elif kind == "scp":
            path, kind, scp_original, scp_read_only, scp_warnings = self._open_scp(path)
        custom_loader = False
        try:
            if kind == "rom":
                # The raw ROM override says the caller wants the banked view
                # of these bytes whatever they turn out to hold, which is how
                # a TOS image is inspected chip by chip. Otherwise ``.rom``
                # and ``.tos`` name a ROM outright and only the bytes can
                # promote one to a mountable TOS ROM, so an image that is not
                # yet linked, or is one half of a set, still opens.
                if force_rom:
                    kind = "rom"
                elif path.suffix.lower() in ROM_ONLY_EXTENSIONS:
                    kind = self._rom_kind(path) or "rom"
                else:
                    kind = self.identify_kind(path, "rom")
            elif kind == "unknown":
                kind = self.identify_kind(path)
            elif kind in {"gemdos", "hd", "tosrom"}:
                # ``.img`` and ``.bin`` are shared by a cartridge dump, a
                # drive image and a bare volume, so the bytes settle which
                # it is.
                kind = self.identify_kind(path, kind)
        except DiskError:
            if not self._custom_loader_disk(path):
                raise
            kind = "unknown"
            custom_loader = True
        if kind == "gemdos" and self._custom_loader_disk(path):
            kind = "unknown"
            custom_loader = True
        session = ImageSession(
            id=image_id,
            name=name,
            kind=kind,
            path=path,
            target_hardware=self._target_hardware(target_hardware),
            hfe_original_path=hfe_original,
            hfe_version=hfe_header.version if hfe_header else None,
            hfe_read_only=hfe_read_only,
            scp_original_path=scp_original,
            scp_read_only=scp_read_only,
            warnings=hfe_warnings + scp_warnings + ipf_warnings,
        )
        if custom_loader:
            session.warnings.append(
                "This disk boots its own loader and carries no GEMDOS filing "
                "system, which is how a great many ST games were published. "
                "There is nothing to list, but its sectors can be inspected, "
                "converted between disk containers and written back to a "
                "floppy unchanged."
            )
        if kind == "gemdos":
            self.refresh_gemdos_capabilities(session)
        elif kind == "hd":
            self._note_partition_table(session)
        elif kind in CONTAINER_KINDS:
            # Parse the header now so an unreadable container is refused at
            # open time rather than when the pane is first listed.
            self._container(session)
        elif kind == "rom":
            self._apply_rom_options(session, rom_options or {})
        elif kind == "tosrom":
            details = self.tosrom_details(session)
            session.warnings.extend(details["warnings"])
        self._apply_target_hardware(session)
        with self._lock:
            self.sessions[image_id] = session
        self._persist_session(session)
        return session

    def _apply_rom_options(self, session: ImageSession, rom_options: dict) -> None:
        """Record how a raw ROM image is to be read, and check its size."""
        try:
            session.rom_platform = validate_platform(rom_options.get("platform"))
            session.rom_layout = validate_layout(rom_options.get("layout"))
        except RomError as exc:
            raise DiskError(str(exc)) from exc
        session.rom_component_names = [
            self.safe_filename(name)
            for name in rom_options.get("componentNames", [])
            if str(name).strip()
        ]
        size = session.path.stat().st_size
        if not size or size > MAX_ROM_SIZE:
            raise DiskError("ROM images must contain between 1 byte and 64 MiB.")
        if size % DEFAULT_BANK_SIZE:
            session.warnings.append(
                f"The final ROM bank is partial ({size % DEFAULT_BANK_SIZE:,} bytes). "
                "It is preserved exactly; choose another bank size if this layout is intentional."
            )

    def _note_partition_table(self, session: ImageSession) -> None:
        """Record what a drive's table says, so the pane can explain itself."""
        try:
            table = self.partition_table(session)
        except DiskError as exc:
            self._append_warning(session, f"The partition table could not be read: {exc}")
            return
        scheme = str(table.get("scheme") or "ahdi").upper()
        count = len(table.get("partitions") or [])
        self._append_warning(
            session,
            f"Opened a {scheme} hard disk with {count} partition"
            f"{'s' if count != 1 else ''}.",
        )
        if table.get("byteSwapped"):
            self._append_warning(
                session,
                "This image was taken through a byte-swapping IDE adapter: every "
                "sector's byte pairs are reversed. The workbench reads through the "
                "swap, so the contents are correct here even though a hex editor "
                "shows the bytes transposed.",
            )
        for note in table.get("notes") or []:
            self._append_warning(session, str(note))

    # Flux geometry policy is shared with the SCP container and unit tested
    # without HxCFE; see app/flux_containers.py.
    _hfe_working_suffix = staticmethod(sector_image_suffix)
    _normalise_decoded_flux_size = staticmethod(restore_omitted_tail_sector)

    @property
    def _flux(self) -> FluxEngine:
        return FluxEngine(self._run_hxcfe)

    def _decode_flux_to_sectors(
        self,
        original: Path,
        container: FluxContainer,
        *,
        sides: int = 1,
    ) -> tuple[Path, str, bool, str]:
        """Decode a flux container and place its sectors under a working name.

        Shared by both containers: decode, refuse an empty or non-Atari result,
        repair a single omitted tail sector, then rename to the extension that
        matches the recovered geometry so the rest of the workbench sees an
        ordinary sector image.

        Returns the working path, the filesystem kind, whether a tail sector was
        restored, and HxCFE's decode output.
        """
        raw = original.parent / f"{container.identifier}-decoded.img"
        decode_info = self._flux.decode_to_sectors(original, raw)
        if not raw.is_file() or not raw.stat().st_size:
            raise DiskError(
                f"The {container.noun} did not contain a usable sector filesystem."
            )
        try:
            kind = self.identify_kind(raw)
        except DiskError as exc:
            raise DiskError(
                f"HxCFE decoded the {container.noun}, but the resulting sectors do not "
                "contain a GEMDOS filing system. The "
                f"{container.display} container is valid, but its contents cannot be "
                "browsed as an Atari disk image."
            ) from exc
        if kind not in BROWSEABLE_KINDS:
            raise DiskError(
                f"HxCFE decoded the {container.noun} as {kind.upper()}, but only "
                f"GEMDOS-formatted {container.display} images are browseable."
            )
        padded_tail = restore_omitted_tail_sector(raw, kind)
        working = raw.with_suffix(sector_image_suffix(kind, raw.stat().st_size, sides))
        raw.replace(working)
        return working, kind, padded_tail, decode_info

    def _open_hfe(self, original: Path) -> tuple[Path, str, Path, HFEHeader, bool, list[str]]:
        """Decode an HxC container into the ``.st`` the workbench browses.

        HxCFE writes eighty-four tracks into an HFE whatever the image it was
        given holds, so a track count above eighty is normal padding and is
        not treated as damage. What does make the container read-only is an
        advanced track feature the sector view cannot express, or a sector
        the capture could not read.
        """
        try:
            with original.open("rb") as source:
                header = parse_hfe_header(source.read(512))
        except (OSError, HFEError) as exc:
            raise DiskError(str(exc)) from exc
        info = self._flux.container_info(original)
        working, kind, _padded_tail, _decode_info = self._decode_flux_to_sectors(
            original, HFE, sides=header.sides
        )
        bad_match = re.search(r"Number of bad sectors\s*:\s*(\d+)", info, re.IGNORECASE)
        bad_sectors = int(bad_match.group(1)) if bad_match else 0
        read_only = header.advanced or bad_sectors > 0
        warnings = [
            f"Opened HFE {header.version}: {header.tracks} tracks, {header.sides} side"
            f"{'s' if header.sides != 1 else ''}, {header.bitrate or 'variable'} Kbit/s."
        ]
        if read_only:
            reason = (
                "advanced timing/track features"
                if header.advanced
                else f"{bad_sectors} unreadable sector(s)"
            )
            warnings.append(
                f"This HFE contains {reason}. It is read-only to preserve data that a sector editor cannot represent."
            )
        return working, kind, original, header, read_only, warnings

    def _open_scp(self, original: Path) -> tuple[Path, str, Path, bool, list[str]]:
        """Decode a SuperCard Pro capture, and decide whether it may be edited."""
        try:
            with original.open("rb") as source:
                signature = source.read(3)
        except OSError as exc:
            raise DiskError(f"The SCP flux capture could not be read: {exc}") from exc
        if signature != b"SCP":
            raise DiskError("The selected file does not have a valid SuperCard Pro SCP signature.")
        working, kind, padded_tail, decode_info = self._decode_flux_to_sectors(original, SCP)
        try:
            self._run(["validate", str(working)])
        except DiskError as exc:
            raise DiskError(
                "The SCP capture contains missing or inconsistent filesystem sectors. "
                "HxCFE recovered a GEMDOS boot sector, but the complete directory "
                f"tree is not safe to browse: {exc}"
            ) from exc
        read_only = not self._scp_round_trips(working, original, kind)
        warnings = [
            "Opened SCP flux capture: HxCFE decoded a GEMDOS sector filesystem "
            f"({working.stat().st_size:,} bytes)."
        ]
        if padded_tail:
            warnings.append(
                "HxCFE omitted the blank final sector from the capture. "
                "Atari File Forge restored the declared floppy geometry before validation."
            )
        if "Invalid rpm or tracklen" in decode_info:
            warnings.append(
                "The capture contains non-standard index timing reported by HxCFE. "
                "The recovered sectors passed full filesystem validation."
            )
        if read_only:
            warnings.append(
                "This SCP capture could not be re-encoded and decoded back to identical sectors, so it is "
                "read-only. It can be browsed and copied from, but not rewritten safely."
            )
        return working, kind, original, read_only, warnings

    def _open_ipf(self, original: Path) -> tuple[Path, str, list[str]]:
        """Decode an SPS capture into the sectors a GEMDOS volume holds.

        The capture itself is kept beside the working image and never edited:
        an IPF records timing and protection a sector image cannot express, so
        the image the workbench opens is a reading of it rather than a copy.
        """
        from .ipf import IPFError, read_ipf

        try:
            report = read_ipf(original)
        except IPFError as exc:
            raise DiskError(str(exc)) from exc
        working = original.with_suffix(".st")
        if working == original:
            working = original.with_name(f"{original.stem}-decoded.st")
        working.write_bytes(report.sectors)
        warnings = [
            f"{original.name} was decoded from an SPS capture. "
            f"{report.recovered:,} of {report.expected:,} standard sectors were "
            "recovered; anything the capture holds that a sector image cannot "
            "represent is not in this image."
        ]
        warnings.extend(report.warnings[:20])
        if len(report.warnings) > 20:
            warnings.append(
                f"{len(report.warnings) - 20} further track warnings were not listed."
            )
        return working, self.identify_kind(working), warnings

    def _scp_round_trips(self, working: Path, original: Path, kind: str) -> bool:
        """Confirm HxCFE can re-encode these sectors before allowing edits.

        An SCP capture that cannot be rebuilt from its own decoded sectors is
        opened read-only rather than risking a save the user cannot verify.
        """
        probe = working.parent / "scp-open-check.scp"
        probe.unlink(missing_ok=True)
        try:
            self._flux.encode_from_sectors(
                working, SCP, probe, kind=kind, reference=original
            )
            return self._flux.decodes_back_to(probe, working, kind)
        except DiskError:
            return False
        finally:
            probe.unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Target hardware
    # ------------------------------------------------------------------
    #: What an image is being prepared for, and what that claim means.
    TARGET_HARDWARE = {
        "auto": "no particular medium",
        "floppy": "a GEMDOS floppy",
        "hd": "a partitioned hard disk",
        "volume": "a bare partition image",
        "tos": "a TOS ROM",
    }

    @staticmethod
    def _target_hardware(value: str | None) -> str:
        profile = str(value or "auto").strip().lower()
        if profile not in DiskService.TARGET_HARDWARE:
            raise DiskError("Unknown Atari target hardware profile.")
        return profile

    #: Which session kinds each target claim is true of.
    TARGET_KINDS = {
        "floppy": {"gemdos", "msa", "dim", "stx"},
        "hd": {"hd"},
        "volume": {"gemdos"},
        "tos": {"tosrom"},
    }

    def _apply_target_hardware(self, session: ImageSession) -> None:
        """Check a volume against the medium it is destined for.

        The check is a statement rather than a repair. What can go wrong is
        a claim that does not match the image: a floppy target on a hard disk
        image, or a partition larger than the TOS release the user named will
        mount. Nothing is reformatted, because silently reformatting a volume
        would destroy exactly the data the user is trying to move.
        """
        if session.target_hardware == "auto":
            return
        allowed = self.TARGET_KINDS.get(session.target_hardware, set())
        if session.kind not in allowed:
            self._append_warning(
                session,
                f"This image was opened as {session.kind} but is marked for "
                f"{self.TARGET_HARDWARE[session.target_hardware]}.",
            )
            return
        if session.target_hardware == "floppy":
            size = session.path.stat().st_size
            if size not in FLOPPY_SIZES:
                self._append_warning(
                    session,
                    f"This volume is {size:,} bytes, which is not one of the floppy "
                    "formats a TOS machine's drive can write.",
                )
        if session.target_hardware == "hd":
            for partition in self.list_partitions(session):
                if int(partition.get("sizeBytes") or 0) > TOS_PARTITION_LIMIT:
                    self._append_warning(
                        session,
                        f"Partition {partition.get('name')} is "
                        f"{int(partition['sizeBytes']) // MIB:,} MiB. TOS 1.04 mounts "
                        f"at most {TOS_PARTITION_LIMIT // MIB} MiB per partition; "
                        "later releases and replacement drivers go further.",
                    )

    # ------------------------------------------------------------------
    # Saving and exporting
    # ------------------------------------------------------------------
    @staticmethod
    def _optimise_sparse_file(path: Path) -> None:
        """Turn allocated zero ranges into holes without changing file bytes."""
        try:
            original = path.stat()
            subprocess.run(
                ["fallocate", "--dig-holes", str(path)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            os.utime(
                path,
                ns=(original.st_atime_ns, original.st_mtime_ns),
                follow_symlinks=False,
            )
        except (OSError, subprocess.CalledProcessError):
            # Sparse optimisation is an optional performance improvement. The
            # image remains valid on filesystems or platforms without it.
            return

    def prepare_download(
        self,
        session: ImageSession,
        progress: progress_module.Progress | None = None,
    ) -> Path:
        """Finalise an image so the downloaded bytes are hardware-ready."""
        report = progress_module.reporter(progress)
        total = 2
        report("Checking the image against its target medium", 0, total)
        if session.kind == "hd":
            self._optimise_sparse_file(session.path)
        if session.hfe_original_path:
            report("Encoding and verifying the HFE image", 1, total)
            output = self._prepare_hfe_download(session)
            report("The hardware-ready image is prepared", total, total)
            return output
        if session.scp_original_path:
            report("Encoding and verifying the SCP flux image", 1, total)
            output = self._prepare_scp_download(session)
            report("The hardware-ready image is prepared", total, total)
            return output
        report("The hardware-ready image is prepared", total, total)
        return session.path

    def _prepare_hfe_download(self, session: ImageSession) -> Path:
        return self._prepare_flux_download(session, HFE)

    def _prepare_scp_download(self, session: ImageSession) -> Path:
        return self._prepare_flux_download(session, SCP)

    def _prepare_flux_download(
        self,
        session: ImageSession,
        container: FluxContainer,
    ) -> Path:
        """Re-encode an edited flux image, or hand back the untouched original.

        Both containers follow the same rule: an unedited session downloads the
        bytes it was opened from, and an edited one is only released after the
        new container decodes back to exactly the sectors on screen.
        """
        original = getattr(session, f"{container.identifier}_original_path")
        export_attribute = f"{container.identifier}_export_path"
        if not session.dirty:
            existing = getattr(session, export_attribute)
            if existing and existing.is_file():
                return existing
            return original
        self.require_writable_geometry(session)
        output = session.path.parent / (
            f"{Path(session.name).stem}-edited{container.extension}"
        )
        self._flux.encode_and_verify(
            session.path,
            container,
            output,
            kind=session.kind,
            reference=original,
            failure_message=(
                f"The edited sectors did not survive {container.display} encoding "
                f"exactly, so the original {container.display} was left unchanged."
            ),
        )
        setattr(session, export_attribute, output)
        return output

    @staticmethod
    def is_bare_hard_drive(session: ImageSession, size: int | None = None) -> bool:
        """Whether this is one volume too large to be a floppy.

        A partitioned drive opens as ``hd`` and is never this. What this
        recognises is the bare volume: a single FAT filesystem at sector zero
        that fills a hard disk, which TOS mounts through a driver rather than
        through the floppy BIOS.
        """
        if session.kind != "gemdos":
            return False
        measured = session.path.stat().st_size if size is None else int(size)
        return measured not in FLOPPY_SIZES and measured > 2 * MIB

    def export_formats(self, session: ImageSession) -> list[dict]:
        """List the containers this image's sectors can be written back out as.

        Export is independent of how the image was opened. A GEMDOS volume can
        always be written back as its own sector image, and a floppy-shaped one
        can also be wrapped as an MSA or a DIM, or as HFE or SCP flux when
        HxCFE has a loader for its geometry.
        """
        if session.kind not in {"gemdos", "hd", "unknown"}:
            return []
        size = session.path.stat().st_size
        if session.kind == "unknown" and size not in FLOPPY_SIZES:
            return []
        native_extension = "img" if session.kind == "hd" else "st"
        formats = [{
            "format": "native",
            "extension": native_extension,
            "label": f"Native sector image (.{native_extension})",
        }]
        if session.kind in {"gemdos", "unknown"} and size in FLOPPY_SIZES:
            formats.append({
                "format": "msa",
                "extension": "msa",
                "label": "Magic Shadow Archiver image (.msa)",
            })
            formats.append({
                "format": "dim",
                "extension": "dim",
                "label": "FastCopy Pro image (.dim)",
            })
        if is_flux_encodable(session.kind, size):
            formats.extend(
                {
                    "format": container.identifier,
                    "extension": container.extension.lstrip("."),
                    "label": container.label,
                }
                for container in FLUX_CONTAINERS.values()
            )
        return formats

    def export_image(self, session: ImageSession, target_format: str) -> tuple[Path, str]:
        """Convert this image's current sectors to another compatible container."""
        with session.lock:
            available = {entry["format"] for entry in self.export_formats(session)}
            if target_format not in available:
                raise DiskError(f"“{target_format}” is not an available export format for this image.")
            stem = self.safe_filename(Path(session.name).stem) or "image"
            if target_format == "native":
                extension = "img" if session.kind == "hd" else "st"
                output = session.path.parent / f"{stem}-export.{extension}"
                shutil.copyfile(session.path, output)
                return output, output.name
            if target_format in {"msa", "dim"}:
                return self._export_container(session, stem, target_format)
            container = FLUX_CONTAINERS[target_format]
            output = session.path.parent / f"{stem}-export{container.extension}"
            self._flux.encode_and_verify(
                session.path,
                container,
                output,
                kind=session.kind,
                failure_message=(
                    f"The exported {container.display} image did not decode back to "
                    "identical sectors, so the export was discarded."
                ),
            )
            return output, output.name

    def _export_container(
        self, session: ImageSession, stem: str, target_format: str
    ) -> tuple[Path, str]:
        """Wrap the current sectors as an MSA or a DIM.

        Both containers store whole tracks, so the shape of the disk has to be
        known before one can be written. It is read from the boot sector's own
        parameter block, with the file size as a cross-check, which is what
        makes a single-sided or eleven-sector disk come out the shape it went
        in rather than the shape the size alone suggests.
        """
        from .dim import DIMError, st_to_dim
        from .msa import MSAError, st_to_msa

        data = session.path.read_bytes()
        geometry = resolve_geometry(len(data), data[:512])
        if geometry is None:
            raise DiskError(
                "The shape of this disk could not be established from its boot "
                "sector or its size, so it cannot be written as a track-based "
                "container."
            )
        try:
            payload = (
                st_to_msa(data, geometry)
                if target_format == "msa"
                else st_to_dim(data, geometry)
            )
        except (MSAError, DIMError) as exc:
            raise DiskError(str(exc)) from exc
        output = session.path.parent / f"{stem}-export.{target_format}"
        output.write_bytes(payload)
        return output, output.name

    def mark_saved(self, session: ImageSession) -> None:
        """Record that the current working bytes have been prepared for download."""
        with session.lock:
            session.dirty = False
            self._persist_session(session)

    @staticmethod
    def _copy_stream(stream: BinaryIO, target: Path) -> None:
        """Use an in-kernel copy for spooled uploads, with a portable fallback."""
        seekable = getattr(stream, "seekable", lambda: False)()
        start = stream.tell() if seekable else None
        with target.open("wb") as output:
            try:
                source_fd = stream.fileno()
                while os.sendfile(output.fileno(), source_fd, None, COPY_BUFFER_SIZE):
                    pass
                return
            except (AttributeError, io.UnsupportedOperation, OSError):
                output.seek(0)
                output.truncate()
                if start is not None:
                    stream.seek(start)
                shutil.copyfileobj(stream, output, length=COPY_BUFFER_SIZE)

    @staticmethod
    def _copy_local_file(source: Path, target: Path) -> None:
        """Clone or sparsely copy a local image without allocating zero ranges."""
        try:
            import fcntl

            with source.open("rb") as source_file, target.open("wb") as target_file:
                fcntl.ioctl(target_file.fileno(), FICLONE, source_file.fileno())
            return
        except OSError:
            target.unlink(missing_ok=True)
        try:
            subprocess.run(
                [
                    "cp",
                    "--reflink=auto",
                    "--sparse=always",
                    "--",
                    str(source),
                    str(target),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return
        except (OSError, subprocess.CalledProcessError):
            target.unlink(missing_ok=True)
        shutil.copyfile(source, target)

    def preview_image_contents(
        self,
        session: ImageSession,
        limit: int = 500,
    ) -> dict:
        """Return a bounded, read-only preview suitable for an import plan."""
        limit = max(1, min(int(limit), 1000))
        if session.kind == "rom":
            rows = self.list_rom_banks(session)
            return {
                "entries": [{
                    "path": f"Bank {row['bank']:03d}",
                    "name": row["name"],
                    "type": "ROM bank",
                    "size": row["length"],
                    "detail": row["filetype"],
                } for row in rows[:limit]],
                "total": len(rows),
                "truncated": len(rows) > limit,
                "summary": f"{len(rows)} ROM bank(s) of {session.rom_bank_size:,} bytes",
            }
        if session.kind == "tosrom":
            listing = self.list_directory(session, "")
            rows = listing["entries"]
            return {
                "entries": [{
                    "path": row["path"],
                    "name": row["name"],
                    "type": "TOS ROM segment",
                    "size": row["length"],
                    "detail": str(row.get("detail") or ""),
                } for row in rows[:limit]],
                "total": len(rows),
                "truncated": len(rows) > limit,
                "summary": f"{len(rows)} segment(s) in {listing['title']}",
            }
        if session.kind in CONTAINER_KINDS:
            members = self.container_members(session)
            return {
                "entries": [
                    {
                        "path": "",
                        "name": member["name"],
                        "type": "track",
                        "size": member["length"],
                        "detail": "complete" if member["complete"] else "incomplete",
                    }
                    for member in members[:limit]
                ],
                "total": len(members),
                "truncated": len(members) > limit,
                "summary": f"{len(members)} track(s) in a {CONTAINER_KINDS[session.kind]}",
            }

        entries: list[dict] = []
        pending: list[str] = [""]
        visited: set[str] = set()
        truncated = False
        while pending:
            path = pending.pop(0)
            if path.casefold() in visited:
                continue
            visited.add(path.casefold())
            listing = self.list_directory(session, path)
            for row in listing["entries"]:
                if len(entries) >= limit:
                    truncated = True
                    break
                name = str(row.get("name") or "Untitled")
                item_path = atari_paths.join(path, name)
                entries.append({
                    "path": path,
                    "name": name,
                    "type": row.get("type", "file"),
                    "size": row.get("length"),
                    "detail": str(row.get("attributes") or ""),
                })
                if self.mountable(session) and row.get("type") == "dir":
                    pending.append(item_path)
            if truncated:
                break
        return {
            "entries": entries,
            "total": len(entries),
            "truncated": truncated or bool(pending),
            "summary": f"{len(entries)} visible object(s)" + (" or more" if truncated else ""),
        }

    # ------------------------------------------------------------------
    # Creating blank media
    # ------------------------------------------------------------------
    @staticmethod
    def parse_capacity(text: object, default: int) -> int:
        """Read a capacity a person typed, such as ``32MB`` or ``512M``."""
        raw = str(text or "").strip().lower().replace(" ", "").replace("ib", "b")
        if not raw:
            return default
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(k|kb|m|mb|g|gb)?", raw)
        if not match:
            raise DiskError(
                "A capacity is a number with an optional unit, such as 32MB or 512MB."
            )
        amount = float(match.group(1))
        scale = {
            None: 1, "k": 1024, "kb": 1024,
            "m": MIB, "mb": MIB,
            "g": 1024 * MIB, "gb": 1024 * MIB,
        }[match.group(2)]
        value = int(amount * scale)
        if value <= 0:
            raise DiskError("A capacity must be greater than zero.")
        return value

    def create_blank(
        self,
        format_name: str,
        title: str,
        capacity: str | None = None,
        target_hardware: str = "auto",
        options: dict | None = None,
    ) -> ImageSession:
        """Create a new empty image of one of the shapes TOS can read."""
        options = dict(options or {})
        format_name = str(format_name or "").strip().lower()
        image_id = uuid.uuid4().hex
        folder = self.work_dir / image_id
        folder.mkdir()
        try:
            if format_name in HFE_FORMATS:
                session = self._create_blank_hfe(
                    image_id, folder, format_name, title, options
                )
            elif format_name in FLOPPY_FORMATS:
                session = self._create_blank_floppy(
                    image_id, folder, format_name, title, options
                )
            elif format_name == "hd":
                session = self._create_blank_hard_disk(
                    image_id, folder, title, capacity, options
                )
            elif format_name == "volume":
                session = self._create_blank_volume(
                    image_id, folder, title, capacity
                )
            elif format_name in {"rom", "cartridge"}:
                session = self._create_blank_rom(
                    image_id, folder, format_name, title, options
                )
            else:
                raise DiskError(
                    "Unknown blank image format. Choose a floppy format such as "
                    "ds-720k, an HFE wrapper, hd, volume, rom or cartridge."
                )
            session.target_hardware = self._target_hardware(
                self._blank_target_hardware(format_name, target_hardware)
            )
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        if session.kind == "gemdos":
            self.refresh_gemdos_capabilities(session)
        with self._lock:
            self.sessions[session.id] = session
        self._persist_session(session)
        return session

    def _format_floppy_image(
        self, path: Path, geometry_name: str, label: str, *, bootable: bool
    ) -> None:
        """Write an empty FAT12 volume of a named floppy geometry."""
        try:
            from atarinut.filesystem import format_volume, named_geometry, reader_for
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise DiskError("The Atarinut format API is unavailable.") from exc
        geometry = named_geometry(geometry_name)
        with path.open("wb") as image:
            image.truncate(geometry.size_bytes)
        reader = reader_for(path, writable=True)
        try:
            format_volume(
                reader, label=label, geometry=geometry, bootable=bootable
            )
        except Exception as exc:
            raise DiskError(self._friendly_engine_error(str(exc))) from exc
        finally:
            reader.close()

    @staticmethod
    def _volume_label(title: str) -> str:
        """Fold a requested title into the eleven characters a label holds."""
        try:
            from atarinut.filesystem import validate_label
        except ImportError:  # pragma: no cover - packaging failure
            return str(title or "")[:11]
        candidate = "".join(
            character
            for character in str(title or "").upper()
            if character.isalnum() or character in "!#$%&'()-@^_`{}~ "
        ).strip()[:11]
        try:
            return validate_label(candidate)
        except Exception:
            return ""

    def _create_blank_floppy(
        self, image_id: str, folder: Path, geometry_name: str, title: str, options: dict
    ) -> ImageSession:
        """Create one empty floppy image of a named geometry."""
        label = self._volume_label(title)
        path = folder / f"{self.safe_filename(title) or 'blank'}.st"
        self._format_floppy_image(
            path, geometry_name, label, bootable=bool(options.get("bootable"))
        )
        session = ImageSession(image_id, path.name, "gemdos", path, dirty=True)
        if options.get("bootable"):
            session.warnings.append(
                "The boot sector is executable and its checksum is set to 0x1234, so "
                "a TOS machine will run it. It contains no loader yet."
            )
        return session

    def _create_blank_hfe(
        self, image_id: str, folder: Path, format_name: str, title: str, options: dict
    ) -> ImageSession:
        """Create a blank floppy and wrap it as an HxC flux container.

        The sectors are written to a ``.st`` first because that suffix is how
        HxCFE selects the ST loader, and the loader is what reads the BIOS
        parameter block and settles the geometry it encodes. A blank image
        without a correct parameter block would be wrapped at the wrong shape.
        """
        geometry_name = HFE_FORMATS[format_name]
        session = self._create_blank_floppy(
            image_id, folder, geometry_name, title, options
        )
        original = folder / f"{self.safe_filename(title) or 'blank'}.hfe"
        self._flux.encode_from_sectors(session.path, HFE, original, kind=session.kind)
        header = parse_hfe_header(original.read_bytes()[:512])
        session.name = original.name
        session.hfe_original_path = original
        session.hfe_version = header.version
        session.warnings.append(
            f"Created an editable HFE {header.version} container around a "
            f"{geometry_name} floppy."
        )
        return session

    def _partition_plan(
        self, total_bytes: int, label: str, options: dict
    ) -> list[dict]:
        """Divide a new drive into partitions TOS can mount.

        Four equal partitions is the default because that is what AHDI's own
        root sector holds without chaining, and each is capped at 256 MiB so
        the drive works under TOS 1.04 as well as later releases. A drive
        larger than the four capped partitions cover simply leaves the
        remainder unallocated rather than silently building something the
        target machine cannot mount.
        """
        try:
            count = int(options.get("partitions", 4))
        except (TypeError, ValueError) as exc:
            raise DiskError("The number of partitions must be a whole number.") from exc
        if not 1 <= count <= 14:
            raise DiskError("A drive can hold from one to fourteen partitions.")
        usable = total_bytes - 512
        share = min(TOS_PARTITION_LIMIT, (usable // count) & ~511)
        if share < 64 * 1024:
            raise DiskError(
                f"{count} partitions leave too little room on a "
                f"{total_bytes // MIB:,} MiB drive."
            )
        base = (label or "DISK")[:10] or "DISK"
        return [
            {
                "label": base if count == 1 else f"{base}{index}"[:11],
                "size_bytes": share,
                "bootable": index == 0,
            }
            for index in range(count)
        ]

    def _create_blank_hard_disk(
        self, image_id: str, folder: Path, title: str, capacity: str | None, options: dict
    ) -> ImageSession:
        """Create a partitioned hard-disk image and format every partition."""
        try:
            from atarinut.filesystem import create_partitioned_image
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise DiskError("The Atarinut partitioning API is unavailable.") from exc
        scheme = str(options.get("scheme") or "ahdi").strip().lower()
        if scheme not in PARTITION_SCHEMES:
            raise DiskError("A new hard disk uses either the AHDI or the MBR scheme.")
        total = self.parse_capacity(capacity or options.get("size"), 32 * MIB)
        if total < MIB:
            raise DiskError("A hard-disk image is at least 1 MiB.")
        label = self._volume_label(title)
        plan = self._partition_plan(total, label, options)
        path = folder / f"{self.safe_filename(title) or 'harddisk'}.img"
        try:
            disk = create_partitioned_image(
                path,
                total,
                plan,
                bootable=bool(options.get("bootable", True)),
                scheme=scheme,
            )
        except Exception as exc:
            raise DiskError(self._friendly_engine_error(str(exc))) from exc
        session = ImageSession(image_id, path.name, "hd", path, dirty=True, partition=0)
        session.warnings.append(
            f"Created a {scheme.upper()} hard disk of {total // MIB:,} MiB with "
            f"{len(disk.partitions)} partition{'s' if len(disk.partitions) != 1 else ''}."
        )
        for note in disk.notes:
            session.warnings.append(str(note))
        self._optimise_sparse_file(path)
        return session

    def _create_blank_volume(
        self, image_id: str, folder: Path, title: str, capacity: str | None
    ) -> ImageSession:
        """Create one bare FAT16 volume with no partition table above it.

        This is what a driver hands TOS when a drive holds a single filesystem
        starting at sector zero. It has no table, so the geometry has to come
        from the boot sector, which is what the engine writes here.
        """
        try:
            from atarinut.filesystem import (
                format_volume,
                partition_geometry,
                reader_for,
            )
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise DiskError("The Atarinut format API is unavailable.") from exc
        total = self.parse_capacity(capacity, 32 * MIB)
        if total < MIB:
            raise DiskError("A bare volume image is at least 1 MiB.")
        total -= total % 512
        label = self._volume_label(title)
        path = folder / f"{self.safe_filename(title) or 'volume'}.img"
        with path.open("wb") as image:
            image.truncate(total)
        reader = reader_for(path, writable=True)
        try:
            geometry = partition_geometry(total // 512, label=label)
            volume = format_volume(reader, label=label, geometry=geometry)
            notes = list(volume.notes)
        except Exception as exc:
            raise DiskError(self._friendly_engine_error(str(exc))) from exc
        finally:
            reader.close()
        session = ImageSession(image_id, path.name, "gemdos", path, dirty=True)
        session.warnings.append(
            f"Created a bare {geometry.format} volume of {total // MIB:,} MiB with "
            f"{geometry.sector_size:,}-byte logical sectors."
        )
        session.warnings.extend(str(note) for note in notes)
        self._optimise_sparse_file(path)
        return session

    def _create_blank_rom(
        self, image_id: str, folder: Path, format_name: str, title: str, options: dict
    ) -> ImageSession:
        """Create a blank banked ROM, or a structurally valid cartridge."""
        erase_byte = int(options.get("eraseByte", 0xFF)) & 0xFF
        if format_name == "cartridge":
            bank_size = 128 * 1024
            total_size = bank_size
            template = "cartridge"
        else:
            try:
                bank_size = validate_bank_size(int(options.get("bankSize", DEFAULT_BANK_SIZE)))
                total_size = int(options.get("totalSize", bank_size))
            except (TypeError, ValueError, RomError) as exc:
                raise DiskError(str(exc) or "Choose valid ROM dimensions.") from exc
            template = str(options.get("template") or "blank")
            if template == "cartridge" and bank_size > 128 * 1024:
                raise DiskError("A cartridge ROM bank is at most 128 KiB.")
        if total_size < 1 or total_size > MAX_ROM_SIZE:
            raise DiskError("ROM images must contain between 1 byte and 64 MiB.")
        path = folder / f"{self.safe_filename(title) or 'blank'}.rom"
        try:
            first = (
                make_cartridge_rom(bank_size, title, erase_byte)
                if template == "cartridge"
                else bytes((erase_byte,)) * min(bank_size, total_size)
            )
        except RomError as exc:
            raise DiskError(str(exc)) from exc
        with path.open("wb") as image:
            image.write(first[:total_size])
            remaining = total_size - len(first)
            chunk = bytes((erase_byte,)) * min(COPY_BUFFER_SIZE, max(0, remaining))
            while remaining > 0:
                part = chunk[:remaining]
                image.write(part)
                remaining -= len(part)
        return ImageSession(
            image_id, path.name, "rom", path, dirty=True,
            rom_bank_size=bank_size,
            rom_erase_byte=erase_byte,
            rom_platform=validate_platform(
                options.get("platform") or ("cartridge" if template == "cartridge" else "tos")
            ),
            rom_layout=validate_layout(options.get("layout")),
            rom_component_names=[
                self.safe_filename(name)
                for name in options.get("componentNames", [])
                if name
            ],
        )

    @staticmethod
    def _blank_target_hardware(format_name: str, requested: str | None) -> str:
        """Apply only target profiles that are meaningful for a new format."""
        if format_name == "hd":
            return "hd"
        if format_name == "volume":
            return "volume"
        if format_name in {"rom", "cartridge"}:
            return "auto"
        # Every floppy is the same disk on every ST, so the machine a new one
        # is meant for is not a choice the format makes.
        requested = str(requested or "auto")
        return requested if requested in {"auto", "floppy"} else "floppy"

    # ------------------------------------------------------------------
    # Session bookkeeping
    # ------------------------------------------------------------------
    def set_source_name(self, session: ImageSession, path: str, source_name: str) -> None:
        session.source_names[str(path)] = str(source_name).replace("\\", "/")[-500:]
        self._persist_session(session)

    def set_distribution_name(self, session: ImageSession, source_name: str) -> None:
        session.distribution_name = str(source_name).replace("\\", "/")[-500:]
        self._persist_session(session)

    def _mark_mutated(self, session: ImageSession) -> None:
        """Record that this image has been edited since it was opened.

        The volume's own description is re-read as well. A write can change
        the label, the free cluster count or the boot sector's executable
        word sum, and a report that still showed the values from before the
        edit would be describing an image that no longer exists.
        """
        session.dirty = True
        session.hfe_export_path = None
        session.scp_export_path = None
        session.content_kind_cache.clear()
        if self.mountable(session):
            self.refresh_gemdos_capabilities(session)

    def resolve(self, session: ImageSession) -> Path:
        """Return the working file the engine should be pointed at."""
        return session.path

    @staticmethod
    def inner_for(session: ImageSession, inner: str, side: int | None = None) -> str:
        """Return the inner path the engine should be given.

        ``side`` is accepted because callers still pass it and is ignored: a
        GEMDOS volume is one filesystem whether the disk it sits on is
        recorded on one side or two.
        """
        del side
        if session.kind == "tosrom":
            return "" if atari_paths.is_root(inner) else str(inner)
        return atari_paths.normalise(inner)

    @staticmethod
    def compound(path: Path, inner: str | None = None) -> str:
        return f"{path}:{inner}" if inner is not None else str(path)

    @staticmethod
    def _capacity_from_mount(mount) -> dict:
        try:
            total = max(0, int(mount.size_bytes()))
            free = min(total, max(0, int(mount.free_bytes())))
        except (AttributeError, TypeError, ValueError):
            return {
                "available": False,
                "reason": "This filesystem does not report free-space capacity.",
            }
        return {
            "available": total > 0,
            "unit": "bytes",
            "total": total,
            "used": total - free,
            "free": free,
        }

    def _listing_content_kind(
        self,
        session: ImageSession,
        side: int | None,
        path: str,
        row: dict,
        reader: Callable[[], bytes],
    ) -> str | None:
        """Classify one listed file without remounting or reading large payloads."""
        hint = metadata_kind(str(row.get("name") or ""), row.get("filetype"))
        if hint:
            return hint
        length = int(row.get("length") or 0)
        if length <= 0 or length > LISTING_SNIFF_LIMIT:
            return None
        key = (
            side, str(path).casefold(), length,
            str(row.get("attributes") or ""), str(row.get("filetype") or ""),
        )
        cached = session.content_kind_cache.get(key)
        if cached:
            return cached
        try:
            kind = analyse_content(reader(), path)[0]
        except Exception:
            # A damaged or unusually encoded file must not prevent its parent
            # directory from being listed. It can still be inspected on open.
            return None
        session.content_kind_cache[key] = kind
        return kind

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------
    def partition_index(self, session: ImageSession) -> dict:
        """List a hard disk's partitions in the same shape as a directory.

        A drive that has not had a partition chosen shows its partition table,
        which is what TOS sees before it mounts anything. Each row is presented
        as a folder so the pane can be opened into exactly as a directory is,
        and carries the drive letter, the three-letter identifier or MBR type
        code, and the boot flag the table declares.
        """
        table = self.partition_table(session)
        partitions = list(table.get("partitions") or [])
        rows = [
            {
                "name": str(partition.get("device") or partition.get("name") or f"Partition {index}"),
                "type": "dir",
                "attributes": "",
                "attributeBits": 0,
                "attr": "bootable" if partition.get("bootable") else "",
                "filetype": "",
                "datestamp": "",
                "length": int(partition.get("sizeBytes") or 0),
                "label": str(partition.get("label") or ""),
                "id": str(partition.get("id") or ""),
                "typeCode": partition.get("typeCode"),
                "startSector": int(partition.get("startSector") or 0),
                "sizeSectors": int(partition.get("sizeSectors") or 0),
                "byteSwapped": bool(partition.get("byteSwapped")),
                "bootable": bool(partition.get("bootable")),
                "gemdos": bool(partition.get("gemdos")),
                "partition": index,
            }
            for index, partition in enumerate(partitions)
        ]
        scheme = str(table.get("scheme") or "ahdi").upper()
        description = (
            f"{scheme} table · {len(rows)} partition{'s' if len(rows) != 1 else ''}"
        )
        if table.get("byteSwapped"):
            description += " · byte-swapped image"
        return {
            "entries": rows,
            "title": session.name,
            "description": description,
            "path": "",
            "scheme": str(table.get("scheme") or "ahdi"),
            "byteSwapped": bool(table.get("byteSwapped")),
            "hdSize": int(table.get("hdSize") or 0),
        }

    def _list_gemdos_mount(self, mount, inner: str, session: ImageSession) -> dict:
        """Return the same stable row schema as ``python -m atarinut ls --as json``."""
        target = inner or ""
        if not mount.exists(target):
            raise DiskError(f"Path not found: {target}")
        if not mount.stat(target).is_dir:
            raise DiskError(f"{target} is not a directory.")

        rows: list[dict] = []
        for child in sorted(
            mount.iter_entries(target), key=lambda entry: natural_name_key(entry.name)
        ):
            bits = int(child.attributes or 0)
            attributes = format_attributes(bits)
            stamp = child.datestamp
            datestamp = (
                stamp.isoformat(sep="T", timespec="milliseconds") if stamp else ""
            )
            row = {
                "name": child.name,
                "path": str(child.path),
                "type": "dir" if child.is_dir else "file",
                "attributes": attributes,
                "attributeBits": bits,
                "attr": attributes,
                "datestamp": datestamp,
                "length": int(child.length),
                "filetype": "" if child.is_dir else (mount.filetype(child.path) or ""),
            }
            if child.is_dir:
                # A directory entry's length field is meaningless on a FAT
                # volume, so the useful number is how many entries it holds.
                # A damaged entry that points outside the volume must not
                # stop the rest of its parent being listed, which is exactly
                # the state a cracked or partly overwritten game disk is
                # often found in.
                try:
                    row["length"] = sum(1 for _entry in mount.iter_entries(child.path))
                except Exception as exc:
                    row["length"] = 0
                    row["damaged"] = self._friendly_engine_error(str(exc))
            if not child.is_dir:
                content_kind = self._listing_content_kind(
                    session, None, str(child.path), row,
                    lambda child_path=str(child.path): mount.read_bytes(child_path),
                )
                if content_kind:
                    row["contentKind"] = content_kind
            rows.append(row)

        capacity = DiskService._capacity_from_mount(mount)
        free = capacity.get("free")
        listing = {
            "entries": rows,
            "title": str(getattr(mount, "title", "") or session.name),
            "description": f"Free: {free:,} bytes" if isinstance(free, int) else "",
            "path": target,
            "capacity": capacity,
        }
        if not atari_paths.split(target):
            # Only the root directory has a fixed entry count, because it is a
            # fixed area written at format time. A subdirectory is an ordinary
            # cluster chain and grows as long as there are free clusters.
            limit = (session.gemdos_capabilities or {}).get("directoryEntryLimit")
            if isinstance(limit, int) and limit > 0:
                listing["directoryEntryLimit"] = limit
                listing["directoryEntriesUsed"] = len(rows)
        return listing

    def browse_directory(
        self,
        session: ImageSession,
        inner: str,
        side: int | None = None,
    ) -> dict:
        """List one directory and return its capacity without a second mount."""
        del side
        if self.mountable(session):
            with self.gemdos_mount(session, writable=False) as mount:
                return self._list_gemdos_mount(
                    mount, atari_paths.normalise(inner or ""), session
                )
        listing = self.list_directory(session, inner)
        listing.setdefault("capacity", self.capacity(session))
        return listing

    def list_directory(
        self, session: ImageSession, inner: str, side: int | None = None
    ) -> dict:
        del side
        if session.kind == "rom":
            if not atari_paths.is_root(inner):
                raise DiskError("ROM images contain banks, not directories.")
            rows = self.list_rom_banks(session)
            partial = session.path.stat().st_size % session.rom_bank_size
            description = (
                f"{len(rows)} bank{'s' if len(rows) != 1 else ''} × {session.rom_bank_size:,} bytes"
                + (f" · final bank has {partial:,} bytes" if partial else "")
            )
            return {"entries": rows, "title": session.name, "description": description, "path": ""}
        if session.kind == "tosrom":
            return self._list_tosrom(session, inner)
        if session.kind == "iso":
            return self.iso_listing(session, inner)
        if session.kind in CONTAINER_KINDS:
            return self._list_container(session, inner)
        if session.kind == "hd" and session.partition is None:
            return self.partition_index(session)
        if self.mountable(session):
            with self.gemdos_mount(session, writable=False) as mount:
                return self._list_gemdos_mount(
                    mount, atari_paths.normalise(inner or ""), session
                )
        raise DiskError("This image does not contain a directory that can be listed.")

    def _list_tosrom(self, session: ImageSession, inner: str) -> dict:
        """List the segments a TOS ROM is made of.

        A TOS ROM is not a directory tree. What the workbench shows is the
        parts the header and the dispatch table identify, which is as close to
        a listing as a linked ROM image has.
        """
        if not atari_paths.is_root(inner):
            raise DiskError("A TOS ROM is flat and does not contain directories.")
        rows = []
        with self.tosrom_mount(session) as mount:
            for entry in mount.iter_entries(""):
                row = {
                    "name": entry.name,
                    "path": entry.name,
                    "type": "file",
                    "attributes": "r-----",
                    "attributeBits": 0x01,
                    "attr": "r-----",
                    "filetype": "",
                    "datestamp": "",
                    "length": int(entry.length or 0),
                    "readOnly": True,
                }
                content_kind = self._listing_content_kind(
                    session, None, entry.name, row,
                    lambda name=entry.name: mount.read_bytes(name),
                )
                if content_kind:
                    row["contentKind"] = content_kind
                rows.append(row)
            title = str(mount.title or session.name)
        details = self.tosrom_details(session)
        return {
            "entries": rows,
            "title": title,
            "description": (
                f"TOS ROM {session.path.stat().st_size // 1024} KiB · "
                f"{len(rows)} segment{'s' if len(rows) != 1 else ''} · "
                f"version {details['version']}"
            ),
            "path": "",
        }

    def _list_container(self, session: ImageSession, inner: str) -> dict:
        """List the tracks an MSA, DIM or Pasti container holds."""
        if not atari_paths.is_root(inner):
            raise DiskError("A disk container holds tracks, not directories.")
        rows = []
        for member in self.container_members(session):
            row = {
                "name": member["name"],
                "type": "file",
                "attributes": "r-----",
                "attributeBits": 0x01,
                "attr": "r-----",
                "filetype": "",
                "datestamp": "",
                "length": int(member["length"]),
                "packedLength": int(member.get("packedLength") or 0),
                "complete": bool(member["complete"]),
                "track": member["track"],
                "side": member["side"],
            }
            rows.append(row)
        complete = sum(1 for row in rows if row["complete"])
        return {
            "entries": rows,
            "title": session.name,
            "description": (
                f"{CONTAINER_KINDS[session.kind]} · {len(rows)} track"
                f"{'s' if len(rows) != 1 else ''} · {complete} complete"
            ),
            "path": "",
        }

    def list_volume_files(
        self, session: ImageSession, side: int | None = None
    ) -> list[dict]:
        """Return every file on a mounted volume, directories walked through.

        One mount rather than one engine call per directory: the whole tree is
        walked in process, which is what makes scanning a full hard-disk
        partition take a moment rather than minutes.
        """
        del side
        if not self.mountable(session):
            raise DiskError("Open a GEMDOS volume before listing its files.")
        files: list[dict] = []
        with self.gemdos_mount(session, writable=False) as mount:
            pending = [""]
            while pending:
                directory = pending.pop()
                for entry in sorted(
                    mount.iter_entries(directory),
                    key=lambda item: natural_name_key(item.name),
                ):
                    path = str(entry.path)
                    if entry.is_dir:
                        pending.append(path)
                        continue
                    meta = mount.atari_meta(path)
                    bits = int(meta.attributes or 0)
                    stamp = meta.datestamp
                    row = {
                        "name": entry.name,
                        "type": "file",
                        "attributes": format_attributes(bits),
                        "attributeBits": bits,
                        "attr": format_attributes(bits),
                        "filetype": mount.filetype(path) or "",
                        "datestamp": (
                            stamp.isoformat(sep="T", timespec="milliseconds")
                            if stamp
                            else ""
                        ),
                        "length": int(entry.length),
                        "prefix": atari_paths.parent(path),
                        "path": path,
                    }
                    content_kind = self._listing_content_kind(
                        session, None, path, row,
                        lambda path=path: mount.read_bytes(path),
                    )
                    if content_kind:
                        row["contentKind"] = content_kind
                    files.append(row)
        return files

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def stat(self, session: ImageSession) -> dict:
        disk_path = self.resolve(session)
        return self._run_json(["stat", "--as", "json", str(disk_path)])

    def capacity(self, session: ImageSession) -> dict:
        """Return authoritative writable capacity for a pane-level filesystem."""
        if session.kind == "rom":
            rows = self.list_rom_banks(session)
            used = sum(not row["empty"] for row in rows)
            return {
                "available": True,
                "unit": "banks",
                "total": len(rows),
                "used": used,
                "free": len(rows) - used,
            }
        if session.kind in CONTAINER_KINDS:
            return {
                "available": False,
                "reason": (
                    "A disk container holds a fixed set of tracks and has no free space."
                ),
            }
        if session.kind == "iso":
            # A CD is full by definition and cannot be written to, so the
            # useful number is how much of the disc holds data rather than how
            # much is left, which would always be none.
            total = session.path.stat().st_size
            return {
                "available": True,
                "unit": "bytes",
                "total": total,
                "used": total,
                "free": 0,
                "detail": "read-only CD image",
            }
        if session.kind == "tosrom":
            return self.tosrom_details(session)["capacity"]
        if session.kind == "hd" and session.partition is None:
            table = self.partition_table(session)
            partitions = table.get("partitions") or []
            allocated = sum(int(item.get("sizeBytes") or 0) for item in partitions)
            total = session.path.stat().st_size
            return {
                "available": True,
                "unit": "bytes",
                "total": total,
                "used": allocated,
                "free": max(0, total - allocated),
                "detail": (
                    f"{len(partitions)} partition{'s' if len(partitions) != 1 else ''}"
                ),
            }
        if self.mountable(session):
            with self.gemdos_mount(session, writable=False) as mount:
                return self._capacity_from_mount(mount)
        return {
            "available": False,
            "reason": "This filesystem does not report free-space capacity.",
        }

    def validate(self, session: ImageSession) -> str:
        """Check the structures on this image and report what was found."""
        if session.kind == "rom":
            rows = self.list_rom_banks(session)
            recognised = sum(bool(row["header"]) for row in rows)
            partial = session.path.stat().st_size % session.rom_bank_size
            if partial:
                return (
                    f"ROM bytes are readable · {len(rows)} banks · {recognised} Atari-family header(s) · "
                    f"final bank is partial ({partial:,} bytes)"
                )
            return f"ROM bytes are readable · {len(rows)} complete bank(s) · {recognised} Atari-family header(s)"
        if session.kind in CONTAINER_KINDS:
            members = self.container_members(session)
            incomplete = [member for member in members if not member["complete"]]
            if incomplete:
                return (
                    f"{CONTAINER_KINDS[session.kind]} · {len(members)} track(s) · "
                    f"{len(incomplete)} incomplete"
                )
            return f"Valid {CONTAINER_KINDS[session.kind]} · {len(members)} complete track(s)"
        if session.kind == "tosrom":
            details = self.tosrom_details(session)
            state = "complete" if details["complete"] else "incomplete"
            return (
                f"Valid TOS ROM · version {details['version']} · "
                f"{details['fileCount']} segment(s) · "
                f"{session.path.stat().st_size // 1024} KiB · {state}"
            )
        if session.kind == "hd" and session.partition is None:
            table = self.partition_table(session)
            notes = list(table.get("notes") or [])
            if notes:
                return " · ".join(notes)
            return "No structural errors found"
        if self.mountable(session):
            with self.gemdos_mount(session, writable=False) as mount:
                problems = list(mount.validate())
            if problems:
                return " · ".join(str(problem) for problem in problems)
            return "No structural errors found"
        raise DiskError("This image does not contain a filing system to validate.")

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------
    def mutate(self, session: ImageSession, args: list[str], side: int | None = None) -> None:
        """Run one engine command against the working image."""
        del side
        self.require_writable_geometry(session)
        with session.lock:
            disk_path = self.resolve(session)
            expanded = []
            for part in args:
                if part.startswith("{image}:"):
                    inner = part[len("{image}:") :]
                    expanded.append(self.compound(disk_path, self.inner_for(session, inner)))
                else:
                    expanded.append(part.replace("{image}", str(disk_path)))
            self._run(expanded)
            self._mark_mutated(session)

    @staticmethod
    def validate_directory_path(prefix: str) -> str:
        """Validate and normalise a directory path inside a GEMDOS volume.

        GEMDOS folders nest, so a destination is a full path rather than a
        single name. Every component is checked against the same 8.3 rules
        that apply to a file, because a folder a real machine cannot name is
        no more useful than a file it cannot name.
        """
        from .filename_policy import target_name_policy

        path = atari_paths.normalise(prefix)
        policy = target_name_policy("gemdos")
        for part in atari_paths.split(path):
            policy.validate(part)
        return path

    def make_directory(
        self, session: ImageSession, path: str, side: int | None = None
    ) -> None:
        """Create one folder, building the chain above it if it is missing."""
        del side
        self.require_writable_geometry(session)
        if not self.mountable(session):
            raise DiskError("Folders can only be created inside a mounted GEMDOS volume.")
        target = self.validate_directory_path(path)
        if not target:
            raise DiskError("Enter a name for the new folder.")
        with self.gemdos_mount(session) as mount:
            mount.make_directory(target, parents=True, exist_ok=False)
        self._mark_mutated(session)

    def set_access(
        self,
        session: ImageSession,
        paths: list[str],
        writable: bool,
        side: int | None = None,
    ) -> list[str]:
        """Set or clear the read-only attribute on several entries at once.

        GEMDOS has one bit that stops a file being changed or deleted, and
        that bit is what "locked" means here. The other five attribute bits
        are left exactly as they were, because a lock is not a statement about
        whether a file is hidden or has been archived.
        """
        del side
        self.require_writable_geometry(session)
        targets = list(dict.fromkeys(str(path or "").strip() for path in paths))
        if not targets:
            raise DiskError("Choose at least one file or directory to update.")
        self.require_mounted_volume(session)
        if not self.mountable(session):
            raise DiskError("Attributes can only be set inside a mounted GEMDOS volume.")
        try:
            from atarinut.file import Access
        except ImportError as exc:
            raise DiskError("The Atarinut attribute API is unavailable.") from exc

        with session.lock, self.gemdos_mount(session) as mount:
            resolved = [self.inner_for(session, path) for path in targets]
            for target in resolved:
                if not mount.exists(target):
                    raise DiskError(f"“{target}” no longer exists.")
            for target in resolved:
                current = Access(int(mount.atari_meta(target).attributes or 0))
                mount.set_access(target, current.with_locked(not writable))
        self._mark_mutated(session)
        return targets

    def set_file_metadata(
        self,
        session: ImageSession,
        path: str,
        attributes: str = "",
        comment: str = "",
        side: int | None = None,
        datestamp: str | None = None,
    ) -> dict:
        """Update an entry's attribute byte and datestamp.

        These are the two things GEMDOS lets a person change about a file
        without rewriting it. There is no load or execution address to change:
        a GEMDOS program carries its own relocation table, so where it goes in
        memory is decided when TOS runs it.

        ``datestamp`` is normally left alone, because changing an attribute is
        not a reason to claim the file's contents changed. A caller
        reproducing a recorded image passes the datestamp it recorded, so the
        result matches the image it is meant to reproduce rather than the
        moment it was rebuilt.

        ``comment`` is accepted and ignored: a GEMDOS directory entry has
        nowhere to put one.
        """
        del comment, side
        if session.kind in {"rom", "tosrom"} or session.kind in CONTAINER_KINDS:
            raise DiskError("This view does not contain editable directory entries.")
        self.require_writable_geometry(session)
        if not self.mountable(session):
            raise DiskError("Metadata can only be edited inside a mounted GEMDOS volume.")
        try:
            from atarinut.file import AtariMeta
        except ImportError as exc:
            raise DiskError("The Atarinut directory metadata API is unavailable.") from exc
        parsed = attribute_value(attributes)
        requested_datestamp = self._parse_datestamp(datestamp)

        with session.lock, self.gemdos_mount(session) as mount:
            target = self.inner_for(session, path)
            if not mount.exists(target):
                raise DiskError(f"“{target}” no longer exists.")
            stat = mount.stat(target)
            current = mount.atari_meta(target)
            moment = requested_datestamp or current.datestamp
            mount.set_atari_meta(
                target, AtariMeta(attributes=parsed, datestamp=moment)
            )
            metadata = {
                "attributes": format_attributes(parsed),
                "attributeBits": parsed,
                "datestamp": moment,
                "length": int(stat.length or 0),
            }
        self._mark_mutated(session)
        return metadata

    @staticmethod
    def _parse_datestamp(value: object):
        """Read a recorded ISO datestamp, or None to leave the entry's alone."""
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def put(
        self,
        session: ImageSession,
        destination: str,
        host_path: Path,
        attributes: str | None = None,
        comment: str | None = None,
        filetype: str | None = None,
        side: int | None = None,
        datestamp: str | None = None,
    ) -> None:
        """Import one host file with the metadata GEMDOS actually records.

        A host file arrives with no attribute byte of its own. Whatever the
        caller could establish, from an attribute sidecar, from an
        Atari-written ZIP, or from the source volume in an image-to-image
        copy, is applied here; anything it could not is left at the filing
        system's own default rather than invented.

        ``datestamp`` is normally left alone, so a newly written file carries
        the moment it was written. A caller reproducing a recorded image
        passes the datestamp it recorded instead.

        ``comment`` and ``filetype`` are accepted and ignored: a GEMDOS
        directory entry records neither.
        """
        del comment, filetype, side
        if session.kind == "rom":
            self.put_rom_bank(session, host_path.read_bytes())
            return
        self.require_writable_geometry(session)
        if not self.mountable(session):
            raise DiskError("Files can only be added to a mounted GEMDOS volume.")
        self.validate_directory_path(atari_paths.parent(destination))
        self.validate_leaf_name(session, atari_paths.leaf(destination))
        try:
            from atarinut.file import AtariMeta
        except ImportError as exc:
            raise DiskError("The Atarinut import API is unavailable.") from exc
        requested_datestamp = self._parse_datestamp(datestamp)
        with self.gemdos_mount(session) as mount:
            target = self.inner_for(session, destination)
            mount.write_bytes(target, host_path.read_bytes())
            current = mount.atari_meta(target)
            mount.set_atari_meta(
                target,
                AtariMeta(
                    attributes=(
                        attribute_value(attributes)
                        if attributes
                        else int(current.attributes)
                    ),
                    datestamp=requested_datestamp or current.datestamp,
                ),
            )
        self._mark_mutated(session)

    def put_host_tree(
        self,
        session: ImageSession,
        destination_dir: str,
        items: list[dict],
        *,
        preserve_directories: bool,
        replace: bool = False,
        side: int | None = None,
    ) -> dict:
        """Import a reviewed host folder in one writable filesystem mount.

        Each item contains a validated target path relative to
        ``destination_dir`` and a local temporary ``hostPath``. Keeping the
        complete batch in one mount avoids reopening and checkpointing a large
        image for every small file.
        """
        del side
        self.require_writable_geometry(session)
        if not self.mountable(session):
            raise DiskError("Open a writable GEMDOS volume before importing a host folder.")
        destination_dir = self.validate_directory_path(destination_dir)
        if not items:
            raise DiskError("No relevant files were selected for import.")

        plans: list[dict] = []
        seen: set[str] = set()
        for item in items:
            relative = str(item.get("targetPath") or "").replace("\\", "/").strip("/")
            parts = [part for part in relative.split("/") if part]
            if not parts or any(part in {".", ".."} for part in parts):
                raise DiskError("A selected folder contains an invalid relative path.")
            for part in parts:
                self.validate_leaf_name(session, part)
            destination = atari_paths.join(destination_dir, "\\".join(parts))
            key = destination.casefold()
            if key in seen:
                raise DiskError(f"More than one selected file maps to {destination}.")
            seen.add(key)
            plans.append({**item, "parts": parts, "destination": destination})

        try:
            from atarinut.file import AtariMeta
        except ImportError as exc:
            raise DiskError("The Atarinut folder import API is unavailable.") from exc

        with session.lock, self.gemdos_mount(session) as mount:
            conflicts: list[str] = []
            directories: set[str] = set()
            if preserve_directories:
                for plan in plans:
                    for depth in range(1, len(plan["parts"])):
                        directories.add(
                            atari_paths.SEPARATOR.join(
                                [*atari_paths.split(destination_dir), *plan["parts"][:depth]]
                            )
                        )
            ordered = sorted(
                directories, key=lambda value: (atari_paths.depth(value), value.casefold())
            )
            for directory in ordered:
                if mount.exists(directory) and not mount.stat(directory).is_dir:
                    raise DiskError(
                        f"{directory} is an ordinary file, so a folder cannot be created there."
                    )
            for plan in plans:
                destination = plan["destination"]
                if mount.exists(destination):
                    if mount.stat(destination).is_dir:
                        raise DiskError(
                            f"{destination} is a directory, so a file cannot replace it."
                        )
                    conflicts.append(destination)
            if conflicts and not replace:
                return {"imported": [], "conflicts": conflicts}
            for directory in ordered:
                mount.make_directory(directory, parents=True, exist_ok=True)
            imported: list[str] = []
            for plan in plans:
                parent = atari_paths.parent(plan["destination"])
                if parent and not mount.exists(parent):
                    mount.make_directory(parent, parents=True, exist_ok=True)
                mount.write_bytes(
                    plan["destination"], Path(plan["hostPath"]).read_bytes()
                )
                metadata = plan.get("metadata") or {}
                supplied = metadata.get("attributes", metadata.get("access"))
                stamp = self._parse_datestamp(metadata.get("datestamp"))
                if supplied not in (None, "") or stamp is not None:
                    current = mount.atari_meta(plan["destination"])
                    mount.set_atari_meta(
                        plan["destination"],
                        AtariMeta(
                            attributes=(
                                attribute_value(supplied)
                                if supplied not in (None, "")
                                else int(current.attributes)
                            ),
                            datestamp=stamp or current.datestamp,
                        ),
                    )
                imported.append(plan["destination"])
        self._mark_mutated(session)
        return {"imported": imported, "conflicts": []}

    def copy(
        self,
        source: ImageSession,
        source_inner: str,
        target: ImageSession,
        target_inner: str,
        recursive: bool,
        source_side: int | None = None,
        target_side: int | None = None,
    ) -> None:
        """Copy one entry, or one tree, from any open image into another."""
        del source_side, target_side
        if source.kind == "rom" or target.kind == "rom":
            if recursive:
                raise DiskError("ROM banks are byte images and cannot contain directories.")
            data = (
                self.rom_bank_bytes(source, source_inner)
                if source.kind == "rom"
                else self.read_file(source, source_inner)
            )
            if target.kind == "rom":
                requested_bank = None
                if str(target_inner).lower().startswith(("bank:", "bank-")):
                    try:
                        requested_bank = bank_number(target_inner)
                    except RomError as exc:
                        raise DiskError(str(exc)) from exc
                self.put_rom_bank(target, data, requested_bank)
            else:
                temp_path = self.work_dir / f"rom-copy-{uuid.uuid4().hex}"
                temp_path.write_bytes(data)
                try:
                    self.put(target, target_inner, temp_path)
                finally:
                    temp_path.unlink(missing_ok=True)
            return
        self.require_writable_geometry(target)
        if not self.mountable(target):
            raise DiskError("Files can only be copied into a mounted GEMDOS volume.")
        self.validate_directory_path(atari_paths.parent(target_inner))
        self.validate_leaf_name(target, atari_paths.leaf(target_inner))
        if not self.mountable(source):
            # A read-only view: a CD, a TOS ROM or a container track. Copy the
            # bytes through a host temporary, which is what those views expose.
            data = self.read_file(source, source_inner)
            temp_path = self.work_dir / f"copy-{uuid.uuid4().hex}"
            temp_path.write_bytes(data)
            try:
                self.put(target, target_inner, temp_path)
            finally:
                temp_path.unlink(missing_ok=True)
            return
        with self._locked_sessions(source, target):
            if source.id == target.id:
                with self.gemdos_mount(target) as mount:
                    self._copy_between_mounts(
                        mount, mount, source_inner, target_inner, recursive=recursive
                    )
            else:
                with self.gemdos_mount(source, writable=False) as source_mount:
                    with self.gemdos_mount(target) as target_mount:
                        self._copy_between_mounts(
                            source_mount,
                            target_mount,
                            source_inner,
                            target_inner,
                            recursive=recursive,
                        )
            self._mark_mutated(target)

    def _copy_between_mounts(
        self,
        source_mount,
        target_mount,
        source_inner: str,
        target_inner: str,
        *,
        recursive: bool,
        destination_slash: bool = False,
    ) -> None:
        """Copy one path between two mounted volumes, metadata included.

        The copy descriptors are built by the engine's own bulk-copy helpers
        and then reordered into the source's storage order, so the tree lands
        in the destination laid out the way it was laid out on the source
        rather than interleaved with whatever was written between files.
        """
        from .atarinut_internals import collect_copy_items

        items = collect_copy_items(
            source_mount,
            atari_paths.normalise(source_inner),
            dst_mount=target_mount,
            dst_bare=atari_paths.normalise(target_inner),
            dst_slash=destination_slash,
            recursive=recursive,
            wildcards=False,
        )
        for item in in_storage_order(source_mount, items):
            if item.get("kind") == "mkdir":
                ensure_directory_chain(target_mount, str(item["dst"]))
            else:
                write_copy_item(target_mount, str(item["dst"]), item, True)

    def replace_blank_image(
        self,
        target: ImageSession,
        source: ImageSession,
        source_name: str,
        *,
        target_path: str,
    ) -> bool:
        """Install a floppy image into an empty one of the same or larger size.

        Copying file by file into a blank disk of the same shape is slower and
        loses the source's own boot sector. When the destination is genuinely
        empty and no smaller than the source, replacing its bytes outright is
        both faster and more faithful.
        """
        if (
            target.kind != "gemdos"
            or source.kind != "gemdos"
            or not atari_paths.is_root(target_path)
            or target.path.suffix.lower() != ".st"
            or source.path.suffix.lower() != ".st"
            or self.list_directory(target, "")["entries"]
        ):
            return False
        target_size = target.path.stat().st_size
        if source.path.stat().st_size > target_size:
            return False
        replacement = target.path.parent / f".online-replacement-{uuid.uuid4().hex}.st"
        try:
            with self._locked_sessions(source, target):
                self._copy_local_file(source.path, replacement)
                with replacement.open("ab") as image:
                    image.truncate(target_size)
                replacement.replace(target.path)
                target.name = self.safe_filename(Path(source_name).name)
                target.dirty = True
                target.hfe_export_path = None
                target.finalised_mtime_ns = None
                self._persist_session(target)
        finally:
            replacement.unlink(missing_ok=True)
        return True

    @staticmethod
    def _collect_volume_items(
        source_mount,
        destination: str,
        file_item: Callable,
    ) -> list[dict]:
        """Collect every file on a volume, ready to be written under one folder.

        The whole tree is walked rather than only its root, because a GEMDOS
        volume nests. Directory descriptors are emitted before the files that
        need them, so the destination is built top-down and never has to guess
        at a parent.
        """
        items: list[dict] = []
        order = 0

        def walk(path: str) -> None:
            nonlocal order
            for entry in sorted(
                source_mount.iter_entries(path),
                key=lambda item: natural_name_key(item.name),
            ):
                target = atari_paths.join(
                    destination, atari_paths.normalise(entry.path)
                )
                if entry.is_dir:
                    items.append({"kind": "mkdir", "dst": target, "order": order})
                    order += 1
                    walk(entry.path)
                    continue
                item = file_item(source_mount, entry.path, target)
                item["sourceName"] = atari_paths.normalise(entry.path)
                items.append(item)

        walk("")
        return items

    @staticmethod
    def _is_empty_directory(mount, path: str) -> bool:
        """True when a path exists, is a folder, and holds nothing.

        An empty destination can be reused without asking. A populated one
        cannot, because reusing it would merge two unrelated disks into the
        same folder, so the two cases are told apart before anything is
        written rather than after.
        """
        try:
            if not mount.exists(path):
                return False
            if not mount.stat(path).is_dir:
                return False
            return not any(True for _entry in mount.iter_entries(path))
        except Exception:
            return False

    def extract_image_to_directory(
        self,
        source: ImageSession,
        target: ImageSession,
        target_parent: str,
        directory_name: str | None,
        progress: progress_module.Progress | None = None,
        *,
        create_directory: bool = True,
    ) -> str:
        with self._locked_sessions(source, target):
            return self._extract_image_to_directory(
                source,
                target,
                target_parent,
                directory_name,
                progress,
                create_directory=create_directory,
            )


    def _extract_image_to_directory(
        self,
        source: ImageSession,
        target: ImageSession,
        target_parent: str,
        directory_name: str | None,
        progress: progress_module.Progress | None = None,
        *,
        create_directory: bool = True,
    ) -> str:
        report = progress_module.reporter(progress)
        if not self.mountable(target):
            raise DiskError("Disk images can only be expanded into a mounted GEMDOS volume.")
        self.require_writable_geometry(target)
        target_parent = self.validate_directory_path(target_parent)
        if create_directory:
            directory_name = self.validate_leaf_name(target, directory_name or "")
            target_directory = atari_paths.join(target_parent, directory_name)
        else:
            # Resolve the destination before taking a rollback copy. This also
            # rejects stale browser paths without modifying the image.
            self.list_directory(target, target_parent)
            target_directory = target_parent

        rebuilt: ImageSession | None = None
        if source.kind in CONTAINER_KINDS:
            # A container is a whole floppy, so the honest extraction is to
            # rebuild the disk it was made from and copy that volume's files.
            # Treating its tracks as files would present raw cylinders as
            # though they were software.
            report("Rebuilding the disk from its container tracks", 0, None)
            rebuilt, _rows = self.convert_container(source, "st")
            source = rebuilt
        if not self.mountable(source):
            raise DiskError(
                "This image does not contain a GEMDOS volume that can be extracted."
            )
        if not self.list_directory(source, "")["entries"]:
            if rebuilt is not None:
                self.discard_session(rebuilt)
            raise DiskError("The source disk image is empty. Nothing was extracted.")

        if create_directory:
            # Check and create through one trusted mount. This avoids two
            # complete opens before an import can begin.
            with self.gemdos_mount(target) as target_mount:
                if target_parent and not target_mount.exists(target_parent):
                    raise DiskError(f"Path not found: {target_parent}")
                if target_mount.exists(target_directory):
                    raise DiskError(
                        f"“{directory_name}” already exists in the destination directory."
                    )
                report(f"Creating destination directory {target_directory}", 0, None)
                target_mount.make_directory(target_directory, parents=True, exist_ok=False)
            self._mark_mutated(target)

        rollback_path: Path | None = None
        dirty_before = target.dirty
        warnings_before = list(target.warnings)
        hfe_export_before = target.hfe_export_path
        if not create_directory:
            report(f"Preparing safe extraction into {target_directory}", 0, None)
            rollback_path = target.path.parent / f".import-rollback-{uuid.uuid4().hex}"
            self._copy_local_file(target.path, rollback_path)
        try:
            self._copy_volume_to_directory(source, target, target_directory, report)
            self.carry_boot_option(source, target, target_directory)
        except Exception:
            if create_directory:
                try:
                    with self.gemdos_mount(target) as target_mount:
                        target_mount.remove(target_directory, recursive=True, force=True)
                except Exception:
                    pass
            elif rollback_path and rollback_path.is_file():
                rollback_path.replace(target.path)
                target.dirty = dirty_before
                target.warnings = warnings_before
                target.hfe_export_path = hfe_export_before
            raise
        finally:
            if rollback_path:
                rollback_path.unlink(missing_ok=True)
            if rebuilt is not None:
                self.discard_session(rebuilt)
        self._mark_mutated(target)
        return target_directory

    def _copy_volume_to_directory(
        self,
        source: ImageSession,
        target: ImageSession,
        target_directory: str,
        report,
    ) -> None:
        """Copy every file on one volume into a folder on another."""
        report("Copying the complete disk catalogue in one batch", 0, None)
        with self._locked_sessions(source, target):
            with self.gemdos_mount(source, writable=False) as source_mount:
                items = self._collect_volume_items(
                    source_mount, target_directory, file_copy_item
                )
                items = in_storage_order(source_mount, items)
            with self.gemdos_mount(target) as target_mount:
                for item in items:
                    if item.get("kind") == "mkdir":
                        ensure_directory_chain(target_mount, str(item["dst"]))
                    else:
                        write_copy_item(target_mount, str(item["dst"]), item, True)
        report("Copied the complete disk catalogue", len(items), len(items))

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def read_file(self, session: ImageSession, inner: str, side: int | None = None) -> bytes:
        del side
        if session.kind == "rom":
            return self.rom_bank_bytes(session, inner)
        if session.kind == "iso":
            return self.iso_file(session, inner)
        if session.kind in CONTAINER_KINDS:
            return self._container_track_bytes(session, inner)
        if session.kind == "tosrom":
            with self.tosrom_mount(session) as mount:
                return mount.read_bytes(self.inner_for(session, inner))
        if self.mountable(session):
            with self.gemdos_mount(session, writable=False) as mount:
                return mount.read_bytes(self.inner_for(session, inner))
        raise DiskError("This image does not contain a file that can be read.")

    def _container_track_bytes(self, session: ImageSession, inner: str) -> bytes:
        """Return the sectors of one track from an MSA, DIM or Pasti container.

        A container stores whole tracks, and where a track sits in the disk it
        describes is decided by the geometry rather than by the order the
        tracks happen to be stored in. The honest way to read one is therefore
        to rebuild the disk and take the track out of it, which is also what
        makes a Pasti track come back with its unreadable sectors filled the
        same way the conversion fills them.
        """
        member = self._container_member(session, inner)
        rebuilt, _rows = self.convert_container(session, "st")
        try:
            sectors = rebuilt.path.read_bytes()
            geometry = resolve_geometry(len(sectors), sectors[:512])
            if geometry is None:
                raise DiskError("The shape of this container could not be established.")
            index = int(member["track"]) * geometry.sides + int(member["side"])
            offset = index * geometry.track_size
            return sectors[offset : offset + geometry.track_size]
        finally:
            self.discard_session(rebuilt)

    def file_metadata(
        self,
        session: ImageSession,
        inner: str,
        side: int | None = None,
    ) -> dict:
        """Return portable GEMDOS metadata for one exported loose file."""
        del side
        if session.kind == "rom":
            data = self.rom_bank_bytes(session, inner)
            return {"attributes": 0, "access": 0, "length": len(data)}
        if session.kind in CONTAINER_KINDS:
            member = self._container_member(session, inner)
            return {
                "attributes": 0x01,
                "access": 0x01,
                "length": int(member["length"]),
                "complete": bool(member["complete"]),
            }
        if session.kind == "tosrom":
            with self.tosrom_mount(session) as mount:
                stat = mount.stat(inner)
                return {
                    "attributes": 0x01,
                    "access": 0x01,
                    "length": int(stat.length or 0),
                }
        if not self.mountable(session):
            raise DiskError("This image does not contain readable directory metadata.")
        with self.gemdos_mount(session, writable=False) as mount:
            target = self.inner_for(session, inner)
            stat = mount.stat(target)
            meta = mount.atari_meta(target)
            bits = int(meta.attributes or 0)
            return {
                "attributes": bits,
                "attributesText": format_attributes(bits),
                "access": bits,
                "length": int(stat.length or 0),
                "datestamp": (
                    meta.datestamp.isoformat(sep="T", timespec="milliseconds")
                    if meta.datestamp
                    else ""
                ),
            }

    def export_file(
        self,
        session: ImageSession,
        inner: str,
        side: int | None = None,
    ) -> Path:
        """Export an image file without buffering its contents in application RAM."""
        del side
        target = self.work_dir / f"download-{uuid.uuid4().hex}"
        try:
            target.write_bytes(self.read_file(session, inner))
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return target

    def compact(self, session: ImageSession) -> None:
        """Defragment a volume so its files occupy consecutive clusters.

        FAT allows a file's clusters to be anywhere, and a disk written and
        deleted over time ends up with files threaded through each other. That
        costs a real machine seek time on every read, so the volume is rewritten
        with each file's clusters consecutive.
        """
        self.require_writable_geometry(session)
        if not self.mountable(session):
            raise DiskError("Only a mounted GEMDOS volume can be defragmented.")
        with session.lock, self.gemdos_mount(session) as mount:
            mount.defragment()
        self._mark_mutated(session)

    def free_map(self, session: ImageSession) -> list[bool]:
        """Return one flag per cluster, True where the cluster is free."""
        if not self.mountable(session):
            raise DiskError("Only a mounted GEMDOS volume reports a free-space map.")
        with self.gemdos_mount(session, writable=False) as mount:
            return list(mount.free_map())

    @staticmethod
    def _friendly_engine_error(message: str) -> str:
        return friendly_engine_error(message)

    @staticmethod
    def _run(args: list[str], binary: bool = False) -> bytes | str:
        return run_disc(args, binary)

    @staticmethod
    def _run_hxcfe(args: list[str]) -> str:
        return run_hxcfe(args)

    @classmethod
    def _run_json(cls, args: list[str]) -> dict:
        return decode_disc_json(cls._run(args))
