from __future__ import annotations

import unittest

from app.emulator_evidence import EmulatorEvidenceError, private_display_arguments


class EmulatorEvidenceTests(unittest.TestCase):
    def test_private_display_replaces_nested_xvfb_wrapper_and_extends_bound(self):
        source = [
            "timeout", "--signal=TERM", "--kill-after=2", "8", "env",
            "SDL_AUDIODRIVER=dummy", "xvfb-run", "-a", "/usr/bin/hatari",
            "--disk-a", "/work/menu.st", "--run-vbls", "350",
        ]
        command = private_display_arguments(source, ":147", 14)
        self.assertEqual(command[3], "14")
        self.assertIn("DISPLAY=:147", command)
        self.assertNotIn("xvfb-run", command)
        self.assertEqual(source[3], "8", "The shared emulator command must not be mutated")

    def test_the_frame_limit_is_removed_so_the_machine_stays_on_screen(self):
        """Hatari must not leave after its frame count while frames are being captured."""
        source = [
            "timeout", "--signal=TERM", "--kill-after=2", "8", "env",
            "SDL_AUDIODRIVER=dummy", "xvfb-run", "-a", "/usr/bin/hatari",
            "--acsi", "0=/work/drive.img", "--run-vbls", "350", "--log-level", "warn",
        ]
        command = private_display_arguments(source, ":150", 20)
        self.assertNotIn("--run-vbls", command)
        self.assertNotIn("350", command)
        self.assertEqual(command[-2:], ["--log-level", "warn"])
        self.assertIn("--run-vbls", source, "The shared emulator command must not be mutated")

    def test_private_display_refuses_an_unmanaged_command(self):
        with self.assertRaisesRegex(EmulatorEvidenceError, "headless display"):
            private_display_arguments(["/usr/bin/emulator"], ":147")


if __name__ == "__main__":
    unittest.main()
