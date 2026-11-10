"""Verify startup changes preserve user code and can be removed safely."""
import importlib.util
import os
from pathlib import Path
import runpy
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ui_install', ROOT / 'scripts/install-maya-ui-fixes.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class StartupInstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Path(self.directory.name)
        self.target = self.app / '2027/scripts/userSetup.py'

    def write(self, content):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_bytes(content)

    def test_new_install_and_repeated_install_are_idempotent(self):
        target, changed, backup = installer.configure(self.app, '2027')
        self.assertEqual(target, self.target)
        self.assertTrue(changed)
        self.assertIsNone(backup)
        source = target.read_text()
        self.assertIn(repr(str(ROOT / 'scripts/fix-maya-hotbox-geometry.py')), source)
        self.assertNotIn('__MAYA_HOTBOX_SCRIPT__', source)
        self.assertIn('utils.executeDeferred(activate)', source)
        self.assertEqual(installer.configure(self.app, '2027'), (target, False, None))

    def test_user_code_backup_and_remove(self):
        original = b'# existing startup\nvalue = 42\n'
        self.write(original)
        _, changed, backup = installer.configure(self.app, '2027')
        self.assertTrue(changed)
        self.assertEqual(backup.read_bytes(), original)
        self.assertTrue(self.target.read_bytes().startswith(original))
        installer.configure(self.app, '2027', remove=True)
        self.assertEqual(self.target.read_bytes(), original)

    def test_windows_line_endings_are_preserved(self):
        original = b'# startup\r\nvalue = 42\r\n'
        self.write(original)
        installer.configure(self.app, '2027')
        self.assertNotIn(b'\n', self.target.read_bytes().replace(b'\r\n', b''))
        installer.configure(self.app, '2027', remove=True)
        self.assertEqual(self.target.read_bytes(), original)

    def test_removal_deletes_new_startup_file_but_preserves_later_user_code(self):
        installer.configure(self.app, '2027')
        installer.configure(self.app, '2027', remove=True)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.with_name('.maya-hotbox-undo.json').exists())
        installer.configure(self.app, '2027')
        with self.target.open('a') as stream:
            stream.write('user_value = 42\n')
        installer.configure(self.app, '2027', remove=True)
        self.assertEqual(self.target.read_text(), 'user_value = 42\n')

    def test_original_missing_final_newline_is_restored_exactly(self):
        original = b'value = 42'
        self.write(original)
        installer.configure(self.app, '2027')
        installer.configure(self.app, '2027', remove=True)
        self.assertEqual(self.target.read_bytes(), original)

    def test_marker_text_inside_strings_is_preserved(self):
        originals = (
            b'note = "# BEGIN maya-debian-hotbox"\n',
            b'note = """Example:\n# BEGIN maya-debian-hotbox\n'
            b'keep this text\n# END maya-debian-hotbox\n"""\n',
        )
        for original in originals:
            with self.subTest(original=original):
                self.write(original)
                installer.configure(self.app, '2027')
                self.assertTrue(self.target.read_bytes().startswith(original))
                installer.configure(self.app, '2027', remove=True)
                self.assertEqual(self.target.read_bytes(), original)

    def test_python_source_encodings_are_preserved(self):
        for original in (b'\xef\xbb\xbf# UTF-8 BOM\nvalue = "Gr\xc3\xbc\xc3\x9fe"\n',
                         b'# coding: latin-1\nvalue = "Gr\xfc\xdfe"\n'):
            with self.subTest(original=original):
                self.write(original)
                _, _, backup = installer.configure(self.app, '2027')
                self.assertEqual(backup.read_bytes(), original)
                self.assertTrue(self.target.read_bytes().startswith(original))
                compile(self.target.read_bytes(), str(self.target), 'exec')
                installer.configure(self.app, '2027', remove=True)
                self.assertEqual(self.target.read_bytes(), original)

    def test_misplaced_or_duplicate_markers_are_rejected_without_backup(self):
        for original in (
                b'# END maya-debian-hotbox\n# BEGIN maya-debian-hotbox\n',
                b'# BEGIN maya-debian-hotbox\n# BEGIN maya-debian-hotbox\n'
                b'# END maya-debian-hotbox\n# END maya-debian-hotbox\n',
                b'if True:\n    # BEGIN maya-debian-hotbox\n    value = 42\n'
                b'    # END maya-debian-hotbox\n'):
            with self.subTest(original=original):
                self.write(original)
                with self.assertRaises(ValueError):
                    installer.configure(self.app, '2027')
                self.assertEqual(self.target.read_bytes(), original)
                self.assertEqual(list(self.target.parent.glob('*.before-hotbox-*')), [])

    def test_incomplete_marker_and_invalid_python_do_not_change_file(self):
        for original in (b'# BEGIN maya-debian-hotbox\n', b'if !!!\n'):
            self.write(original)
            with self.assertRaises((ValueError, SyntaxError)):
                installer.configure(self.app, '2027')
            self.assertEqual(self.target.read_bytes(), original)

    def test_symlink_target_is_not_modified(self):
        destination = self.app / 'actual.py'
        destination.write_text('value = 42\n')
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(destination)
        with self.assertRaises(ValueError):
            installer.configure(self.app, '2027')
        self.assertEqual(destination.read_text(), 'value = 42\n')

    def test_missing_install_removal_creates_nothing(self):
        self.assertEqual(installer.configure(self.app, '2027', remove=True),
                         (self.target, False, None))
        self.assertFalse(self.target.exists())

    def test_generated_startup_defers_gui_and_skips_batch_or_opt_out(self):
        installer.configure(self.app, '2027')
        for batch, enabled, expected in ((False, '1', 1), (True, '1', 0), (False, '0', 0)):
            queued = []
            maya = SimpleNamespace(cmds=SimpleNamespace(about=lambda **kwargs: batch),
                                   utils=SimpleNamespace(executeDeferred=queued.append))
            with self.subTest(batch=batch, enabled=enabled), \
                    patch.dict(sys.modules, {'maya': maya}), \
                    patch.dict(os.environ, {'MAYA_HOTBOX_GEOMETRY_FIX': enabled}):
                runpy.run_path(str(self.target))
            self.assertEqual(len(queued), expected)


if __name__ == '__main__':
    unittest.main()
