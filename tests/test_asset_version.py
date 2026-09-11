"""The version the page stamps on its own scripts and stylesheets."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.asset_version import PLACEHOLDER, asset_version, stamp_index


class AssetVersionTests(unittest.TestCase):
    """A stale version is worse than no caching at all.

    It leaves an operator running new code underneath an old interface, with
    nothing on screen to say so. That is exactly what happened when the
    version was a literal somebody had to remember to change: the application
    found two hard-disk drivers and the page went on reporting neither.
    """

    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="aff-assets-"))
        self.addCleanup(lambda: __import__("shutil").rmtree(self.folder, ignore_errors=True))
        (self.folder / "app.js").write_text("first")
        (self.folder / "styles.css").write_text("body {}")
        (self.folder / "index.html").write_text(
            f'<script src="/app.js?v={PLACEHOLDER}"></script>'
        )

    def test_changing_a_script_changes_the_version(self) -> None:
        before = asset_version(self.folder)
        (self.folder / "app.js").write_text("second")
        self.assertNotEqual(asset_version(self.folder), before)

    def test_changing_nothing_leaves_the_version_alone(self) -> None:
        """Caching still has to work, or every load fetches everything again."""
        self.assertEqual(asset_version(self.folder), asset_version(self.folder))

    def test_the_version_follows_the_contents_not_the_timestamps(self) -> None:
        """The same code on another machine should not invalidate a cache."""
        before = asset_version(self.folder)
        (self.folder / "app.js").write_text("first")
        self.assertEqual(asset_version(self.folder), before)

    def test_a_file_the_page_does_not_load_is_ignored(self) -> None:
        before = asset_version(self.folder)
        (self.folder / "notes.txt").write_text("not loaded by the page")
        self.assertEqual(asset_version(self.folder), before)

    def test_the_placeholder_is_filled_in(self) -> None:
        page = stamp_index(self.folder, "abc123")
        self.assertIn("/app.js?v=abc123", page)
        self.assertNotIn(PLACEHOLDER, page)

    def test_a_page_still_carrying_a_literal_is_rewritten(self) -> None:
        """The page must never be served with a version somebody typed."""
        (self.folder / "index.html").write_text(
            '<script src="/app.js?v=20260910.1"></script>'
        )
        page = stamp_index(self.folder, "abc123")
        self.assertIn("/app.js?v=abc123", page)
        self.assertNotIn("20260910.1", page)


class ShippedPageTests(unittest.TestCase):
    def test_the_real_page_carries_no_literal_version(self) -> None:
        """A literal here is the fault this exists to prevent."""
        static = Path(__file__).resolve().parents[1] / "app" / "static"
        text = (static / "index.html").read_text(encoding="utf-8")
        self.assertIn(PLACEHOLDER, text)
        stamped = stamp_index(static, asset_version(static))
        self.assertNotIn(PLACEHOLDER, stamped)


if __name__ == "__main__":
    unittest.main()
