from __future__ import annotations

import json
import unittest

import tempfile
from pathlib import Path

from desktop.__main__ import (
    _close_chooser_later,
    _desktop_message_text,
    _folder_selection,
    _open_error_script,
)


class _ScriptValue:
    def __init__(self, value) -> None:
        self.value = value

    def to_string(self):
        return self.value


class _LegacyJavascriptResult:
    def __init__(self, value) -> None:
        self.value = value

    def get_js_value(self):
        return self.value


class DesktopMessageTests(unittest.TestCase):
    def test_current_webkit_value_is_read_directly(self) -> None:
        self.assertEqual(
            "open-images:2",
            _desktop_message_text(_ScriptValue("open-images:2")),
        )

    def test_legacy_webkit_result_wrapper_remains_supported(self) -> None:
        self.assertEqual(
            '{"command":"open-plans","plans":[]}',
            _desktop_message_text(
                _LegacyJavascriptResult(
                    _ScriptValue('{"command":"open-plans","plans":[]}')
                )
            ),
        )

    def test_unsupported_message_object_is_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "unsupported script message"):
            _desktop_message_text(object())

    def test_non_text_message_is_rejected(self) -> None:
        with self.assertRaisesRegex(TypeError, "non-text script message"):
            _desktop_message_text(_ScriptValue(42))




class FolderSelectionTests(unittest.TestCase):
    """What a chosen folder hands back to the page.

    WebKitGTK's file chooser has no concept of a directory, so a directory
    input in the Linux desktop host opens an ordinary file chooser that an
    operator cannot pick a folder in. Pointing a batch import at a collection
    folder therefore came back with whichever single file happened to be
    selected. The host answers that request itself now, and this is the part
    that decides what the page receives.
    """

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        self.addCleanup(self._temporary.cleanup)

    def test_every_file_below_the_folder_is_offered(self) -> None:
        """A TOSEC set is one file per disk, often in subdirectories."""
        (self.root / "Games").mkdir()
        (self.root / "Games" / "disk1.zip").write_bytes(b"one")
        (self.root / "Games" / "disk2.zip").write_bytes(b"two")
        (self.root / "loose.st").write_bytes(b"three")

        selected = _folder_selection(self.root)

        # Sorted by full path, so a subdirectory's contents group together
        # rather than being interleaved with the files beside it.
        self.assertEqual(
            [str(Path(path).relative_to(self.root)) for path in selected],
            ["Games/disk1.zip", "Games/disk2.zip", "loose.st"],
        )

    def test_directories_are_not_offered_as_files(self) -> None:
        (self.root / "Extras").mkdir()
        self.assertEqual(_folder_selection(self.root), [])

    def test_a_link_that_points_at_its_own_parent_does_not_run_away(self) -> None:
        """A collection folder linking to itself would be walked for ever."""
        (self.root / "real.st").write_bytes(b"disk")
        (self.root / "loop").symlink_to(self.root, target_is_directory=True)

        selected = _folder_selection(self.root)

        self.assertEqual([Path(path).name for path in selected], ["real.st"])

    def test_the_selection_is_bounded(self) -> None:
        """A whole collection drive must not be handed over in one go."""
        for index in range(12):
            (self.root / f"disk{index:02d}.st").write_bytes(b"x")

        self.assertEqual(len(_folder_selection(self.root, limit=5)), 5)


class _RecordingGLib:
    """Just enough of GLib to see whether the teardown was deferred."""

    def __init__(self) -> None:
        self.deferred = []

    def idle_add(self, callback, *args):
        self.deferred.append((callback, args))
        return 1


class _Chooser:
    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class NativeChooserTeardownTests(unittest.TestCase):
    """A native dialog must outlive the response it is delivering.

    GtkNativeDialog is portal-backed. Destroying one from inside its own
    response handler frees it while GTK is still unwinding that emission,
    which segfaults inside GTK with nothing in the Python traceback to show
    for it. The crash is intermittent, because it depends on whether the
    freed memory has been reused by the time GTK reads it again, so the
    ordering is asserted rather than left to be noticed.
    """

    def test_the_dialog_is_not_destroyed_while_its_signal_is_running(self) -> None:
        glib = _RecordingGLib()
        chooser = _Chooser()
        _close_chooser_later(glib, chooser)
        self.assertFalse(
            chooser.destroyed,
            "the dialog was torn down inside its own response emission",
        )
        self.assertEqual(len(glib.deferred), 1)

    def test_the_deferred_teardown_really_destroys_the_dialog(self) -> None:
        glib = _RecordingGLib()
        chooser = _Chooser()
        _close_chooser_later(glib, chooser)
        callback, args = glib.deferred[0]
        callback(*args)
        self.assertTrue(chooser.destroyed)


class FailedOpenTests(unittest.TestCase):
    """A refused image must not leave a pane saying it is still working.

    The pane is put into the opening state before the work starts, and
    nothing else takes it out again. A failure that does not name the pane
    leaves the workspace reporting progress on an image that was refused
    seconds ago, which reads as the application having hung rather than
    having answered.
    """

    def test_a_failure_names_the_pane_it_left_waiting(self) -> None:
        script = _open_error_script("EasyAraMint 2.zip", "no image inside", 2)
        self.assertIn("EasyAraMint 2.zip", script)
        self.assertIn("no image inside", script)
        self.assertTrue(script.rstrip().endswith(", 2);"), script)

    def test_a_failure_with_no_pane_says_so_rather_than_guessing(self) -> None:
        script = _open_error_script("a dropped disk", "not readable", None)
        self.assertTrue(script.rstrip().endswith(", null);"), script)

    def test_a_name_carrying_quotes_stays_inside_the_string(self) -> None:
        """A filename is data. It reaches the page as one string argument.

        The name is somebody's file on disk, so it can hold quotes and
        semicolons. What matters is that the emitted call still has exactly
        two arguments and that the first one reads back as the message that
        was meant, rather than escaping into code.
        """
        awkward = 'od"d\'; alert(1);//'
        script = _open_error_script(awkward, "refused", 0)
        prefix = "window.AtariDesktopHost.showError("
        self.assertTrue(script.startswith(prefix))
        arguments = json.loads("[" + script[len(prefix):].rstrip().removesuffix(");") + "]")
        self.assertEqual(arguments, [f"Could not open {awkward}: refused", 0])


if __name__ == "__main__":
    unittest.main()
