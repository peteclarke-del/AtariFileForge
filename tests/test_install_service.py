"""Installing a disk, as opposed to copying one, has to be checked end to end.

These tests build real images through the public service API and read the
results back the same way, because every interesting failure in this area is
one where the files are present and the thing still does not run: a second disk
that quietly replaced the first, a set staged somewhere no Atari can reach, a
title moved into a folder that already held something else.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import volume_copy
from app.disk_service import DiskError, DiskService
from app.install_service import (
    DEFAULT_INSTALL_PARENT,
    DEFAULT_STAGING_PARENT,
    HOUSEKEEPING_DIRECTORY,
    is_program_name,
    slugify,
)


def program(body: bytes = b"code") -> bytes:
    """The smallest thing TOS would accept as a program."""
    return b"\x60\x1a" + (0).to_bytes(4, "big") * 5 + (0).to_bytes(2, "big") + body


class StagingTests(unittest.TestCase):
    """Staging writes onto the drive, so every check is made against the drive.

    A staged set has to be reachable from the machine the title will run on.
    Reading the results back off the host filesystem would pass just as well
    against a staging directory nobody with an Atari could ever open.
    """

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)
        self.service = DiskService(self.root / "work")
        self.drive = self._drive()

    def _drive(self, name: str = "SYSTEM"):
        drive = self.service.create_blank("hd", name, "40MB")
        self.service.select_partition(drive, 0)
        return drive

    def _floppy(self, name: str, *, payload: bytes = b"data", locked: bool = False):
        floppy = self.service.create_blank("ds-720k", name)
        self.service.make_directory(floppy, "DATA")
        launcher = self.root / f"prg-{name}"
        launcher.write_bytes(program())
        self.service.put(
            floppy, "GAME.PRG", launcher, attributes="r----" if locked else None
        )
        data = self.root / f"dat-{name}"
        data.write_bytes(payload)
        self.service.put(floppy, "DATA\\LEVEL.DAT", data)
        return floppy

    def _names(self, directory: str) -> set[str]:
        return {
            str(row["name"])
            for row in self.service.list_directory(self.drive, directory)["entries"]
        }

    # -- where a staged set lands ---------------------------------------

    def test_a_staged_disk_lands_on_the_target_image_not_on_the_host(self) -> None:
        staged = self.service.stage_disk(
            self._floppy("GAME"), self.drive, "Hyper Sports"
        )

        self.assertEqual(staged["path"], "INSTALL\\STAGE\\HYPER_SP")
        self.assertEqual(
            self.service.read_file(self.drive, "INSTALL\\STAGE\\HYPER_SP\\DATA\\LEVEL.DAT"),
            b"data",
        )
        # Nothing is left behind on the host: the working directory holds
        # sessions and checkpoints, never a staging tree.
        self.assertFalse((self.service.work_dir / "staging").exists())

    def test_the_default_staging_folder_is_a_pair_of_gemdos_names(self) -> None:
        """The interface prints this path, and GEMDOS holds 8.3 names only."""
        self.assertEqual(DEFAULT_STAGING_PARENT, "INSTALL\\STAGE")
        for part in DEFAULT_STAGING_PARENT.split("\\"):
            self.assertLessEqual(len(part), 8)
        self.assertEqual(self.service.staging_parent(), DEFAULT_STAGING_PARENT)

    def test_a_sentence_of_a_title_becomes_a_folder_gemdos_can_hold(self) -> None:
        staged = self.service.stage_disk(
            self._floppy("GAME"), self.drive, "Bubble Bobble (1987)"
        )
        self.assertEqual(staged["name"], "BUBBLE_B")
        self.assertEqual(staged["title"], "Bubble Bobble (1987)")

    def test_the_staging_folder_can_be_chosen(self) -> None:
        staged = self.service.stage_disk(
            self._floppy("GAME"), self.drive, "TITLE", parent="GAMES\\WAITING"
        )
        self.assertEqual(staged["path"], "GAMES\\WAITING\\TITLE")

    def test_a_forward_slash_path_is_accepted_and_normalised(self) -> None:
        """A browser joins paths its own way; GEMDOS spells them with a backslash."""
        self.assertEqual(self.service.staging_parent("INSTALL/STAGE"), "INSTALL\\STAGE")

    # -- merging a set ---------------------------------------------------

    def test_two_disks_of_one_title_merge_into_one_tree(self) -> None:
        title = "Chuck Rock"
        self.service.stage_disk(self._floppy("ONE", payload=b"one"), self.drive, title)
        second = self._floppy("TWO", payload=b"one")
        extra = self.root / "extra"
        extra.write_bytes(b"level two")
        self.service.put(second, "DATA\\LEVEL2.DAT", extra)

        staged = self.service.stage_disk(second, self.drive, title)

        self.assertEqual(staged["diskCount"], 2)
        self.assertEqual(
            self._names("INSTALL\\STAGE\\CHUCK_RO\\DATA"), {"LEVEL.DAT", "LEVEL2.DAT"}
        )
        self.assertEqual(staged["conflicts"], [])

    def test_a_file_two_disks_disagree_about_is_kept_and_the_other_filed_aside(self) -> None:
        """A set is never silently reduced to whichever disk was staged last."""
        title = "Chuck Rock"
        self.service.stage_disk(self._floppy("ONE", payload=b"first"), self.drive, title)
        staged = self.service.stage_disk(
            self._floppy("TWO", payload=b"second"), self.drive, title
        )

        self.assertEqual(
            self.service.read_file(self.drive, "INSTALL\\STAGE\\CHUCK_RO\\DATA\\LEVEL.DAT"),
            b"first",
        )
        self.assertEqual(len(staged["conflicts"]), 1)
        conflict = staged["conflicts"][0]
        self.assertEqual(conflict["keptFrom"], "Disk 1")
        self.assertEqual(conflict["alsoIn"], "Disk 2")
        self.assertEqual(
            self.service.read_file(self.drive, conflict["storedAs"]), b"second"
        )

    def test_restaging_one_disk_corrects_it_rather_than_adding_another(self) -> None:
        title = "Chuck Rock"
        self.service.stage_disk(
            self._floppy("ONE", payload=b"broken"), self.drive, title, disk_label="Disk 1"
        )
        staged = self.service.stage_disk(
            self._floppy("ONE", payload=b"fixed"), self.drive, title, disk_label="Disk 1"
        )

        self.assertEqual(staged["diskCount"], 1)
        self.assertEqual(
            self.service.read_file(self.drive, "INSTALL\\STAGE\\CHUCK_RO\\DATA\\LEVEL.DAT"),
            b"fixed",
        )
        self.assertEqual(staged["conflicts"], [])

    def test_the_housekeeping_folder_is_never_listed_as_a_staged_title(self) -> None:
        self.service.stage_disk(self._floppy("ONE"), self.drive, "Title A")
        names = [row["name"] for row in self.service.staged_titles(self.drive)]
        self.assertEqual(names, ["TITLE_A"])
        self.assertIn(HOUSEKEEPING_DIRECTORY, self._names(DEFAULT_STAGING_PARENT))

    def test_the_manifest_lives_on_the_drive_and_not_beside_the_payload(self) -> None:
        """A drive carried to another machine still describes what is waiting."""
        self.service.stage_disk(self._floppy("ONE"), self.drive, "Title A")

        payload = self._names("INSTALL\\STAGE\\TITLE_A")
        self.assertEqual(payload, {"GAME.PRG", "DATA"})
        self.assertIn(
            "STAGE.INF", self._names("INSTALL\\STAGE\\CLASH\\TITLE_A")
        )

    def test_a_title_staged_by_hand_is_still_reported(self) -> None:
        """A folder somebody made themselves is a staged title; measuring beats hiding."""
        self.service.make_directory(self.drive, "INSTALL\\STAGE\\BYHAND")
        volume_copy.write_file(self.service, self.drive, "INSTALL\\STAGE\\BYHAND\\A.PRG", program())

        titles = {row["name"]: row for row in self.service.staged_titles(self.drive)}

        self.assertIn("BYHAND", titles)
        self.assertEqual(titles["BYHAND"]["fileCount"], 1)
        self.assertEqual(titles["BYHAND"]["diskCount"], 0)

    def test_discarding_removes_the_payload_and_the_record_together(self) -> None:
        self.service.stage_disk(self._floppy("ONE"), self.drive, "Title A")
        self.service.discard_staged_title(self.drive, "Title A")

        self.assertEqual(self.service.staged_titles(self.drive), [])
        self.assertFalse(
            volume_copy.directory_exists(self.service, self.drive, "INSTALL\\STAGE\\TITLE_A")
        )
        self.assertFalse(
            volume_copy.directory_exists(
                self.service, self.drive, "INSTALL\\STAGE\\CLASH\\TITLE_A"
            )
        )

    def test_discarding_something_that_is_not_there_is_refused(self) -> None:
        with self.assertRaises(DiskError):
            self.service.discard_staged_title(self.drive, "Nothing")

    def test_a_drive_with_no_partition_chosen_cannot_be_staged_onto(self) -> None:
        """A partitioned drive opens on its table, which is not a volume."""
        drive = self.service.create_blank("hd", "UNCHOSEN", "40MB")
        self.service.select_partition(drive, None)
        with self.assertRaises(DiskError) as raised:
            self.service.stage_disk(self._floppy("ONE"), drive, "Title")
        self.assertIn("partition", str(raised.exception))


class InstallingAStagedTitleTests(unittest.TestCase):
    """Installing moves the tree; both ends are on the same volume."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)
        self.service = DiskService(self.root / "work")
        self.drive = self.service.create_blank("hd", "SYSTEM", "40MB")
        self.service.select_partition(self.drive, 0)
        self.floppy = self.service.create_blank("ds-720k", "GAME")
        launcher = self.root / "prg"
        launcher.write_bytes(program())
        self.service.put(self.floppy, "CHUCK.PRG", launcher)
        self.service.make_directory(self.floppy, "DATA")
        data = self.root / "dat"
        data.write_bytes(b"level")
        self.service.put(self.floppy, "DATA\\LEVEL.DAT", data)

    def _stage(self, title: str = "Chuck Rock"):
        return self.service.stage_disk(self.floppy, self.drive, title)

    def test_a_staged_title_is_moved_into_its_own_folder(self) -> None:
        self._stage()
        result = self.service.install_staged_title(self.drive, "Chuck Rock")

        self.assertEqual(result["path"], "GAMES\\CHUCK_RO")
        self.assertEqual(result["fileCount"], 2)
        self.assertEqual(result["programs"], ["CHUCK.PRG"])
        self.assertEqual(
            self.service.read_file(self.drive, "GAMES\\CHUCK_RO\\DATA\\LEVEL.DAT"), b"level"
        )
        self.assertFalse(
            volume_copy.directory_exists(self.service, self.drive, "INSTALL\\STAGE\\CHUCK_RO")
        )

    def test_the_default_install_folder_is_the_one_a_prepared_drive_has(self) -> None:
        self.assertEqual(DEFAULT_INSTALL_PARENT, "GAMES")

    def test_the_volume_root_is_a_legitimate_destination(self) -> None:
        self._stage()
        result = self.service.install_staged_title(self.drive, "Chuck Rock", parent="")
        self.assertEqual(result["path"], "CHUCK_RO")

    def test_the_folder_name_can_be_chosen(self) -> None:
        self._stage()
        result = self.service.install_staged_title(
            self.drive, "Chuck Rock", folder="CHUCK"
        )
        self.assertEqual(result["path"], "GAMES\\CHUCK")

    def test_installing_over_something_that_is_there_is_refused(self) -> None:
        self._stage()
        self.service.make_directory(self.drive, "GAMES\\CHUCK_RO")
        with self.assertRaises(DiskError) as raised:
            self.service.install_staged_title(self.drive, "Chuck Rock")
        self.assertIn("already exists", str(raised.exception))

    def test_installing_something_that_was_never_staged_is_refused(self) -> None:
        with self.assertRaises(DiskError):
            self.service.install_staged_title(self.drive, "Nothing")

    def test_the_housekeeping_record_goes_with_the_title(self) -> None:
        self._stage()
        self.service.install_staged_title(self.drive, "Chuck Rock")
        self.assertFalse(
            volume_copy.directory_exists(
                self.service, self.drive, "INSTALL\\STAGE\\CLASH\\CHUCK_RO"
            )
        )

    def test_a_title_with_no_program_in_its_root_says_so(self) -> None:
        """A folder of data is not something the desktop could ever start."""
        data_only = self.service.create_blank("ds-720k", "DATA")
        payload = self.root / "only"
        payload.write_bytes(b"sample")
        self.service.put(data_only, "READ.ME", payload)
        self.service.stage_disk(data_only, self.drive, "Notes")

        result = self.service.install_staged_title(self.drive, "Notes")

        self.assertEqual(result["programs"], [])
        self.assertTrue(result["warnings"])
        self.assertIn("No program was found", result["warnings"][0])


class SingleProgramTests(unittest.TestCase):
    """The smallest install there is, and the commonest."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)
        self.service = DiskService(self.root / "work")
        self.drive = self.service.create_blank("hd", "SYSTEM", "40MB")
        self.service.select_partition(self.drive, 0)
        self.floppy = self.service.create_blank("ds-720k", "TOOLS")
        source = self.root / "prg"
        source.write_bytes(program(b"a tool"))
        self.service.put(self.floppy, "TOOL.PRG", source)
        note = self.root / "note"
        note.write_bytes(b"read me")
        self.service.put(self.floppy, "READ.ME", note)

    def test_one_program_is_copied_into_the_folder_named(self) -> None:
        result = self.service.install_program(
            self.floppy, self.drive, "TOOL.PRG", parent="GEMSYS"
        )

        self.assertEqual(result["path"], "GEMSYS\\TOOL.PRG")
        self.assertEqual(
            self.service.read_file(self.drive, "GEMSYS\\TOOL.PRG"), program(b"a tool")
        )

    def test_the_program_can_be_renamed_on_the_way_in(self) -> None:
        result = self.service.install_program(
            self.floppy, self.drive, "TOOL.PRG", name="Hard Disk Tool.PRG"
        )
        self.assertEqual(result["name"], "HARD_DIS.PRG")

    def test_a_file_tos_would_not_start_is_refused(self) -> None:
        with self.assertRaises(DiskError) as raised:
            self.service.install_program(self.floppy, self.drive, "READ.ME")
        self.assertIn(".PRG", str(raised.exception))

    def test_the_extensions_tos_starts_are_the_ones_accepted(self) -> None:
        for name in ("A.PRG", "A.APP", "A.TOS", "A.TTP", "A.GTP", "A.ACC"):
            self.assertTrue(is_program_name(name), name)
        for name in ("A.DAT", "READ.ME", "A"):
            self.assertFalse(is_program_name(name), name)


class SlugTests(unittest.TestCase):
    def test_a_title_reduces_to_a_stable_identifier(self) -> None:
        self.assertEqual(slugify("Chuck Rock (1991)"), "chuck-rock-1991")
        self.assertEqual(slugify("  "), "untitled")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
