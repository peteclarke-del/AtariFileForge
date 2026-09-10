from __future__ import annotations

import contextlib
import json
import re
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import Mock, PropertyMock, patch

from flask import Flask

from app import emulator_config
from app.emulator_config import (
    ALL_MACHINES,
    DEBUGGER_SCRIPT,
    EMUTOS_DIR,
    MAXIMUM_CD_DRIVES,
    MAXIMUM_FLOPPY_DRIVES,
    TOS_DIR,
    ManagedEmulator,
    cd_drives_for,
    configured_emulator,
    control_socket_path,
    emulator_command,
    emulator_status,
    emutos_for,
    firmware_for,
    profile_machine,
    tos_for,
)
from app.hardware_profiles import (
    ADDONS,
    GROUPS,
    MACHINES,
    hardware_catalogue,
    normalise_hardware_profile,
    profile_addons,
)
from app.operations import OperationRegistry
from app.disk_service import DiskService
from app.routes.images import create_images_blueprint
from app.routes.tools import clean_emulator_output, create_tools_blueprint

HATARI = "/usr/bin/hatari"
XVFB = ["timeout", "--signal=TERM", "--kill-after=2", "8", "env", "SDL_AUDIODRIVER=dummy", "xvfb-run", "-a", HATARI]
XVFB_DEBUG = ["timeout", "--signal=TERM", "--kill-after=2", "15", "env", "SDL_AUDIODRIVER=dummy", "xvfb-run", "-a", HATARI]
SHARED_DISPLAY = ["timeout", "--signal=TERM", "--kill-after=2", "900", "env", "SDL_AUDIODRIVER=dummy", "DISPLAY=:99", HATARI]
COMMON = ["--fast-boot", "true", "--confirm-quit", "false", "--statusbar", "false"]


@contextlib.contextmanager
def _hatari():
    """Pretend Hatari is installed at its Debian path, whatever this host has."""
    emulators = {
        "hatari": ManagedEmulator("hatari", "Hatari", HATARI, "hatari --debug", ALL_MACHINES),
    }
    with patch.object(emulator_config, "EMULATORS", emulators), patch.object(
        ManagedEmulator, "available", new_callable=PropertyMock, return_value=True,
    ):
        yield


#: Sizes and mapped addresses by release, so a fixture ROM is the shape the
#: real one is. A ROM built any other way is rejected before it is offered,
#: which is the point of the check.
_ROM_SHAPE = {
    "100": (192, 0xFC0000), "102": (192, 0xFC0000), "104": (192, 0xFC0000),
    "106": (256, 0xE00000), "162": (256, 0xE00000),
    "205": (256, 0xE00000), "206": (256, 0xE00000),
    "306": (512, 0xE00000),
    "400": (512, 0xE00000), "402": (512, 0xE00000), "404": (512, 0xE00000),
}


def rom_bytes(name: str) -> bytes:
    """A ROM the decoder accepts, shaped by the release its name states."""
    release = re.match(r"tos(\d{3})", name)
    kilobytes, base = _ROM_SHAPE.get(release.group(1) if release else "", (192, 0xFC0000))
    version = int(release.group(1), 16) if release else 0x104
    size = kilobytes * 1024
    data = bytearray(size)
    struct.pack_into(">H", data, 0x00, 0x602E)
    struct.pack_into(">H", data, 0x02, version)
    struct.pack_into(">I", data, 0x04, base + 0x30)
    struct.pack_into(">I", data, 0x08, base)
    struct.pack_into(">I", data, 0x0C, base + size)
    struct.pack_into(">I", data, 0x18, 0x04141993)
    struct.pack_into(">H", data, 0x1C, 0x0006)
    return bytes(data)


@contextlib.contextmanager
def _firmware(*names: str):
    """An operator ROM directory holding exactly ``names``, and no repository ROMs.

    The repository directory is pointed at a path that does not exist so a
    developer's own git-ignored ``firmware/tos/`` cannot leak into a test. The
    bundled EmuTOS is left as it is: it is committed, so it is always there.
    """
    with tempfile.TemporaryDirectory() as temporary:
        roms = Path(temporary) / "tos"
        roms.mkdir()
        for name in names:
            (roms / name).write_bytes(rom_bytes(name))
        with patch.object(emulator_config, "TOS_DIR", roms), patch.object(
            emulator_config, "REPOSITORY_TOS_DIR", Path(temporary) / "absent",
        ):
            yield roms


def _session(machine: str, *addons: str, **profile):
    return SimpleNamespace(
        hardware_profile={"machine": machine, "emulator": "auto", "addons": list(addons), **profile},
        target_hardware="auto",
    )


class HatariCommandTests(unittest.TestCase):
    def test_every_machine_defaults_to_hatari(self):
        for machine in ALL_MACHINES:
            with self.subTest(machine=machine):
                session = _session(machine)
                self.assertEqual(profile_machine(session), machine)
                self.assertEqual(configured_emulator(session).identifier, "hatari")

    def test_the_machine_is_inferred_from_aliases_and_defaults_to_an_st(self):
        self.assertEqual(profile_machine(SimpleNamespace(hardware_profile={"machine": "Atari TT"}, target_hardware="")), "tt030")
        self.assertEqual(profile_machine(SimpleNamespace(hardware_profile={"machine": "Falcon"}, target_hardware="")), "falcon030")
        self.assertEqual(profile_machine(SimpleNamespace(hardware_profile={"machine": "1040STE"}, target_hardware="")), "ste")
        self.assertEqual(profile_machine(SimpleNamespace(hardware_profile={}, target_hardware="auto")), "st")
        self.assertEqual(profile_machine(SimpleNamespace(hardware_profile={}, target_hardware="megaste-hd")), "megaste")

    def test_an_st_with_tos_104_boots_one_floppy_in_drive_a(self):
        with _hatari(), _firmware("tos104uk.img") as roms:
            command, cwd = emulator_command(_session("st", "tos-104", "drive-a-ds"), "/work/game.st")
        self.assertEqual(command, [
            *XVFB,
            "--machine", "st", "--tos", str(roms / "tos104uk.img"),
            "--memsize", "0",
            "--cpulevel", "0", "--cpuclock", "8",
            "--monitor", "rgb",
            "--drive-b", "false",
            "--disk-a", "/work/game.st",
            *COMMON,
            "--sound", "off",
            "--log-level", "warn",
            "--screenshot-dir", "/work",
            "--run-vbls", "350",
        ])
        self.assertEqual(cwd, "/work")

    def test_a_mega_ste_attaches_an_acsi_image_on_the_shared_display(self):
        session = _session("megaste", "tos-206", "ram-4m", "acsi-megafile", "drive-b-external")
        with _hatari(), _firmware("tos206uk.img") as roms:
            command, cwd = emulator_command(session, "/work/megafile.img", interactive=True)
        self.assertEqual(command, [
            *SHARED_DISPLAY,
            "--machine", "megaste", "--tos", str(roms / "tos206uk.img"),
            "--memsize", "4",
            "--cpulevel", "0", "--cpuclock", "16",
            "--monitor", "rgb",
            "--acsi", "0=/work/megafile.img",
            *COMMON,
            "--sound", "off",
            "--log-level", "warn",
            "--screenshot-dir", "/work",
        ])
        self.assertEqual(cwd, "/work")

    def test_a_falcon_boots_emutos_512_with_an_ide_image_in_a_native_window(self):
        session = _session("falcon030", "tos-emutos", "ram-14m", "ide-internal", "fpu-68882", "monitor-vga")
        with _hatari(), _firmware("tos404.img"):
            command, _cwd = emulator_command(session, "/work/falcon.img", interactive=True, native=True)
        self.assertEqual(command, [
            HATARI,
            "--machine", "falcon", "--tos", str(EMUTOS_DIR / "etos512uk.img"),
            "--memsize", "14",
            "--cpulevel", "3", "--cpuclock", "16",
            "--fpu", "68882",
            "--dsp", "emu",
            "--monitor", "vga",
            "--drive-b", "false",
            "--ide-master", "/work/falcon.img",
            *COMMON,
            "--log-level", "warn",
            "--screenshot-dir", "/work",
        ])

    def test_a_folder_is_handed_over_as_gemdos_drive_c(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "HARDDISK"
            folder.mkdir()
            with _hatari(), _firmware():
                command, cwd = emulator_command(_session("ste", "gemdos-hd-folder"), folder)
            self.assertEqual(command, [
                *XVFB,
                "--machine", "ste", "--tos", str(EMUTOS_DIR / "etos256uk.img"),
                "--memsize", "1",
                "--cpulevel", "0", "--cpuclock", "8",
                "--monitor", "rgb",
                "--drive-b", "false",
                "--harddrive", str(folder), "--gemdos-drive", "c",
                *COMMON,
                "--sound", "off",
                "--log-level", "warn",
                "--screenshot-dir", temporary,
                "--run-vbls", "350",
            ])
            self.assertEqual(cwd, temporary)

    def test_a_bounded_run_uses_a_private_x_server_and_a_frame_limit(self):
        with _hatari(), _firmware():
            command, _cwd = emulator_command(_session("st"), "/work/demo.msa")
        self.assertEqual(command[:9], XVFB)
        self.assertEqual(command[3], "8")
        self.assertEqual(command[-2:], ["--run-vbls", "350"])
        self.assertIn("--sound", command)

    def test_the_debugger_runs_hatari_with_its_script(self):
        with _hatari(), _firmware("tos104uk.img") as roms:
            command, _cwd = emulator_command(_session("st", "tos-104"), "/work/game.st", debug=True)
        self.assertEqual(command, [
            *XVFB_DEBUG,
            "--machine", "st", "--tos", str(roms / "tos104uk.img"),
            "--memsize", "0",
            "--cpulevel", "0", "--cpuclock", "8",
            "--monitor", "rgb",
            "--drive-b", "false",
            "--disk-a", "/work/game.st",
            *COMMON,
            "--sound", "off",
            "--log-level", "info",
            "--screenshot-dir", "/work",
            "--run-vbls", "700",
            "--debug", "--parse", str(DEBUGGER_SCRIPT),
        ])
        self.assertTrue(DEBUGGER_SCRIPT.is_file(), "the debugger script ships with the application")
        self.assertIn("setopt -D", DEBUGGER_SCRIPT.read_text(encoding="utf-8"))

    def test_a_tt_takes_tt_ram_a_scsi_drive_and_a_cd_image(self):
        session = _session("tt030", "tos-306", "tt-ram", "scsi-internal", "monitor-mono")
        with _hatari(), _firmware("tos306uk.img") as roms:
            command, _cwd = emulator_command(
                session, "/work/tt.img", cdroms=["/work/release.iso"], interactive=True,
            )
        self.assertEqual(command[8:], [
            "--machine", "tt", "--tos", str(roms / "tos306uk.img"),
            "--memsize", "2",
            "--ttram", "16", "--addr24", "false",
            "--cpulevel", "3", "--cpuclock", "32",
            "--monitor", "mono",
            "--drive-b", "false",
            "--scsi", "0=/work/tt.img",
            "--scsi", "1=/work/release.iso",
            *COMMON,
            "--sound", "off",
            "--log-level", "warn",
            "--screenshot-dir", "/work",
        ])

    def test_a_cd_is_refused_on_a_machine_without_scsi(self):
        self.assertEqual(cd_drives_for("st"), 0)
        self.assertEqual(cd_drives_for("falcon030"), 1)
        self.assertEqual(MAXIMUM_CD_DRIVES, 1)
        with _hatari(), _firmware():
            with self.assertRaisesRegex(ValueError, "SCSI port of a TT030 or Falcon030"):
                emulator_command(_session("st"), "/work/drive.img", cdroms=["/work/cd.iso"])

    def test_the_machine_has_two_floppy_drives(self):
        self.assertEqual(MAXIMUM_FLOPPY_DRIVES, 2)
        with _hatari(), _firmware():
            command, _cwd = emulator_command(
                _session("st"), "/work/drive.img", floppies=["/work/disk1.st", "/work/disk2.st"],
            )
            self.assertIn("--disk-b", command)
            self.assertNotIn("--drive-b", command)
            with self.assertRaisesRegex(ValueError, "2 floppy drives"):
                emulator_command(
                    _session("st"), "/work/disk1.st", floppies=["/work/disk2.st", "/work/disk3.st"],
                )

    def test_a_single_sided_early_st_and_a_blitter_reach_the_command(self):
        with _hatari(), _firmware():
            command, _cwd = emulator_command(_session("st", "drive-a-ss", "blitter"), "/work/game.st")
        self.assertIn("--drive-a-heads", command)
        self.assertEqual(command[command.index("--drive-a-heads") + 1], "1")
        self.assertEqual(command[command.index("--blitter") + 1], "true")

    def test_an_accelerated_st_is_a_68030_with_its_fpu(self):
        with _hatari(), _firmware():
            command, _cwd = emulator_command(
                _session("ste", "acc-68030-pak", "fpu-68881", "ram-2.5m"), "/work/game.st",
            )
        self.assertEqual(command[command.index("--cpulevel") + 1], "3")
        self.assertEqual(command[command.index("--fpu") + 1], "68881")
        self.assertEqual(command[command.index("--memsize") + 1], "2560")

    def test_a_control_socket_is_passed_through_when_the_caller_listens_on_one(self):
        socket = control_socket_path("/app/work")
        self.assertEqual(socket, Path("/app/work/hatari-control.sock"))
        with _hatari(), _firmware():
            command, _cwd = emulator_command(_session("st"), "/work/game.st", control_socket=socket)
        self.assertEqual(command[command.index("--control-socket") + 1], str(socket))

    def test_media_that_cannot_be_attached_is_refused(self):
        with _hatari(), _firmware():
            with self.assertRaisesRegex(ValueError, "floppy image"):
                emulator_command(_session("st"), "/work/tos104uk.rom")

    def test_a_missing_executable_is_reported(self):
        emulators = {
            "hatari": ManagedEmulator("hatari", "Hatari", "/nonexistent/hatari", "hatari --debug", ALL_MACHINES),
        }
        with patch.object(emulator_config, "EMULATORS", emulators), _firmware():
            status = emulator_status(_session("st"))
            self.assertFalse(status["available"])
            self.assertIn("executable is missing", status["message"])
            with self.assertRaisesRegex(ValueError, "not installed"):
                emulator_command(_session("st"), "/work/game.st")

    def test_expected_headless_shutdown_noise_is_removed(self):
        output = "\n".join([
            "Hatari v2.4.1",
            "ALSA lib confmisc.c:855:(parse_card) cannot find card '0'",
            "TOS version 1.04 loaded",
            "X connection to :99 broken (explicit kill or server shutdown).",
        ])
        self.assertEqual(
            clean_emulator_output(output),
            "\n".join(["Hatari v2.4.1", "TOS version 1.04 loaded"]),
        )


class FirmwareLookupTests(unittest.TestCase):
    def test_the_bundled_emutos_is_committed_for_every_machine_size(self):
        for machine, name in (
            ("st", "etos192uk.img"), ("megast", "etos192uk.img"),
            ("ste", "etos256uk.img"), ("megaste", "etos256uk.img"),
            ("tt030", "etos512uk.img"), ("falcon030", "etos512uk.img"),
        ):
            with self.subTest(machine=machine):
                self.assertEqual(emutos_for(machine), EMUTOS_DIR / name)
                self.assertTrue(emutos_for(machine).is_file())
        self.assertEqual(emutos_for("st", "1024"), EMUTOS_DIR / "etos1024k.img")

    def test_a_machine_without_a_tos_falls_back_to_emutos_and_says_so(self):
        with _firmware():
            self.assertIsNone(tos_for("st"))
            firmware = firmware_for("st")
            self.assertEqual(firmware.kind, "emutos")
            self.assertEqual(firmware.path, EMUTOS_DIR / "etos192uk.img")
            self.assertIn("no TOS ROM for the ST was found", firmware.reason)
            with _hatari():
                status = emulator_status(_session("st"))
            self.assertTrue(status["available"], status["message"])
            self.assertEqual(status["firmwareKind"], "emutos")
            self.assertIn("EmuTOS 192 KiB", status["message"])

    def test_a_real_tos_is_preferred_and_the_newest_shipped_release_wins(self):
        with _firmware("tos100uk.img", "tos104uk.img", "tos102uk.img") as roms:
            firmware = firmware_for("st")
            self.assertEqual(firmware.path, roms / "tos104uk.img")
            self.assertEqual(firmware.kind, "tos")
            self.assertEqual(firmware.label, "TOS 1.04")
            self.assertIn("shipped with", firmware.reason)
            self.assertEqual(tos_for("st", ["tos-100"]), roms / "tos100uk.img")

    def test_uk_is_preferred_then_us_then_any_other_language(self):
        with _firmware("tos104de.img", "tos104us.img", "tos104uk.img") as roms:
            self.assertEqual(tos_for("st"), roms / "tos104uk.img")
        with _firmware("tos104de.img", "tos104us.img") as roms:
            self.assertEqual(tos_for("st"), roms / "tos104us.img")
        with _firmware("tos104fr.img", "tos104de.img") as roms:
            self.assertEqual(tos_for("st"), roms / "tos104de.img")

    def test_the_operator_directory_is_searched_before_the_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            operator = Path(temporary) / "operator"
            repository = Path(temporary) / "repository"
            operator.mkdir()
            repository.mkdir()
            (operator / "tos104us.img").write_bytes(rom_bytes("tos104us.img"))
            (repository / "tos104uk.img").write_bytes(rom_bytes("tos104uk.img"))
            with patch.object(emulator_config, "TOS_DIR", operator), patch.object(
                emulator_config, "REPOSITORY_TOS_DIR", repository,
            ):
                self.assertEqual(tos_for("st"), operator / "tos104us.img")
                self.assertEqual(tos_for("megast", ["tos-102"]), None)

    def test_the_emutos_add_on_forces_emutos_even_when_a_tos_is_present(self):
        with _firmware("tos104uk.img"):
            firmware = firmware_for("st", ["tos-emutos"])
            self.assertEqual(firmware.kind, "emutos")
            self.assertIn("profile asks for EmuTOS", firmware.reason)

    def test_a_requested_tos_that_is_absent_falls_back_and_explains(self):
        with _firmware("tos104uk.img"):
            firmware = firmware_for("st", ["tos-100"])
            self.assertEqual(firmware.kind, "emutos")
            self.assertIn("the TOS the profile asks for was not found", firmware.reason)

    def test_the_1024k_emutos_is_an_explicit_choice(self):
        with _hatari(), _firmware("tos404.img"):
            command, _cwd = emulator_command(
                _session("falcon030", emulatorFirmware="emutos-1024k"), "/work/falcon.img",
            )
        self.assertEqual(command[command.index("--tos") + 1], str(EMUTOS_DIR / "etos1024k.img"))

    def test_the_operator_tos_directory_is_named_for_tos(self):
        self.assertIn("tos", str(TOS_DIR).lower())


class HardwareProfileTests(unittest.TestCase):
    def test_hardware_catalogue_has_the_atari_range(self):
        machines = {row["id"] for row in hardware_catalogue()["machines"]}
        self.assertEqual(machines, {"st", "megast", "ste", "megaste", "tt030", "falcon030"})
        self.assertEqual([row["id"] for row in MACHINES], list(ALL_MACHINES))

    def test_every_add_on_is_well_formed(self):
        known = {row["id"] for row in ADDONS}
        machines = {row["id"] for row in MACHINES}
        for addon in ADDONS:
            with self.subTest(addon=addon["id"]):
                self.assertIn(addon["group"], GROUPS)
                self.assertTrue(addon["machines"])
                self.assertTrue(set(addon["machines"]) <= machines, addon["machines"])
                self.assertTrue(addon["description"].endswith("."), addon["description"])
                self.assertIn(addon["emulator"], {"hatari", "profile"})
                for requirement in addon["requires"]:
                    _scope, _, expression = requirement.partition(":")
                    for choice in (expression or requirement).split("|"):
                        self.assertIn(choice, known)
                for conflict in addon["conflicts"]:
                    self.assertIn(conflict, known)

    def test_a_profile_rejects_incompatible_and_conflicting_additions(self):
        with self.assertRaisesRegex(ValueError, "cannot be fitted to st"):
            normalise_hardware_profile({"machine": "st", "addons": ["ide-internal"]})
        with self.assertRaisesRegex(ValueError, "cannot be fitted with"):
            normalise_hardware_profile({"machine": "st", "addons": ["drive-a-ss", "drive-a-ds"]})
        with self.assertRaisesRegex(ValueError, "no more than 1 option"):
            normalise_hardware_profile({"machine": "st", "addons": ["tos-104", "tos-emutos"]})

    def test_tos_releases_are_offered_only_to_the_machines_that_shipped_them(self):
        catalogue = {row["id"]: row for row in hardware_catalogue()["addons"]}
        self.assertEqual(catalogue["tos-100"]["machines"], ["st"])
        self.assertEqual(catalogue["tos-306"]["machines"], ["tt030"])
        self.assertEqual(catalogue["tos-4xx"]["machines"], ["falcon030"])
        self.assertEqual(set(catalogue["tos-emutos"]["machines"]), set(ALL_MACHINES))
        with self.assertRaisesRegex(ValueError, "cannot be fitted to falcon030"):
            normalise_hardware_profile({"machine": "falcon030", "addons": ["tos-104"]})

    def test_an_fpu_on_an_st_requires_the_accelerator_that_carries_it(self):
        with self.assertRaisesRegex(ValueError, "requires 68030 accelerator"):
            normalise_hardware_profile({"machine": "st", "addons": ["fpu-68881"]})
        profile = normalise_hardware_profile({"machine": "st", "addons": ["acc-68030-pak", "fpu-68881"]})
        self.assertTrue(profile["accelerated"])
        self.assertFalse(normalise_hardware_profile({"machine": "tt030", "addons": ["fpu-68882"]})["accelerated"])

    def test_a_compactflash_card_needs_an_ide_interface(self):
        with self.assertRaisesRegex(ValueError, "requires IDE adapter board or Internal IDE"):
            normalise_hardware_profile({"machine": "st", "addons": ["cf-adapter"]})
        profile = normalise_hardware_profile({"machine": "falcon030", "addons": ["ide-internal", "cf-adapter"]})
        self.assertEqual(profile["addons"], ["ide-internal", "cf-adapter"])

    def test_the_emutos_driver_needs_emutos(self):
        with self.assertRaisesRegex(ValueError, "requires EmuTOS"):
            normalise_hardware_profile({"machine": "st", "addons": ["driver-emutos-builtin"]})
        with self.assertRaisesRegex(ValueError, "no more than 1 option"):
            normalise_hardware_profile({"machine": "st", "addons": ["driver-ahdi", "driver-hddriver"]})

    def test_high_density_floppies_are_offered_only_to_the_machines_that_had_them(self):
        catalogue = hardware_catalogue()
        hd = next(row for row in catalogue["addons"] if row["id"] == "hd-floppy")
        self.assertEqual(set(hd["machines"]), {"megaste", "tt030", "falcon030"})
        self.assertEqual(next(row for row in catalogue["addons"] if row["id"] == "drive-a-ss")["machines"], ["st"])

    def test_an_accelerated_flag_without_a_board_implies_the_68030_board(self):
        session = SimpleNamespace(hardware_profile={"machine": "st", "accelerated": True, "addons": []})
        self.assertIn("acc-68030-pak", profile_addons(session))
        self.assertEqual(normalise_hardware_profile({"machine": "st"})["machine"], "st")
        self.assertEqual(normalise_hardware_profile({})["machine"], "st")


class EmulatorRouteTests(unittest.TestCase):
    def test_editor_status_uses_the_managed_profile(self):
        service = Mock()
        service.get.return_value = SimpleNamespace(
            hardware_profile={"machine": "st", "emulator": "hatari"},
            target_hardware="auto", path=Path("/work/test.st"),
        )
        app = Flask(__name__)
        app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
        with patch(
            "app.routes.tools.emulator_status",
            return_value={
                "available": True,
                "label": "Hatari",
                "machine": "st",
                "configuredBy": "managed workbench profile",
            },
        ), patch(
            "app.routes.tools.emulator_command",
            return_value=([HATARI, "--machine", "st"], "/work"),
        ):
            result = app.test_client().get("/api/images/test/editor-emulator").get_json()
        self.assertTrue(result["available"])
        self.assertEqual(result["command"], "/usr/bin/hatari --machine st")
        self.assertEqual(result["configuredBy"], "managed workbench profile")

    def test_editor_status_uses_the_effective_workbench_profile(self):
        service = Mock()
        service.get.return_value = SimpleNamespace(
            hardware_profile={"machine": "st", "emulator": "hatari"},
            target_hardware="auto", path=Path("/work/test.st"),
        )
        app = Flask(__name__)
        app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
        profile = {"machine": "ste", "emulator": "hatari", "addons": ["tos-emutos"]}
        with _hatari(), _firmware():
            result = app.test_client().get(
                "/api/images/test/editor-emulator",
                query_string={"hardwareProfile": json.dumps(profile), "basic": "true"},
            ).get_json()
        self.assertEqual(result["id"], "hatari")
        self.assertEqual(result["machine"], "ste")
        self.assertEqual(result["firmwareKind"], "emutos")
        self.assertIn("--machine ste", result["command"])

    def test_a_drive_run_attaches_the_drive_image_itself(self):
        """A hard drive is handed over entire, and as the image, not a wrapper.

        An Atari hard-disk interface reads the partition table out of the
        image's own first sector. Wrapping the image in a container means the
        machine finds a disk it does not recognise and starts with no drive,
        after a long wait while the wrapper is built.
        """
        with tempfile.TemporaryDirectory() as temporary:
            service = DiskService(temporary)
            drive = service.create_blank("hd", "Collection", capacity="4MB")
            app = Flask(__name__)
            app.register_blueprint(create_tools_blueprint(service, OperationRegistry()))
            with patch("app.routes.tools.run_emulator_process") as run, _hatari(), _firmware():
                run.return_value = SimpleNamespace(returncode=0, stdout="", stderr="")
                response = app.test_client().post(
                    f"/api/images/{drive.id}/editor-emulator",
                    json={
                        "path": "", "mode": "whole-drive-mount",
                        "hardwareProfile": {
                            "machine": "st", "emulator": "hatari", "addons": ["acsi-megafile"],
                        },
                    },
                )
                command = run.call_args.args[0]
            attached = command[command.index("--acsi") + 1]
            self.assertTrue(attached.startswith("0="), attached)
            media = Path(attached.split("=", 1)[1])
            self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
            # The session's own working image, so a change made inside the
            # emulator is a change to the image being worked on, and nothing
            # the size of the drive has to be built first.
            self.assertEqual(media, drive.path)
            self.assertTrue(media.exists())
            self.assertEqual(media.read_bytes()[:2], drive.path.read_bytes()[:2])

    def test_hardware_profile_retains_only_bounded_managed_choices(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        service = Mock()
        session = SimpleNamespace(kind="ofs", hardware_profile={}, target_hardware="auto")
        service.get.return_value = session
        service.summary.return_value = {
            "id": "test", "kind": "ofs", "hardwareProfile": session.hardware_profile,
        }
        app = Flask(__name__)
        app.register_blueprint(
            create_images_blueprint(service, Path(temporary.name), OperationRegistry())
        )
        response = app.test_client().patch(
            "/api/images/test/hardware-profile",
            json={
                "name": "Test profile", "machine": "st", "filingSystem": "gemdos",
                "addons": ["tos-104", "drive-a-ds"],
                "emulator": "hatari", "debugger": "hatari-debug",
                "emulatorRam": "1M", "emulatorBoot": "boot",
                "fileEmulatorCommand": "/untrusted/tool {file}",
            },
        )
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(session.hardware_profile["emulator"], "hatari")
        self.assertEqual(session.hardware_profile["debugger"], "hatari-debug")
        self.assertEqual(session.hardware_profile["addons"], ["tos-104", "drive-a-ds"])
        self.assertNotIn("fileEmulatorCommand", session.hardware_profile)

    def test_hardware_profile_catalogue_endpoint(self):
        app = Flask(__name__)
        app.register_blueprint(
            create_images_blueprint(Mock(), Path("/tmp"), OperationRegistry())
        )
        data = app.test_client().get("/api/hardware-profiles").get_json()
        self.assertIn("machines", data)
        self.assertTrue(any(row["id"] == "falcon030" for row in data["machines"]))


if __name__ == "__main__":
    unittest.main()


class RomChoiceTests(unittest.TestCase):
    """A collection from the preservation archives is not a tidy folder.

    It carries alternative dumps beside the good ones, some of them
    truncated and some not ROMs at all, and the later releases were never
    published per country. All of that decides which file the emulator gets.
    """

    def _rom(self, size: int, version: int = 0x0404, base: int = 0xE00000) -> bytes:
        """A ROM the decoder accepts: the header fields it insists on."""
        data = bytearray(size)
        struct.pack_into(">H", data, 0x00, 0x602E)
        struct.pack_into(">H", data, 0x02, version)
        struct.pack_into(">I", data, 0x04, base + 0x30)
        struct.pack_into(">I", data, 0x08, base)
        struct.pack_into(">I", data, 0x0C, base + size)
        struct.pack_into(">I", data, 0x18, 0x04141993)
        struct.pack_into(">H", data, 0x1C, 0x0006)
        return bytes(data)

    def _folder(self, files: dict[str, bytes]):
        folder = Path(tempfile.mkdtemp())
        for name, data in files.items():
            (folder / name).write_bytes(data)
        self.addCleanup(shutil.rmtree, folder, True)
        return folder

    def _choose(self, folder, machine: str):
        with mock.patch.object(emulator_config, "tos_directories", lambda: [folder]):
            return emulator_config.tos_for(machine)

    def test_a_release_with_no_language_prefers_the_plain_file(self) -> None:
        """The later releases were not published per country.

        `tos404.img` is the ROM. `tos404-a.img` is somebody's other dump of
        it, and sorting names alone put that first.
        """
        whole = self._rom(512 * 1024)
        folder = self._folder({
            "tos404-a.img": whole,
            "tos404-a2.img": whole,
            "tos404.img": whole,
        })
        self.assertEqual(self._choose(folder, "falcon030").name, "tos404.img")

    def test_a_truncated_dump_loses_to_a_whole_one(self) -> None:
        """A half-length dump still carries a perfectly good header.

        So the header cannot settle this and the length has to: every genuine
        dump of one release is the same size.
        """
        folder = self._folder({
            "tos404-a.img": self._rom(256 * 1024),
            "tos404-b.img": self._rom(512 * 1024),
        })
        self.assertEqual(self._choose(folder, "falcon030").name, "tos404-b.img")

    def test_a_file_that_is_not_a_rom_is_never_offered(self) -> None:
        """Better the bundled firmware than a machine that hangs."""
        folder = self._folder({"tos404.img": bytes(12345)})
        self.assertIsNone(self._choose(folder, "falcon030"))

    def test_the_language_order_still_decides_between_whole_roms(self) -> None:
        early = self._rom(192 * 1024, version=0x0104, base=0xFC0000)
        folder = self._folder({
            "tos104us.img": early,
            "tos104uk.img": early,
            "tos104fr.img": early,
        })
        self.assertEqual(self._choose(folder, "st").name, "tos104uk.img")
