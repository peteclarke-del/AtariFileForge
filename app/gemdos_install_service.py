r"""Carrying a disk's bootability with its files, and auditing what is installed.

Two jobs that both belong to software already on a drive rather than to the
act of putting it there.

``carry_boot_option`` copies a source disk's boot-sector executability onto
the destination volume, because a disk's files without its boot sector give a
volume the machine will not start from.

The audit is the other half. Once a drive has software on it, the questions
worth asking are whether every program on it is a program the machine would
actually run, and whether the desktop still names files that are there. Both
are answered from the drive itself, and only the second has a repair, because
it is the only one where the right change is provable: a desktop record that
names a file which is not on the volume cannot start anything, and removing it
takes nothing away.

There is no path-rewriting pass here. The previous platform named files
through a device, so a program copied from a floppy to a hard disk referred to
a drive that was no longer where it lived. TOS resolves a path at run time
against the drive the program was started from, and a relative path spelled
with a leading backslash means the current drive either way, so a program
installed onto a partition finds its files without anything being patched.
"""

from __future__ import annotations

import re

from . import atari_paths
from . import progress as progress_module
from .disk_identity import (
    DESKTOP_FILES,
    INSTALL_RECORDS,
    LAUNCH_ACTIONS,
    extension_of,
    program_header,
)
from .errors import DiskError
from .image_session import ImageSession


#: How much of a file is read to decide whether it is a program. A GEMDOS
#: header is 28 bytes, but the sizes in it are checked against the file's own
#: length, so the whole file is what settles it.
PROGRAM_AUDIT_LIMIT = 8 * 1024 * 1024


def desktop_record_paths(text: str) -> list[tuple[str, str]]:
    r"""Every ``(record, path)`` pair a desktop configuration installs.

    Only records that name one file are returned. ``#G 03 FF 000 *.PRG@ @ @``
    associates an extension with the desktop's GEM launcher and names nothing,
    so there is nothing about it that could be stale.
    """
    found: list[tuple[str, str]] = []
    for line in re.split(r"\r\n|\r|\n", str(text or "")):
        if len(line) < 2 or line[0] != "#" or line[1] not in (INSTALL_RECORDS | {"X"}):
            continue
        head = line.split("@", 1)[0].split(None, 4)
        if len(head) < 2:
            continue
        path = head[-1].strip()
        if not path or "*" in path or "?" in path:
            continue
        found.append((line, path))
    return found


def inner_path_of(record_path: str) -> str:
    r"""The volume-relative path a desktop record names.

    A record spells its path from the drive letter, ``C:\GAMES\X\X.PRG``. The
    volume it is on is the volume the configuration was read from, so the
    letter is dropped and what is left is an ordinary inner path.
    """
    text = str(record_path or "").strip()
    if len(text) > 1 and text[1] == ":":
        text = text[2:]
    return atari_paths.normalise(text)


class GemdosInstallMixin:
    """Carry a disk's bootability with its files, and audit installed trees."""

    def carry_boot_option(
        self, source: ImageSession, target: ImageSession, destination: str
    ) -> int | None:
        """Give the destination volume the source disk's bootability.

        Installing a disk's files without its boot sector leaves an image the
        machine will not start from: the ROM reads sector 0, finds a sector
        whose word sum is not 0x1234, and carries on to the next drive. The
        boot sector is what makes the difference, so it is carried across with
        the files.

        Only the volume root is eligible. A boot sector's own code loads what
        it expects to find in the root of the disk it came from, so setting it
        after extracting into a folder would start a loader whose files are no
        longer where it looks, and turn a working image into one that fails on
        boot. Software installed into its own folder is reached from the
        desktop instead, which makes that folder current first.

        Returns the option carried across, or None when there was nothing to
        carry. A failure to set it is reported as a warning rather than
        raised: the files are already installed and are still usable by hand.
        """
        if target.kind != "gemdos":
            return None
        if atari_paths.normalise(destination):
            return None
        try:
            reported = str(self._run(["opt", str(source.path)])).strip()
        except DiskError:
            return None
        digits = reported.split(" ", 1)[0]
        if not digits.isdigit():
            return None
        option = int(digits)
        if option == 0:
            return None
        try:
            self._run(["opt", str(target.path), str(option)])
        except DiskError as exc:
            self._append_warning(
                target,
                "The files were installed, but the source disk's boot option "
                f"could not be set on the destination: {exc}",
            )
            return None
        self._mark_mutated(target)
        return option

    # ------------------------------------------------------------------
    # Auditing what is installed
    # ------------------------------------------------------------------
    def _require_drive_volume(self, session: ImageSession) -> None:
        if not self.mountable(session):
            raise DiskError(
                "Installed software auditing needs a GEMDOS volume. Open a "
                "partition on the drive first."
            )
        if session.kind != "hd" and not self.summary(session)["hardDisk"]:
            raise DiskError(
                "Installed software auditing is available only for a volume on a "
                "hard drive. A floppy holds one title and is read as one."
            )

    def _desktop_configurations(self, mount) -> list[tuple[str, str]]:
        """Every desktop configuration on this volume, with its text."""
        found = []
        for name in DESKTOP_FILES:
            if not mount.exists(name):
                continue
            try:
                found.append((name, mount.read_bytes(name).decode("latin-1", "replace")))
            except Exception:
                continue
        return found

    @staticmethod
    def _program_fault(mount, path: str) -> str:
        """Why the machine would refuse this program, or an empty string.

        A name is not evidence. A file called ``GAME.PRG`` whose first word is
        not ``0x601A`` is a data file somebody misnamed, and one whose header
        declares more text and data than the file holds was truncated on its
        way here. Both are worth saying and neither can be repaired from here.
        """
        try:
            if mount.stat(path).size > PROGRAM_AUDIT_LIMIT:
                return ""
            data = mount.read_bytes(path)
        except Exception as exc:
            return f"{path} could not be read: {exc}"
        header = program_header(data)
        if header is None:
            if len(data) < 28:
                return f"{path} is {len(data)} bytes, which is shorter than a program header."
            if data[:2] != b"\x60\x1a":
                return (
                    f"{path} is named as a program but its first word is not 0x601A, "
                    "so TOS would refuse to run it."
                )
            return (
                f"{path} carries a 0x601A header whose declared sizes are larger than "
                "the file, so it is truncated."
            )
        return ""

    def audit_drive_software(
        self,
        session: ImageSession,
        root: str = "",
        progress: progress_module.Progress | None = None,
    ) -> dict:
        """Report every folder of installed software and what is wrong with it.

        The first pass is read-only and says exactly what it would change. A
        desktop record naming a file that is not on the volume is the only
        provable fault, so it is the only one offered as a repair; everything
        else is reported and left alone.
        """
        self._require_drive_volume(session)
        report = progress_module.reporter(progress)
        start = atari_paths.normalise(root)
        findings: list[dict] = []
        with self.gemdos_mount(session, writable=False) as mount:
            if not mount.exists(start):
                raise DiskError(f"Path not found: {atari_paths.display(start)}")

            report("Reading the desktop configuration", 0, None)
            stale: dict[str, list[dict]] = {}
            for name, text in self._desktop_configurations(mount):
                for record, spelled in desktop_record_paths(text):
                    inner = inner_path_of(spelled)
                    if not inner or mount.exists(inner):
                        continue
                    owner = atari_paths.parent(inner)
                    stale.setdefault(owner, []).append(
                        {"file": name, "record": record, "path": inner}
                    )

            directories: dict[str, list[str]] = {}
            pending = [start]
            while pending:
                current = pending.pop()
                try:
                    entries = list(mount.iter_entries(current))
                except Exception:
                    continue
                directories[current] = [
                    str(entry.name) for entry in entries if not entry.is_dir
                ]
                pending.extend(str(entry.path) for entry in entries if entry.is_dir)

            interesting = sorted(
                set(stale) | {
                    path for path, names in directories.items()
                    if any(extension_of(name) in LAUNCH_ACTIONS for name in names)
                },
                key=lambda item: (atari_paths.depth(item), item.casefold()),
            )
            for offset, directory in enumerate(interesting):
                report(f"Checking installed software in {atari_paths.display(directory)}",
                       offset, len(interesting))
                names = directories.get(directory, [])
                programs = [name for name in names if extension_of(name) in LAUNCH_ACTIONS]
                warnings = [
                    fault for fault in (
                        self._program_fault(mount, atari_paths.join(directory, name))
                        for name in programs
                    ) if fault
                ]
                repairs = [
                    f"Remove the {item['file']} record that installs "
                    f"{atari_paths.display(item['path'])}, which is not on this volume"
                    for item in stale.get(directory, [])
                ]
                findings.append({
                    "path": directory,
                    "source": session.source_names.get(directory, ""),
                    "fileCount": len(names),
                    "programs": sorted(programs),
                    "repairs": repairs,
                    "warnings": warnings,
                    "status": "repairable" if repairs else "warning" if warnings else "clean",
                })
            report("Installed software audit complete", len(interesting), len(interesting))
        return {
            "root": start,
            "directories": findings,
            "checked": len(findings),
            "repairable": sum(bool(item["repairs"]) for item in findings),
            "warnings": sum(bool(item["warnings"]) for item in findings),
        }

    def repair_drive_software(
        self,
        session: ImageSession,
        directories: list[str],
        progress: progress_module.Progress | None = None,
    ) -> dict:
        """Remove the desktop records that name files which are not there.

        The audit is run again first. An audit result can be minutes old and
        the drive can have changed since, and a repair that acts on a stale
        finding would delete a record that had just become correct.
        """
        self._require_drive_volume(session)
        unique = [
            atari_paths.normalise(path) for path in directories if str(path or "").strip()
        ]
        unique = list(dict.fromkeys(unique))
        if not unique:
            raise DiskError("Choose at least one folder with a repair to make.")
        current = self.audit_drive_software(session)
        available = {item["path"] for item in current["directories"] if item["repairs"]}
        unknown = [path for path in unique if path not in available]
        if unknown:
            raise DiskError(
                "The audit result is stale, or no provable repair remains for: "
                + ", ".join(atari_paths.display(path) for path in unknown)
            )
        report = progress_module.reporter(progress)
        repaired: list[dict] = []
        with self.gemdos_mount(session) as mount:
            configurations = self._desktop_configurations(mount)
            dropped: dict[str, list[str]] = {name: [] for name, _text in configurations}
            for offset, directory in enumerate(unique):
                report(f"Repairing the desktop record for {atari_paths.display(directory)}",
                       offset, len(unique))
                removed: list[str] = []
                for name, text in configurations:
                    for record, spelled in desktop_record_paths(text):
                        inner = inner_path_of(spelled)
                        if atari_paths.parent(inner) != directory or mount.exists(inner):
                            continue
                        dropped[name].append(record)
                        removed.append(record)
                repaired.append({"path": directory, "repairs": removed, "warnings": []})
            for name, text in configurations:
                if not dropped[name]:
                    continue
                keep = [
                    line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                    if line and line not in dropped[name]
                ]
                mount.write_bytes(name, ("\r\n".join(keep) + "\r\n").encode("latin-1"))
                self._append_warning(
                    session,
                    f"{name}: {len(dropped[name])} desktop record(s) that named files "
                    "which are not on this volume were removed.",
                )
        self._mark_mutated(session)
        self._persist_session(session)
        report("Installed software repair complete", len(unique), len(unique))
        return {"repaired": repaired, "count": len(repaired)}


__all__ = [
    "PROGRAM_AUDIT_LIMIT",
    "GemdosInstallMixin",
    "desktop_record_paths",
    "inner_path_of",
]
