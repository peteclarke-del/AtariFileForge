from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.analysis_service import preflight_report
from app.disk_service import DiskService
from app.filename_policy import target_name_policy


class FilenamePolicyTests(unittest.TestCase):
    def test_tosrom_preflight_and_mutation_share_one_module_name_policy(self):
        session = SimpleNamespace(
            kind="tosrom",
            name="tos104.img",
            hardware_profile={},
            gemdos_capabilities={},
        )
        long_name = "a" * 61
        report = preflight_report(None, session, {
            "targetKind": "tosrom",
            "changes": [{"name": long_name, "nameIsLeaf": True}],
        })

        self.assertEqual(report["items"][0]["targetName"], "a" * 60)
        with self.assertRaisesRegex(Exception, "at most 60"):
            DiskService.validate_leaf_name(session, long_name)

    def test_a_rom_segment_name_is_not_rewritten_by_preflight(self):
        """A ROM segment is named by the image, not by a directory entry.

        ``os.img`` and ``TOS 1.04`` are both ordinary segment names, so the
        preflight has nothing to fold them into.
        """
        session = SimpleNamespace(
            kind="tosrom",
            name="tos104.img",
            hardware_profile={},
            gemdos_capabilities={},
        )
        report = preflight_report(None, session, {
            "targetKind": "tosrom",
            "changes": [{"name": "TOS 1.04", "nameIsLeaf": True}],
        })

        self.assertEqual(report["items"][0]["targetName"], "TOS 1.04")
        self.assertEqual(
            DiskService.validate_leaf_name(session, "TOS 1.04"), "TOS 1.04"
        )

    def test_gemdos_allocator_uniquifies_on_the_base_and_keeps_the_extension(self):
        policy = target_name_policy("gemdos")

        self.assertEqual(policy.allocate("LONGNAME.DOC", []), "LONGNAME.DOC")
        # The extension says which program opens the file, so the counter eats
        # into the base rather than the three characters after the full stop.
        self.assertEqual(
            policy.allocate("LONGNAME.DOC", ["longname.doc"]), "LONGNAM1.DOC"
        )
        # A host name may carry several full stops. The last one is the
        # separator; the rest are ordinary characters GEMDOS cannot hold.
        self.assertEqual(policy.normalise("read.me.txt"), "READ_ME.TXT")

    def test_gemdos_names_reject_unrepresentable_and_edge_whitespace(self):
        policy = target_name_policy("gemdos")

        with self.assertRaisesRegex(Exception, "cannot contain"):
            policy.validate("ELITE\U0001f642")
        with self.assertRaisesRegex(Exception, "start or end"):
            policy.validate(" ELITE")
        # A space inside a name is indistinguishable from the padding TOS
        # writes into the eleven-byte field, so it is refused by name.
        with self.assertRaisesRegex(Exception, "space"):
            policy.validate("ELITE II.PRG")
        self.assertEqual(policy.validate("readme.txt"), "README.TXT")

    def test_the_allocator_never_overflows_the_eight_character_base(self):
        policy = target_name_policy("gemdos")
        used = ["LONGNAME.DOC", *[f"LONGNAM{digit}.DOC" for digit in range(1, 10)]]

        allocated = policy.allocate("LONGNAME.DOC", used)

        base, _stop, extension = allocated.partition(".")
        self.assertEqual(len(base), 8)
        self.assertEqual(extension, "DOC")
        self.assertNotIn(allocated.casefold(), {name.casefold() for name in used})

    def test_preflight_only_reports_collisions_within_the_same_parent(self):
        session = SimpleNamespace(
            kind="gemdos", name="files.st", hardware_profile={},
            gemdos_capabilities={"nameLimit": 12},
        )
        changes = [
            {"name": "ReadMe", "nameIsLeaf": True, "parent": "ONE"},
            {"name": "ReadMe", "nameIsLeaf": True, "parent": "TWO"},
        ]

        report = preflight_report(None, session, {"changes": changes})

        self.assertTrue(report["canProceed"])

    def test_partition_label_preflight_uses_the_boot_sector_field_width(self):
        session = SimpleNamespace(
            kind="hd", name="drive.img", hardware_profile={},
            gemdos_capabilities={},
        )

        report = preflight_report(None, session, {
            "targetKind": "hd",
            "changes": [
                {"name": "A" * 32, "nameIsLeaf": True, "type": "partition"}
            ],
        })

        # A partition label is the eleven characters its own boot sector
        # holds, not an 8.3 filename.
        self.assertEqual(report["items"][0]["targetName"], "A" * 11)


if __name__ == "__main__":
    unittest.main()
