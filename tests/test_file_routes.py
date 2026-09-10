import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from flask import Flask

from app.errors import DiskError
from app.operations import OperationRegistry
from app.routes.files import create_files_blueprint


class FileRouteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.service = Mock()
        self.session = SimpleNamespace(kind="gemdos")
        self.service.get.return_value = self.session
        self.service.summary.return_value = {"id": "a" * 32, "kind": "gemdos"}
        app = Flask(__name__)
        app.register_blueprint(
            create_files_blueprint(
                self.service,
                Path(self.temporary.name),
                OperationRegistry(),
            )
        )
        # The production server turns a DiskError into a 400; the blueprint
        # under test is registered on its own, so the same handler is added
        # here rather than letting a refusal look like a crash.
        app.register_error_handler(DiskError, lambda error: ({"error": str(error)}, 400))
        self.client = app.test_client()

    def tearDown(self):
        self.temporary.cleanup()

    def test_delete_sends_all_selected_rom_banks_in_one_call(self):
        """A bank inside a ROM is addressed by index, not by path."""
        self.session.kind = "rom"
        response = self.client.post(
            "/api/images/test/delete",
            json={
                "items": [
                    {"bank": 1},
                    {"bank": 3},
                ],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.service.clear_rom_banks.assert_called_once_with(self.session, [1, 3])
        self.assertEqual(len(response.get_json()["deletedItems"]), 2)

    def test_access_change_sends_all_selected_files_in_one_mutation(self):
        self.service.set_access.return_value = ["ONE.DAT", "TWO.DAT"]
        response = self.client.post(
            "/api/images/test/lock",
            json={
                "paths": ["ONE.DAT", "TWO.DAT"],
                "unlock": True,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.service.set_access.assert_called_once_with(
            self.session,
            ["ONE.DAT", "TWO.DAT"],
            True,
        )

    def test_metadata_change_writes_the_attribute_byte_and_the_datestamp(self):
        self.service.set_file_metadata.return_value = {
            "attributes": 0x05,
            "attributesText": "r-s---",
            "access": 0x05,
            "datestamp": "1987-06-30T12:00:00.000",
            "length": 2048,
        }
        response = self.client.post(
            "/api/images/test/metadata",
            json={
                "path": "GAMES\\LOADER.PRG",
                "attributes": "r-s---",
                "datestamp": "1987-06-30T12:00:00.000",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.service.set_file_metadata.assert_called_once_with(
            self.session,
            "GAMES\\LOADER.PRG",
            "r-s---",
            datestamp="1987-06-30T12:00:00.000",
        )
        self.assertEqual(
            response.get_json()["metadata"]["attributesText"], "r-s---"
        )

    def test_mkdir_validates_and_creates_a_folder(self):
        response = self.client.post(
            "/api/images/test/mkdir",
            json={"path": "GAMES/NEWDIR"},
        )

        self.assertEqual(response.status_code, 200)
        self.service.validate_leaf_name.assert_called_once_with(
            self.session,
            "NEWDIR",
        )
        # Either separator is accepted on input, and the path travels to the
        # volume as it was written; the volume itself decides the spelling.
        self.service.make_directory.assert_called_once_with(
            self.session,
            "GAMES/NEWDIR",
        )

    def test_mkdir_creates_a_folder_inside_a_partition(self):
        """A partition is a real GEMDOS volume, so it nests folders."""
        self.session.kind = "hd"
        self.session.partition = 0

        response = self.client.post(
            "/api/images/test/mkdir",
            json={"path": "GAMES/NEWDIR", "partition": 0},
        )

        self.assertEqual(response.status_code, 200)
        self.service.select_partition.assert_called_once_with(self.session, 0)
        self.service.make_directory.assert_called_once_with(
            self.session,
            "GAMES/NEWDIR",
        )

    def test_mkdir_is_refused_where_there_are_no_directories(self):
        self.session.kind = "rom"
        self.service.mountable.return_value = False

        response = self.client.post(
            "/api/images/test/mkdir",
            json={"path": "GAMES"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("no directories", response.get_json()["error"])
        self.service.make_directory.assert_not_called()

    def test_folder_import_sends_the_complete_reviewed_batch_once(self):
        self.service.put_host_tree.return_value = {
            "imported": ["GAMES\\PACK\\ONE.DAT", "GAMES\\PACK\\SUB\\TWO.DAT"],
            "conflicts": [],
        }

        response = self.client.post(
            "/api/images/test/folder-import",
            data={
                "files": [
                    (io.BytesIO(b"one"), "one.bin"),
                    (io.BytesIO(b"two"), "two.bin"),
                ],
                "targetPaths": '["PACK/ONE.DAT", "PACK/SUB/TWO.DAT"]',
                "metadata": '[{"attributes":"r----a"},{}]',
                "destination": "GAMES",
                "mode": "preserve",
                "replace": "false",
            },
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        call = self.service.put_host_tree.call_args
        self.assertEqual(call.args[:2], (self.session, "GAMES"))
        self.assertEqual(
            [item["targetPath"] for item in call.args[2]],
            ["PACK/ONE.DAT", "PACK/SUB/TWO.DAT"],
        )
        self.assertEqual(call.args[2][0]["metadata"]["attributes"], "r----a")
        self.assertTrue(all(item["hostPath"].exists() is False for item in call.args[2]))
        self.assertEqual(
            call.kwargs,
            {"preserve_directories": True, "replace": False},
        )

    def test_loose_file_download_can_include_a_metadata_sidecar(self):
        exported = Path(self.temporary.name) / "exported"
        exported.write_bytes(b"payload")
        self.service.export_file.return_value = exported
        # The read-only bit is the only one set, so the six letters print as
        # r----- and the sidecar records exactly that byte.
        self.service.file_metadata.return_value = {
            "attributes": 0x01,
            "access": 0x01,
            "length": 7,
        }

        response = self.client.get(
            "/api/images/test/file",
            query_string={"path": "LOADER.PRG", "bundle": "metadata"},
        )

        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(archive.read("LOADER.PRG"), b"payload")
            self.assertEqual(
                archive.read("LOADER.PRG.attr"),
                b"LOADER.PRG r----- 00000007\n",
            )
        response.close()

    def test_the_sidecar_retains_the_file_folder(self):
        exported = Path(self.temporary.name) / "exported-folder"
        exported.write_bytes(b"payload")
        self.service.export_file.return_value = exported
        self.service.file_metadata.return_value = {
            "attributes": 0,
            "access": 0,
            "length": 7,
        }

        response = self.client.get(
            "/api/images/test/file",
            query_string={"path": "GAMES\\DEMO.PRG", "bundle": "metadata"},
        )
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            self.assertEqual(
                archive.read("DEMO.PRG.attr"),
                b"GAMES\\DEMO.PRG ------ 00000007\n",
            )
        response.close()

    @patch("app.routes.files.move_gemdos_items")
    def test_a_folder_move_is_sent_as_one_route_operation(self, move_items):
        move_items.return_value = {
            "movedItems": [{
                "source": "HELLO.PRG",
                "destination": "GAMES\\HELLO.PRG",
                "isDirectory": False,
            }],
        }

        response = self.client.post(
            "/api/images/test/move",
            json={
                "items": [{"source": "HELLO.PRG", "destination": "GAMES\\HELLO.PRG"}],
            },
        )

        self.assertEqual(response.status_code, 200)
        move_items.assert_called_once_with(
            self.service,
            self.session,
            [{"source": "HELLO.PRG", "destination": "GAMES\\HELLO.PRG"}],
        )
        self.assertEqual(len(response.get_json()["movedItems"]), 1)

    @patch("app.routes.files.delete_gemdos_items")
    def test_batch_delete_reaches_the_volume_once(self, delete_items):
        delete_items.return_value = {
            "deletedItems": [
                {"path": "ONE.DAT", "isDirectory": False},
                {"path": "TWO.DAT", "isDirectory": False},
            ],
        }

        response = self.client.post(
            "/api/images/test/delete",
            json={"items": [{"path": "ONE.DAT"}, {"path": "TWO.DAT"}]},
        )

        self.assertEqual(response.status_code, 200)
        delete_items.assert_called_once_with(
            self.service,
            self.session,
            ["ONE.DAT", "TWO.DAT"],
        )
        self.assertEqual(len(response.get_json()["deletedItems"]), 2)


if __name__ == "__main__":
    unittest.main()
