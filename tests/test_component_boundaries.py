import ast
import inspect
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app.boot_sector import (
    STACK_SETTING,
    gemdos_catalogue_files,
    looks_like_text_script,
    read_gemdos_file,
)
from app.container_disk_service import ContainerDiskMixin
from app.disk_identity import analyse_directory
from app.disk_service import DiskService
from app.filesystem_disk_service import FilesystemDiskMixin
from app.flux_containers import FLUX_CONTAINERS
from app.gemdos_install_service import GemdosInstallMixin
from app.gemdos_items import delete_gemdos_items, move_gemdos_items
from app.partition_service import PartitionMixin
from app.rom_disk_service import RomDiskMixin
from app.session_disk_service import SessionDiskMixin


APP_ROOT = Path(__file__).resolve().parents[1] / "app"
ATARINUT_ADAPTER = APP_ROOT / "atarinut_internals.py"


def _private_engine_imports(source: Path) -> list[str]:
    """Return the private Atarinut names one module imports."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    borrowed: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if node.module != "atarinut" and not node.module.startswith("atarinut."):
            continue
        borrowed.extend(
            alias.name for alias in node.names if alias.name.startswith("_")
        )
    return borrowed


class ComponentBoundaryTests(unittest.TestCase):
    def test_partition_reading_is_owned_by_the_partition_component(self):
        self.assertTrue(issubclass(DiskService, PartitionMixin))
        self.assertNotIn("list_partitions", DiskService.__dict__)
        self.assertIs(DiskService.list_partitions, PartitionMixin.list_partitions)

    def test_boot_sector_helpers_answer_from_bytes_alone(self):
        """A catalogue scan reads an image in hand, with no session behind it.

        This is the whole reason the helpers are separate from the service: a
        sweep over several hundred images cannot afford to open a session for
        each one, so the volume walk and the shell-text checks take a buffer
        and give an answer.
        """
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = DiskService(root / "work")
            session = service.create_blank("ds-720k", "SCAN")
            payload = b"STACK 16384\r\nEXEC SETUP.PRG\r\n"
            source = root / "SETUP.BAT"
            source.write_bytes(payload)
            service.put(session, "SETUP.BAT", source)

            image = session.path.read_bytes()
            found = {item.path: item for item in gemdos_catalogue_files(image)}
            self.assertIn("SETUP.BAT", found)
            self.assertEqual(found["SETUP.BAT"].length, len(payload))
            self.assertEqual(read_gemdos_file(image, found["SETUP.BAT"]), payload)

            # The same bytes, read without a volume around them at all.
            self.assertTrue(looks_like_text_script(payload))
            self.assertFalse(looks_like_text_script(b"\x60\x1a\x00\x00"))
            match = STACK_SETTING.search(payload.decode("ascii"))
            self.assertIsNotNone(match)
            self.assertEqual(int(match.group(1)), 16384)

    def test_disk_identity_and_item_moves_have_one_home_each(self):
        """Neither is a service method, so neither can drift into two copies."""
        self.assertTrue(callable(analyse_directory))
        self.assertTrue(callable(move_gemdos_items))
        self.assertTrue(callable(delete_gemdos_items))
        routes = APP_ROOT / "routes"
        offenders = [
            path.name
            for path in routes.glob("*.py")
            if "def analyse_directory" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_container_conversion_is_owned_by_the_container_component(self):
        self.assertTrue(issubclass(DiskService, ContainerDiskMixin))
        self.assertNotIn("convert_container", DiskService.__dict__)
        self.assertIs(
            DiskService.convert_container, ContainerDiskMixin.convert_container
        )

    def test_rom_operations_are_owned_by_the_rom_component(self):
        self.assertTrue(issubclass(DiskService, RomDiskMixin))
        self.assertNotIn("put_rom_bank", DiskService.__dict__)
        self.assertIs(DiskService.put_rom_bank, RomDiskMixin.put_rom_bank)

    def test_session_operations_are_owned_by_the_session_component(self):
        self.assertTrue(issubclass(DiskService, SessionDiskMixin))
        self.assertNotIn("recoverable_sessions", DiskService.__dict__)
        self.assertIs(
            DiskService.recoverable_sessions, SessionDiskMixin.recoverable_sessions
        )

    def test_filesystem_mounts_are_owned_by_the_filesystem_component(self):
        self.assertTrue(issubclass(DiskService, FilesystemDiskMixin))
        self.assertNotIn("gemdos_mount", DiskService.__dict__)
        self.assertNotIn("tosrom_details", DiskService.__dict__)
        self.assertIs(DiskService.gemdos_mount, FilesystemDiskMixin.gemdos_mount)
        self.assertIs(DiskService.tosrom_details, FilesystemDiskMixin.tosrom_details)

    def test_system_installation_is_owned_by_the_install_component(self):
        self.assertTrue(issubclass(DiskService, GemdosInstallMixin))
        self.assertNotIn("carry_boot_option", DiskService.__dict__)
        self.assertIs(
            DiskService.carry_boot_option, GemdosInstallMixin.carry_boot_option
        )

    def test_copying_a_volume_into_another_has_one_implementation(self):
        """Staging and the system install were the same code twice.

        They were written separately, came out almost identical, and had
        already drifted: one warned about a file it could not read and carried
        on, the other raised and threw away everything it had copied. The
        shared component is what stops that happening again, so both callers
        are required to go through it rather than walk and write themselves.
        """
        for module in ("install_service.py", "workbench_install.py"):
            source = (APP_ROOT / module).read_text(encoding="utf-8")
            with self.subTest(module=module):
                self.assertIn("volume_copy.copy_volume_tree", source)
                # Reading a volume, writing the batch and spilling files to
                # host temporaries all belong to the shared component.
                self.assertNotIn("put_host_tree", source)
                self.assertNotIn("NamedTemporaryFile", source)

    def test_the_progress_callback_contract_is_declared_once(self):
        """Eighteen files each wrote out the same do-nothing callback."""
        offenders = [
            path.relative_to(APP_ROOT).as_posix()
            for path in APP_ROOT.rglob("*.py")
            if path.name != "progress.py"
            and (
                "progress or (lambda" in path.read_text(encoding="utf-8")
                or "Callable[[str, int | None, int | None], None]"
                in path.read_text(encoding="utf-8")
            )
        ]
        self.assertEqual(offenders, [])

    def test_byte_checksums_have_one_canonical_implementation(self):
        offenders = [
            path.relative_to(APP_ROOT).as_posix()
            for path in APP_ROOT.rglob("*.py")
            if path.name != "checksum.py"
            and "hashlib.sha256" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_the_engine_private_api_is_borrowed_in_one_module_only(self):
        """Reaching into Atarinut's underscore names stays contained.

        ``app/atarinut_internals.py`` is the reviewed place a private engine
        name may be named. Anywhere else and an engine upgrade breaks in front
        of a user instead of in the adapter's own test.
        """
        offenders = {
            path.relative_to(APP_ROOT.parent).as_posix(): borrowed
            for path in sorted(APP_ROOT.rglob("*.py"))
            if path != ATARINUT_ADAPTER
            and (borrowed := _private_engine_imports(path))
        }
        self.assertEqual(offenders, {})

    def test_flux_layout_rules_have_one_canonical_definition(self):
        """HFE and SCP drifted apart once; the shared module is what prevents it.

        The encode deliberately passes no layout argument at all. HxCFE picks
        its ST loader from the ``.st`` suffix and reads the shape out of the
        boot sector, so a layout name here would be a second copy of the
        geometry table kept in step by hand. The invariant is therefore that
        no layout argument and no engine layout name appears anywhere but the
        module that explains why.
        """
        offenders = [
            path.relative_to(APP_ROOT).as_posix()
            for path in APP_ROOT.rglob("*.py")
            if path.name != "flux_containers.py"
            and any(
                token in path.read_text(encoding="utf-8")
                for token in ("-uselayout:", "ATARIST_")
            )
        ]
        self.assertEqual(offenders, [])

    def test_both_flux_containers_share_one_save_implementation(self):
        self.assertIsNot(
            DiskService._prepare_hfe_download,
            DiskService._prepare_scp_download,
        )
        for container in ("hfe", "scp"):
            with self.subTest(container=container):
                source = inspect.getsource(
                    getattr(DiskService, f"_prepare_{container}_download")
                )
                self.assertIn("_prepare_flux_download", source)

    def test_the_hxcfe_conversion_plugins_are_declared_once(self):
        self.assertEqual(
            {identifier: container.plugin for identifier, container in FLUX_CONTAINERS.items()},
            {"hfe": "HXC_HFE", "scp": "SCP_FLUX_STREAM"},
        )
        offenders = [
            path.relative_to(APP_ROOT).as_posix()
            for path in APP_ROOT.rglob("*.py")
            if path.name != "flux_containers.py"
            and "SCP_FLUX_STREAM" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
