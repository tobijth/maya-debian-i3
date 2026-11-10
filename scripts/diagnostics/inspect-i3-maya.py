#!/usr/bin/env python3
"""Read Maya's actual i3/X11 properties without changing windows or preferences."""
import json
import subprocess
import sys


def main():
    result = subprocess.run(['i3-msg', '-t', 'get_tree'], text=True, capture_output=True)
    if result.returncode:
        sys.exit('i3 nicht erreichbar. Im normalen Desktop-Terminal ausfuehren.\n' + result.stderr)
    pending = [json.loads(result.stdout)]
    windows = []
    while pending:
        node = pending.pop()
        pending.extend(node.get('nodes', []))
        pending.extend(node.get('floating_nodes', []))
        props = node.get('window_properties') or {}
        if not node.get('window') or 'maya' not in props.get('class', '').lower():
            continue
        xprop = subprocess.run(
            ['xprop', '-notype', '-id', str(node['window']), 'WM_CLASS', 'WM_WINDOW_ROLE',
             'WM_TRANSIENT_FOR', '_NET_WM_WINDOW_TYPE', '_NET_WM_STATE'],
            text=True, capture_output=True)
        windows.append({
            'window': node['window'], 'con_id': node['id'],
            'class': props.get('class'), 'instance': props.get('instance'),
            'role': props.get('window_role'), 'transient_for': props.get('transient_for'),
            'floating': node.get('floating'), 'fullscreen_mode': node.get('fullscreen_mode'),
            'rect': node.get('rect'), 'x11': xprop.stdout.strip(),
        })
    print(json.dumps(windows, ensure_ascii=False, indent=2))
    if not windows:
        sys.exit('Keine Maya-Fenster gefunden. Maya und ein herausgeloestes Panel offen lassen.')


if __name__ == '__main__':
    main()
