from __future__ import annotations

import json
import re
import secrets
import shutil
from pathlib import Path

from .checkpoints import CheckpointError
from .editor_project import normalise_editor_project
from .errors import DiskError
from .filename_policy import session_name_policy, target_name_policy
from .image_session import ImageSession, SESSION_OWNER
from .rom import DEFAULT_BANK_SIZE, bank_count, validate_bank_size
from .rom_workbench import normalise_project
from .floppy_geometry import resolve_geometry
from .session_state import session_metadata


class SessionDiskMixin:
    """Persistence, recovery, ownership, checkpoints and image summaries."""

    def _persist_session(self, session: ImageSession) -> None:
        session.warnings = self._normalise_warnings(session.warnings)
        target = session.path.parent / "session.json"
        temporary = session.path.parent / "session.json.tmp"
        temporary.write_text(json.dumps(session_metadata(session), separators=(",", ":")), encoding="utf-8")
        temporary.replace(target)

    def _restore_session(self, image_id: str) -> ImageSession:
        if not re.fullmatch(r"[0-9a-f]{32}", image_id):
            raise DiskError("That image session no longer exists.")
        folder = self.work_dir / image_id
        metadata_path = folder / "session.json"
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            name = self.safe_filename(metadata["name"])
            path = folder / self.safe_filename(metadata.get("workingFile") or name)
            if not path.is_file() or path.parent != folder:
                raise ValueError
            # A session.json written by an earlier build may still name a
            # companion geometry file. An Atari image never had one, so those
            # keys are left unread and such a session restores like any other.
            kind = metadata.get("kind") or self.detect_kind(name)
            if kind not in {
                "gemdos", "hd", "msa", "dim", "stx", "iso", "rom", "tosrom",
            }:
                raise ValueError
            session = ImageSession(
                id=image_id,
                name=name,
                kind=kind,
                path=path,
                dirty=bool(metadata.get("dirty", True)),
                partition=(
                    int(metadata["partition"])
                    if metadata.get("partition") is not None
                    else None
                ),
                source_names={
                    str(path): str(name)
                    for path, name in metadata.get("sourceNames", {}).items()
                },
                distribution_name=metadata.get("distributionName"),
                target_hardware=str(metadata.get("targetHardware") or "auto"),
                hardware_profile=(
                    dict(metadata.get("hardwareProfile") or {})
                    if isinstance(metadata.get("hardwareProfile"), dict)
                    else {}
                ),
                hfe_original_path=(
                    folder / self.safe_filename(metadata["hfeOriginalFile"])
                    if metadata.get("hfeOriginalFile")
                    else None
                ),
                hfe_version=metadata.get("hfeVersion"),
                hfe_read_only=bool(metadata.get("hfeReadOnly")),
                hfe_export_path=(
                    folder / self.safe_filename(metadata["hfeExportFile"])
                    if metadata.get("hfeExportFile")
                    else None
                ),
                scp_original_path=(
                    folder / self.safe_filename(metadata["scpOriginalFile"])
                    if metadata.get("scpOriginalFile")
                    else None
                ),
                scp_read_only=bool(metadata.get("scpReadOnly")),
                scp_export_path=(
                    folder / self.safe_filename(metadata["scpExportFile"])
                    if metadata.get("scpExportFile")
                    else None
                ),
                rom_bank_size=validate_bank_size(int(metadata.get("romBankSize", DEFAULT_BANK_SIZE))),
                rom_erase_byte=int(metadata.get("romEraseByte", 0xFF)) & 0xFF,
                rom_platform=str(metadata.get("romPlatform") or "tos"),
                rom_layout=str(metadata.get("romLayout") or "linear"),
                rom_component_names=[
                    self.safe_filename(name)
                    for name in metadata.get("romComponentNames", [])
                    if name
                ],
                rom_project=normalise_project(metadata.get("romProject")),
                editor_projects={
                    str(key): normalise_editor_project(value)
                    for key, value in dict(metadata.get("editorProjects") or {}).items()
                },
                compatibility_reports=[
                    dict(report)
                    for report in list(metadata.get("compatibilityReports") or [])[-10:]
                    if isinstance(report, dict)
                ],
                finalised_mtime_ns=(
                    int(metadata["finalisedMtimeNs"])
                    if metadata.get("finalisedMtimeNs") is not None
                    else None
                ),
                owner_id=metadata.get("ownerId"),
                warnings=self._normalise_warnings(
                    [str(warning) for warning in metadata.get("warnings", [])]
                ),
                gemdos_capabilities=(
                    dict(metadata.get("gemdosCapabilities") or {})
                    if isinstance(metadata.get("gemdosCapabilities"), dict)
                    else {}
                ),
            )
            if session.hfe_original_path and not session.hfe_original_path.is_file():
                raise ValueError
            if session.hfe_export_path and not session.hfe_export_path.is_file():
                session.hfe_export_path = None
            if session.scp_original_path and not session.scp_original_path.is_file():
                raise ValueError
            if session.scp_export_path and not session.scp_export_path.is_file():
                session.scp_export_path = None
            if self.mountable(session) and not session.gemdos_capabilities:
                self.refresh_gemdos_capabilities(session)
        except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise DiskError("That image session no longer exists.") from exc
        # Loading from disk is the first this process knows of the session, so
        # a copy left half-written by an earlier run can be cleared here.
        self.checkpoints.discard_abandoned(session)
        with self._lock:
            self.sessions[image_id] = session
        return session

    def get(self, image_id: str) -> ImageSession:
        try:
            session = self.sessions[image_id]
        except KeyError:
            session = self._restore_session(image_id)
        owner_id = SESSION_OWNER.get()
        if owner_id is None:
            return session
        if not session.owner_id or not secrets.compare_digest(
            session.owner_id,
            owner_id,
        ):
            raise DiskError("That image session no longer exists.")
        return session

    def recoverable_sessions(self, limit: int = 50) -> list[dict]:
        """List persisted working images without opening their large data files."""
        recovered: list[dict] = []
        owner_id = SESSION_OWNER.get()
        for metadata_path in self.work_dir.glob("*/session.json"):
            image_id = metadata_path.parent.name
            if not re.fullmatch(r"[0-9a-f]{32}", image_id):
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                persisted_owner = metadata.get("ownerId")
                if owner_id is not None and persisted_owner != owner_id:
                    continue
                name = self.safe_filename(metadata["name"])
                working_name = self.safe_filename(metadata.get("workingFile") or name)
                image_path = metadata_path.parent / working_name
                if not image_path.is_file() or image_path.parent != metadata_path.parent:
                    continue
                stat = image_path.stat()
                recovered.append({
                    "id": image_id,
                    "name": name,
                    "kind": str(metadata.get("kind") or self.detect_kind(name)),
                    "size": stat.st_size,
                    "modified": stat.st_mtime_ns // 1_000_000,
                    "targetHardware": str(metadata.get("targetHardware") or "auto"),
                })
            except (OSError, KeyError, ValueError, json.JSONDecodeError):
                continue
        recovered.sort(key=lambda item: item["modified"], reverse=True)
        return recovered[: max(1, min(int(limit), 100))]

    def clear_recoverable_sessions(self, image_ids: list[str] | None = None) -> int:
        """Delete only working copies owned by the current browser identity."""
        owner_id = SESSION_OWNER.get()
        if owner_id is None:
            raise DiskError("Session ownership is unavailable for this request.")
        requested = set(image_ids) if image_ids is not None else None
        removed = 0
        for metadata_path in tuple(self.work_dir.glob("*/session.json")):
            image_id = metadata_path.parent.name
            if requested is not None and image_id not in requested:
                continue
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                persisted_owner = str(metadata.get("ownerId") or "")
                if not persisted_owner or not secrets.compare_digest(persisted_owner, owner_id):
                    continue
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            with self._lock:
                self.sessions.pop(image_id, None)
            shutil.rmtree(metadata_path.parent, ignore_errors=True)
            removed += 1
        return removed

    def discard_session(self, session: ImageSession) -> None:
        with self._lock:
            self.sessions.pop(session.id, None)
        shutil.rmtree(session.path.parent, ignore_errors=True)

    def rename_session(self, session: ImageSession, requested_name: str) -> None:
        """Rename an image for display, recovery and download without moving its working file."""
        requested_name = str(requested_name or "").strip()
        if not requested_name or requested_name != Path(requested_name).name:
            raise DiskError("Enter a filename without a directory path.")

        current_suffix = Path(session.name).suffix
        requested_suffix = Path(requested_name).suffix
        if current_suffix:
            if not requested_suffix:
                requested_name += current_suffix
            elif requested_suffix.casefold() != current_suffix.casefold():
                raise DiskError(f"Keep the {current_suffix} extension for this image.")
        elif requested_suffix:
            raise DiskError("This image has no extension; keep its filename extensionless.")

        safe_name = self.safe_filename(requested_name)
        if safe_name != requested_name:
            raise DiskError("Use letters, numbers, spaces and ordinary filename punctuation only.")
        if not Path(safe_name).stem:
            raise DiskError("Enter a filename before the extension.")
        if safe_name == session.name:
            return

        with session.lock:
            previous_name = session.name
            session.name = safe_name
            session.hfe_export_path = None
            session.scp_export_path = None
            self._persist_session(session)
            try:
                self.checkpoints.relabel(session, previous_name, safe_name)
            except OSError:
                # The rename itself has succeeded. A checkpoint left with the
                # old name only means undoing it brings that name back.
                pass

    def list_checkpoints(self, session: ImageSession) -> list[dict]:
        with session.lock:
            return self.checkpoints.list(session)

    def oldest_checkpoint_snapshot(
        self, session: ImageSession
    ) -> tuple[Path, dict] | None:
        with session.lock:
            try:
                return self.checkpoints.oldest_snapshot(session)
            except CheckpointError as exc:
                raise DiskError(str(exc)) from exc

    def create_checkpoint(
        self,
        session: ImageSession,
        name: str,
        *,
        automatic: bool = False,
        reason: str | None = None,
    ) -> dict:
        with session.lock:
            try:
                return self.checkpoints.create(
                    session,
                    name,
                    automatic=automatic,
                    reason=reason,
                )
            except CheckpointError as exc:
                raise DiskError(str(exc)) from exc

    def begin_automatic_checkpoint(self, session: ImageSession, reason: str) -> dict:
        """Capture the image before one API operation and return a finalisation token."""
        with session.lock:
            fingerprint = self.checkpoints.fingerprint(session)
            checkpoint = self.create_checkpoint(
                session,
                f"Before {reason}",
                automatic=True,
                reason=reason,
            )
        return {"checkpoint": checkpoint, "fingerprint": fingerprint}

    def finish_automatic_checkpoint(self, session: ImageSession, token: dict) -> None:
        """Discard a speculative undo point when the request changed nothing."""
        with session.lock:
            try:
                unchanged = self.checkpoints.fingerprint(session) == token["fingerprint"]
            except OSError:
                unchanged = False
            if unchanged:
                try:
                    self.checkpoints.delete(session, token["checkpoint"]["id"])
                except CheckpointError:
                    pass
            else:
                self.checkpoints.prune_automatic(session)
            # Every API mutation passes through this finaliser. Persist the
            # resulting dirty/export state here so recovery cannot resurrect
            # an edited image as though it were still saved.
            self._persist_session(session)

    def rollback_automatic_checkpoint(self, session: ImageSession, token: dict) -> None:
        """Restore a failed mutation and remove its now-redundant undo point."""
        checkpoint_id = str(token["checkpoint"]["id"])
        self.restore_checkpoint(session, checkpoint_id)
        try:
            self.delete_checkpoint(session, checkpoint_id)
        except DiskError:
            pass

    def restore_checkpoint(self, session: ImageSession, checkpoint_id: str) -> dict:
        with session.lock:
            try:
                restored = self.checkpoints.restore(session, checkpoint_id)
            except CheckpointError as exc:
                raise DiskError(str(exc)) from exc
            session.invalidate_cached_views()
            session.container = None
            self._persist_session(session)
            return restored

    def undo_last_change(self, session: ImageSession) -> dict:
        with session.lock:
            latest = self.checkpoints.latest_automatic(session)
            if latest is None:
                raise DiskError("There is no automatic checkpoint to undo.")
            restored = self.restore_checkpoint(session, latest["id"])
            try:
                self.checkpoints.delete(session, latest["id"])
            except CheckpointError as exc:
                raise DiskError(str(exc)) from exc
            return restored

    def delete_checkpoint(self, session: ImageSession, checkpoint_id: str) -> None:
        with session.lock:
            try:
                self.checkpoints.delete(session, checkpoint_id)
            except CheckpointError as exc:
                raise DiskError(str(exc)) from exc

    def _drive_facts(self, session: ImageSession) -> dict:
        """The partition table's own description, for a hard-disk session."""
        if session.kind != "hd":
            return {}
        try:
            table = self.partition_table(session)
        except DiskError:
            return {}
        return {
            "scheme": str(table.get("scheme") or ""),
            "partitionScheme": str(table.get("scheme") or ""),
            "byteSwapped": bool(table.get("byteSwapped")),
            "partitionCount": len(table.get("partitions") or []),
        }

    def image_geometry(self, session: ImageSession) -> dict | None:
        """The shape of a floppy image, read from its own boot sector.

        A hard-disk volume has no cylinders, heads and sectors worth
        reporting: it is addressed as logical sectors through a driver. Only
        a floppy has a geometry a person can act on, so only a floppy
        reports one.
        """
        if session.kind != "gemdos":
            return None
        try:
            size = session.path.stat().st_size
            with session.path.open("rb") as image:
                boot = image.read(512)
        except OSError:
            return None
        found = resolve_geometry(size, boot)
        if found is None:
            return None
        return {
            "id": found.identifier,
            "label": found.label,
            "tracks": found.tracks,
            "sides": found.sides,
            "sectors": found.sectors,
            "size": found.size,
        }

    def summary(self, session: ImageSession) -> dict:
        checkpoints = self.list_checkpoints(session)
        tosrom = self.tosrom_details(session) if session.kind == "tosrom" else None
        image_stat = session.path.stat()
        image_size = image_stat.st_size
        file_policy = session_name_policy(session)
        partition_policy = target_name_policy("hd", item_type="partition")
        capabilities = session.gemdos_capabilities or {}
        drive = self._drive_facts(session)
        return {
            "id": session.id,
            "name": session.name,
            "kind": session.kind,
            "size": image_size,
            "revision": f"{image_size:x}-{image_stat.st_mtime_ns:x}",
            "hardDisk": self.is_bare_hard_drive(session, image_size),
            "dirty": session.dirty,
            "doubleSided": self.is_double_sided(session),
            "containerFormat": "hfe" if session.hfe_original_path else "scp" if session.scp_original_path else None,
            # A CD is read-only by construction, so saying so here is what
            # disables every control that would write to it, rather than each
            # one having to know what an ISO is.
            "readOnly": (
                session.kind == "iso"
                or session.hfe_read_only
                or session.scp_read_only
                or session.kind in {"stx", "tosrom"}
            ),
            "exportFormats": self.export_formats(session),
            "rom": ({
                "bankSize": session.rom_bank_size,
                "bankCount": bank_count(image_size, session.rom_bank_size),
                "eraseByte": session.rom_erase_byte,
                "platform": session.rom_platform,
                "layout": session.rom_layout,
                "componentNames": session.rom_component_names,
                "project": session.rom_project,
            } if session.kind == "rom" else None),
            "tosrom": tosrom,
            "filesystemCapabilities": session.gemdos_capabilities or None,
            "filenamePolicies": {
                "file": file_policy.public_contract(),
                "disk": partition_policy.public_contract() if session.kind == "hd" else None,
            },
            # The volume's own description, so a report does not have to
            # mount the image again to say what shape it is.
            "title": capabilities.get("label") or None,
            "label": capabilities.get("label") or None,
            "format": capabilities.get("format") or None,
            "clusters": capabilities.get("clusters") or None,
            "sizeBytes": capabilities.get("sizeBytes") or image_size,
            "bootable": capabilities.get("bootable"),
            "tosLimits": capabilities.get("tosLimits") or [],
            "geometry": self.image_geometry(session),
            **drive,
            "targetHardware": session.target_hardware,
            "hardwareProfile": session.hardware_profile,
            "warnings": self._normalise_warnings(session.warnings),
            "checkpoints": {
                "total": len(checkpoints),
                "named": sum(not item["automatic"] for item in checkpoints),
                "canUndo": any(item["automatic"] for item in checkpoints),
                # Not every change takes an undo point, so the most recent
                # thing done may not be what Undo reverses. This names it.
                "undoReason": next(
                    (item["reason"] for item in checkpoints if item["automatic"]), None
                ),
            },
        }
