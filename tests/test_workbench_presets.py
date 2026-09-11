"""The Workbench presets must be hardware the catalogue lets their machine take.

The presets live in app.js as JavaScript literals, and the Workbench drops any
add-on the catalogue does not offer for the machine as the preset loads. Five
presets once carried such add-ons, so the profile a person applied quietly
differed from the one they chose. These tests hold every preset, and every
machine's defaults, to the same validation the server applies to a profile.
"""

import json
import re
import unittest
from pathlib import Path

from app.hardware_profiles import normalise_hardware_profile


APP = (Path(__file__).resolve().parents[1] / "app" / "static" / "app.js").read_text()
DRIVER_BUILD_FOR = {
    "driver-emutos-builtin": "emutos",
    "driver-ahdi": "ahdi",
    "driver-hddriver": "hddriver",
    "driver-pp": "pp",
    "driver-icd": "icd",
}


def _literal(pattern: str):
    """Read one object or array literal of plain keys and strings from app.js."""
    match = re.search(pattern, APP, re.S)
    if match is None:
        raise AssertionError(f"{pattern} was not found in app.js")
    # A whole-line // comment is ordinary JavaScript between entries, and
    # nothing JSON can carry.
    text = re.sub(r"(?m)^\s*//.*$", "", match.group(1))
    text = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', text)
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", text))


class WorkbenchPresetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.presets = _literal(r"const BUILTIN_PROFILES = (\[.*?\n\]);")
        cls.defaults = _literal(r"const machineDefaults = (\{.*?\n  \});")

    def test_every_preset_is_hardware_its_machine_can_take(self):
        self.assertEqual(len(self.presets), 17)
        for preset in self.presets:
            with self.subTest(preset=preset["name"]):
                normalised = normalise_hardware_profile(dict(preset))
                self.assertEqual(normalised["addons"], preset["addons"])

    def test_every_machine_default_is_hardware_that_machine_can_take(self):
        for machine, defaults in self.defaults.items():
            with self.subTest(machine=machine):
                normalise_hardware_profile({"machine": machine, "addons": defaults["addons"]})

    def test_the_driver_field_agrees_with_the_driver_add_on(self):
        for profile in [
            *self.presets,
            *({"name": machine, **defaults} for machine, defaults in self.defaults.items()),
        ]:
            with self.subTest(profile=profile["name"]):
                drivers = [DRIVER_BUILD_FOR[item] for item in profile["addons"] if item in DRIVER_BUILD_FOR]
                self.assertEqual(profile["driverBuild"], drivers[0] if drivers else "none")


if __name__ == "__main__":
    unittest.main()
