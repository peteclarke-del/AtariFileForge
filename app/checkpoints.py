from __future__ import annotations

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
        session.target_hardware = str(state.get("targetHardware") or "auto")
        session.hardware_profile = dict(state.get("hardwareProfile") or {})
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
