from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import cli
from app.disk_service import DiskError
from app.headless import (
    BLANK_FORMATS,
    RECIPE_FORMAT,
    RECIPE_VERSION,
    create_recipe,
    load_recipe,
    save_image,
    source_identity,
    verify_identity,
)


class CopyService:
    def prepare_download(self, session, progress=None):
        if progress:
            progress("Prepared", 1, 1)
        return session.path

    @staticmethod
    def _copy_local_file(source, destination):
        destination.write_bytes(source.read_bytes())


class FailingCopyService(CopyService):
    def _copy_local_file(self, source, destination):
        raise OSError("image copy failed")


class HeadlessCliTests(unittest.TestCase):
    def test_create_dry_run_has_stable_json_status(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("app.cli.DiskService") as service_type:
            service = service_type.return_value
            service.create_blank.return_value = SimpleNamespace()
            service.summary.return_value = {"kind": "gemdos", "name": "blank.st"}
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli.main([
                    "create", "--format", "ds-720k", "--title", "TEST",
                    "--output", "test.st", "--dry-run",
                ])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(result["format"], "atari-file-forge-cli-result")
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["status"], "planned")
        self.assertTrue(result["dryRun"])
        self.assertEqual(result["result"]["format"], "ds-720k")
        service.create_blank.assert_called_once()

    def test_create_only_offers_the_blank_formats_the_disk_service_builds(self):
        self.assertIn("ds-720k", BLANK_FORMATS)
        self.assertIn("hd", BLANK_FORMATS)
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                cli.main([
                    "create", "--format", "floppy-disk", "--title", "TEST",
                    "--output", "test.st",
                ])
        result = json.loads(stdout.getvalue())
        self.assertEqual(raised.exception.code, cli.EXIT_USAGE)
        self.assertEqual(result["status"], "usage-error")

    def test_output_cannot_replace_source_even_with_force(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "disk.st"
            source.write_bytes(b"image")
            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                code = cli.main([
                    "save", str(source), "--output", str(source), "--force",
                ])
            result = json.loads(stdout.getvalue())
            self.assertEqual(code, cli.EXIT_VALIDATION)
            self.assertEqual(result["status"], "validation-failed")
            self.assertEqual(source.read_bytes(), b"image")

    def test_report_output_cannot_replace_image_even_with_force(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "disk.st"
            source.write_bytes(b"image")
            stdout = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                code = cli.main([
                    "manifest", str(source), "--output", str(source), "--force",
                ])
            result = json.loads(stdout.getvalue())
            self.assertEqual(code, cli.EXIT_VALIDATION)
            self.assertIn("different from every source", result["result"]["error"])
            self.assertEqual(source.read_bytes(), b"image")

    def test_preflight_command_returns_shared_compatibility_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            image = root / "disk.st"
            image.write_bytes(b"image")
            changes = root / "changes.json"
            changes.write_text(json.dumps([{"name": "LONG-FILENAME"}]), encoding="utf-8")
            session = SimpleNamespace(
                kind="gemdos", name=image.name, hardware_profile={}, path=image,
            )
            opened = Mock()
            opened.__enter__ = Mock(return_value=(Mock(), session))
            opened.__exit__ = Mock(return_value=False)
            stdout = io.StringIO()
            with patch("app.cli.open_image", return_value=opened):
                with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
                    code = cli.main([
                        "preflight", str(image), "--changes", str(changes),
                        "--source-kind", "host", "--target-kind", "gemdos",
                    ])
            result = json.loads(stdout.getvalue())
            report = result["result"]
            self.assertEqual(code, cli.EXIT_OK)
            self.assertEqual(report["format"], "atari-file-forge-compatibility-report")
            self.assertEqual(report["version"], 1)
            # GEMDOS holds eight characters and an extension, so the long host
            # name is reported as the 8.3 name the volume will really carry.
            self.assertEqual(report["items"][0]["targetName"], "LONG-FIL")

    def test_usage_error_is_json_and_uses_documented_exit_code(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                cli.main([])
        result = json.loads(stdout.getvalue())
        self.assertEqual(raised.exception.code, cli.EXIT_USAGE)
        self.assertEqual(result["status"], "usage-error")
        self.assertEqual(result["exitCode"], cli.EXIT_USAGE)

    def test_recipe_round_trip_records_exact_source_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.bin"
            source.write_bytes(b"Atari")
            identity = source_identity(source)
            recipe_path = root / "workflow.affrecipe.json"
            document = create_recipe(
                "Import one file",
                {"payload": identity},
                [{"action": "import-file", "source": "payload", "destination": "FILE.DAT"}],
                {"path": "result.st"},
            )
            recipe_path.write_text(json.dumps(document), encoding="utf-8")

            loaded = load_recipe(recipe_path)

            self.assertEqual(loaded["format"], RECIPE_FORMAT)
            self.assertEqual(loaded["version"], RECIPE_VERSION)
            self.assertEqual(verify_identity(source, loaded["sources"]["payload"]), identity)

    def test_recipe_accepts_the_container_conversion_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            recipe_path = Path(temporary) / "convert.json"
            recipe_path.write_text(json.dumps({
                "format": RECIPE_FORMAT,
                "version": RECIPE_VERSION,
                "name": "Rebuild the disk a container describes",
                "sources": {"image": {"size": 1, "sha256": "a" * 64}},
                "actions": [{"action": "convert-container", "format": "st"}],
                "output": {"path": "result.st", "files": []},
            }), encoding="utf-8")

            loaded = load_recipe(recipe_path)

            self.assertEqual(loaded["actions"][0]["action"], "convert-container")

    def test_recipe_identity_rejects_changed_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source.bin"
            source.write_bytes(b"before")
            identity = source_identity(source)
            source.write_bytes(b"after")
            with self.assertRaisesRegex(DiskError, "expected size|expected sha256"):
                verify_identity(source, identity)

    def test_recipe_rejects_action_that_bypasses_source_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            recipe_path = Path(temporary) / "unsafe.json"
            recipe_path.write_text(json.dumps({
                "format": RECIPE_FORMAT,
                "version": RECIPE_VERSION,
                "name": "Unsafe",
                "sources": {},
                "actions": [{
                    "action": "import-file",
                    "source": "unchecked",
                    "destination": "FILE.DAT",
                }],
                "output": {"path": "result.st", "files": []},
            }), encoding="utf-8")
            with self.assertRaisesRegex(DiskError, "unverified source alias"):
                load_recipe(recipe_path)

    def test_recipe_rejects_patch_action_that_bypasses_source_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            recipe_path = Path(temporary) / "unsafe-patch.json"
            recipe_path.write_text(json.dumps({
                "format": RECIPE_FORMAT,
                "version": RECIPE_VERSION,
                "name": "Unsafe patch",
                "sources": {
                    "image": {"size": 1, "sha256": "a" * 64},
                },
                "actions": [{"action": "apply-patch", "source": "unchecked"}],
                "output": {"path": "result.st", "files": []},
            }), encoding="utf-8")
            with self.assertRaisesRegex(DiskError, "unverified source alias"):
                load_recipe(recipe_path)

    def test_recipe_output_identity_must_match_rebuild(self):
        document = {"output": {"files": [{"size": 10, "sha256": "a" * 64}]}}
        with self.assertRaisesRegex(cli.IdentityError, "does not match"):
            cli._verify_recipe_outputs(
                document,
                [{"size": 11, "sha256": "b" * 64}],
            )

    def test_save_image_writes_the_single_atari_image_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "working.st"
            primary.write_bytes(b"ST")
            session = SimpleNamespace(path=primary)
            output = root / "out" / "games.st"

            files = save_image(CopyService(), session, output)

            self.assertEqual(output.read_bytes(), b"ST")
            self.assertEqual([Path(row["path"]).suffix for row in files], [".st"])
            # An Atari image is one file: nothing is written beside it.
            self.assertEqual([item.name for item in output.parent.iterdir()], ["games.st"])

    def test_failed_staging_leaves_no_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "working.st"
            primary.write_bytes(b"ST")
            session = SimpleNamespace(path=primary)
            output = root / "out" / "games.st"
            with self.assertRaisesRegex(OSError, "image copy failed"):
                save_image(FailingCopyService(), session, output)
            self.assertFalse(output.exists())
            self.assertEqual(list(output.parent.iterdir()), [])

    def test_failed_recipe_verification_does_not_publish_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            primary = root / "working.st"
            primary.write_bytes(b"image")
            session = SimpleNamespace(path=primary)
            output = root / "out" / "result.st"
            with self.assertRaisesRegex(cli.IdentityError, "does not match"):
                save_image(
                    CopyService(), session, output,
                    verify=lambda files: cli._verify_recipe_outputs(
                        {"output": {"files": [{"size": 1, "sha256": "0" * 64}]}},
                        files,
                    ),
                )
            self.assertFalse(output.exists())

    def test_image_and_recipe_outputs_must_be_different(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            code = cli.main([
                "create", "--format", "ds-720k", "--title", "TEST",
                "--output", "same.file", "--recipe-out", "same.file",
            ])
        result = json.loads(stdout.getvalue())
        self.assertEqual(code, cli.EXIT_VALIDATION)
        self.assertIn("must be different", result["result"]["error"])

    def test_import_creates_the_destination_folder_only_when_asked(self):
        """The command line has no separate folder command, so import must offer one."""
        service = Mock()
        session = SimpleNamespace()

        cli._ensure_parent(service, session, "GAMES\\PROGRAM.PRG", False)
        service.make_directory.assert_not_called()

        cli._ensure_parent(service, session, "GAMES\\PROGRAM.PRG", True)
        service.make_directory.assert_called_once_with(session, "GAMES")

    def test_import_accepts_a_destination_folder_that_is_already_there(self):
        """Asking for a folder that exists has the outcome the caller wanted."""
        service = Mock()
        service.make_directory.side_effect = DiskError("GAMES already exists.")
        cli._ensure_parent(service, SimpleNamespace(), "GAMES\\PROGRAM.PRG", True)

    def test_import_still_reports_a_folder_it_could_not_create(self):
        service = Mock()
        service.make_directory.side_effect = DiskError("The disk is full.")
        with self.assertRaises(DiskError):
            cli._ensure_parent(service, SimpleNamespace(), "GAMES\\PROGRAM.PRG", True)

    def test_import_at_the_root_needs_no_folder(self):
        service = Mock()
        cli._ensure_parent(service, SimpleNamespace(), "PROGRAM.PRG", True)
        service.make_directory.assert_not_called()

    def test_recipe_records_image_interpretation_context(self):
        args = SimpleNamespace(target_hardware="hd", force_kind="rom")
        self.assertEqual(cli._recorded_open_context(args), {
            "targetHardware": "hd",
            "forceKind": "rom",
        })


if __name__ == "__main__":
    unittest.main()
