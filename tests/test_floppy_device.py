from __future__ import annotations

import errno
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from atari_floppy import (
    ATARI_GEOMETRIES,
    DEVICE_SUFFIXES,
    FloppyDevice,
    FloppyError,
    available_devices,
    device_suffix,
    geometry,
    geometry_for_size,
    image_geometry,
)
from app.floppy_geometry import GEOMETRIES
from tests.msa_fixture import DS_720K, PC_360K, SS_360K, blank_image

try:
    from flask import Flask, jsonify
    from app.disk_service import DiskError
    from app.operations import OperationRegistry
    from app.routes.desktop import create_desktop_blueprint
except ImportError:  # Flask is installed in the production image; the service is ported separately.
    Flask = None


def as_block_device(device: Path):
    """Treat one ordinary file as a block device for the duration of a test.

    No development machine has a floppy controller, so the adapter is exercised
    against a file standing in for the drive.
    """
    return patch(
        "atari_floppy.device.is_block_device",
        side_effect=lambda path: str(path) == str(device),
    )


class FloppyGeometryTests(unittest.TestCase):
    def test_the_adapter_uses_the_shared_geometry_table(self) -> None:
        self.assertIs(ATARI_GEOMETRIES, GEOMETRIES)
        expected = {
            "ds-80t-9s": 737_280, "ds-80t-10s": 819_200, "ds-80t-11s": 901_120,
            "ss-80t-9s": 368_640, "ds-82t-10s": 839_680,
            "pc-360k": 368_640, "pc-180k": 184_320, "hd-1440k": 1_474_560,
        }
        for identifier, size in expected.items():
            with self.subTest(geometry=identifier):
                self.assertEqual(ATARI_GEOMETRIES[identifier].size, size)

    def test_an_unknown_geometry_names_the_accepted_values(self) -> None:
        with self.assertRaisesRegex(FloppyError, "Choose a floppy geometry"):
            geometry("betamax")

    def test_geometry_names_are_matched_without_case_or_padding(self) -> None:
        self.assertEqual(geometry("  DS-80T-9S ").identifier, "ds-80t-9s")

    def test_a_size_identifies_its_geometry_when_unambiguous(self) -> None:
        self.assertEqual(geometry_for_size(737_280).identifier, "ds-80t-9s")
        self.assertEqual(geometry_for_size(1_474_560).identifier, "hd-1440k")

    def test_an_ambiguous_or_unknown_size_identifies_nothing(self) -> None:
        # 360 KiB is both an 80-track single-sided ST disk and a 40-track
        # double-sided PC one, so nothing is guessed from the size alone.
        self.assertIsNone(geometry_for_size(368_640))
        self.assertIsNone(geometry_for_size(819_712))

    def test_the_stock_device_nodes_carry_the_common_geometries(self) -> None:
        self.assertEqual(
            DEVICE_SUFFIXES,
            {"ds-80t-9s": "u720", "ds-80t-10s": "u800", "ds-80t-11s": "u880",
             "pc-360k": "u360", "hd-1440k": "u1440"},
        )
        self.assertEqual(device_suffix(DS_720K), "u720")
        self.assertIsNone(device_suffix(SS_360K))


class ImageGeometryTests(unittest.TestCase):
    """What shape an image about to be written has."""

    def test_the_boot_sector_settles_an_ambiguous_size(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            single = Path(folder) / "single.st"
            single.write_bytes(blank_image(SS_360K))
            double = Path(folder) / "double.st"
            double.write_bytes(blank_image(PC_360K))
            self.assertIs(image_geometry(single), SS_360K)
            self.assertIs(image_geometry(double), PC_360K)

    def test_an_ambiguous_size_without_a_boot_sector_must_be_chosen(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "blank.st"
            image.write_bytes(bytes(368_640))
            with self.assertRaisesRegex(FloppyError, "fits more than one geometry"):
                image_geometry(image)
            self.assertIs(image_geometry(image, "pc-360k"), PC_360K)

    def test_an_explicit_geometry_must_match_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.st"
            image.write_bytes(bytes(737_280))
            with self.assertRaisesRegex(FloppyError, "is 737,280 bytes but"):
                image_geometry(image, "ss-80t-9s")

    def test_an_unknown_size_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.img"
            image.write_bytes(bytes(12_345))
            with self.assertRaisesRegex(FloppyError, "not one of the floppy geometries"):
                image_geometry(image)


class FloppyProbeTests(unittest.TestCase):
    def test_a_missing_device_explains_that_there_is_no_controller(self) -> None:
        probe = FloppyDevice("/dev/definitely-not-a-floppy").probe()
        self.assertFalse(probe.available)
        self.assertIn("does not exist", probe.detail)

    def test_a_regular_file_is_not_accepted_as_a_drive(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            plain = Path(folder) / "notadevice"
            plain.write_bytes(b"")
            probe = FloppyDevice(plain).probe()
        self.assertFalse(probe.available)
        self.assertIn("not a block device", probe.detail)

    def test_a_ready_drive_reports_its_size(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            device = Path(folder) / "fd0"
            device.write_bytes(bytes(737_280))
            with as_block_device(device):
                probe = FloppyDevice(device).probe()
            self.assertTrue(probe.available)
            self.assertEqual(probe.size, 737_280)

    def test_an_empty_drive_is_reported_as_having_no_disk(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            device = Path(folder) / "fd0"
            device.write_bytes(bytes(1024))
            with as_block_device(device):
                with patch.object(Path, "open", side_effect=OSError(errno.ENOMEDIUM, "no medium")):
                    probe = FloppyDevice(device).probe()
        self.assertFalse(probe.available)
        self.assertIn("No readable disk", probe.detail)

    def test_a_permission_failure_names_the_group_to_join(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            device = Path(folder) / "fd0"
            device.write_bytes(bytes(1024))
            with as_block_device(device):
                with patch.object(Path, "open", side_effect=PermissionError("denied")):
                    probe = FloppyDevice(device).probe()
        self.assertFalse(probe.available)
        self.assertIn("floppy", probe.detail)


class FloppyReadTests(unittest.TestCase):
    def _drive(self, folder: str, payload: bytes):
        device = Path(folder) / "fd0"
        device.write_bytes(payload)
        return device

    def test_a_complete_disk_is_captured_at_its_declared_geometry(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            device = self._drive(folder, bytes(range(256)) * 2880)
            target = Path(folder) / "capture.st"
            progress = Mock()
            with as_block_device(device):
                result = FloppyDevice(device).read(target, "ds-80t-9s", progress)
            self.assertEqual(result.size, 737_280)
            self.assertEqual(result.geometry, "ds-80t-9s")
            self.assertEqual(target.stat().st_size, 737_280)
            self.assertTrue(progress.called)

    def test_a_short_read_is_refused_and_leaves_no_partial_image(self) -> None:
        """A disk the controller cannot fully decode must not look complete."""
        with tempfile.TemporaryDirectory() as folder:
            device = self._drive(folder, bytes(100_000))
            target = Path(folder) / "capture.st"
            with as_block_device(device):
                with self.assertRaisesRegex(FloppyError, "does not match the chosen format"):
                    FloppyDevice(device).read(target, "ds-80t-9s")
            self.assertFalse(target.exists())

    def test_a_read_error_names_the_track_and_suggests_flux(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            device = self._drive(folder, bytes(737_280))
            target = Path(folder) / "capture.st"

            class _Failing:
                """A drive that reads a couple of tracks and then fails."""

                def __init__(self): self.calls = 0
                def read(self, _size=-1):
                    self.calls += 1
                    if self.calls > 3:
                        raise OSError(errno.EIO, "media error")
                    return bytes(64 * 1024)
                def seek(self, _offset, _whence=0): return 737_280
                def __enter__(self): return self
                def __exit__(self, *_a): return False

            real_open = Path.open

            def fake_open(self_path, mode="r", *args, **kwargs):
                if str(self_path) == str(device) and "b" in mode and "r" in mode:
                    return _Failing()
                return real_open(self_path, mode, *args, **kwargs)

            with as_block_device(device), patch.object(Path, "open", fake_open):
                with self.assertRaisesRegex(FloppyError, "could not read track"):
                    FloppyDevice(device).read(target, "ds-80t-9s")
            self.assertFalse(target.exists())

    def test_reading_from_an_absent_drive_is_refused_before_any_file_is_made(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "capture.st"
            with self.assertRaisesRegex(FloppyError, "does not exist"):
                FloppyDevice("/dev/definitely-not-a-floppy").read(target, "pc-360k")
            self.assertFalse(target.exists())

    def test_an_unknown_geometry_is_refused_before_the_drive_is_touched(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(FloppyError, "Choose a floppy geometry"):
                FloppyDevice("/dev/definitely-not-a-floppy").read(
                    Path(folder) / "capture.st", "vhs",
                )


class FloppyWriteTests(unittest.TestCase):
    def test_a_write_is_refused_until_it_is_confirmed(self) -> None:
        """The destructive step is never reached by default."""
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.st"
            image.write_bytes(blank_image(DS_720K))
            with self.assertRaisesRegex(FloppyError, "cannot be undone"):
                FloppyDevice("/dev/definitely-not-a-floppy").write(image)

    def test_an_image_of_an_unsupported_size_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.img"
            image.write_bytes(bytes(12_345))
            with self.assertRaisesRegex(FloppyError, "not one of the floppy geometries"):
                FloppyDevice("/dev/definitely-not-a-floppy").write(image, confirm=True)

    def test_an_ambiguous_image_is_refused_until_its_geometry_is_chosen(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder) / "disk.st"
            image.write_bytes(bytes(368_640))
            with self.assertRaisesRegex(FloppyError, "Choose the geometry explicitly"):
                FloppyDevice("/dev/definitely-not-a-floppy").write(image, confirm=True)

    def test_a_size_mismatch_against_the_drive_names_the_node_to_use(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            device = Path(folder) / "fd0"
            device.write_bytes(bytes(368_640))
            image = Path(folder) / "disk.st"
            image.write_bytes(blank_image(DS_720K))
            with as_block_device(device):
                with self.assertRaisesRegex(FloppyError, "Set the kernel geometry.*fd0u720"):
                    FloppyDevice(device).write(image, confirm=True)

    def test_a_confirmed_write_of_a_matching_image_reaches_the_drive(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            device = Path(folder) / "fd0"
            device.write_bytes(bytes(737_280))
            image = Path(folder) / "disk.st"
            payload = bytearray(blank_image(DS_720K))
            payload[512:] = b"\xA5" * (737_280 - 512)
            image.write_bytes(bytes(payload))
            progress = Mock()
            with as_block_device(device):
                result = FloppyDevice(device).write(image, progress, confirm=True)
            self.assertEqual(result.size, 737_280)
            self.assertEqual(result.geometry, "ds-80t-9s")
            self.assertEqual(device.read_bytes(), bytes(payload))
            self.assertTrue(progress.called)

    def test_the_caller_may_name_the_geometry_of_a_boot_sector_less_image(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            device = Path(folder) / "fd0"
            device.write_bytes(bytes(368_640))
            image = Path(folder) / "disk.st"
            image.write_bytes(b"\x33" * 368_640)
            with as_block_device(device):
                result = FloppyDevice(device).write(image, confirm=True, geometry_id="ss-80t-9s")
            self.assertEqual(result.geometry, "ss-80t-9s")


class DeviceDiscoveryTests(unittest.TestCase):
    def test_a_host_without_a_controller_lists_no_drives(self) -> None:
        # This machine has no floppy controller, which is the common case.
        self.assertEqual(available_devices(), [])


class DeviceValidationTests(unittest.TestCase):
    """A request may name the drive, so the value must be constrained."""

    def test_real_floppy_nodes_are_accepted(self) -> None:
        from atari_floppy import validated_device

        for name in ("/dev/fd0", "/dev/fd1", "/dev/fd0u720", "/dev/fd0u800", "/dev/fd0u880",
                     "/dev/fd0u360", "/dev/fd0u1440", "  /dev/fd0  "):
            with self.subTest(name=name):
                self.assertEqual(validated_device(name), name.strip())

    def test_the_accepted_value_is_a_known_constant_not_the_input(self) -> None:
        """Returning the caller's own string would carry its taint onward."""
        from atari_floppy import KNOWN_DEVICES, validated_device

        result = validated_device("  /dev/fd0  ")
        self.assertIn(result, KNOWN_DEVICES)
        self.assertTrue(any(result is candidate for candidate in KNOWN_DEVICES))

    def test_other_block_devices_are_refused(self) -> None:
        """A system disk is a block device too, and must never be readable here."""
        from atari_floppy import validated_device

        for name in ("/dev/sda", "/dev/sda1", "/dev/nvme0n1", "/dev/mapper/root"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(FloppyError, "not a floppy device"):
                    validated_device(name)

    def test_traversal_and_arbitrary_paths_are_refused(self) -> None:
        from atari_floppy import validated_device

        for name in ("/etc/passwd", "/dev/fd0/../sda", "../fd0", "", None, "fd0", "/dev/fd9"):
            with self.subTest(name=name):
                with self.assertRaises(FloppyError):
                    validated_device(name)


@unittest.skipIf(Flask is None, "Flask and the ported service are installed in the production image")
class FloppyDriveRouteTests(unittest.TestCase):
    """The desktop endpoints for a host with a real floppy controller."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.service = Mock()
        self.service.work_dir = Path(self.temporary.name)
        self.service.safe_filename = staticmethod(lambda value: value)
        self.session = Mock()
        self.service.create_from_path.return_value = self.session
        self.service.summary.return_value = {"id": "a" * 32, "kind": "gemdos"}
        app = Flask(__name__)
        app.register_blueprint(
            create_desktop_blueprint(self.service, OperationRegistry(), Mock())
        )

        @app.errorhandler(DiskError)
        def _disk_error(error):
            return jsonify(error=str(error)), 400

        self.client = app.test_client()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_the_status_endpoint_lists_the_supported_geometries(self) -> None:
        response = self.client.get("/api/desktop/floppy-drive")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        identifiers = {row["id"] for row in body["geometries"]}
        self.assertEqual(identifiers, set(ATARI_GEOMETRIES))
        # This host has no controller, which the endpoint reports rather than hides.
        self.assertFalse(body["available"])

    def test_a_capture_is_opened_as_a_new_image(self) -> None:
        from atari_floppy import FloppyReadResult

        with patch("app.routes.desktop.FloppyDevice") as device:
            device.return_value.read.return_value = FloppyReadResult(
                device="/dev/fd0", image="capture.st", geometry="ds-80t-9s", size=737_280,
            )
            response = self.client.post(
                "/api/desktop/floppy-drive/read",
                json={"device": "/dev/fd0", "geometry": "ds-80t-9s", "name": "capture"},
            )
        self.assertEqual(response.status_code, 200)
        self.service.create_from_path.assert_called_once()
        destination = device.return_value.read.call_args[0][0]
        self.assertEqual(Path(destination).suffix, ".st")

    def test_an_unknown_geometry_is_refused_before_the_drive_is_touched(self) -> None:
        with patch("app.routes.desktop.FloppyDevice") as device:
            response = self.client.post(
                "/api/desktop/floppy-drive/read",
                json={"device": "/dev/fd0", "geometry": "laserdisc"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Choose a floppy geometry", response.get_json()["error"])
        device.return_value.read.assert_not_called()

    def test_a_drive_failure_is_reported_and_opens_nothing(self) -> None:
        with patch("app.routes.desktop.FloppyDevice") as device:
            device.return_value.read.side_effect = FloppyError("The drive reported no disk.")
            response = self.client.post(
                "/api/desktop/floppy-drive/read",
                json={"device": "/dev/fd0", "geometry": "pc-360k"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("no disk", response.get_json()["error"])
        self.service.create_from_path.assert_not_called()

    def test_the_capture_scratch_directory_does_not_outlive_the_request(self) -> None:
        from atari_floppy import FloppyReadResult

        with patch("app.routes.desktop.FloppyDevice") as device:
            device.return_value.read.return_value = FloppyReadResult(
                device="/dev/fd0", image="capture.st", geometry="pc-360k", size=368_640,
            )
            self.client.post(
                "/api/desktop/floppy-drive/read",
                json={"device": "/dev/fd0", "geometry": "pc-360k"},
            )
        self.assertEqual(list(Path(self.temporary.name).glob("fd-read-*")), [])


@unittest.skipIf(Flask is None, "Flask and the ported service are installed in the production image")
class DeviceRouteHardeningTests(unittest.TestCase):
    """The endpoints must refuse a non-floppy device before touching it."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.service = Mock()
        self.service.work_dir = Path(self.temporary.name)
        app = Flask(__name__)
        app.register_blueprint(
            create_desktop_blueprint(self.service, OperationRegistry(), Mock())
        )

        @app.errorhandler(DiskError)
        def _disk_error(error):
            return jsonify(error=str(error)), 400

        self.client = app.test_client()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_reading_a_system_disk_is_refused(self) -> None:
        with patch("app.routes.desktop.FloppyDevice") as device:
            response = self.client.post(
                "/api/desktop/floppy-drive/read",
                json={"device": "/dev/sda", "geometry": "pc-360k"},
            )
        self.assertEqual(response.status_code, 400)
        self.assertIn("not a floppy device", response.get_json()["error"])
        device.return_value.read.assert_not_called()

    def test_the_capture_filename_never_comes_from_the_request(self) -> None:
        """A requested name is applied to the session, never to the path."""
        from atari_floppy import FloppyReadResult

        with patch("app.routes.desktop.FloppyDevice") as device:
            device.return_value.read.return_value = FloppyReadResult(
                device="/dev/fd0", image="capture.st", geometry="ds-80t-9s", size=737_280,
            )
            self.client.post(
                "/api/desktop/floppy-drive/read",
                json={"device": "/dev/fd0", "geometry": "ds-80t-9s", "name": "../../escape"},
            )
            destination = Path(device.return_value.read.call_args[0][0])
            self.assertEqual(destination.name, "capture.st")
            self.assertTrue(
                str(destination.resolve()).startswith(str(Path(self.temporary.name).resolve())),
                f"capture escaped to {destination}",
            )


if __name__ == "__main__":
    unittest.main()
