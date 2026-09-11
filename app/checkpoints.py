from __future__ import annotations

import glob
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .editor_project import normalise_editor_project

if TYPE_CHECKING:
    from .disk_service import ImageSession


CHECKPOINT_NAME_LIMIT = 60
AUTOMATIC_CHECKPOINT_LIMIT = 20
# A copy in progress is written to continuously, so one untouched for this
# long belongs to a process that stopped.
ABANDONED_COPY_AGE = 10 * 60


class CheckpointError(RuntimeError):
    pass


class CheckpointStore:
    """Persistent, per-image snapshots for undo and named restore points."""

    def __init__(
        self,
        copy_file: Callable[[Path, Path], None],
        *,
        automatic_limit: int = AUTOMATIC_CHECKPOINT_LIMIT,
    ) -> None:
        self._copy_file = copy_file
        self.automatic_limit = max(1, automatic_limit)

    @staticmethod
    def _root(session: ImageSession) -> Path:
        return session.path.parent / "checkpoints"

    @staticmethod
    def _state(session: ImageSession) -> dict:
        return {
            "name": session.name,
            "dirty": session.dirty,
            "partition": session.partition,
            "sourceNames": dict(session.source_names),
            "distributionName": session.distribution_name,
            "targetHardware": session.target_hardware,
            "hardwareProfile": dict(session.hardware_profile),
            "warnings": list(session.warnings),
            "romBankSize": session.rom_bank_size,
            "romEraseByte": session.rom_erase_byte,
            "romPlatform": session.rom_platform,
            "romLayout": session.rom_layout,
            "romComponentNames": list(session.rom_component_names),
            "romProject": dict(session.rom_project),
            "editorProjects": dict(session.editor_projects),
            "compatibilityReports": list(session.compatibility_reports),
        }

    @classmethod
    def fingerprint(cls, session: ImageSession) -> tuple:
        image = session.path.stat()
        state_fields = cls._state(session)
        # Saved/unsaved is UI state, not an image edit. Saving an unchanged
        # image must not create a new undo checkpoint merely because its dot
        # was cleared.
        state_fields.pop("dirty", None)
        state = json.dumps(state_fields, sort_keys=True, separators=(",", ":"))
        return (image.st_size, image.st_mtime_ns, state)

    @staticmethod
    def _normalise_name(name: str) -> str:
        value = re.sub(r"\s+", " ", str(name or "").strip())
        if not value:
            raise CheckpointError("Enter a name for this checkpoint.")
        if len(value) > CHECKPOINT_NAME_LIMIT:
            raise CheckpointError(
                f"Checkpoint names can contain at most {CHECKPOINT_NAME_LIMIT} characters."
            )
        if any(ord(character) < 32 for character in value):
            raise CheckpointError("Checkpoint names cannot contain control characters.")
        return value

    @staticmethod
    def _read_metadata(folder: Path) -> dict | None:
        try:
            metadata = json.loads((folder / "checkpoint.json").read_text(encoding="utf-8"))
            if metadata.get("id") != folder.name or not (folder / "image.bin").is_file():
                return None
            return metadata
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _public(metadata: dict) -> dict:
        return {
            "id": metadata["id"],
            "name": metadata["name"],
            "reason": metadata.get("reason") or metadata["name"],
            "automatic": bool(metadata.get("automatic")),
            "created": int(metadata["created"]),
            "size": int(metadata.get("size") or 0),
        }

    def list(self, session: ImageSession) -> list[dict]:
        return [self._public(item) for item in self._metadata(session)]

    def _metadata(self, session: ImageSession) -> list[dict]:
        """Return valid checkpoint metadata newest first for internal consumers."""
        root = self._root(session)
        if not root.is_dir():
            return []
        checkpoints = [
            metadata
            for folder in root.iterdir()
            if folder.is_dir() and (metadata := self._read_metadata(folder)) is not None
        ]
        checkpoints.sort(key=lambda item: int(item.get("created") or 0), reverse=True)
        return checkpoints

    def oldest_snapshot(self, session: ImageSession) -> tuple[Path, dict] | None:
        """Return the oldest retained image and its full metadata."""
        checkpoints = self._metadata(session)
        if not checkpoints:
            return None
        metadata = checkpoints[-1]
        folder = self._root(session) / str(metadata["id"])
        return folder / "image.bin", metadata

    def create(
        self,
        session: ImageSession,
        name: str,
        *,
        automatic: bool = False,
        reason: str | None = None,
    ) -> dict:
        display_name = self._normalise_name(name)
        checkpoint_id = uuid.uuid4().hex
        root = self._root(session)
        root.mkdir(exist_ok=True)
        temporary = root / f".{checkpoint_id}.tmp"
        folder = root / checkpoint_id
        temporary.mkdir()
        try:
            image_copy = temporary / "image.bin"
            self._copy_file(session.path, image_copy)
            size = image_copy.stat().st_size
            metadata = {
                "id": checkpoint_id,
                "name": display_name,
                "reason": str(reason or display_name),
                "automatic": bool(automatic),
                "created": time.time_ns() // 1_000_000,
                "size": size,
                "state": self._state(session),
            }
            (temporary / "checkpoint.json").write_text(
                json.dumps(metadata, separators=(",", ":")),
                encoding="utf-8",
            )
            temporary.replace(folder)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return self._public(metadata)

    def prune_automatic(self, session: ImageSession) -> None:
        automatic = [item for item in self.list(session) if item["automatic"]]
        for item in automatic[self.automatic_limit :]:
            self.delete(session, item["id"])

    def delete(self, session: ImageSession, checkpoint_id: str) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", str(checkpoint_id or "")):
            raise CheckpointError("That checkpoint no longer exists.")
        folder = self._root(session) / checkpoint_id
        if self._read_metadata(folder) is None:
            raise CheckpointError("That checkpoint no longer exists.")
        shutil.rmtree(folder)

    def restore(self, session: ImageSession, checkpoint_id: str) -> dict:
        if not re.fullmatch(r"[0-9a-f]{32}", str(checkpoint_id or "")):
            raise CheckpointError("That checkpoint no longer exists.")
        folder = self._root(session) / checkpoint_id
        metadata = self._read_metadata(folder)
        if metadata is None:
            raise CheckpointError("That checkpoint no longer exists.")
        state = metadata.get("state") or {}
        image_temp = session.path.parent / f".{session.path.name}.restore-{uuid.uuid4().hex}"
        try:
            self._copy_file(folder / "image.bin", image_temp)
            image_temp.replace(session.path)
        finally:
            image_temp.unlink(missing_ok=True)

        session.name = str(state.get("name") or session.name)
        session.dirty = bool(state.get("dirty"))
        session.partition = (
            int(state["partition"]) if state.get("partition") is not None else None
        )
        session.source_names = {
            str(path): str(name)
            for path, name in (state.get("sourceNames") or {}).items()
        }
        session.distribution_name = state.get("distributionName")
        # The hardware profile and target hardware are left as they are. They
        # describe the machine the whole workspace is set up for, and applying
        # a profile takes no checkpoint of its own, so rewinding them here
        # would quietly return one image to an older machine whenever an edit
        # made before the profile changed was undone.
        session.warnings = [str(warning) for warning in state.get("warnings") or []]
        session.rom_bank_size = int(state.get("romBankSize") or session.rom_bank_size)
        session.rom_erase_byte = int(state.get("romEraseByte", session.rom_erase_byte)) & 0xFF
        session.rom_platform = str(state.get("romPlatform") or session.rom_platform)
        session.rom_layout = str(state.get("romLayout") or session.rom_layout)
        session.rom_component_names = [
            str(name) for name in state.get("romComponentNames") or []
        ]
        session.rom_project = dict(state.get("romProject") or session.rom_project)
        session.editor_projects = {
            str(key): normalise_editor_project(value)
            for key, value in dict(state.get("editorProjects") or session.editor_projects).items()
        }
        session.compatibility_reports = [
            dict(report)
            for report in list(state.get("compatibilityReports") or [])[-10:]
            if isinstance(report, dict)
        ]
        return self._public(metadata)

    def latest_automatic(self, session: ImageSession) -> dict | None:
        return next((item for item in self.list(session) if item["automatic"]), None)

    def relabel(self, session: ImageSession, old_name: str, new_name: str) -> None:
        """Carry a rename back through the checkpoints taken under the old name.

        A rename changes no byte of the image, so it takes no checkpoint of its
        own. Each checkpoint still records the name it was taken under, and
        restoring one puts that name back, so without this, undoing an edit
        made before the rename would undo the rename as well. A checkpoint
        taken under a different name belongs to an operation that changed the
        name itself, such as replacing the image, and keeps the name it had.
        """
        root = self._root(session)
        if not root.is_dir():
            return
        for folder in root.iterdir():
            metadata = self._read_metadata(folder) if folder.is_dir() else None
            if metadata is None or (metadata.get("state") or {}).get("name") != old_name:
                continue
            metadata["state"]["name"] = new_name
            target = folder / "checkpoint.json"
            temporary = folder / "checkpoint.json.tmp"
            temporary.write_text(json.dumps(metadata, separators=(",", ":")), encoding="utf-8")
            temporary.replace(target)

    def discard_abandoned(self, session: ImageSession) -> None:
        """Remove the half-written copies a stopped process left behind.

        A checkpoint is copied into a hidden folder and renamed into place only
        once it is complete, and a restore copies into a hidden file beside the
        image. Closing the application part way through leaves that copy, as
        large as the image, with nothing referring to it. A copy written to in
        the last few minutes is left alone in case another process is still
        writing it.
        """
        cutoff = time.time() - ABANDONED_COPY_AGE
        root = self._root(session)
        folders = [
            folder for folder in (root.iterdir() if root.is_dir() else ())
            if re.fullmatch(r"\.[0-9a-f]{32}\.tmp", folder.name) and folder.is_dir()
        ]
        restores = [
            path for path in session.path.parent.glob(f".{glob.escape(session.path.name)}.restore-*")
            if re.fullmatch(r"[0-9a-f]{32}", path.name.rsplit("-", 1)[-1]) and path.is_file()
        ]
        for path in [*folders, *restores]:
            try:
                paths = [path, *path.iterdir()] if path.is_dir() else [path]
                if max(item.stat().st_mtime for item in paths) >= cutoff:
                    continue
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            except OSError:
                continue
