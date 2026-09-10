from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

from app.deployment_service import (
    DEPLOYMENT_FORMAT,
    _profile_findings,
    available_deployment_targets,
    build_deployment_archive,
    deployment_plan,
    deployment_readme,
)
from app.errors import DiskError


MEBIBYTE = 1024 * 1024


class FakeService:
    """Everything the deployment assistant asks a disk service for.

    Building the fixture here rather than through ``DiskService`` keeps the
    packaging logic under test on its own: what the assistant does with a
    catalogue row, a partition entry and a summary is exactly what a real
    service would hand it.
    """

    def __init__(self, work_dir: Path, *, hard_disk=False, byte_swapped=False,
                 partitions=None, tree=None, contents=None):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.hard_disk = hard_disk
        self.byte_swapped = byte_swapped
        self.partitions = list(partitions or [])
        self.tree = dict(tree or {})
        self.contents = dict(contents or {})
        self.exports = 0

    def summary(self, session):
        stat = session.path.stat()
        return {
            "revision": f"{stat.st_size}:{stat.st_mtime_ns}",
            "hardDisk": self.hard_disk,
            "byteSwapped": self.byte_swapped,
        }

    def prepare_download(self, session, progress=None):
        return session.path

    def list_partitions(self, session):
        return list(self.partitions)

    def list_directory(self, session, inner, side=None):
        return {"entries": list(self.tree.get(inner, [])), "path": inner}

    def export_file(self, session, path, side=None):
        self.exports += 1
        target = self.work_dir / f"export-{self.exports}.bin"
        target.write_bytes(self.contents.get(path, b"data"))
        return target


def make_session(path: Path, kind: str = "gemdos", **overrides) -> SimpleNamespace:
    session = SimpleNamespace(
        id="a" * 32,
        name=path.name,
        kind=kind,
        path=path,
        descriptor_path=None,
        descriptor_name=None,
        partition=None,
        hardware_profile={},
        target_hardware="auto",
        warnings=[],
        compatibility_reports=[],
        editor_projects={},
        ffs_capabilities={},
        lock=None,
        finalised_mtime_ns=None,
    )
    for key, value in overrides.items():
        setattr(session, key, value)
    return session


def floppy(work_dir: Path, name: str = "ARCADIAN") -> SimpleNamespace:
    path = work_dir / f"{name}.st"
    path.write_bytes(bytes(720 * 1024))
    return make_session(path)


def drive(work_dir: Path, name: str = "SYSTEM") -> SimpleNamespace:
    path = work_dir / f"{name}.img"
    path.write_bytes(bytes(4 * MEBIBYTE))
    return make_session(path, "hd")


class DeploymentTargetTests(unittest.TestCase):
    def test_a_floppy_offers_the_gotek_and_explains_the_card_targets(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = FakeService(Path(folder) / "work")
            session = floppy(service.work_dir)

            targets = {row["id"]: row for row in available_deployment_targets(service, session)}

            self.assertTrue(targets["gotek"]["available"])
            self.assertTrue(targets["gemdos-folder"]["available"])
            for identifier in ("sd-card", "cf-card", "acsi-drive"):
                self.assertFalse(targets[identifier]["available"])
                self.assertIn("hard-drive image", targets[identifier]["reason"])

    def test_a_drive_offers_the_card_targets_and_refuses_the_gotek(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = FakeService(Path(folder) / "work", hard_disk=True)
            session = drive(service.work_dir)

            targets = {row["id"]: row for row in available_deployment_targets(service, session)}

            self.assertTrue(targets["sd-card"]["available"])
            self.assertTrue(targets["cf-card"]["available"])
            self.assertTrue(targets["acsi-drive"]["available"])
            self.assertFalse(targets["gotek"]["available"])
            self.assertIn("floppy images", targets["gotek"]["reason"])
            # A whole drive is not one volume, so there is nothing to copy out
            # as a folder until a partition is selected.
            self.assertFalse(targets["gemdos-folder"]["available"])
            session.partition = 0
            selected = {row["id"]: row for row in available_deployment_targets(service, session)}
            self.assertTrue(selected["gemdos-folder"]["available"])


class GotekDeploymentTests(unittest.TestCase):
    def test_native_plan_uses_a_snapshot_without_touching_the_source(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = FakeService(Path(folder) / "work")
            session = floppy(service.work_dir)
            original = session.path.read_bytes()
            revision = service.summary(session)["revision"]

            plan = deployment_plan(service, session, {"target": "gotek", "gotekMode": "native"})

            self.assertEqual(plan["format"], DEPLOYMENT_FORMAT)
            self.assertEqual(plan["source"]["revision"], revision)
            self.assertEqual(plan["entries"][0]["path"], "GOTEK-USB/ARCADIAN.st")
            self.assertEqual(plan["entries"][1]["path"], "GOTEK-USB/FF.CFG")
            self.assertTrue(plan["canProceed"])
            self.assertEqual(session.path.read_bytes(), original)
            self.assertEqual(service.summary(session)["revision"], revision)

    def test_indexed_package_names_the_image_dska_and_carries_its_config(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = FakeService(Path(folder) / "work")
            session = floppy(service.work_dir, "GAME")
            output = Path(folder) / "deployment.zip"
            payload = {"target": "gotek", "gotekMode": "indexed", "startIndex": 12}
            plan = deployment_plan(service, session, payload)

            built = build_deployment_archive(
                service, session,
                {**payload, "expectedRevision": plan["source"]["revision"]},
                output,
            )

            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("Deployment/manifest.json"))
                config = archive.read("GOTEK-USB/FF.CFG").decode("ascii")
                readme = archive.read("README.md").decode("utf-8")
            self.assertIn("GOTEK-USB/DSKA0012.st", names)
            self.assertIn("Deployment/compatibility-report.md", names)
            self.assertIn("nav-mode = indexed", config)
            self.assertIn("host = atari", config)
            self.assertEqual(manifest["target"], "gotek")
            self.assertEqual(built["source"]["revision"], plan["source"]["revision"])
            self.assertIn("## Verification", readme)
            self.assertIn("## Recovery", readme)

    def test_a_package_built_from_a_stale_review_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = FakeService(Path(folder) / "work")
            session = floppy(service.work_dir, "GAME")

            with self.assertRaisesRegex(DiskError, "changed after deployment review"):
                build_deployment_archive(service, session, {
                    "target": "gotek", "gotekMode": "native", "expectedRevision": "stale",
                }, Path(folder) / "deployment.zip")

    def test_a_container_flashfloppy_cannot_read_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = FakeService(Path(folder) / "work")
            path = service.work_dir / "RECORDING.scp"
            path.write_bytes(bytes(1024))
            session = make_session(path, "gemdos")

            with self.assertRaisesRegex(DiskError, "FlashFloppy reads"):
                deployment_plan(service, session, {"target": "gotek", "gotekMode": "native"})


class CardDeploymentTests(unittest.TestCase):
    def test_the_sd_card_package_is_the_whole_drive_as_one_raw_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = FakeService(
                Path(folder) / "work", hard_disk=True,
                partitions=[{"device": "C:", "id": "GEM", "sizeBytes": 4 * MEBIBYTE}],
            )
            session = drive(service.work_dir)

            plan = deployment_plan(service, session, {"target": "sd-card"})

            self.assertEqual(plan["entries"][0]["path"], "SD-CARD/SYSTEM.img")
            self.assertEqual(plan["entries"][0]["role"], "whole drive image")
            self.assertTrue(plan["canProceed"])
            self.assertTrue(any("dd" in step for step in plan["instructions"]))
            self.assertTrue(any("1 GiB" in step for step in plan["instructions"]))

    def test_the_cf_card_package_names_the_hatari_swap_option(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = FakeService(Path(folder) / "work", hard_disk=True, byte_swapped=True)
            session = drive(service.work_dir)

            plan = deployment_plan(service, session, {"target": "cf-card"})

            self.assertEqual(plan["entries"][0]["path"], "CF-CARD/SYSTEM.img")
            self.assertTrue(any("--ide-swap" in step for step in plan["instructions"]))

    def test_the_acsi_package_records_the_tos_partition_limits(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            service = FakeService(
                Path(folder) / "work", hard_disk=True,
                partitions=[{"device": "C:", "id": "BGM", "sizeBytes": 300 * MEBIBYTE}],
            )
            session = drive(service.work_dir)

            plan = deployment_plan(service, session, {"target": "acsi-drive"})
            readme = deployment_readme(plan)

            self.assertEqual(plan["entries"][0]["path"], "ACSI-DRIVE/SYSTEM.img")
            self.assertTrue(any("256 MiB" in item["message"] for item in plan["issues"]))
            self.assertIn("256 MiB", readme)


class GemdosFolderDeploymentTests(unittest.TestCase):
    def test_the_folder_tree_is_upper_case_8_3_and_keeps_auto(self) -> None:
        tree = {
            "": [
                {"name": "AUTO", "type": "dir", "length": 0},
                {"name": "readme.txt", "type": "file", "length": 4},
            ],
            "AUTO": [{"name": "START.PRG", "type": "file", "length": 4}],
        }
        with tempfile.TemporaryDirectory() as folder:
            service = FakeService(Path(folder) / "work", tree=tree)
            session = floppy(service.work_dir, "TOOLS")
            output = Path(folder) / "deployment.zip"

            build_deployment_archive(service, session, {"target": "gemdos-folder"}, output)

            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                config = archive.read("hatari.cfg").decode("utf-8")
            self.assertIn("GEMDOS-DRIVE/AUTO/START.PRG", names)
            self.assertIn("GEMDOS-DRIVE/README.TXT", names)
            self.assertIn("bUseHardDiskDirectory = TRUE", config)


class ProfileFindingTests(unittest.TestCase):
    def test_a_target_the_machine_cannot_read_is_reported(self) -> None:
        session = make_session(Path("unused.st"), hardware_profile={
            "machine": "st", "addons": ["tos-104", "drive-a-ds"],
        })

        messages = [item["message"] for item in _profile_findings(session, "gotek")]

        self.assertTrue(any("gotek" in message for message in messages), messages)

    def test_a_declared_interface_satisfies_its_target(self) -> None:
        session = make_session(Path("unused.img"), "hd", hardware_profile={
            "machine": "st", "addons": ["tos-206", "ultrasatan", "driver-hddriver"],
        })

        messages = [item["message"] for item in _profile_findings(session, "sd-card")]

        self.assertFalse(any("declares none of" in message for message in messages), messages)

    def test_a_partition_larger_than_the_selected_tos_mounts_is_reported(self) -> None:
        session = make_session(Path("unused.img"), "hd", hardware_profile={
            "machine": "st", "addons": ["tos-100", "acsi-megafile"],
        })

        messages = [
            item["message"] for item in _profile_findings(
                session, "acsi-drive",
                partitions=[{"device": "C:", "sizeBytes": 40 * MEBIBYTE}],
            )
        ]

        self.assertTrue(any("tos-100 will mount" in message for message in messages), messages)

    def test_a_byte_swapped_image_is_reported_for_an_acsi_target(self) -> None:
        session = make_session(Path("unused.img"), "hd", hardware_profile={
            "machine": "megaste", "addons": ["tos-206", "acsi2stm"],
        })

        messages = [
            item["message"]
            for item in _profile_findings(session, "sd-card", byte_swapped=True)
        ]

        self.assertTrue(any("un-swap the image" in message for message in messages), messages)

    def test_a_plain_image_is_reported_for_an_ide_target(self) -> None:
        session = make_session(Path("unused.img"), "hd", hardware_profile={
            "machine": "falcon030", "addons": ["tos-4xx", "ide-internal"],
        })

        messages = [
            item["message"]
            for item in _profile_findings(session, "cf-card", byte_swapped=False)
        ]

        self.assertTrue(any("--ide-swap" in message for message in messages), messages)

    def test_a_bare_volume_is_still_a_card_target_with_a_geometry_warning(self) -> None:
        session = make_session(Path("unused.img"), "hd", hardware_profile={
            "machine": "st", "addons": ["tos-206", "ultrasatan"],
        })

        messages = [
            item["message"]
            for item in _profile_findings(session, "sd-card", has_partition_table=False)
        ]

        self.assertTrue(any("no partition table" in message for message in messages), messages)


if __name__ == "__main__":
    unittest.main()
