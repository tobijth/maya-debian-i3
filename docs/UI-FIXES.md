# Individual Maya UI fixes

Choose the symptom that matches your setup. These fixes can be used with an existing Maya installation. The observations came from one Debian 13, X11, i3 desktop running Maya 2027.2. Read [Meat Proxy's notes](../README.md#meat-proxys-notes) for authorship and maintenance expectations.

## Invisible Hotbox

### Try the fix

If Space reaches Maya but the Hotbox remains invisible, use the Python tab of Maya's Script Editor. Replace the path with the absolute path to your clone:

```python
import runpy
_ = runpy.run_path('/path/to/repo/scripts/fix-maya-hotbox-geometry.py', run_name='__main__')
```

Hold Space in a viewport and check that the Hotbox is visible and usable. If it helps, set up automatic activation below. Reassigning the Space hotkey alone did not solve the observed display problem.

### What was observed

Space reached Maya correctly, and calling `hotBox` directly also created a window. The default hotkeys were correct.

Native X11 measurements showed a transparent `QtransparentWindow` named `hotboxWindow`, sized `640x480` at `0,0`. Maya was on the middle of three monitors. The Hotbox drawing area did not cover the required position. A compositor was active; the window was `override_redirect` and unmanaged by i3. The panel helper was paused during measurement.

[The fix](../scripts/fix-maya-hotbox-geometry.py) checks visible Hotbox windows through `QAbstractEventDispatcher.aboutToBlock`, after Qt has processed GUI events. It sets that window's geometry to the combined area of the current Qt screens. This made the Hotbox visible and usable in the original setup, including after a full Maya restart with automatic activation.

A global Python event filter worked in a manual test but caused a PySide crash during startup when QObject wrappers were created. The published fix uses no global event filter and has a reentry guard. The underlying cause of Maya's incorrect Hotbox initialization remains uncertain.

Screen arrangement and resolution are reread each time the Hotbox appears; no desktop size is hardcoded. If monitors change while it is open, release Space and hold it again. Other Maya/Qt versions and mixed scaling factors have not been systematically tested.

### Enable at startup

After a successful manual test, run this in your desktop terminal from the repository root:

```bash
# Use the actual MAYA_APP_DIR from your Maya launcher:
python3 scripts/install-maya-ui-fixes.py --app-dir "$HOME/maya" --version 2027
```

Find the actual directory in Maya:

```python
import maya.cmds as cmds
print(cmds.internalVar(userAppDir=True))
```

The native installer in this repository uses `<repo>/user` and configures startup itself. For that installation, use `--app-dir "$PWD/user"` when running from the repository root.

The helper adds a marked block to `<MAYA_APP_DIR>/2027/scripts/userSetup.py`. It preserves existing Python code and creates a dated backup before changing the file. Repeating the command does not duplicate the block. Incomplete markers and symlinks are rejected for manual review.

Only actual standalone Python comments mark the generated block; examples of the marker text inside strings are preserved. Existing source encodings (including UTF-8 BOM and encoding declarations) and CRLF line endings are retained. The resulting Python is checked before the startup file is replaced.

New installs also write a private `.maya-hotbox-undo.json` beside the startup file. Removal uses it to delete a startup file created solely for the fix, or restore an original missing final newline exactly. Later user code is preserved. Dated backups remain as recovery evidence.

The startup block loads the fix through `maya.utils.executeDeferred` after the interface is built. A reference on the QApplication object keeps it alive and prevents duplicate activation. Batch processes are skipped. Keep the repository at its configured location.

### Disable or remove

For one launch without the startup fix, when using this repository's launcher:

```bash
MAYA_HOTBOX_GEOMETRY_FIX=0 ./scripts/maya-2027
```

To remove only this repository's startup block, preserving other startup commands:

```bash
# Again, use your actual MAYA_APP_DIR:
python3 scripts/install-maya-ui-fixes.py --app-dir "$HOME/maya" --version 2027 --remove
```

To stop the currently running fix, use Maya's Python tab:

```python
from PySide6 import QtWidgets
fix = getattr(QtWidgets.QApplication.instance(), '_maya_hotbox_geometry_fix', None)
if fix:
    fix.stop()
```

The startup helper configures only the Hotbox fix. It does not change hotkeys, Arnold settings, or global i3 configuration.

## Detached panels in i3

For a combined startup-fix and panel-helper removal command, see [standalone UI rollback](ROLLBACK.md#standalone-ui-fixes). Close Maya first so its session-only geometry changes and windows also disappear.

### Symptom and scope

In the measured setup, the main window and a detached panel shared class `Maya-2027`, instance `maya.bin`, and no window role. The panel's `WM_TRANSIENT_FOR` relationship linked it to Maya's main window. i3 tiled it as `auto_off`; in a tabbed layout this looked like maximization.

[The panel helper](../scripts/helpers/maya-i3-panels.py) floats only automatically tiled, normal transient Maya child windows. It leaves the main window tiled and excludes manually tiled windows, other applications, popups, and deliberate fullscreen windows.

### Start or stop the helper

In a desktop terminal, from the repository root:

```bash
# System dependency for this optional helper:
sudo apt-get install python3-i3ipc
python3 scripts/helpers/maya-i3-panels.py --start
# Stop the running automation:
python3 scripts/helpers/maya-i3-panels.py --stop
```

The repository's launcher starts the helper in an i3 session. It also enables `MAYA_WORKSPACES_ALWAYS_SHOW_TAB=1` so Maya's docking tabs/grips stay visible. Use those Maya handles to redock. The i3 floating modifier, often Super/Windows, moves the whole X11 window instead. Maya's workspace lock can also prevent docking.

## Diagnose the window behavior

In a normal desktop terminal, read the Maya window relationships:

```bash
python3 scripts/diagnostics/inspect-i3-maya.py
```

For a bounded Hotbox diagnostic, use Maya's Python tab:

```python
import runpy
_ = runpy.run_path('/path/to/repo/scripts/diagnostics/diagnose-maya-hotbox.py', run_name='__main__')
```

The diagnostic briefly shows the Hotbox directly, then observes changes to its window. Hold Space in a viewport during that period. It ends after 22 seconds, pauses an active panel helper, and then restarts it. JSONL output under `logs` includes configured Space commands, window geometry, and native X11/compositor data. It uses no global event filter and does not record keystrokes or window titles.

Logs remain local and are ignored by Git. Review any files before sharing them: paths and other system details can still identify your environment. See [TESTING.md](TESTING.md) for what was verified.

## Laptops and external monitors

A single laptop screen can behave differently from the three-monitor setup. Debian plus i3 alone does not establish that the Hotbox bug will occur. The measured drawing-area mismatch suggests a monitor-related problem but does not prove its internal cause.

On another machine, check:

1. Internal screen only: launch Maya, open and use the Hotbox, restart, and check again.
2. Attach an external monitor, move Maya to each display, and test the Hotbox on both.
3. Arrange the monitor to the left, right, or above, including negative desktop coordinates where applicable, and test again.
4. Disconnect the external monitor and reopen the Hotbox.
5. With mixed scaling factors, check positioning and usability carefully; this has not been confirmed on the original desktop.

Set up projects normally on the other machine. Sign in independently; do not transfer tokens, license state, or private Autodesk directories from the original machine.

Sources: [Autodesk Linux variables](https://help.autodesk.com/cloudhelp/2026/ENU/Maya-EnvVar/files/GUID-A0F704AD-911B-499D-B07A-71A70E7E9ADE.htm), [Autodesk docking](https://help.autodesk.com/cloudhelp/2027/ENU/Maya-Basics/files/GUID-67562106-21C8-4ADD-B315-297F94CC8B4C.htm), [i3 user guide](https://i3wm.org/docs/userguide.html).
