r"""Putting a floppy's software onto a hard drive, rather than only copying it.

Copying a disk into a partition gives you the files. It does not give you
something an operator can run: the title still expects to find itself in the
root of A:, and the drive still has nothing on its desktop that would start it.
Closing that gap is what this component is for, and there are four honest ways
to do it.

**Staging** extracts a disk into a folder *on the drive being built*, merging a
multi-disk set into one tree the way an installer would see it. Nothing is
emulated and nothing is guessed at, so it always works and it is always fast.
Putting it on the target image rather than in a directory on this machine is
the whole point: the operator boots the drive in Hatari, or puts it in a real
Atari, and finishes the job there with the disks already in front of them. This
is the default because it is the only mode that cannot half-succeed.

**Installing a staged title** moves it out of the staging folder into a folder
of its own. Both ends are on the same volume, so it is a move rather than a
copy and the attributes and datestamps the disks carried are the ones already
written.

**The title's own installer** cannot be second-guessed at all. Productivity
software asks questions this application has no answer to, so that mode boots
Hatari with the drive attached and the disk in A: and gets out of the way. It
lives in the emulator routes, because nothing here writes anything for it.

**A single program** is the smallest case and the commonest: one ``.PRG`` or
``.TOS`` that is the whole of the software. It is copied into the folder the
operator names and, where they ask for it, installed on the desktop.

There is no fifth mode. The previous platform had a loader that games were
patched to run under; TOS has no counterpart, because a program installed onto
a partition resolves its own paths against the drive it was started from.

Every mode here changes a drive an operator may have spent a long time
building, so each one is reached through a route that declares itself an image
mutation and therefore gets an undo checkpoint before it runs. The checkpoint
is not taken in this module: putting it in one place, at the boundary, is what
stops a new entry point from quietly arriving without one.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone

from . import atari_paths, volume_copy
from . import progress as progress_module
from .errors import DiskError
from .filename_policy import session_name_policy
from .image_session import ImageSession


#: The folder on the target volume that holds staged disks, unless the
#: operator names another.
#:
#: ``INSTALL`` at the volume root is where a prepared drive keeps what is
#: waiting to be installed, and ``STAGE`` inside it is this application's own
#: part of that. Both components are 8.3 names, because that is all a GEMDOS
#: directory entry can hold, and the interface shows the same path.
DEFAULT_STAGING_PARENT = "INSTALL" + atari_paths.SEPARATOR + "STAGE"

#: Staging keeps its own records out of the payload folder, because that
#: folder has to be exactly what gets installed. Everything belonging to this
#: application, the manifest and the files a later disk disagreed about, lives
#: here instead, and the whole folder can be deleted once a set is in.
HOUSEKEEPING_DIRECTORY = "CLASH"
MANIFEST_NAME = "STAGE.INF"

#: Where an install puts a title inside the destination volume, unless the
#: operator picks somewhere else. ``GAMES`` is the conventional folder and is
#: one of the folders a prepared drive is given.
DEFAULT_INSTALL_PARENT = "GAMES"

#: The extensions TOS will start. A folder with none of these in it is a
#: folder of data, and saying so is more use than installing it silently.
PROGRAM_EXTENSIONS = ("PRG", "APP", "TOS", "TTP", "GTP", "ACC")

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(title: str) -> str:
    """Reduce a title to a stable identifier that survives every filesystem.

    The folder a title is staged into is an 8.3 GEMDOS name and several
    different titles can reduce to the same one, so the manifest carries this
    alongside it. The readable title is kept there too, and that is what the
    interface shows.
    """
    folded = unicodedata.normalize("NFKD", str(title or "")).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_STRIP.sub("-", folded.casefold()).strip("-")
    return slug[:48] or "untitled"


def is_program_name(name: str) -> bool:
    """Whether TOS would start a file with this name."""
    leaf = atari_paths.leaf(str(name or "")) or str(name or "")
    return "." in leaf and leaf.rsplit(".", 1)[-1].upper() in PROGRAM_EXTENSIONS


class InstallMixin:
    """Stage, install and hand over disks that are meant to be run, not stored."""

    # ------------------------------------------------------------------
    # Staging
    # ------------------------------------------------------------------

    def staging_parent(self, requested: str = "") -> str:
        """The folder on the target volume that holds staged disks."""
        value = str(requested or "").strip()
        return atari_paths.normalise(value) or DEFAULT_STAGING_PARENT

    def _housekeeping_folder(self, staging: str, leaf: str = "") -> str:
        """Where the record of a staging run lives, away from the payload.

        The payload folder has to be exactly what gets installed, so nothing
        belonging to this application may sit inside it. Everything that is
        bookkeeping, the manifest and the files a later disk disagreed about,
        goes here instead, in one folder the operator can delete once the
        title is in place.
        """
        base = atari_paths.join(staging, HOUSEKEEPING_DIRECTORY)
        return atari_paths.join(base, leaf) if leaf else base

    def _staging_paths(
        self, target: ImageSession, title: str, parent: str
    ) -> tuple[str, str, str]:
        """The three places a staged title occupies, worked out in one place.

        Every entry point needs the same trio and they have to agree: the
        payload folder that gets installed, the housekeeping folder beside it,
        and the legal GEMDOS leaf name both are built from. A title is a
        sentence and a GEMDOS name is eight characters, so the readable form
        is reduced here and kept in the manifest.
        """
        staging = self.staging_parent(parent)
        leaf = self.staged_folder_name(target, title)
        return staging, leaf, atari_paths.join(staging, leaf)

    @staticmethod
    def staged_folder_name(target: ImageSession, title: str) -> str:
        """The 8.3 folder name a readable title is staged under.

        ``Hyper Sports`` cannot be a GEMDOS name, so it becomes ``HYPER_SP``.
        The reduction is the filing system's own policy rather than a rule of
        this module, which is what keeps it the same everywhere.
        """
        policy = session_name_policy(target)
        wanted = str(title or "").strip()
        if not wanted:
            raise DiskError("Name the title before staging a disk under it.")
        return policy.normalise(wanted, fallback="TITLE")

    def _read_staged_manifest(self, target: ImageSession, staging: str, leaf: str) -> dict:
        folder = self._housekeeping_folder(staging, leaf)
        if not volume_copy.directory_exists(self, target, folder):
            return {}
        try:
            return json.loads(
                self.read_file(target, atari_paths.join(folder, MANIFEST_NAME)).decode("utf-8")
            )
        except Exception:
            # A record that cannot be read is a record that is not there. The
            # payload on the drive is the authority, and a staged set has to
            # stay usable when its notes are damaged or were never written.
            return {}

    def _write_staged_manifest(
        self, target: ImageSession, staging: str, leaf: str, manifest: dict
    ) -> None:
        """Record what was staged, on the drive itself.

        Keeping this on the image rather than on the host is what lets a drive
        be carried to another machine, or to a real Atari, and still describe
        the set that is waiting on it. It is written into the housekeeping
        folder, so installing the title never carries it along.
        """
        body = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
        volume_copy.write_file(
            self, target,
            atari_paths.join(self._housekeeping_folder(staging, leaf), MANIFEST_NAME),
            body,
        )

    def _next_disk_label(self, disks: list[dict], requested: str | None) -> str:
        """The label this disk is filed under, named or numbered in turn."""
        label = str(requested or "").strip()
        if label:
            return label
        used = {disk["label"] for disk in disks}
        position = 1
        while f"Disk {position}" in used:
            position += 1
        return f"Disk {position}"

    def stage_disk(
        self,
        source: ImageSession,
        target: ImageSession,
        title: str,
        *,
        parent: str = "",
        disk_label: str | None = None,
        progress: progress_module.Progress | None = None,
    ) -> dict:
        """Extract one disk into a folder on the drive it is destined for.

        Staging exists so that the install can be finished where the title
        will actually run, which means the disks have to be somewhere an Atari
        can reach: a folder on the target volume, not a directory on the
        machine running this application. An operator can then boot the drive
        in Hatari or put it in a real machine, open the folder and run the
        title's own installer against it.

        Disks of the same title merge into one tree, which is what an
        installer expects to be pointed at. Where two disks carry the same
        path with different contents the first is kept and the later one is
        filed in the housekeeping folder under the disk it came from, so a set
        is never silently reduced to its last disk.

        Staging under a label that is already present is the one exception:
        that is a correction, not a second disk, so its files overwrite what
        the earlier attempt left behind and any conflict recorded against that
        label is dropped.
        """
        report = progress_module.reporter(progress)
        self.require_mounted_volume(target)
        if self.summary(target).get("readOnly"):
            raise DiskError(f"{target.name} is open read-only, so nothing can be staged onto it.")
        self.require_writable_geometry(target)

        readable = str(title or source.name or "Untitled").strip() or "Untitled"
        staging, leaf, folder = self._staging_paths(target, readable, parent)

        manifest = self._read_staged_manifest(target, staging, leaf)
        disks = list(manifest.get("disks") or [])
        label = self._next_disk_label(disks, disk_label)
        alternates = atari_paths.join(
            self._housekeeping_folder(staging, leaf),
            session_name_policy(target).normalise(label, fallback="DISK"),
        )
        # Re-staging a disk under a label that is already there is a
        # correction, so its files replace what the earlier attempt wrote and
        # anything filed aside for that disk stops being true.
        replacing = any(disk["label"] == label for disk in disks)
        if replacing and volume_copy.directory_exists(self, target, alternates):
            volume_copy.delete_tree(self, target, alternates)

        report(f"Reading {source.name}", 0, None)
        copied = volume_copy.copy_volume_tree(
            self, source, target, folder,
            existing="replace" if replacing else "divert",
            divert_to=alternates,
            progress=report,
            message="Staging",
        )

        summary = self.summary(source)
        record = {
            "label": label,
            "source": source.name,
            # The volume label is what an installer and an operator both
            # recognise a disk by, and it is a property of the filing system
            # rather than of the file the image happens to be stored in.
            "volume": volume_copy.volume_name(self, source),
            "format": str(summary.get("kind") or source.kind),
            "bootable": bool(summary.get("bootable")),
            "files": copied.file_count,
            "bytes": copied.bytes_written,
            "added": _now(),
            "paths": sorted(set(copied.written) | set(copied.skipped) | set(copied.diverted)),
        }
        # Somebody re-staging Disk 1 after fixing it has one Disk 1, not two.
        # A set that silently grew every time it was corrected would be
        # impossible to reason about by the time it was installed.
        position = next(
            (offset for offset, disk in enumerate(disks) if disk["label"] == label), None
        )
        if position is None:
            disks.append(record)
        else:
            disks[position] = record

        earlier = {disk["label"] for disk in disks if disk["label"] != label}
        conflicts = [
            {
                "path": path,
                "keptFrom": next(
                    (disk["label"] for disk in disks if path in disk.get("paths", [])
                     and disk["label"] in earlier),
                    sorted(earlier)[0] if earlier else label,
                ),
                "alsoIn": label,
                "storedAs": atari_paths.join(alternates, path),
            }
            for path in copied.diverted
        ]
        # A conflict is only still true if the file it named is still the one
        # on disk. Restaging a disk rewrites its files, so anything recorded
        # against this label, or against a path this disk has just replaced,
        # is stale and would otherwise be reported for ever.
        rewritten = set(copied.written)
        carried = [
            conflict
            for conflict in (manifest.get("conflicts") or [])
            if conflict.get("alsoIn") != label and conflict.get("path") not in rewritten
        ]
        manifest.update({
            "title": readable,
            "name": leaf,
            "slug": slugify(readable),
            "parent": staging,
            "created": manifest.get("created") or _now(),
            "updated": _now(),
            "disks": disks,
            "conflicts": carried + conflicts,
        })
        self._write_staged_manifest(target, staging, leaf, manifest)
        self._persist_session(target)
        report("Staged", 1, 1)
        staged = self._staged_summary(target, staging, leaf, manifest)
        staged["warnings"] = copied.warnings
        return staged

    def _staged_summary(
        self, target: ImageSession, staging: str, leaf: str, manifest: dict | None = None
    ) -> dict:
        manifest = (
            manifest if manifest is not None
            else self._read_staged_manifest(target, staging, leaf)
        )
        folder = atari_paths.join(staging, leaf)
        disks = list(manifest.get("disks") or [])
        if disks:
            file_count = sum(int(disk.get("files") or 0) for disk in disks)
            total_bytes = sum(int(disk.get("bytes") or 0) for disk in disks)
        else:
            # A folder somebody made by hand, or one whose record was deleted,
            # is still a staged title. Measuring it is better than hiding it.
            staged_files = [
                entry for entry in volume_copy.walk_volume(self, target, folder)
                if not entry["directory"]
            ]
            file_count = len(staged_files)
            total_bytes = sum(int(entry.get("length") or 0) for entry in staged_files)
        return {
            "name": leaf,
            "slug": str(manifest.get("slug") or slugify(leaf)),
            "title": str(manifest.get("title") or leaf),
            "path": folder,
            "parent": staging,
            "disks": [
                {key: value for key, value in disk.items() if key != "paths"}
                for disk in disks
            ],
            "diskCount": len(disks),
            "fileCount": file_count,
            "bytes": total_bytes,
            "conflicts": list(manifest.get("conflicts") or []),
            "warnings": [],
            "created": str(manifest.get("created") or ""),
            "updated": str(manifest.get("updated") or ""),
        }

    def staged_titles(self, target: ImageSession, *, parent: str = "") -> list[dict]:
        """Every title waiting on this drive, most recently touched first.

        The list is read off the volume rather than out of a record kept here,
        so a drive built somewhere else, or one whose manifest was deleted,
        still reports what is sitting in its staging folder.
        """
        self.require_mounted_volume(target)
        staging = self.staging_parent(parent)
        if not volume_copy.directory_exists(self, target, staging):
            return []
        listing = self.list_directory(target, staging)
        titles = [
            self._staged_summary(target, staging, str(entry.get("name") or ""))
            for entry in listing.get("entries", [])
            if entry.get("type") == "dir"
            and str(entry.get("name") or "").casefold() != HOUSEKEEPING_DIRECTORY.casefold()
        ]
        return sorted(titles, key=lambda item: (item["updated"], item["name"]), reverse=True)

    def discard_staged_title(self, target: ImageSession, name: str, *, parent: str = "") -> None:
        """Remove a staged title from the drive, payload and record together."""
        self.require_mounted_volume(target)
        staging, leaf, folder = self._staging_paths(target, name, parent)
        if not volume_copy.directory_exists(self, target, folder):
            raise DiskError(f"There is no staged title called {leaf} in {staging}.")
        volume_copy.delete_tree(self, target, folder)
        housekeeping = self._housekeeping_folder(staging, leaf)
        if volume_copy.directory_exists(self, target, housekeeping):
            volume_copy.delete_tree(self, target, housekeeping)
        self._persist_session(target)

    def install_staged_title(
        self,
        target: ImageSession,
        name: str,
        *,
        parent: str = DEFAULT_INSTALL_PARENT,
        staging: str = "",
        folder: str | None = None,
        progress: progress_module.Progress | None = None,
    ) -> dict:
        """Move a staged title out of the staging folder into its own home.

        Both ends are on the same volume, so this is a move rather than a
        copy: the attributes and datestamps the disks carried are the ones
        already written, and nothing is read or written twice.

        Nothing in the moved tree is rewritten. TOS resolves a path at run
        time against the drive the program was started from, so a program that
        worked in A: works in ``C:\\GAMES\\TITLE`` without being patched, which
        is why there is no repair pass here.
        """
        from .gemdos_items import move_gemdos_items

        self.require_mounted_volume(target)
        self.require_writable_geometry(target)
        staging_parent, leaf, source = self._staging_paths(target, name, staging)
        if not volume_copy.directory_exists(self, target, source):
            raise DiskError(f"There is no staged title called {leaf} in {staging_parent}.")

        manifest = self._read_staged_manifest(target, staging_parent, leaf)
        readable = str(manifest.get("title") or leaf)
        policy = session_name_policy(target)
        target_leaf = policy.normalise(str(folder or "").strip() or leaf, fallback="TITLE")
        destination = atari_paths.join(atari_paths.normalise(parent), target_leaf)
        if destination.casefold() == source.casefold():
            raise DiskError(f"{readable} is already installed at {atari_paths.display(destination)}.")
        if volume_copy.directory_exists(self, target, destination):
            raise DiskError(
                f"{atari_paths.display(destination)} already exists. Choose another folder name."
            )

        report = progress_module.reporter(progress)
        report(f"Installing {readable}", 0, None)
        staged_files = [
            entry for entry in volume_copy.walk_volume(self, target, source)
            if not entry["directory"]
        ]
        if not staged_files:
            raise DiskError(f"{readable} has no staged files to install.")
        if atari_paths.normalise(parent):
            if not volume_copy.directory_exists(self, target, parent):
                self.make_directory(target, atari_paths.normalise(parent))
        move_gemdos_items(self, target, [{"source": source, "destination": destination}])
        housekeeping = self._housekeeping_folder(staging_parent, leaf)
        if volume_copy.directory_exists(self, target, housekeeping):
            volume_copy.delete_tree(self, target, housekeeping)
        self._persist_session(target)
        report("Installed", len(staged_files), len(staged_files))
        programs = sorted(
            atari_paths.leaf(entry["path"])
            for entry in staged_files
            if is_program_name(entry["path"])
            and atari_paths.parent(entry["path"]).casefold() == destination.casefold()
        )
        return {
            "path": destination,
            "title": readable,
            "name": target_leaf,
            "fileCount": len(staged_files),
            "programs": programs,
            "warnings": (
                [] if programs else
                [f"No program was found in {atari_paths.display(destination)}, so there is "
                 "nothing on this drive the desktop could start. Look in the folders "
                 "below it for the one the title runs."]
            ),
        }

    # ------------------------------------------------------------------
    # One program on its own
    # ------------------------------------------------------------------

    def install_program(
        self,
        source: ImageSession,
        target: ImageSession,
        path: str,
        *,
        parent: str = DEFAULT_INSTALL_PARENT,
        name: str = "",
    ) -> dict:
        """Copy one program off a disk into a folder on the drive.

        The smallest install there is, and the commonest: a single ``.PRG`` or
        ``.TOS`` that is the whole of the software. It is copied rather than
        staged, because there is nothing to merge and nothing to finish later.
        """
        self.require_mounted_volume(target)
        self.require_writable_geometry(target)
        if self.summary(target).get("readOnly"):
            raise DiskError(f"{target.name} is open read-only, so nothing can be installed onto it.")
        inner = atari_paths.normalise(path)
        if not inner:
            raise DiskError("Choose the program to install.")
        policy = session_name_policy(target)
        leaf = policy.normalise(str(name or "").strip() or atari_paths.leaf(inner), fallback="PROGRAM")
        if not is_program_name(leaf):
            raise DiskError(
                f"{leaf} is not a program TOS would start. A program is a .PRG, .APP, "
                ".TOS, .TTP, .GTP or .ACC."
            )
        payload = self.read_file(source, inner)
        folder = atari_paths.normalise(parent)
        if folder and not volume_copy.directory_exists(self, target, folder):
            self.make_directory(target, folder)
        destination = atari_paths.join(folder, leaf)
        volume_copy.write_file(self, target, destination, payload)
        self._mark_mutated(target)
        self._persist_session(target)
        return {
            "path": destination,
            "name": leaf,
            "bytes": len(payload),
            "source": source.name,
        }


__all__ = [
    "DEFAULT_INSTALL_PARENT",
    "DEFAULT_STAGING_PARENT",
    "HOUSEKEEPING_DIRECTORY",
    "MANIFEST_NAME",
    "PROGRAM_EXTENSIONS",
    "InstallMixin",
    "is_program_name",
    "slugify",
]
