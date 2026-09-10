from __future__ import annotations

import unittest
from threading import RLock
from types import SimpleNamespace
from unittest.mock import Mock

from app.disk_service import DiskService
from app.editor_project import EDITOR_PROJECT_FORMAT, editor_project_key, normalise_editor_project


class EditorProjectTests(unittest.TestCase):
    def test_key_separates_side_and_path(self):
        self.assertEqual(editor_project_key("GAME.PRG", 1), "1|GAME.PRG")
        self.assertEqual(editor_project_key("GAME.PRG", None), "-|GAME.PRG")
        self.assertNotEqual(editor_project_key("GAME.PRG", 0), editor_project_key("GAME.PRG", 1))

    def test_normalisation_rejects_bad_regions_and_cleans_symbols(self):
        project = normalise_editor_project({
            "notes": "Research",
            "symbols": {"0x8000": "start here", "bad": "ignored"},
            "regions": [
                {"start": "0x10", "end": "0x20", "kind": "text", "name": "Message"},
                {"start": 20, "end": 10, "kind": "bytes"},
                {"start": 0, "end": 4, "kind": "unknown"},
            ],
            "bookmarks": [{"offset": "0x12", "name": "Entry", "note": "Check this"}],
            "comments": {"0x12": "Initialisation entry", "bad": "ignored", "32": ""},
        })
        self.assertEqual(project["format"], EDITOR_PROJECT_FORMAT)
        self.assertEqual(project["symbols"], {"32768": "start_here"})
        self.assertEqual(project["regions"], [{"start": 16, "end": 32, "kind": "text", "name": "Message", "width": 8}])
        self.assertEqual(project["bookmarks"][0]["offset"], 18)
        self.assertEqual(project["comments"], {"18": "Initialisation entry"})

    def test_annotations_follow_file_and_directory_moves(self):
        service = DiskService.__new__(DiskService)
        service._persist_session = Mock()
        session = SimpleNamespace(
            lock=RLock(),
            editor_projects={
                "-|GAMES/FRAK/DESKTOP.INF": {"notes": "loader"},
                "-|OTHER.TXT": {"notes": "leave me"},
            },
        )
        changed = service.move_editor_projects(
            session,
            [{"source": "GAMES/FRAK", "destination": "ARCADE/FRAK"}],
            None,
        )
        self.assertEqual(changed, 1)
        self.assertIn("-|ARCADE/FRAK/DESKTOP.INF", session.editor_projects)
        self.assertNotIn("-|GAMES/FRAK/DESKTOP.INF", session.editor_projects)
        self.assertIn("-|OTHER.TXT", session.editor_projects)

    def test_annotations_are_removed_with_deleted_directory(self):
        service = DiskService.__new__(DiskService)
        service._persist_session = Mock()
        session = SimpleNamespace(
            lock=RLock(),
            editor_projects={
                "0|GAMES/FRAK/DESKTOP.INF": {"notes": "loader"},
                "1|GAMES/FRAK/DESKTOP.INF": {"notes": "the same path in another view"},
            },
        )
        removed = service.delete_editor_projects(session, ["GAMES"], 0)
        self.assertEqual(removed, 1)
        self.assertEqual(list(session.editor_projects), ["1|GAMES/FRAK/DESKTOP.INF"])


if __name__ == "__main__":
    unittest.main()
