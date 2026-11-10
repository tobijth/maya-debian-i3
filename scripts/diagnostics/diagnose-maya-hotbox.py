"""Bounded in-session diagnostic of the native Hotbox, without global filters."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess

from PySide6 import QtCore, QtWidgets

BASE = Path(__file__).resolve().parents[2]


def widget_info(widget):
    if widget is None:
        return None
    return {'class': widget.metaObject().className(), 'object': widget.objectName()}


class HotboxProbe(QtCore.QObject):
    def __init__(self, app, log):
        super().__init__(app)
        self.app = app
        self.log = Path(log)
        self.running = False
        self.restore_helper = False
        self.dispatcher = QtCore.QAbstractEventDispatcher.instance(app.thread())
        self.last_hotbox_state = None
        self.native_seen = set()

    def record(self, kind, **data):
        with self.log.open('a') as stream:
            stream.write(json.dumps({'time': datetime.now().isoformat(timespec='milliseconds'),
                                     'kind': kind, **data}, ensure_ascii=False) + '\n')

    def helper(self, action):
        environment = dict(os.environ)
        for key in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONHOME', 'PYTHONPATH',
                    'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
            environment.pop(key, None)
        result = subprocess.run(['/usr/bin/python3', str(BASE / 'scripts/helpers/maya-i3-panels.py'), action],
                                env=environment, text=True, capture_output=True, timeout=5)
        self.record('panel_helper', action=action, status=result.returncode,
                    output=(result.stdout + result.stderr).strip())
        return result.returncode

    def snapshot(self, label):
        if not self.running:
            return
        windows = []
        for widget in self.app.topLevelWidgets():
            info = widget_info(widget)
            # Never record project titles or text typed into any input field.
            if not widget.isVisible() and 'hotbox' not in str(info).lower():
                continue
            rect = widget.geometry()
            info.update(visible=widget.isVisible(), window_type=widget.windowType().value,
                        flags=widget.windowFlags().value,
                        window_id=int(widget.effectiveWinId() or 0),
                        geometry=[rect.x(), rect.y(), rect.width(), rect.height()])
            windows.append(info)
        self.record('windows', label=label, focus=widget_info(self.app.focusWidget()),
                    active=widget_info(self.app.activeWindow()), windows=windows)
        hotboxes = [w['window_id'] for w in windows
                    if w['object'] == 'hotboxWindow' and w['visible'] and w['window_id']]
        if hotboxes and not self.native_seen:
            self.native_seen.update(hotboxes)
            environment = dict(os.environ)
            for name in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONHOME', 'PYTHONPATH',
                         'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
                environment.pop(name, None)
            try:
                result = subprocess.run(
                    ['/usr/bin/python3', str(BASE / 'scripts/diagnostics/inspect-hotbox-x11.py'),
                     *map(str, hotboxes)], env=environment, text=True,
                    capture_output=True, timeout=8)
                if result.returncode:
                    self.record('native_error', error=result.stderr.strip()[:600])
                else:
                    self.record('native', **json.loads(result.stdout))
            except Exception as error:
                self.record('native_error', error=str(error))

    def on_idle(self):
        if not self.running:
            return
        state = []
        for widget in self.app.topLevelWidgets():
            if widget.objectName() == 'hotboxWindow' and widget.isVisible():
                rect = widget.geometry()
                state.append((int(widget.effectiveWinId() or 0), rect.x(), rect.y(),
                              rect.width(), rect.height()))
        state = tuple(sorted(state))
        if state != self.last_hotbox_state:
            self.last_hotbox_state = state
            self.snapshot('hotbox_change')

    def direct_show(self):
        import maya.cmds as cmds
        # Always arm release before attempting the popup, including nested loops.
        QtCore.QTimer.singleShot(2000, self.release)
        try:
            panels = cmds.getPanel(type='modelPanel') or []
            visible = cmds.getPanel(visiblePanels=True) or []
            candidates = [panel for panel in panels if panel in visible]
            if candidates:
                cmds.setFocus(candidates[0])
            focused = self.app.focusWidget()
            if focused:
                center = focused.mapToGlobal(focused.rect().center())
                cmds.hotBox(position=(max(0, center.x()), max(0, center.y())))
            self.record('direct_show_begin')
            cmds.hotBox(noKeyPress=True)
            self.record('direct_show_return')
            QtCore.QTimer.singleShot(100, lambda: self.snapshot('direct_hotbox'))
        except Exception as error:
            self.record('direct_show_error', error=str(error))

    def release(self):
        import maya.cmds as cmds
        try:
            cmds.hotBox(release=True)
        except Exception as error:
            self.record('release_error', error=str(error))
        print('Hotbox-Test: Jetzt im Viewport Space 2 Sekunden halten und loslassen (bis Diagnoseende).')
        QtCore.QTimer.singleShot(100, lambda: self.snapshot('after_direct_release'))

    def stop(self):
        if not self.running:
            return
        self.running = False
        self.dispatcher.aboutToBlock.disconnect(self.on_idle)
        self.snapshot('finished')
        if self.restore_helper:
            try:
                self.helper('--start')
            except Exception as error:
                self.record('helper_restore_error', error=str(error))
        self.record('finished')
        print('Hotbox-Diagnose beendet. Protokoll:', self.log)

    def start(self):
        import maya.cmds as cmds
        self.running = True
        self.record('start', hotkey_set=cmds.hotkeySet(query=True, current=True),
                    press=cmds.hotkey('Space', query=True, name=True),
                    release=cmds.hotkey('Space', query=True, releaseName=True),
                    style=cmds.hotBox(query=True, displayStyle=True),
                    transparency=cmds.hotBox(query=True, transparenyLevel=True))
        self.record('screens', screens=[{
            'geometry': [s.geometry().x(), s.geometry().y(),
                         s.geometry().width(), s.geometry().height()],
            'scale': s.devicePixelRatio()} for s in self.app.screens()])
        if (BASE / 'state/i3/panels-status.json').exists():
            try:
                self.restore_helper = self.helper('--stop') == 0
            except Exception as error:
                self.record('helper_pause_error', error=str(error))
        self.dispatcher.aboutToBlock.connect(self.on_idle)
        self.snapshot('before')
        print('Hotbox-Diagnose: In 1 Sekunde direkter Anzeigetest fuer 2 Sekunden.')
        print('Danach bitte in den Viewport klicken und Space 2 Sekunden halten. Beobachtung endet nach 22 Sekunden.')
        QtCore.QTimer.singleShot(1000, self.direct_show)
        QtCore.QTimer.singleShot(22000, self.stop)


def start_probe():
    app = QtWidgets.QApplication.instance()
    if app is None:
        raise RuntimeError('In der laufenden Maya-Oberflaeche im Python Script Editor ausfuehren.')
    previous = getattr(app, '_maya_hotbox_probe', None)
    if previous and previous.running:
        previous.stop()
    environment = dict(os.environ)
    for name in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'PYTHONHOME', 'PYTHONPATH',
                 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        environment.pop(name, None)
    subprocess.run(['/usr/bin/python3', str(BASE / 'scripts/helpers/local_undo.py'),
                    'capture', 'diagnostic'], env=environment, check=True)
    log_dir = BASE / 'logs'
    log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    log = log_dir / ('hotbox-probe-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.jsonl')
    with open(log, 'x', opener=lambda path, flags: os.open(path, flags, 0o600)):
        pass
    probe = HotboxProbe(app, log)
    app._maya_hotbox_probe = probe
    probe.start()


if __name__ == '__main__':
    start_probe()
