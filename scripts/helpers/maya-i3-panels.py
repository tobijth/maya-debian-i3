#!/usr/bin/python3
"""Keep transient Maya panels floating in i3 while leaving main windows tiled."""
import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parents[2]
STATE = BASE / 'state/i3'
STATUS = STATE / 'panels-status.json'
LOCK = STATE / 'panels.lock'
SCRIPT = Path(__file__).resolve()


def maya_window(node):
    props = node.get('window_properties') or {}
    return (isinstance(node.get('window'), int)
            and re.fullmatch(r'Maya(?:-\d{4})?', props.get('class') or '', re.I)
            and props.get('instance') == 'maya.bin')


def walk(node, workspace=None):
    if node.get('type') == 'workspace':
        workspace = node.get('rect')
    if node.get('window'):
        yield node, workspace
    for child in node.get('nodes', []) + node.get('floating_nodes', []):
        yield from walk(child, workspace)


def adjustments(tree):
    windows = list(walk(tree))
    by_window = {node['window']: node for node, _ in windows}
    result = []
    for node, workspace in windows:
        if not maya_window(node) or node.get('floating') != 'auto_off':
            continue
        if node.get('fullscreen_mode', 0) or node.get('window_type', 'normal') != 'normal':
            continue
        props = node['window_properties']
        parent = by_window.get(props.get('transient_for'))
        # Both observed windows have the same class and no role. Their actual
        # WM_TRANSIENT_FOR relationship distinguishes the panel from the main UI.
        if parent is None or not maya_window(parent) or parent is node:
            continue
        if parent['window_properties']['class'] != props['class']:
            continue
        command = 'floating enable'
        area = workspace or node.get('rect') or {}
        geometry = node.get('geometry') or {}
        aw, ah = area.get('width', 0), area.get('height', 0)
        gw, gh = geometry.get('width', 0), geometry.get('height', 0)
        # i3 normally restores the original requested geometry on floating.
        # Bound a panel that has already inherited the entire tiled workspace.
        if aw > 300 and ah > 250 and (gw >= aw * .9 or gh >= ah * .9):
            width = min(gw if 200 <= gw < aw * .9 else 900, int(aw * .8))
            height = min(gh if 150 <= gh < ah * .9 else 650, int(ah * .8))
            command += f', resize set {width} px {height} px'
        result.append((node['id'], command))
    return result


def reconcile(connection):
    changed = 0
    for container, command in adjustments(connection.get_tree().ipc_data):
        replies = connection.command(f'[con_id={int(container)}] {command}')
        if not replies or not all(reply.success for reply in replies):
            raise RuntimeError(f'i3 konnte Panel {container} nicht schwebend setzen.')
        changed += 1
        print(f'{datetime.now().isoformat(timespec="seconds")} Panel {container}: {command}', flush=True)
    return changed


def connect():
    import i3ipc
    return i3ipc.Connection(auto_reconnect=True)


def read_status():
    try:
        return json.loads(STATUS.read_text())
    except (OSError, ValueError):
        return {}


def watcher_running():
    with LOCK.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def watch():
    import i3ipc
    with LOCK.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        connection = connect()

        def update(conn):
            try:
                reconcile(conn)
            except RuntimeError as error:
                # Docking can destroy an X11 window between its event and the
                # command reply. Keep watching the replacement window.
                print(f'{datetime.now().isoformat(timespec="seconds")} {error}', flush=True)

        def on_window(conn, event):
            if maya_window(event.container.ipc_data):
                update(conn)

        def on_tick(conn, event):
            if event.first:
                update(conn)

        def on_shutdown(conn, event):
            if event.change == 'exit':
                conn.main_quit()

        for event in (i3ipc.Event.WINDOW_NEW, i3ipc.Event.WINDOW_TITLE,
                      i3ipc.Event.WINDOW_FOCUS, i3ipc.Event.WINDOW_FLOATING):
            connection.on(event, on_window)
        connection.on(i3ipc.Event.TICK, on_tick)
        connection.on(i3ipc.Event.SHUTDOWN, on_shutdown)
        signal.signal(signal.SIGTERM, lambda *_: connection.main_quit())
        signal.signal(signal.SIGINT, lambda *_: connection.main_quit())
        reconcile(connection)
        temporary = STATUS.with_suffix('.new')
        temporary.write_text(json.dumps({'pid': os.getpid(), 'script': str(SCRIPT)}))
        temporary.replace(STATUS)
        try:
            connection.main()
        finally:
            if read_status().get('pid') == os.getpid():
                STATUS.unlink(missing_ok=True)


def start():
    # Check the real desktop connection and fix already-open panels immediately.
    changed = reconcile(connect())
    if watcher_running():
        print(f'Maya-i3-Anpassung bereits aktiv; {changed} offene Panels angepasst.')
        return
    log = BASE / 'logs/maya-i3-panels.txt'
    with log.open('a') as output:
        process = subprocess.Popen([sys.executable, str(SCRIPT), '--watch'],
                                   stdin=subprocess.DEVNULL, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
    for _ in range(40):
        if process.poll() is not None:
            if process.returncode == 0 and watcher_running():
                return
            raise RuntimeError(f'Panel-Anpassung konnte nicht starten. Details: {log}')
        if read_status().get('pid') == process.pid and watcher_running():
            print(f'Maya-i3-Anpassung aktiv; {changed} offene Panels angepasst. Hauptfenster bleibt unveraendert.')
            return
        time.sleep(.05)
    raise RuntimeError(f'Keine Startbestaetigung. Details: {log}')


def stop():
    status = read_status()
    pid = status.get('pid')
    if not isinstance(pid, int) or not watcher_running():
        print('Keine aktive Maya-i3-Anpassung gefunden.')
        return
    try:
        command = Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
    except FileNotFoundError:
        return
    if os.fsencode(SCRIPT) not in command or b'--watch' not in command:
        raise RuntimeError('PID gehoert nicht zur Maya-Panel-Anpassung; kein Prozess beendet.')
    os.kill(pid, signal.SIGTERM)
    print('Maya-i3-Anpassung beendet. Bestehende Fensterpositionen bleiben erhalten.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--start', action='store_true')
    mode.add_argument('--watch', action='store_true')
    mode.add_argument('--stop', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    if args.start or args.watch:
        from local_undo import capture
        capture('panels')
    elif not STATE.exists():
        print('Keine aktive Maya-i3-Anpassung gefunden.')
        return
    STATE.mkdir(parents=True, exist_ok=True)
    (BASE / 'logs').mkdir(exist_ok=True)
    if args.start:
        start()
    elif args.watch:
        watch()
    else:
        stop()


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ImportError) as error:
        sys.exit(f'Maya-i3-Anpassung: {error}')
