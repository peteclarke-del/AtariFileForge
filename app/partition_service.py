"""Atari hard disks, addressed as the partitions their table declares.

An ACSI, SCSI or IDE drive prepared for TOS keeps its partition table in the
root sector. AHDI writes up to four entries there, each naming a three-letter
identifier (``GEM`` for a volume up to 16 MiB, ``BGM`` for a larger one) with
a start sector and a length; ``XGM`` chains a further table so a drive can
carry more than four. ICD's driver adds eight more entries lower in the same
sector, and a drive prepared on a PC carries an ordinary MBR instead, which
TOS 4 and MiNT both mount. The engine reads all four schemes and reports
which one it found.

A drive is therefore opened as a list of partitions, and one of them is
selected. Everything downstream, listing, reading, editing, validating, then
works on that partition exactly as it works on a floppy, because a partition
is an ordinary GEMDOS volume that happens to start part way into a larger
file.

An IDE drive imaged through a byte-swapping adapter has every sector's byte
pairs reversed. The engine detects that and reads through the swap, and the
flag is carried into the listing so a person can see why the image looks
wrong in a hex editor and right in the workbench.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from .errors import DiskError

if TYPE_CHECKING:  # pragma: no cover - imported for type checkers only
    from .image_session import ImageSession


class PartitionMixin:
    """Read a hard disk's partition table and mount one partition."""

    def partition_table(self, session: ImageSession) -> dict:
        """Return the drive's decoded partition table.

        The report is the drive's own description: which scheme was found,
        how many sectors the table claims the drive holds, whether the image
        is byte-swapped, and every partition with its drive letter, three
        letter identifier or MBR type code, extent and boot flag.
        """
        if session.kind != "hd":
            raise DiskError("This image is not a partitioned hard disk.")
        try:
            from atarinut.filesystem import reader_for
            from atarinut.filesystem.ahdi import read_partition_table
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise DiskError("The Atarinut partition-table API is unavailable.") from exc

        with session.lock:
            reader = reader_for(session.path, writable=False)
            try:
                return read_partition_table(reader).to_dict()
            except Exception as exc:
                raise DiskError(self._friendly_engine_error(str(exc))) from exc
            finally:
                reader.close()

    def list_partitions(self, session: ImageSession) -> list[dict]:
        """Return every partition the drive declares, in table order.

        Each row is the engine's own description of the partition with one
        addition: ``format`` names the filing system a report should print.
        A GEMDOS partition reached through a table is FAT16 whatever its
        cluster count, because that is what the driver's own parameter block
        declares and what TOS obeys; a partition of another kind reports its
        three-letter identifier instead.
        """
        rows = []
        for partition in self.partition_table(session)["partitions"]:
            row = dict(partition)
            row["format"] = "FAT16" if partition.get("gemdos") else str(partition.get("id") or "")
            rows.append(row)
        return rows

    def selected_partition(self, session: ImageSession) -> int:
        """Return the partition index in use, defaulting to the first one.

        A drive that has just been opened has no explicit selection. Falling
        back to the first partition matches what TOS does when it boots from
        C:, and means every read path has a volume to work on without the
        caller having to choose first.
        """
        if session.partition is not None:
            return session.partition
        return 0

    def select_partition(self, session: ImageSession, index: int | None) -> int | None:
        """Choose which partition subsequent operations act on."""
        if session.kind != "hd":
            raise DiskError("This image is not a partitioned hard disk.")
        if index is None:
            session.partition = None
            self._persist_session(session)
            return None
        partitions = self.list_partitions(session)
        chosen = int(index)
        if not 0 <= chosen < len(partitions):
            raise DiskError(
                f"This drive has {len(partitions)} partition(s), so there is no "
                f"partition {chosen}."
            )
        session.partition = chosen
        session.content_kind_cache.clear()
        session.gemdos_capabilities = {}
        self._persist_session(session)
        return chosen

    def partition_label(self, session: ImageSession) -> str:
        """Name the open partition the way the desktop would: ``C:``, ``D:``."""
        try:
            partitions = self.list_partitions(session)
        except DiskError:
            return ""
        index = self.selected_partition(session)
        if not 0 <= index < len(partitions):
            return ""
        chosen = partitions[index]
        return str(chosen.get("device") or chosen.get("name") or "")

    @contextmanager
    def partition_mount(self, session: ImageSession, *, writable: bool = True):
        """Mount the selected partition as an ordinary GEMDOS volume."""
        try:
            from atarinut.disc.mount import mount_image
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise DiskError("The Atarinut mount API is unavailable.") from exc

        index = self.selected_partition(session)
        with session.lock:
            try:
                mount, _name = mount_image(
                    session.path, writable=writable, partition=index
                )
            except Exception as exc:
                raise DiskError(self._friendly_engine_error(str(exc))) from exc
            try:
                yield mount
            finally:
                close = getattr(mount, "close", None)
                if callable(close):
                    close()


__all__ = ["PartitionMixin"]
