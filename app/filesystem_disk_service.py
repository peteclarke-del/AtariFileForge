from __future__ import annotations

from contextlib import contextmanager

from .gemdos_capabilities import capabilities_from_mount
from .errors import DiskError
from .image_session import ImageSession


class FilesystemDiskMixin:
    """Trusted GEMDOS and TOS ROM mounts, plus the TOS ROM's own identity."""

    @staticmethod
    def mountable(session: ImageSession) -> bool:
        """Whether this session currently addresses one GEMDOS volume.

        A floppy image or a bare volume image always does. A partitioned hard
        disk does once a partition has been chosen; until then the pane is
        showing the drive's partition table, which is not a volume.
        """
        if session.kind == "gemdos":
            return True
        return session.kind == "hd" and session.partition is not None

    @staticmethod
    def require_mounted_volume(session: ImageSession) -> None:
        """Refuse a volume operation on a drive with no partition chosen.

        A partitioned drive opens on its partition table, which is not a
        volume: there is no single filesystem to write into until one is
        selected. Saying so here keeps the message the same wherever the
        attempt is made, rather than letting a caller reach the raw drive and
        fail later on a mount that has no file operations at all.
        """
        if session.kind == "hd" and session.partition is None:
            raise DiskError("Choose a partition on this hard disk first.")

    @contextmanager
    def gemdos_mount(self, session: ImageSession, *, writable: bool = True):
        """Open an identified GEMDOS volume without probing or copying it again.

        A partition of a hard disk is an ordinary FAT volume that starts part
        way into a larger file, so it is handed back through the same contract
        and every caller downstream stays unaware of the difference.
        """
        if session.kind == "hd":
            if session.partition is None:
                raise DiskError("Choose a partition on this hard disk first.")
            with self.partition_mount(session, writable=writable) as mount:
                yield mount
            return
        if session.kind != "gemdos":
            raise DiskError("This operation requires a GEMDOS volume.")
        try:
            from atarinut.filesystem import create_filesystem, reader_for
        except ImportError as exc:
            raise DiskError("The Atarinut GEMDOS filesystem API is unavailable.") from exc

        with session.lock:
            reader = reader_for(session.path, writable=writable)
            mount = None
            try:
                mount = create_filesystem("gemdos").open(reader)
                yield mount
            except DiskError:
                raise
            except Exception as exc:
                raise DiskError(self._friendly_engine_error(str(exc))) from exc
            finally:
                if mount is not None:
                    close = getattr(mount, "close", None)
                    if callable(close):
                        close()
                reader.close()

    def refresh_gemdos_capabilities(self, session: ImageSession) -> dict:
        """Cache the mounted volume's format and its real name limits.

        A volume that will not mount is still worth opening: its bytes can be
        inspected, compared and repaired in the hex editor. A failure here
        therefore records empty capabilities and a warning rather than making
        the whole session unopenable.
        """
        if not self.mountable(session):
            session.gemdos_capabilities = {}
            return {}
        try:
            with self.gemdos_mount(session, writable=False) as mount:
                capabilities = capabilities_from_mount(mount).to_dict()
        except (DiskError, TypeError) as exc:
            session.gemdos_capabilities = {}
            self._append_warning(
                session,
                f"The filing-system capabilities could not be read: {exc}",
            )
            return {}
        session.gemdos_capabilities = {
            "format": capabilities["format"],
            "fatBits": capabilities["fat_bits"],
            "nameLimit": capabilities["name_limit"],
            "nameForm": capabilities["name_form"],
            "directoryEntryLimit": capabilities["directory_entry_limit"],
            "caseInsensitive": capabilities["case_insensitive"],
            "labelLimit": capabilities["label_limit"],
            "label": capabilities["label"],
            "clusters": capabilities["clusters"],
            "clusterBytes": capabilities["cluster_bytes"],
            "sizeBytes": capabilities["size_bytes"],
            "bootable": capabilities["bootable"],
            "tosLimits": capabilities["tos_limits"],
        }
        return session.gemdos_capabilities

    @contextmanager
    def tosrom_mount(self, session: ImageSession, *, writable: bool = False):
        """Open an identified TOS ROM without probing it again.

        A TOS ROM is read-only in every sense that matters here: its segments
        are addressed by the machine's own reset vector, and moving one would
        break the absolute addresses the rest of the image is linked against.
        ``writable`` is therefore refused rather than honoured.
        """
        if session.kind != "tosrom":
            raise DiskError("This operation requires an Atari TOS ROM.")
        if writable:
            raise DiskError(
                "A TOS ROM is read-only. Its segments sit at the addresses the "
                "machine's reset vector expects, so they cannot be rewritten in "
                "place."
            )
        try:
            from atarinut.filesystem import create_filesystem, reader_for
        except ImportError as exc:
            raise DiskError("The Atarinut TOS ROM API is unavailable.") from exc
        with session.lock:
            reader = reader_for(session.path, writable=False)
            try:
                mount = create_filesystem("tosrom").open(reader, None)
                yield mount
            except DiskError:
                raise
            except Exception as exc:
                raise DiskError(self._friendly_engine_error(str(exc))) from exc
            finally:
                reader.close()

    def tosrom_details(self, session: ImageSession) -> dict:
        """Return the decoded identity of a TOS ROM and why it cannot be written.

        A TOS ROM is not a filing system with free space in it. It is one
        linked image with a header naming its release, its build date and the
        addresses it expects to sit at, followed by the operating system
        itself. Capacity is therefore reported as unavailable with the reason
        rather than as a total and a remainder that would mean nothing.
        """
        try:
            from atarinut.tosrom import TOSRom
        except ImportError as exc:  # pragma: no cover - packaging failure
            raise DiskError("The Atarinut TOS ROM API is unavailable.") from exc
        try:
            rom = TOSRom.from_bytes(session.path.read_bytes())
        except Exception as exc:
            raise DiskError(f"The TOS ROM header is invalid: {exc}") from exc
        segments = list(rom.data_files)
        warnings: list[str] = []
        if not rom.is_complete:
            warnings.append(
                "This TOS ROM is shorter than its header declares. It may be "
                "truncated, or one half of a two-chip set."
            )
        return {
            "title": rom.title,
            "headerTitle": rom.release,
            "version": rom.version,
            "copyright": rom.copyright,
            "romType": rom.rom_type,
            "fileCount": len(segments),
            "complete": rom.is_complete,
            "readOnly": True,
            "capacity": {
                "available": False,
                "reason": "A TOS ROM is read-only",
            },
            "warnings": warnings,
        }
