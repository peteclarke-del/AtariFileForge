"""Safe, streaming access to disk images supplied directly or in ZIP files."""

from __future__ import annotations

import contextlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Iterator

from .errors import DiskError

MAX_ARCHIVE_MEMBERS = 2048
MAX_ARCHIVE_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024


def validated_zip_members(
    archive: zipfile.ZipFile,
    *,
    max_expanded_bytes: int = MAX_ARCHIVE_EXPANDED_BYTES,
) -> list[zipfile.ZipInfo]:
    """Return members after applying shared ZIP bomb and encryption limits."""
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise DiskError(
            f"The ZIP contains more than {MAX_ARCHIVE_MEMBERS:,} entries."
        )
    files = [item for item in members if not item.is_dir()]
    if any(item.flag_bits & 0x1 for item in files):
        raise DiskError("Password-protected ZIP members are not supported.")
    if sum(item.file_size for item in files) > max_expanded_bytes:
        limit_mb = max_expanded_bytes // (1024 * 1024)
        raise DiskError(
            f"The ZIP expands beyond the {limit_mb:,} MB safety limit."
        )
    return members


@dataclass
class ArchiveImage:
    filename: str
    stream: BinaryIO
    metadata_names: list[str]


def _supported_members(
    archive: zipfile.ZipFile,
    extensions: set[str],
) -> list[zipfile.ZipInfo]:
    all_members = validated_zip_members(archive)
    members = [
        item
        for item in all_members
        if not item.is_dir()
        and not item.filename.startswith("__MACOSX/")
        and Path(item.filename).suffix.lower() in extensions
    ]
    return members


def _open_zip(upload) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(upload.stream)
    except (OSError, zipfile.BadZipFile) as exc:
        raise DiskError("The selected ZIP file is damaged or incomplete.") from exc


def is_zip_name(filename: str) -> bool:
    return Path(filename or "").suffix.lower() == ".zip"


@contextlib.contextmanager
def _open_archive_image(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    upload_name: str,
) -> Iterator[ArchiveImage]:
    """Open one validated archive member with a consistent user-facing error."""
    try:
        with archive.open(member) as stream:
            yield ArchiveImage(
                Path(member.filename).name,
                stream,
                [member.filename, upload_name],
            )
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise DiskError(
            f"{member.filename} could not be read from {upload_name}."
        ) from exc


def iter_upload_images(
    uploads,
    extensions: set[str],
) -> Iterator[ArchiveImage]:
    """Yield every supported image, expanding ZIP uploads without filesystem writes."""
    for upload in uploads:
        if not upload or not upload.filename:
            continue
        if not is_zip_name(upload.filename):
            yield ArchiveImage(
                upload.filename,
                upload.stream,
                [upload.filename],
            )
            continue
        with _open_zip(upload) as archive:
            members = _supported_members(archive, extensions)
            if not members:
                supported = ", ".join(sorted(extensions))
                raise DiskError(
                    f"{upload.filename} contains no supported image ({supported})."
                )
            for member in members:
                with _open_archive_image(archive, member, upload.filename) as image:
                    yield image


@contextlib.contextmanager
def open_single_upload_image(
    upload,
    extensions: set[str],
) -> Iterator[ArchiveImage]:
    """Open one image directly or require exactly one supported member in a ZIP."""
    if not is_zip_name(upload.filename):
        yield ArchiveImage(upload.filename, upload.stream, [upload.filename])
        return
    with _open_zip(upload) as archive:
        members = _supported_members(archive, extensions)
        if not members:
            supported = ", ".join(sorted(extensions))
            raise DiskError(
                f"{upload.filename} contains no supported image ({supported})."
            )
        if len(members) != 1:
            names = ", ".join(Path(item.filename).name for item in members[:8])
            suffix = "…" if len(members) > 8 else ""
            raise DiskError(
                f"{upload.filename} contains {len(members)} supported images "
                f"({names}{suffix}). Extract them into a hard-disk image to import "
                "them all, or use a ZIP containing one image here."
            )
        member = members[0]
        with _open_archive_image(archive, member, upload.filename) as image:
            yield image


@contextlib.contextmanager
def open_disk_image_upload(
    upload,
    image_extensions: set[str],
) -> Iterator[ArchiveImage]:
    """Open the one disk image inside a ZIP upload, or the upload itself.

    An Atari image is always a single file: a partitioned drive keeps its
    table in its own root sector and a bare volume its parameter block in its
    own boot sector, so there is nothing that has to arrive alongside it.
    """
    if not is_zip_name(upload.filename):
        yield ArchiveImage(upload.filename, upload.stream, [upload.filename])
        return
    with _open_zip(upload) as archive:
        members = _supported_members(archive, image_extensions)
        if len(members) != 1:
            raise DiskError(
                f"{upload.filename} must contain exactly one supported disk "
                f"image; {len(members)} were found."
            )
        with _open_archive_image(archive, members[0], upload.filename) as image:
            yield image
