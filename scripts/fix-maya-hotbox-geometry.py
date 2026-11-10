"""Correct Maya's X11 Hotbox overlay; also loaded by the local userSetup.py."""
from datetime import datetime
import json
import os
from pathlib import Path
import weakref

from PySide6 import QtCore, QtWidgets
import shiboken6

BASE = Path(__file__).resolve().parents[1]


def rectangle(rect):
    return [rect.x(), rect.y(), rect.width(), rect.height()]


class HotboxGeometryFix(QtCore.QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.active = False
        self.busy = False
        self.dispatcher = QtCore.QAbstractEventDispatcher.instance(app.thread())
        self.originals = {}
        self.log = BASE / 'logs/hotbox-geometry.jsonl'

    @staticmethod
    def is_hotbox(widget):
        return (isinstance(widget, QtWidgets.QWidget)
                and widget.isWindow()
                and widget.objectName() == 'hotboxWindow'
                and widget.metaObject().className() == 'QtransparentWindow')

    def apply(self, widget):
        if not self.active or not shiboken6.isValid(widget) or not self.is_hotbox(widget):
            return
        screens = self.app.screens()
        if not screens:
            return
        bounds = QtCore.QRect(screens[0].geometry())
        for screen in screens[1:]:
            bounds = bounds.united(screen.geometry())
        self.originals = {key: entry for key, entry in self.originals.items()
                          if entry[0]() is not None and shiboken6.isValid(entry[0]())}
        key = id(widget)
        if key not in self.originals:
            previous = QtCore.QRect(widget.geometry())
            self.originals[key] = (weakref.ref(widget), previous)
            try:
                self.log.parent.mkdir(parents=True, exist_ok=True)
                with open(self.log, 'a', opener=lambda p, flags: os.open(p, flags, 0o600)) as stream:
                    stream.write(json.dumps({'time': datetime.now().isoformat(timespec='seconds'),
                                             'before': rectangle(previous),
                                             'target': rectangle(bounds)}) + '\n')
            except OSError:
                # Logging must not prevent the UI fix, e.g. in a read-only clone.
                pass
        if widget.geometry() != bounds:
            # Native inspection showed an override-redirect ARGB window at
            # 0,0,640,480. Preserve its flags/focus and give the overlay the
            # virtual desktop it needs to paint at global cursor coordinates.
            widget.setGeometry(bounds)
            widget.update()

    def check_windows(self):
        if not self.active or self.busy:
            return
        self.busy = True
        try:
            for widget in self.app.topLevelWidgets():
                if widget.isVisible() and self.is_hotbox(widget):
                    self.apply(widget)
        finally:
            self.busy = False

    def stop(self):
        if not self.active:
            return
        self.active = False
        self.dispatcher.aboutToBlock.disconnect(self.check_windows)
        for reference, geometry in self.originals.values():
            widget = reference()
            if widget is not None and shiboken6.isValid(widget):
                widget.setGeometry(geometry)
        self.originals.clear()
        print('Hotbox-Flaechenkorrektur entfernt.')

    def start(self):
        if self.dispatcher is None:
            raise RuntimeError('Qt GUI event dispatcher is unavailable.')
        self.active = True
        # An application-wide Python event filter caused recursive QObject
        # wrapping during Maya startup (PySide::getWrapperForQObject crash).
        # Inspect completed UI updates just before the GUI loop becomes idle;
        # no global filter and no input events need Python QObject wrapping.
        self.dispatcher.aboutToBlock.connect(self.check_windows)
        QtCore.QTimer.singleShot(0, self.check_windows)


def install(quiet=False):
    app = QtWidgets.QApplication.instance()
    if app is None:
        raise RuntimeError('Im Python-Tab der laufenden Maya-Oberflaeche ausfuehren.')
    previous = getattr(app, '_maya_hotbox_geometry_fix', None)
    if previous and previous.active:
        if not quiet:
            print('Hotbox-Flaechenkorrektur bereits aktiv.')
        return
    fix = HotboxGeometryFix(app)
    app._maya_hotbox_geometry_fix = fix
    fix.start()
    if not quiet:
        print('Hotbox-Flaechenkorrektur fuer diese Sitzung aktiv. Jetzt Space im Viewport halten.')
        print('Ruecknahme: from PySide6 import QtWidgets; '
              'QtWidgets.QApplication.instance()._maya_hotbox_geometry_fix.stop()')


if __name__ == '__main__':
    install()
