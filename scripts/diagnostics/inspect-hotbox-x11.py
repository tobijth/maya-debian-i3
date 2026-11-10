#!/usr/bin/env python3
"""Read native geometry/compositor state; never change the desktop."""
import ctypes
import json
import re
import subprocess
import sys


def compositor_owner():
    xlib = ctypes.CDLL('libX11.so.6')
    xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
    xlib.XOpenDisplay.restype = ctypes.c_void_p
    xlib.XDefaultScreen.argtypes = [ctypes.c_void_p]
    xlib.XDefaultScreen.restype = ctypes.c_int
    xlib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    xlib.XInternAtom.restype = ctypes.c_ulong
    xlib.XGetSelectionOwner.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    xlib.XGetSelectionOwner.restype = ctypes.c_ulong
    xlib.XCloseDisplay.argtypes = [ctypes.c_void_p]
    xlib.XCloseDisplay.restype = ctypes.c_int
    display = xlib.XOpenDisplay(None)
    if not display:
        return {'error': 'X display unavailable'}
    try:
        screen = xlib.XDefaultScreen(display)
        atom = xlib.XInternAtom(display, f'_NET_WM_CM_S{screen}'.encode(), 0)
        return {'screen': screen, 'owner': int(xlib.XGetSelectionOwner(display, atom))}
    finally:
        xlib.XCloseDisplay(display)


def command(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True, timeout=2)
    return result.returncode, result.stdout, result.stderr


def inspect(windows):
    report = {'compositor': compositor_owner(), 'windows': []}
    for window in windows:
        entry = {'window': window}
        code, output, error = command(['xwininfo', '-id', str(window), '-stats'])
        # Ignore the header containing the window's title.
        entry['native'] = dict(re.findall(
            r'^\s*(Absolute upper-left X|Absolute upper-left Y|Width|Height|Depth|'
            r'Map State|Override Redirect State):\s*(.+)$', output, re.MULTILINE))
        if code:
            entry['error'] = error.strip()[:300]
        _, output, _ = command(['xprop', '-notype', '-id', str(window), 'WM_CLASS',
                               'WM_WINDOW_ROLE', 'WM_TRANSIENT_FOR',
                               '_NET_WM_WINDOW_TYPE', '_NET_WM_STATE'])
        entry['properties'] = output.strip()
        report['windows'].append(entry)
    code, output, _ = command(['i3-msg', '-t', 'get_tree'])
    if code == 0:
        pending = [json.loads(output)]
        matches = []
        while pending:
            node = pending.pop()
            pending.extend(node.get('nodes', []))
            pending.extend(node.get('floating_nodes', []))
            if node.get('window') in windows:
                matches.append({key: node.get(key) for key in
                                ('window', 'id', 'floating', 'rect', 'window_rect', 'geometry')})
        report['i3'] = matches
    return report


if __name__ == '__main__':
    print(json.dumps(inspect([int(value, 0) for value in sys.argv[1:]])))
