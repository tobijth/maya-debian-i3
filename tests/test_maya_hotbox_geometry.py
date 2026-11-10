"""Optional real-Qt regressions; run with Maya's mayapy and QT_QPA_PLATFORM=offscreen."""
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
try:
    from PySide6 import QtCore, QtWidgets
    import shiboken6
except ImportError:
    QtCore = QtWidgets = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipIf(QtWidgets is None, 'Requires Maya PySide6/shiboken6; use mayapy.')
class HotboxGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reintroducing the startup-crashing application-wide filter must fail.
        class GuardedApplication(QtWidgets.QApplication):
            def installEventFilter(self, *args):
                raise AssertionError('No application-wide event filter may be installed.')

        cls.app = QtWidgets.QApplication.instance() or GuardedApplication([])
        spec = importlib.util.spec_from_file_location(
            'geometry', ROOT / 'scripts/fix-maya-hotbox-geometry.py')
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.fix = self.module.HotboxGeometryFix(self.app)
        self.fix.log = Path(self.directory.name) / 'geometry.jsonl'
        self.widgets = []

    def tearDown(self):
        self.fix.stop()
        for widget in self.widgets:
            if shiboken6.isValid(widget):
                widget.close()

    def hotbox(self):
        class QtransparentWindow(QtWidgets.QWidget):
            pass

        widget = QtransparentWindow()
        widget.setObjectName('hotboxWindow')
        widget.setWindowFlags(QtCore.Qt.WindowType(3073))
        widget.setGeometry(0, 0, 640, 480)
        self.widgets.append(widget)
        return widget

    def run_loop(self):
        loop = QtCore.QEventLoop()
        QtCore.QTimer.singleShot(20, loop.quit)
        loop.exec()

    def test_idle_callback_fixes_real_overlay_and_stop_restores_it(self):
        widget = self.hotbox()
        original = QtCore.QRect(widget.geometry())
        self.fix.start()
        widget.show()
        self.run_loop()
        bounds = QtCore.QRect()
        for screen in self.app.screens():
            bounds = bounds.united(screen.geometry())
        self.assertEqual(widget.geometry(), bounds)
        self.assertEqual(widget.windowFlags().value, 3073)
        self.fix.stop()
        self.assertEqual(widget.geometry(), original)

    def test_plain_widget_with_same_name_is_untouched(self):
        widget = QtWidgets.QWidget()
        widget.setObjectName('hotboxWindow')
        widget.setWindowFlags(QtCore.Qt.WindowType(3073))
        widget.setGeometry(40, 50, 300, 200)
        self.widgets.append(widget)
        self.fix.start()
        widget.show()
        self.run_loop()
        self.assertEqual(widget.geometry(), QtCore.QRect(40, 50, 300, 200))

    def test_current_screen_layout_including_negative_coordinates_is_recomputed(self):
        widget = self.hotbox()
        self.fix.active = True
        def screen(rect):
            return SimpleNamespace(geometry=lambda: QtCore.QRect(*rect))
        with patch.object(self.app, 'screens', return_value=[screen((-1920, 0, 1920, 1080)),
                                                            screen((0, 0, 2560, 1440))]):
            self.fix.apply(widget)
        self.assertEqual(widget.geometry(), QtCore.QRect(-1920, 0, 4480, 1440))
        with patch.object(self.app, 'screens', return_value=[screen((0, 0, 1920, 1080))]):
            self.fix.apply(widget)
        self.assertEqual(widget.geometry(), QtCore.QRect(0, 0, 1920, 1080))
        self.fix.active = False

    def test_failed_log_write_does_not_break_geometry(self):
        widget = self.hotbox()
        self.fix.start()
        self.fix.log = Path(self.directory.name)  # Opening a directory as a file fails.
        self.fix.apply(widget)
        bounds = QtCore.QRect()
        for screen in self.app.screens():
            bounds = bounds.united(screen.geometry())
        self.assertEqual(widget.geometry(), bounds)

    def test_repeated_install_keeps_one_activation(self):
        self.module.install(quiet=True)
        self.fix = self.app._maya_hotbox_geometry_fix
        self.fix.log = Path(self.directory.name) / 'geometry.jsonl'
        self.module.install(quiet=True)
        self.assertIs(self.app._maya_hotbox_geometry_fix, self.fix)

    def test_diagnostic_records_only_hotbox_state_changes_without_a_global_filter(self):
        spec = importlib.util.spec_from_file_location(
            'diagnostic', ROOT / 'scripts/diagnostics/diagnose-maya-hotbox.py')
        diagnostic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(diagnostic)
        probe = diagnostic.HotboxProbe(self.app, Path(self.directory.name) / 'probe.jsonl')
        probe.running = True
        snapshots = []
        probe.snapshot = snapshots.append
        widget = self.hotbox()
        widget.show()
        probe.on_idle()
        probe.on_idle()
        self.assertEqual(snapshots, ['hotbox_change'])
        widget.hide()
        probe.on_idle()
        self.assertEqual(snapshots, ['hotbox_change', 'hotbox_change'])
        probe.running = False


if __name__ == '__main__':
    unittest.main()
